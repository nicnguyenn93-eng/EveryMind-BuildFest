"""
everymind_clean.py - config-driven cleaning pipeline for EveryMind 988 training surveys.

One implementation, imported by both the notebook and the Streamlit app.
Every step takes (df, cfg, audit), returns a DataFrame, and logs what it did.

Design rules
------------
* Flag, never silently delete. Only exact duplicate rows and fully blank rows are removed.
* Never impute an answer. Missing values carry a status code explaining why they are missing.
* Every mapping is explainable: exact, alias, contains, fuzzy (with score) or human-approved.
* Unknown values are queued for human review, never guessed into a category.
* Free text goes through the team privacy tool before it reaches public outputs or any LLM.
* Everything is driven by schema.json + mapping_registry.json, so a new export with drifted
  wording needs a config edit, not a code change.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import csv
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

try:
    from rapidfuzz import fuzz
except ImportError:  # fuzzy tier is optional; exact / alias / contains still work
    fuzz = None

if __package__:
    from . import privacy_adapter
else:  # Retain John's direct-module import convention for existing consumers.
    import privacy_adapter

SOURCE_ROW = "__source_row"
PRIVACY_REVIEW_COLUMNS = [
    "source_row", "original_id", "response_id", "field", "source_field",
    "source_language", "form_language", "language", "original_text",
    "normalized_input", "redacted_text", "normalization_changed", "status", "detections",
]

# ----------------------------------------------------------------------------------------
# Status codes: why a value is (or is not) usable
# ----------------------------------------------------------------------------------------
VALID = "valid"                 # usable answer
SKIPPED = "skipped"             # question was on the form, respondent left it blank
NOT_ASKED = "not_asked"         # question was (very likely) not on this form version
UNCLEAR_ASKED = "unclear_asked" # blank, and we cannot tell whether the question was asked
DECLINED = "declined"           # N/A, prefer not to say
UNMAPPED = "unmapped"           # a label we don't recognise yet (queued for review)
INVALID = "invalid"             # out of range / unparseable

ANSWERED = [VALID, DECLINED, UNMAPPED, INVALID]


class SchemaError(ValueError):
    """Raised when a required column cannot be found."""


# ----------------------------------------------------------------------------------------
# Text helpers
# ----------------------------------------------------------------------------------------
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " "})


def clean_str(x) -> str:
    """Normalize a cell for storage: Unicode NFKC, straight quotes, no invisible
    formatting characters (e.g. the U+200E marks in the Language column), single spaces."""
    if is_blank(x):
        return ""
    s = unicodedata.normalize("NFKC", str(x)).translate(_QUOTES)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
    return re.sub(r"\s+", " ", s).strip()


def is_blank(x) -> bool:
    """True for None / NaN / pd.NA / empty string (pandas 3 may hand back any of these)."""
    if x is None or x is pd.NA:
        return True
    if isinstance(x, float) and np.isnan(x):
        return True
    return isinstance(x, str) and x == ""


def match_key(x, strip_tokens: tuple = ()) -> str:
    """Aggressive key used only for matching (never stored): casefold, punctuation -> space."""
    s = clean_str(x).casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    if strip_tokens:
        s = " ".join(t for t in s.split() if t not in strip_tokens)
    return re.sub(r"\s+", " ", s).strip()


def _fmt(v, limit=400):
    s = json.dumps(v, default=str, ensure_ascii=False) if isinstance(v, (dict, list, tuple)) else str(v)
    return s if len(s) <= limit else s[:limit] + " …"


# ----------------------------------------------------------------------------------------
# Audit trail
# ----------------------------------------------------------------------------------------
@dataclass
class Audit:
    dataset_key: str = ""
    source_name: str = ""
    steps: list = field(default_factory=list)
    review_queue: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    disabled: list = field(default_factory=list)
    privacy_tool: str = "not connected"

    def log(self, step: str, summary: str, **details):
        self.steps.append({"step": step, "summary": summary, **details})

    def warn(self, msg: str):
        self.warnings.append(msg)

    def queue(self, **item):
        self.review_queue.append(item)

    def review_table(self) -> pd.DataFrame:
        cols = ["vocab", "column", "raw_value", "count", "suggestion", "suggestion_score", "suggested_by"]
        return pd.DataFrame(self.review_queue, columns=cols) if self.review_queue else pd.DataFrame(columns=cols)

    def to_markdown(self) -> str:
        out = ["# Cleaning audit report", "",
               f"- Source: `{self.source_name}`", f"- Dataset key (SHA-256 prefix): `{self.dataset_key}`",
               f"- Privacy tool: {self.privacy_tool}", ""]
        for i, s in enumerate(self.steps, 1):
            out += [f"## {i}. {s['step']}", "", s["summary"], ""]
            for k, v in s.items():
                if k not in ("step", "summary"):
                    out.append(f"- **{k}**: {_fmt(v)}")
            out.append("")
        if self.disabled:
            out += ["## Disabled analyses", ""] + [f"- {d}" for d in self.disabled] + [""]
        if self.warnings:
            out += ["## Warnings", ""] + [f"- {w}" for w in self.warnings] + [""]
        rq = self.review_table()
        out += [f"## Values awaiting human review ({len(rq)})", ""]
        if len(rq):
            out.append("| vocab | column | raw value | count | suggestion |")
            out.append("|---|---|---|---|---|")
            for _, r in rq.iterrows():
                sug = "" if pd.isna(r.suggestion) else f"{r.suggestion} ({r.suggested_by}, {r.suggestion_score})"
                out.append(f"| {r.vocab} | {r.column} | {r.raw_value} | {r['count']} | {sug} |")
        else:
            out.append("None.")
        return "\n".join(out) + "\n"


# ----------------------------------------------------------------------------------------
# Step 0: config
# ----------------------------------------------------------------------------------------
def load_config(schema_path, registry_path=None) -> dict:
    cfg = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    cfg.setdefault("vocab", {})
    cfg["_registry_count"] = 0
    if registry_path and Path(registry_path).exists():
        reg = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        for vocab_name, entries in reg.get("approved", {}).items():
            aliases = cfg["vocab"].setdefault(vocab_name, {}).setdefault("aliases", {})
            approved = cfg["vocab"][vocab_name].setdefault("_approved", set())
            for e in entries:
                aliases[e["raw"]] = e["maps_to"]
                approved.add(match_key(e["raw"]))
                cfg["_registry_count"] += 1
    return cfg


# ----------------------------------------------------------------------------------------
# Step 1: ingest
# ----------------------------------------------------------------------------------------
_READ_KW = dict(dtype=object, keep_default_na=False, na_values=[""])  # keep "N/A" as text


def ingest(source, cfg: dict, audit: Audit, filename: str | None = None) -> pd.DataFrame:
    """Read XLSX/CSV from a path or raw bytes (Streamlit upload)."""
    if isinstance(source, (bytes, bytearray)):
        data, name = bytes(source), filename or "upload"
    else:
        p = Path(source)
        data, name = p.read_bytes(), p.name
    audit.dataset_key = hashlib.sha256(data).hexdigest()[:12]
    audit.source_name = name
    ext = name.lower().rsplit(".", 1)[-1]
    sheet_used, encoding = None, None

    if ext in {"xlsx", "xlsm", "xls"}:
        xls = pd.ExcelFile(io.BytesIO(data))
        want = cfg.get("sheet")
        sheet_used = want if want in xls.sheet_names else xls.sheet_names[0]
        if want and want not in xls.sheet_names:
            audit.warn(f"Sheet '{want}' not found; used first sheet '{sheet_used}'.")
        df = pd.read_excel(xls, sheet_name=sheet_used, **_READ_KW)
    elif ext in {"csv", "tsv", "txt"}:
        sep = "\t" if ext == "tsv" else ","
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                df = pd.read_csv(io.BytesIO(data), encoding=encoding, sep=sep, skip_blank_lines=False, **_READ_KW)
                break
            except UnicodeDecodeError:
                continue
    else:
        raise SchemaError(f"Unsupported file type '.{ext}'. Upload .xlsx or .csv.")

    n_raw = len(df)
    kept = df.index[~df.isna().all(axis=1)].tolist()
    kept_set = set(kept)
    blank_rows = [int(i) + 2 for i in df.index if i not in kept_set]
    df = df.dropna(how="all").reset_index(drop=True)
    df.attrs["source_rows"] = [int(i) + 2 for i in kept]
    audit.log("Ingest",
              f"Read `{name}`: {n_raw} rows × {df.shape[1]} columns; removed {n_raw - len(df)} fully blank rows.",
              sheet=sheet_used, encoding=encoding, removed_source_rows=blank_rows)
    return df


# ----------------------------------------------------------------------------------------
# Step 2: match columns to the schema
# ----------------------------------------------------------------------------------------
def _allowed(spec: dict, hkey: str) -> bool:
    must = [match_key(m) for m in spec.get("must_contain", [])]
    must_not = [match_key(m) for m in spec.get("must_not_contain", [])]
    words = set(hkey.split())
    # single tokens must match whole words ("co" must not match "county"); phrases match as substrings
    def has(m):
        return (m in words) if " " not in m and len(m) <= 3 else (m in hkey)
    return all(has(m) for m in must) and not any(has(m) for m in must_not)


def match_columns(df: pd.DataFrame, cfg: dict, audit: Audit, fuzzy_threshold: int = 85) -> pd.DataFrame:
    specs = cfg["columns"]
    headers = {h: match_key(h) for h in df.columns}
    assigned, method = {}, {}
    taken = set()

    # pass 1: exact (on normalized keys)
    for canon, spec in specs.items():
        targets = {match_key(canon)} | {match_key(s) for s in spec.get("synonyms", [])}
        for h, hk in headers.items():
            if h not in taken and hk in targets and _allowed(spec, hk):
                assigned[canon], method[canon] = h, "exact"
                taken.add(h)
                break

    # pass 2: fuzzy, global best-first so one header can't be grabbed by a weaker match
    if fuzz is not None:
        cands = []
        for canon, spec in specs.items():
            if canon in assigned:
                continue
            targets = [match_key(s) for s in spec.get("synonyms", [])] + [match_key(canon)]
            for h, hk in headers.items():
                if h in taken or not _allowed(spec, hk):
                    continue
                score = max(fuzz.token_sort_ratio(hk, t) for t in targets)
                if score >= fuzzy_threshold:
                    cands.append((score, canon, h))
        for score, canon, h in sorted(cands, reverse=True):
            if canon not in assigned and h not in taken:
                assigned[canon], method[canon] = h, f"fuzzy ({score:.0f})"
                taken.add(h)

    missing_req = [c for c, s in specs.items() if s.get("required") and c not in assigned]
    if missing_req:
        hints = []
        for c in missing_req:
            spec = specs[c]
            targets = [match_key(s) for s in spec.get("synonyms", [])] + [match_key(c)]
            if fuzz is not None:
                best = max(((max(fuzz.token_sort_ratio(hk, t) for t in targets), h) for h, hk in headers.items()),
                           default=(0, None))
                owner = next((k for k, v in assigned.items() if v == best[1]), None)
                hints.append(f"'{c}' (closest header: {best[1]!r}, similarity {best[0]:.0f}"
                             + (f", already used for '{owner}')" if owner else ")"))
            else:
                hints.append(f"'{c}'")
        raise SchemaError("Required column(s) not found: " + "; ".join(hints)
                          + ". Add the header wording as a synonym in schema.json.")

    missing_opt = [c for c, s in specs.items() if not s.get("required") and c not in assigned]
    for c in missing_opt:
        audit.disabled.append(f"`{c}` not in this export: analyses that use it are disabled.")
    unmatched = [h for h in df.columns if h not in taken]
    pii_like = [h for h in unmatched if re.search(r"\b(name|email|e mail|phone|address|student id)\b", match_key(h))]
    if pii_like:
        audit.warn(f"Unmatched column(s) that look like personal info were dropped: {pii_like}")

    out = df[[assigned[c] for c in assigned]].copy()
    out.columns = list(assigned)
    audit.log("Match columns",
              f"Matched {len(assigned)}/{len(specs)} schema fields; {len(unmatched)} unrecognised column(s) dropped.",
              methods={c: method[c] for c in assigned},
              missing_optional=missing_opt, unmatched_headers=unmatched)
    out.attrs["column_methods"] = {c: (assigned[c], method[c]) for c in assigned}
    source_rows = df.attrs.get("source_rows", list(range(2, len(df) + 2)))
    out[SOURCE_ROW] = source_rows
    originals = {}
    for position, source_row in enumerate(source_rows):
        originals[source_row] = {
            c: "" if is_blank(out.iloc[position][c]) else str(out.iloc[position][c])
            for c in assigned if c in ("response_id", "form_language") or specs[c]["type"] == "text"
        }
    out.attrs["source_originals"] = originals
    return out


# ----------------------------------------------------------------------------------------
# Step 3: drop structured PII, Step 4: normalize values
# ----------------------------------------------------------------------------------------
def drop_structured_pii(df: pd.DataFrame, cfg: dict, audit: Audit) -> pd.DataFrame:
    drop = [c for c, s in cfg["columns"].items() if s["type"] == "drop" and c in df.columns]
    audit.log("Drop structured PII",
              f"Dropped {len(drop)} identifier column(s)." if drop else "No identifier columns present.",
              dropped=drop)
    return df.drop(columns=drop)


def normalize_values(df: pd.DataFrame, cfg: dict, audit: Audit) -> pd.DataFrame:
    df = df.copy()
    changed = {}
    for c in df.columns:
        if c == SOURCE_ROW:
            continue
        before = df[c]
        after = before.map(clean_str)
        after = after.where(after != "", None)
        was = before.where(before.notna(), None).map(lambda v: None if v is None else str(v))
        n = int(((was != after) & ~(was.isna() & after.isna())).sum())
        if n:
            changed[c] = n
        df[c] = after
    audit.log("Normalize values",
              f"Unicode/whitespace/quote normalization changed {sum(changed.values())} cells in {len(changed)} columns "
              "(includes trailing non-breaking spaces and invisible direction marks).",
              cells_changed_by_column=changed)
    return df


# ----------------------------------------------------------------------------------------
# Step 5: deduplicate
# ----------------------------------------------------------------------------------------
def deduplicate(df: pd.DataFrame, cfg: dict, audit: Audit) -> pd.DataFrame:
    n0 = len(df)
    exact = df.duplicated(subset=[c for c in df.columns if c != SOURCE_ROW], keep="first")
    removed_rows = df.loc[exact, SOURCE_ROW].tolist() if SOURCE_ROW in df else []
    df = df[~exact].reset_index(drop=True)

    content = [c for c in df.columns if c not in ("response_id", SOURCE_ROW)]
    has_ts = any(c in df.columns for c in ("start_time", "completion_time"))
    # same answers AND same timestamps under a different ID = likely double export.
    # Without timestamps, identical answers are common (e.g. a class all ticking 'Agree'), so don't flag.
    df["flag_possible_duplicate"] = df.duplicated(subset=content, keep=False) if has_ts else False
    df["flag_duplicate_id"] = df["response_id"].duplicated(keep=False)
    audit.log("Deduplicate",
              f"Removed {int(exact.sum())} exact duplicate row(s) ({n0} → {len(df)}). "
              f"Flagged {int(df.flag_duplicate_id.sum())} rows sharing an ID and "
              f"{int(df.flag_possible_duplicate.sum())} rows with identical answers and timestamps under different IDs "
              "for operator review (kept).", removed_source_rows=removed_rows)
    if df.flag_duplicate_id.any():
        audit.warn("Duplicate response IDs found. Resolve before replacing the active dataset.")
    return df


# ----------------------------------------------------------------------------------------
# Step 6: parse types (dates, durations, numeric scales)
# ----------------------------------------------------------------------------------------
_DUR = re.compile(r"^(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)$")


def _parse_duration(v) -> float:
    if is_blank(v):
        return np.nan
    s = str(v).strip()
    m = _DUR.match(s)
    if m:
        h, mnt, sec = m.groups()
        return (int(h or 0) * 60 + int(mnt)) * 60 + float(sec)
    try:
        return float(s)
    except ValueError:
        return np.nan


_LEADING_NUM = re.compile(r"^\s*(-?\d+(?:\.\d+)?)")


def parse_types(df: pd.DataFrame, cfg: dict, audit: Audit) -> pd.DataFrame:
    df = df.copy()
    specs = cfg["columns"]
    report = {}
    for c in df.columns:
        spec = specs.get(c)
        if not spec:
            continue
        t = spec["type"]
        if t in ("datetime", "date"):
            raw = df[c]
            parsed = pd.to_datetime(raw, errors="coerce", format="mixed")
            if t == "date":
                parsed = parsed.dt.normalize()
            bad = int((raw.notna() & parsed.isna()).sum())
            df[c] = parsed
            df[f"{c}__status"] = np.where(parsed.notna(), VALID, np.where(raw.notna(), INVALID, SKIPPED))
            report[c] = {"blank": int(raw.isna().sum()), "unparseable": bad}
        elif t == "scale":
            raw = df[c]
            num = raw.map(lambda v: float(_LEADING_NUM.match(str(v)).group(1))
                          if not is_blank(v) and _LEADING_NUM.match(str(v)) else np.nan).astype(float)
            lo, hi = spec["min"], spec["max"]
            ok = num.between(lo, hi) & (num == np.floor(num))
            status = np.where(raw.isna(), SKIPPED, np.where(ok, VALID, INVALID))
            declined = raw.map(lambda v: match_key(v) in {"n a", "na", "prefer not to say"})
            status = np.where(declined, DECLINED, status)
            df[c] = num.where(ok)
            df[f"{c}__status"] = status
            report[c] = {"blank": int(raw.isna().sum()), "out_of_range_or_unparseable": int((status == INVALID).sum())}
        elif t == "id":
            df[c] = df[c].astype("string")

    # derived timing fields
    if {"start_time", "completion_time"} <= set(df.columns):
        dur = (df["completion_time"] - df["start_time"]).dt.total_seconds()
        neg = dur < 0
        df["duration_seconds"] = dur.where(~neg)
        report["duration_seconds"] = {"negative_set_missing": int(neg.sum()),
                                      "median": float(np.nanmedian(df["duration_seconds"]))
                                      if df["duration_seconds"].notna().any() else None}
    if {"training_date", "start_time"} <= set(df.columns):
        gap = (df["start_time"].dt.normalize() - df["training_date"]).dt.days
        df["survey_lag_days"] = gap
        max_gap = cfg.get("dates", {}).get("max_gap_days", 60)
        df["flag_date_inconsistent"] = (gap < 0) | (gap > max_gap)
        report["training_date_vs_submission"] = {
            "submitted_before_training": int((gap < 0).sum()),
            f"submitted_more_than_{max_gap}_days_after": int((gap > max_gap).sum()),
            "median_lag_days": float(np.nanmedian(gap)) if gap.notna().any() else None}
    audit.log("Parse types",
              "Parsed dates and numeric scales; derived survey duration and training-to-survey lag. "
              "Unparseable or out-of-range values are marked invalid, not clipped or guessed.",
              details=report)
    return df


# ----------------------------------------------------------------------------------------
# Step 7: standardize categorical / Likert / multi-select values
# ----------------------------------------------------------------------------------------
def _prep_vocab(v: dict) -> dict:
    strip = tuple(v.get("strip_tokens", ()))
    canon = v["canonical"]
    labels = list(canon) if isinstance(canon, dict) else list(canon)
    ck = {match_key(l, strip): l for l in labels}
    ak = {}
    for raw, target in v.get("aliases", {}).items():
        tk = match_key(target, strip)
        if tk not in ck:
            raise SchemaError(f"Alias '{raw}' maps to '{target}', which is not a canonical value.")
        ak[match_key(raw, strip)] = ck[tk]
    return {"strip": strip, "labels": labels, "codes": canon if isinstance(canon, dict) else None,
            "canon_keys": ck, "alias_keys": ak,
            "approved": v.get("_approved", set()),
            "declined": {match_key(d) for d in v.get("declined", [])},
            "numeric": v.get("accept_numeric_codes", False),
            "contains": v.get("allow_contains", False),
            "fuzzy": v.get("fuzzy_threshold")}


def map_value(raw: str, pv: dict):
    """Return (canonical_label | None, method | None, status)."""
    if is_blank(raw):
        return None, None, SKIPPED
    k = match_key(raw, pv["strip"])
    if match_key(raw) in pv["declined"]:
        return None, "declined", DECLINED
    if k in pv["canon_keys"]:
        return pv["canon_keys"][k], "exact", VALID
    if k in pv["alias_keys"]:
        how = "approved" if match_key(raw) in pv["approved"] else "alias"
        return pv["alias_keys"][k], how, VALID
    if pv["numeric"] and pv["codes"] and re.fullmatch(r"\d+", k):
        inv = {v: l for l, v in pv["codes"].items()}
        if int(k) in inv:
            return inv[int(k)], "numeric code", VALID
    if pv["contains"]:
        hits = {lab for ck, lab in pv["canon_keys"].items() if ck and re.search(rf"\b{re.escape(ck)}\b", k)}
        if len(hits) == 1:
            return hits.pop(), "contains", VALID
    if pv["fuzzy"] and fuzz is not None:
        best = max(((fuzz.token_sort_ratio(k, ck), lab) for ck, lab in {**pv["canon_keys"], **pv["alias_keys"]}.items()),
                   default=(0, None))
        if best[0] >= pv["fuzzy"]:
            return best[1], f"fuzzy ({best[0]:.0f})", VALID
    return None, None, UNMAPPED


def _suggest(raw: str, pv: dict):
    if fuzz is None:
        return None, None
    k = match_key(raw, pv["strip"])
    best = max(((fuzz.token_sort_ratio(k, ck), lab) for ck, lab in pv["canon_keys"].items()), default=(0, None))
    return best[1], round(best[0])


def standardize(df: pd.DataFrame, cfg: dict, audit: Audit,
                suggest_fn: Optional[Callable[[str, list, list], dict]] = None) -> pd.DataFrame:
    """Map Likert, category and multi-select columns onto canonical values.

    suggest_fn(vocab_name, unmapped_raw_values, canonical_labels) -> {raw: suggested_label}
    is an optional LLM hook. Its suggestions go to the review queue only; they are never applied.
    """
    df = df.copy()
    specs = cfg["columns"]
    vocabs = {name: _prep_vocab(v) for name, v in cfg["vocab"].items()}
    methods_report, unmapped_report = {}, {}

    for c in list(df.columns):
        spec = specs.get(c)
        if not spec or spec["type"] not in ("likert5", "category", "multiselect"):
            continue
        vname = "likert5" if spec["type"] == "likert5" else spec["vocab"]
        pv = vocabs[vname]
        raw = df[c]

        if spec["type"] == "multiselect":
            seps = cfg["vocab"][vname].get("separators", [";"])
            slugs = cfg["vocab"][vname].get("slugs", {})
            pattern = "|".join(re.escape(s) for s in seps)
            sets, statuses, unknown = [], [], {}
            for v in raw:
                if is_blank(v):
                    sets.append([]); statuses.append(SKIPPED); continue
                # always split first, so a multi-role answer can never be fuzzy-matched to a single role
                parts = []
                for part in (p.strip() for p in re.split(pattern, v)):
                    if not part:
                        continue
                    lab, how, st_p = map_value(part, pv)
                    if st_p == VALID:
                        parts.append(lab)
                        methods_report.setdefault(c, {}).setdefault(how, 0)
                        methods_report[c][how] += 1
                    else:
                        unknown[part] = unknown.get(part, 0) + 1
                parts = sorted(set(parts), key=pv["labels"].index)
                sets.append(parts)
                statuses.append(VALID if parts else UNMAPPED)
            df[f"{c}__set"] = pd.Series([";".join(p) if p else None for p in sets], index=df.index, dtype=object)
            df[f"{c}__n"] = [len(p) for p in sets]
            for lab in pv["labels"]:
                slug = slugs.get(lab, re.sub(r"\W+", "_", lab.lower()).strip("_"))
                df[f"{c}_{slug}"] = [lab in p for p in sets]
            df[f"{c}__status"] = statuses
            df = df.drop(columns=c)
            unk = unknown
        else:
            res = raw.map(lambda v: map_value(v, pv))
            labels = res.map(lambda r: r[0])
            df[f"{c}__status"] = res.map(lambda r: r[2])
            for how, n in res.map(lambda r: r[1]).value_counts().items():
                methods_report.setdefault(c, {})[how] = int(n)
            if pv["codes"]:  # ordinal / coded vocab -> store the code, e.g. Likert 1..5
                df[c] = labels.map(lambda l: pv["codes"][l] if not is_blank(l) else np.nan).astype(float) \
                    if all(isinstance(x, (int, float)) for x in pv["codes"].values()) \
                    else labels.map(lambda l: pv["codes"][l] if not is_blank(l) else None)
            else:
                df[c] = labels
            unk = raw[df[f"{c}__status"] == UNMAPPED].value_counts().to_dict()

        if unk:
            unmapped_report[c] = unk
            llm = {}
            if suggest_fn is not None:
                try:
                    llm = suggest_fn(vname, list(unk), pv["labels"]) or {}
                except Exception as e:  # an LLM failure must never break cleaning
                    audit.warn(f"suggest_fn failed for {c}: {e}")
            for rv, n in unk.items():
                if rv in llm:
                    sug, score, by = llm[rv], None, "llm"
                else:
                    sug, score = _suggest(rv, pv)
                    by = "fuzzy (below auto-accept threshold)" if sug else None
                audit.queue(vocab=vname, column=c, raw_value=rv, count=int(n),
                            suggestion=sug, suggestion_score=score, suggested_by=by)

    audit.log("Standardize categories",
              "Mapped Likert, county, role and language labels to canonical values. "
              "Multi-select roles become one flag per role, so a parent who is also staff counts in both groups "
              "but only once in each. Unrecognised labels are queued for review, never guessed.",
              mapping_methods=methods_report, unmapped=unmapped_report)
    return df


# ----------------------------------------------------------------------------------------
# Step 8: survey version detection (structural vs. item missingness)
# ----------------------------------------------------------------------------------------
def detect_survey_versions(df: pd.DataFrame, cfg: dict, audit: Audit) -> pd.DataFrame:
    df = df.copy()
    vc = cfg["versioning"]
    keys = [k for k in vc["session_keys"] if k in df.columns]
    items = [c for c, s in cfg["columns"].items() if s.get("versioned") and f"{c}__status" in df.columns]
    if not keys or not items:
        audit.log("Detect survey versions", "Skipped: no session keys or versioned questions present.")
        return df
    def _k(v):
        if is_blank(v) or (not isinstance(v, str) and pd.isna(v)):
            return "unknown"
        return v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v)
    session = pd.Series([" | ".join(_k(v) for v in row) for row in df[keys].itertuples(index=False)],
                        index=df.index)
    df["session_key"] = session
    n = session.map(session.value_counts())
    report = {}
    for c in items:
        st = df[f"{c}__status"]
        rate = st.isin(ANSWERED).groupby(session).transform("mean")
        blank = st.eq(SKIPPED)
        big = n >= vc["min_session_n"]
        not_asked = blank & big & (rate <= vc["not_asked_max_rate"])
        skipped = blank & big & (rate >= vc["skipped_min_rate"])
        unclear = blank & ~not_asked & ~skipped
        df.loc[not_asked, f"{c}__status"] = NOT_ASKED
        df.loc[unclear, f"{c}__status"] = UNCLEAR_ASKED
        report[c] = df[f"{c}__status"].value_counts().to_dict()
    asked = pd.DataFrame({c: df[f"{c}__status"].ne(NOT_ASKED) for c in items})
    sig = asked.groupby(session).agg(lambda s: s.mean() > 0.5)
    versions = sig.apply(lambda r: "+".join(c for c in items if r[c]) or "(none of the optional questions)", axis=1)
    df["form_version"] = session.map(versions)
    audit.log("Detect survey versions",
              f"Grouped responses into {session.nunique()} sessions by {keys}. A blank counts as 'not asked' when "
              f"≤{vc['not_asked_max_rate']:.0%} of a session (n ≥ {vc['min_session_n']}) answered that question, as "
              f"'skipped' when ≥{vc['skipped_min_rate']:.0%} did, otherwise 'unclear'. "
              f"Found {versions.nunique()} form versions.",
              status_by_item=report, sessions_per_version=versions.value_counts().to_dict())
    return df


# ----------------------------------------------------------------------------------------
# Step 9: free text
# ----------------------------------------------------------------------------------------
_ES = {"el", "la", "los", "las", "de", "que", "y", "en", "por", "para", "con", "es", "una", "un", "muy", "más", "mas",
       "pero", "como", "sobre", "fue", "nos", "mi", "lo", "se", "al", "del", "aprendí", "aprendi", "ayuda", "gracias",
       "entrenamiento", "nada", "todo", "bien", "cómo", "qué", "puedo", "personas", "salud", "ayudar", "llamar"}
_EN = {"the", "and", "to", "of", "is", "it", "was", "for", "that", "this", "about", "more", "how", "what", "i", "you",
       "my", "with", "be", "on", "in", "can", "learned", "people", "help", "someone", "when", "use", "call", "nothing"}


def detect_language(text: str, fallback: str = "unknown") -> str:
    toks = re.findall(r"[a-záéíóúñü]+", text.casefold())
    if not toks:
        return fallback
    es = sum(t in _ES for t in toks) + 2 * len(re.findall(r"[áéíóúñ¿¡]", text.casefold()))
    en = sum(t in _EN for t in toks)
    if es > en:
        return "es"
    if en > es:
        return "en"
    return fallback


def classify_response(text: str, unclear: set, none_: set, keep: set = frozenset()) -> str:
    k = match_key(text)
    if k in keep:
        return "substantive"                        # short but meaningful, e.g. "988"
    if not k:
        return "blank" if not text else "unclear"   # only punctuation, e.g. "...", "?"
    if not re.search(r"[^\W\d_]", k):
        return "unclear"                            # digits only
    if k in unclear:
        return "unclear"
    if k in none_:
        return "none_stated"
    if re.fullmatch(r"(nothing|none|no|nope|nah|nada)\b.{0,25}\b(good|great|fine|perfect|amazing|awesome|bien)\b.{0,10}", k):
        return "none_stated"
    return "substantive"


def process_text(df: pd.DataFrame, cfg: dict, audit: Audit,
                 translate_fn: Optional[Callable[[list, str], list]] = None):
    """Classify comments, detect language, flag distress, redact via the privacy tool.

    Returns (public_df, private_df). Raw comments and distress flags exist ONLY in private_df.
    translate_fn(texts, source_lang) -> list[str] is an optional LLM hook; it only ever
    receives text that the privacy tool has already redacted.
    """
    df = df.copy()
    originals = df.attrs.pop("source_originals", {})
    source_rows = df[SOURCE_ROW].tolist() if SOURCE_ROW in df else list(range(2, len(df) + 2))
    df = df.drop(columns=SOURCE_ROW, errors="ignore")
    df.attrs.pop("source_rows", None)
    t = cfg["text"]
    unclear = {match_key(x) for x in t["unclear_phrases"]} | {""}
    none_ = {match_key(x) for x in t["none_phrases"]}
    keep = {match_key(x) for x in t.get("meaningful_short_answers", [])}
    distress_re = re.compile(r"\b(" + "|".join(re.escape(match_key(x)) for x in t["distress_terms"]) + r")\b")
    text_cols = [c for c, s in cfg["columns"].items() if s["type"] == "text" and c in df.columns]
    private = pd.DataFrame({"response_id": df["response_id"]})
    private["source_row"] = source_rows
    private["original_id"] = [originals.get(row, {}).get("response_id", str(identifier))
                              for row, identifier in zip(source_rows, df["response_id"])]
    connected = privacy_adapter.is_connected()
    audit.privacy_tool = privacy_adapter.tool_name()
    report = {}
    review = []

    form_lang = df["form_language"] if "form_language" in df.columns else pd.Series(["unknown"] * len(df), index=df.index)
    form_lang = form_lang.map({"English": "en", "Spanish": "es", "en": "en", "es": "es"}).fillna("unknown")

    for c in text_cols:
        raw = df[c].map(lambda v: "" if is_blank(v) else str(v))
        lang = pd.Series([detect_language(x, fb) if x else "none" for x, fb in zip(raw, form_lang)], index=df.index)
        cat = raw.map(lambda x: classify_response(x, unclear, none_, keep))
        distress = raw.map(lambda x: bool(distress_re.search(match_key(x))) if x else False)
        df[f"{c}__lang"] = lang
        df[f"{c}__category"] = cat
        df[f"{c}__has_question_mark"] = raw.str.contains(r"\?", regex=True) & cat.eq("substantive")
        df[f"{c}__chars"] = raw.str.len()
        private[c] = raw.where(raw != "", None)
        verbatim = [originals.get(row, {}).get(c, text) for row, text in zip(source_rows, raw)]
        private[f"{c}__original"] = verbatim
        private[f"{c}__distress_flag"] = distress

        red = privacy_adapter.redact_texts(raw.tolist(), lang.tolist())
        details = privacy_adapter.review_details() if red is not None else None
        if details is not None and len(details) != len(raw):
            raise ValueError("Privacy review details must align with the comment batch")
        if red is None:
            df[f"{c}__redacted"] = None
            df[f"{c}__privacy"] = np.where(raw != "", "pending", "blank")
        else:
            df[f"{c}__redacted"] = pd.Series(red, index=df.index).where(raw != "", None)
            df[f"{c}__privacy"] = np.where(raw != "", "redacted", "blank")

        for position, (source_row, text, language) in enumerate(zip(source_rows, raw, lang)):
            replacement = red[position] if red is not None else ""
            status = ("blank" if not text.strip() else "pending" if red is None
                      else "changed" if replacement != text else "unchanged")
            review.append({
                "source_row": source_row, "original_id": private["original_id"].iloc[position],
                "response_id": str(df["response_id"].iloc[position]), "field": c,
                "source_field": df.attrs.get("column_methods", {}).get(c, (c,))[0],
                "source_language": originals.get(source_row, {}).get("form_language", ""),
                "form_language": form_lang.iloc[position], "language": language,
                "original_text": verbatim[position], "normalized_input": text,
                "redacted_text": replacement, "normalization_changed": verbatim[position] != text,
                "status": status,
                "detections": json.dumps(details[position]["detections"] if details is not None else [], ensure_ascii=False),
            })

        if translate_fn is not None:
            if not connected:
                audit.warn(f"Translation of `{c}` skipped: privacy tool not connected, so no text may go to an LLM.")
            else:
                es = lang.eq("es") & df[f"{c}__redacted"].notna()
                df[f"{c}__english"] = df[f"{c}__redacted"].where(~es)
                if es.any():
                    df.loc[es, f"{c}__english"] = translate_fn(df.loc[es, f"{c}__redacted"].tolist(), "es")
        df = df.drop(columns=c)
        report[c] = {"categories": cat.value_counts().to_dict(),
                     "languages": lang[raw != ""].value_counts().to_dict(),
                     "distress_flags": int(distress.sum())}

    audit.log("Process free text",
              f"Classified {len(text_cols)} comment field(s) (blank / unclear / none_stated / substantive), detected "
              f"language, and checked for distress language. Privacy tool: "
              f"{'connected (' + privacy_adapter.tool_name() + ')' if connected else 'NOT connected; redacted columns left pending'}. "
              "Raw comments and distress flags are written only to the private folder.",
              details=report)
    private.attrs["privacy_review"] = review
    private.attrs["privacy_summary"] = summarize_privacy(review, privacy_adapter.versions(), connected)
    return df, private


def summarize_privacy(review, versions, connected):
    statuses, entities = Counter(), Counter()
    languages = {}
    mismatches = 0
    for record in review:
        status, language = record["status"], record["language"]
        statuses[status] += 1
        counts = languages.setdefault(language, {"comments": 0, "changed": 0, "unchanged": 0,
                                                "blank": 0, "pending": 0, "detections": Counter()})
        counts["comments"] += 1
        counts[status] += 1
        if status != "blank" and record["form_language"] in ("en", "es") and language != record["form_language"]:
            mismatches += 1
        for detection in json.loads(record["detections"]):
            entities[detection["entity_type"]] += 1
            counts["detections"][detection["entity_type"]] += 1
    return {
        "comments": len(review), "scanned": statuses["changed"] + statuses["unchanged"],
        **{status: statuses[status] for status in ("changed", "unchanged", "blank", "pending")},
        "normalization_changed": sum(record["normalization_changed"] for record in review),
        "form_language_disagreements": mismatches,
        "detections_by_entity_type": dict(sorted(entities.items())), "by_language": languages,
        "versions": versions, "tool_connected": connected,
        "routing": "John's existing per-comment detect_language with form-language fallback",
        "offset_basis": "normalized_input; zero-based Python characters, exclusive end",
        "review_required": True,
    }


# ----------------------------------------------------------------------------------------
# Step 10: quality flags (never delete)
# ----------------------------------------------------------------------------------------
def quality_flags(df: pd.DataFrame, cfg: dict, audit: Audit) -> pd.DataFrame:
    df = df.copy()
    q = cfg["quality"]

    def valid(c):
        return df[c].where(df[f"{c}__status"] == VALID) if c in df.columns else pd.Series(np.nan, index=df.index)

    if "duration_seconds" in df.columns:
        df["flag_fast"] = df["duration_seconds"] < q["min_duration_seconds"]
    else:
        df["flag_fast"] = False
        audit.disabled.append("Speed flag disabled: no start/completion times.")

    items = [c for c in q["straightline_items"] if c in df.columns]
    vals = pd.DataFrame({c: valid(c) for c in items})
    df["flag_straightline"] = (vals.notna().sum(axis=1) >= min(q["straightline_min_items"], len(items))) \
        & (vals.nunique(axis=1) == 1)

    m = q["misread"]
    post = pd.DataFrame({c: valid(c) for c in m["post_items"] if c in df.columns})
    asp = pd.DataFrame({c: valid(c) for c in m["aspect_items"] if c in df.columns})
    if len(post.columns) and len(asp.columns):
        df["flag_scale_misread"] = post.eq(m["post_value"]).any(axis=1) \
            & (asp.notna().sum(axis=1) >= m["aspect_min_items"]) & (asp.mean(axis=1) >= m["aspect_min_mean"])
    else:
        df["flag_scale_misread"] = False

    flags = ["flag_fast", "flag_straightline", "flag_scale_misread"]
    df["n_quality_flags"] = df[flags].sum(axis=1)
    counts = {f: int(df[f].sum()) for f in flags}
    audit.log("Quality flags",
              f"Flagged (kept) {counts}. {int((df.n_quality_flags > 0).sum())} rows have at least one flag. "
              "Analyses should report results with and without flagged rows.",
              definitions={"flag_fast": f"completed in under {q['min_duration_seconds']}s",
                           "flag_straightline": f"identical answer on all {q['straightline_min_items']} rating items",
                           "flag_scale_misread": f"value {m['post_value']} on {m['post_items']} while rating the "
                                                 f"training aspects ≥ {m['aspect_min_mean']} on average"},
              overlap=df[flags].apply(lambda r: "+".join(f for f in flags if r[f]) or "none", axis=1)
              .value_counts().to_dict())
    return df


# ----------------------------------------------------------------------------------------
# Step 11: derived analysis-ready fields
# ----------------------------------------------------------------------------------------
def derive_fields(df: pd.DataFrame, cfg: dict, audit: Audit) -> pd.DataFrame:
    df = df.copy()
    thr = cfg.get("agree_threshold", 4)
    for name, (b, a) in cfg["pairs"].items():
        vb, va = df[f"{b}__status"] == VALID, df[f"{a}__status"] == VALID
        df[f"{name}__paired_valid"] = vb & va
        df[f"{name}__agree_before"] = (df[b] >= thr).where(vb).astype("boolean")
        df[f"{name}__agree_after"] = (df[a] >= thr).where(va).astype("boolean")
        df[f"{name}__change"] = (df[a] - df[b]).where(vb & va)
    audit.log("Derive fields",
              f"Added paired-valid indicators, agreement (≥{thr}) before/after, and point change for "
              f"{len(cfg['pairs'])} before/after items. Note: 'before' is recalled after the training "
              "(retrospective self-report).",
              paired_valid={n: int(df[f"{n}__paired_valid"].sum()) for n in cfg["pairs"]})
    return df


# ----------------------------------------------------------------------------------------
# Step 12: validation
# ----------------------------------------------------------------------------------------
def validate(df: pd.DataFrame, private: pd.DataFrame, cfg: dict, audit: Audit) -> pd.DataFrame:
    rows = []

    def chk(name, ok, detail=""):
        rows.append({"check": name, "pass": bool(ok), "detail": detail})

    text_cols = [c for c, s in cfg["columns"].items() if s["type"] == "text"]
    chk("No raw comment columns in public output", not any(c in df.columns for c in text_cols))
    chk("No distress flags in public output", not any("distress" in c for c in df.columns))
    n_dup = int(df.response_id.duplicated(keep=False).sum())
    chk("Response IDs unique", n_dup == 0, f"{n_dup} rows share an ID (flagged for operator)" if n_dup else "")
    for c, s in cfg["columns"].items():
        if s["type"] == "scale" and c in df.columns:
            v = df[c].dropna()
            chk(f"{c} within [{s['min']}, {s['max']}]", v.between(s["min"], s["max"]).all())
        if s["type"] == "likert5" and c in df.columns:
            v = df[c].dropna()
            chk(f"{c} within 1–5", v.between(1, 5).all())
            if s.get("required"):
                rate = (df[f"{c}__status"] == VALID).mean()
                chk(f"{c} valid rate ≥ 90%", rate >= 0.9, f"{rate:.1%}")
    canaries = cfg["text"].get("privacy_canaries", [])
    if canaries and privacy_adapter.is_connected():
        red = df[[c for c in df.columns if c.endswith("__redacted")]].astype(str).agg(" ".join, axis=1).str.casefold()
        leaked = [cn for cn in canaries if red.str.contains(re.escape(cn.casefold())).any()]
        chk("Privacy canaries absent from redacted text", not leaked, f"leaked: {leaked}" if leaked else "")
    out = pd.DataFrame(rows)
    audit.log("Validate", f"{int(out['pass'].sum())}/{len(out)} checks passed.",
              failed=out.loc[~out["pass"], "check"].tolist())
    return out


# ----------------------------------------------------------------------------------------
# Headline numbers (used to check the pipeline against independently computed values)
# ----------------------------------------------------------------------------------------
def headline_numbers(df: pd.DataFrame, cfg: dict) -> dict:
    thr = cfg.get("agree_threshold", 4)
    out = {"n_responses": len(df)}
    for name, (b, a) in cfg["pairs"].items():
        out[f"{name}: agree before"] = int((df[b] >= thr).sum())
        out[f"{name}: agree after"] = int((df[a] >= thr).sum())
    if "role_student" in df.columns:
        stu = df["role_student"]
        non = (df["role__status"] == VALID) & ~stu
        out["n_students"] = int(stu.sum())
        if "recommend" in df.columns:
            out["recommend mean (students)"] = round(float(df.loc[stu, "recommend"].mean()), 2)
            out["recommend n (students)"] = int(df.loc[stu, "recommend"].notna().sum())
            out["recommend mean (non-students)"] = round(float(df.loc[non, "recommend"].mean()), 2)
            out["recommend n (non-students)"] = int(df.loc[non, "recommend"].notna().sum())
        both = (df["describe_after__status"] == VALID) & (df["when_after__status"] == VALID)
        unsure = both & ((df["describe_after"] < thr) | (df["when_after"] < thr))
        out["unsure on either 988 post item"] = int(unsure.sum())
        out["...of whom students"] = int((unsure & stu).sum())
    if "call_intent" in df.columns:
        out["call intent valid n"] = int((df["call_intent__status"] == VALID).sum())
    return out


def check_expected(actual: dict, expected: dict) -> pd.DataFrame:
    rows = []
    for k, exp in expected.items():
        act = actual.get(k)
        ok = act is not None and (abs(act - exp) < 0.006 if isinstance(exp, float) else act == exp)
        rows.append({"metric": k, "expected": exp, "actual": act, "pass": ok})
    return pd.DataFrame(rows).astype({"expected": object, "actual": object})


# ----------------------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------------------
@dataclass
class Result:
    data: pd.DataFrame
    private: pd.DataFrame
    audit: Audit
    checks: pd.DataFrame
    privacy_review: pd.DataFrame = field(default_factory=pd.DataFrame)
    privacy_summary: dict = field(default_factory=dict)

    def __post_init__(self):
        review = self.private.attrs.pop("privacy_review", [])
        summary = self.private.attrs.pop("privacy_summary", {})
        if self.privacy_review.empty:
            self.privacy_review = pd.DataFrame(review, columns=PRIVACY_REVIEW_COLUMNS)
        if not self.privacy_summary:
            self.privacy_summary = summary
        if self.privacy_summary:
            self.privacy_summary.update(data_rows=len(self.data), columns=len(self.data.columns))


def run_pipeline(source, schema_path, registry_path=None, filename=None,
                 suggest_fn=None, translate_fn=None) -> Result:
    cfg = load_config(schema_path, registry_path)
    audit = Audit()
    df = ingest(source, cfg, audit, filename=filename)
    df = match_columns(df, cfg, audit)
    df = drop_structured_pii(df, cfg, audit)
    df = normalize_values(df, cfg, audit)
    df = deduplicate(df, cfg, audit)
    df = parse_types(df, cfg, audit)
    df = standardize(df, cfg, audit, suggest_fn=suggest_fn)
    df = detect_survey_versions(df, cfg, audit)
    df, private = process_text(df, cfg, audit, translate_fn=translate_fn)
    df = quality_flags(df, cfg, audit)
    df = derive_fields(df, cfg, audit)
    checks = validate(df, private, cfg, audit)
    return Result(df, private, audit, checks)


def write_outputs(result: Result, out_dir, private_dir) -> dict:
    """Stage and verify all outputs before replacing any existing result files."""
    if __package__:
        from .output_utils import finalize_outputs
    else:
        from output_utils import finalize_outputs

    if not result.checks["pass"].all():
        raise ValueError("Validation failed; no results published. Inspect Result.checks locally.")
    out_dir, private_dir = Path(out_dir), Path(private_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)
    key = result.audit.dataset_key
    paths = {
        "cleaned": out_dir / f"cleaned_{key}.csv",
        "audit": out_dir / f"audit_report_{key}.md",
        "review": out_dir / f"mapping_review_{key}.csv",
        "private_comments": private_dir / f"comments_private_{key}.csv",
        "distress_review": private_dir / f"distress_review_{key}.csv",
    }
    flags = [c for c in result.private.columns if c.endswith("__distress_flag")]
    tables = {
        "cleaned": result.data, "review": result.audit.review_table(),
        "private_comments": result.private,
        "distress_review": result.private[result.private[flags].any(axis=1)],
    }
    if result.privacy_summary:
        paths["privacy_review"] = private_dir / f"presidio_review_{key}.csv"
        paths["privacy_summary"] = out_dir / f"presidio_summary_{key}.json"
        tables["privacy_review"] = result.privacy_review
    with tempfile.TemporaryDirectory(prefix=".cleaning-", dir=out_dir) as directory:
        staged = {name: Path(directory) / destination.name for name, destination in paths.items()}
        for name, table in tables.items():
            payload = table.to_csv(index=False)
            staged[name].write_text(payload, encoding="utf-8", newline="")
            with staged[name].open(encoding="utf-8", newline="") as handle:
                if list(csv.reader(handle, strict=True)) != list(csv.reader(io.StringIO(payload, newline=""), strict=True)):
                    raise ValueError("Temporary CSV verification failed; no results published.")
        staged["audit"].write_text(result.audit.to_markdown(), encoding="utf-8")
        if "privacy_summary" in staged:
            payload = json.dumps(result.privacy_summary, ensure_ascii=False, indent=2) + "\n"
            staged["privacy_summary"].write_text(payload, encoding="utf-8")
            if json.loads(staged["privacy_summary"].read_text()) != result.privacy_summary:
                raise ValueError("Temporary summary verification failed; no results published.")
        finalize_outputs([(staged[name], destination) for name, destination in paths.items()])
    return paths
