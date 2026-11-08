"""
release.py - release gate and output contract on top of everymind_clean.py.

Use `run_pipeline` (or `clean_frame` on an in-memory export) for anything that will be shared.
It adds strict header and score parsing, partial-role handling, inferred question availability,
nullable quality flags, blocking-vs-warning release checks, and one documented export:

    outputs/cleaned_<key>.csv   one row per response, no comment text
    outputs/fields_<key>.json   schema version + field dictionary (dtype, meaning) for every column
    outputs/audit_<key>.json    checks (block / warn), missingness and review counts; no raw values
    outputs/manifest_<key>.json input, config, code and package hashes

Read the export with `load_clean(path)`, never bare `pd.read_csv`, so IDs stay strings and
missing/unassessed values stay missing.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import everymind_clean as ec
import privacy_adapter

OUTPUT_SCHEMA_VERSION = "1.0"
SCORE_LABELS = {"0 - not at all likely": "0", "10 - extremely likely": "10"}
QUALITY_FLAGS = ["flag_fast", "flag_straightline", "flag_scale_misread"]
GROUPS = ["Student", "Nonstudent"]
FUZZY_MIN, FUZZY_MARGIN = 85, 5
PACKAGES = ["pandas", "numpy", "openpyxl", "rapidfuzz", "scipy", "statsmodels", "scikit-learn", "matplotlib"]

STATUS_MEANINGS = {
    ec.VALID: "usable answer",
    ec.SKIPPED: "blank; the question was on the form",
    "suspected_not_asked": "blank; inferred from session answer rates that the question was likely not on the form",
    ec.UNCLEAR_ASKED: "blank; cannot tell whether the question was asked",
    ec.DECLINED: "N/A or prefer not to say",
    ec.UNMAPPED: "label not recognised; queued for human review",
    ec.INVALID: "out of range or unparseable",
    "partially_mapped": "multi-select answer with at least one unrecognised option",
    "not_in_export": "the column is absent from this export",
}


# ----------------------------------------------------------------------------------------
# Cleaning steps (wrap everymind_clean with stricter behaviour)
# ----------------------------------------------------------------------------------------
def match_input(raw, cfg, audit):
    keys = [ec.match_key(c) for c in raw.columns]
    if len(keys) != len(set(keys)):
        raise ec.SchemaError("Duplicate normalized headers; resolve privately before continuing.")
    for canon, spec in cfg["columns"].items():
        targets = [ec.match_key(canon), *map(ec.match_key, spec.get("synonyms", []))]
        candidates = [k for k in keys if ec._allowed(spec, k)]
        exact = [k for k in candidates if k in targets]
        if len(exact) > 1:
            raise ec.SchemaError(f"Multiple columns match {canon}; resolve before continuing.")
        if not exact and ec.fuzz is not None:
            scores = sorted([max(ec.fuzz.token_sort_ratio(k, t) for t in targets)
                             for k in candidates], reverse=True)
            if len(scores) > 1 and scores[0] >= FUZZY_MIN and scores[1] >= max(FUZZY_MIN, scores[0] - FUZZY_MARGIN):
                raise ec.SchemaError(f"Ambiguous fuzzy match for {canon}; add an exact schema synonym.")
    try:
        df = ec.match_columns(raw, cfg, audit)
    except ec.SchemaError:
        raise ec.SchemaError("Required schema fields could not be matched; inspect headers privately.") from None
    absent = [c for c, s in cfg["columns"].items()
              if not s.get("required") and s["type"] != "drop" and c not in df]
    for c in absent:
        df[c] = None  # stable schema, with absence preserved explicitly below
    df.attrs["absent_columns"] = absent
    return df


def parse_input(df, cfg, audit):
    raw_scales = {c: df[c].copy() for c, s in cfg["columns"].items() if s["type"] == "scale" and c in df}
    parsed = ec.parse_types(df, cfg, audit)
    for c, raw in raw_scales.items():
        tokens = raw.map(lambda x: SCORE_LABELS.get(ec.clean_str(x).casefold(), ec.clean_str(x)))
        numeric = tokens.str.fullmatch(r"[+-]?\d+(?:\.0+)?").fillna(False)
        num = pd.to_numeric(tokens.where(numeric), errors="coerce")
        spec = cfg["columns"][c]
        valid = numeric & num.between(spec["min"], spec["max"])
        blank = raw.isna() | tokens.eq("")
        declined = tokens.map(ec.match_key).isin({"n a", "na", "not applicable", "prefer not to say", "prefer not to answer"})
        parsed[c] = num.where(valid).astype(float)
        parsed[c + "__status"] = np.select([blank, declined, valid], [ec.SKIPPED, ec.DECLINED, ec.VALID], default=ec.INVALID)
        audit.steps[-1]["details"][c]["out_of_range_or_unparseable"] = int(parsed[c + "__status"].eq(ec.INVALID).sum())
    return parsed


def standardize_input(df, cfg, audit):
    roles = df["role"].copy()
    out = ec.standardize(df, cfg, audit)
    pv = ec._prep_vocab(cfg["vocab"]["role"])
    unknown = roles.map(lambda v: bool(ec.split_multiselect(v, pv, cfg["vocab"]["role"])[2]))
    out["role__has_unmapped"] = unknown
    partial = unknown & out["role__n"].gt(0)
    out.loc[partial, "role__status"] = "partially_mapped"
    for c in [c for c in out if c.startswith("role_") and not c.startswith("role__")]:
        out[c] = out[c].astype("boolean")
        out.loc[~out[c] & out["role__status"].ne(ec.VALID), c] = pd.NA
    return out


def infer_availability(df, cfg, audit):
    before = df.copy()
    out = ec.detect_survey_versions(df, cfg, audit)
    absent = set(out.attrs.get("absent_columns", []))
    keys = cfg["versioning"]["session_keys"]
    known_session = out[keys].notna().all(axis=1)
    signatures = {}
    for c, spec in cfg["columns"].items():
        st = c + "__status"
        if st not in out:
            if c in absent:
                out[st] = "not_in_export"
            continue
        if spec.get("versioned"):
            observed = before[st].isin(ec.ANSWERED)
            rate = observed.groupby(out.session_key).transform("mean")
            size = out.session_key.map(out.session_key.value_counts())
            out[c + "__observed_blank"] = before[st].eq(ec.SKIPPED).astype("boolean")
            out[c + "__session_answer_rate"] = rate.where(known_session)
            blank = before[st].eq(ec.SKIPPED)
            out.loc[blank & ~known_session, st] = ec.UNCLEAR_ASKED
            out[st] = out[st].replace({ec.NOT_ASKED: "suspected_not_asked"})
            state = np.select([~known_session | size.lt(cfg["versioning"]["min_session_n"]),
                               rate.le(cfg["versioning"]["not_asked_max_rate"]),
                               rate.ge(cfg["versioning"]["skipped_min_rate"])],
                              ["unknown", "suspected_absent", "observed"], default="unknown")
            signatures[c] = pd.Series(state if c not in absent else "not_in_export", index=out.index)
        if c in absent:
            out[st] = "not_in_export"
            if spec.get("versioned"):
                out[c + "__observed_blank"] = pd.NA
    out = out.drop(columns="form_version", errors="ignore")
    if signatures:
        out["form_version_inferred"] = pd.DataFrame(signatures).apply(
            lambda r: ";".join(f"{c}:{v}" for c, v in r.items()), axis=1)
    audit.log("Notebook availability", "Availability inferred from response rates; not verified form metadata.")
    return out


def flag_quality(df, cfg, audit):
    out = ec.quality_flags(df, cfg, audit)
    q = cfg["quality"]
    assessed = {
        "flag_fast": out.duration_seconds.notna(),
        "flag_straightline": out[q["straightline_items"]].notna().sum(axis=1).ge(q["straightline_min_items"]),
        "flag_scale_misread": out[q["misread"]["post_items"]].notna().all(axis=1)
            & out[q["misread"]["aspect_items"]].notna().sum(axis=1).ge(q["misread"]["aspect_min_items"]),
    }
    for c, known in assessed.items():
        out[c] = out[c].astype("boolean").where(known)
    out["n_quality_flags"] = out[QUALITY_FLAGS].sum(axis=1, min_count=1).astype("Int64")
    out["n_quality_checks_assessed"] = out[QUALITY_FLAGS].notna().sum(axis=1)
    return out


def comparison_group(df):
    """Student = selected Student (alone or with other roles); Nonstudent = fully mapped role without Student;
    Unknown = blank or partially mapped role without Student."""
    student = df["role_student"].eq(True).fillna(False)
    nonstudent = df["role__status"].eq(ec.VALID) & df["role_student"].eq(False).fillna(False)
    return pd.Series(np.select([student, nonstudent], GROUPS, default="Unknown"), index=df.index, dtype="string")


def derive_release_fields(df, cfg, audit):
    out = ec.derive_fields(df, cfg, audit)
    return out.assign(comparison_group=comparison_group(out))


def public_data(df):
    # Never release comment strings, even when an adapter claims they were redacted.
    return df.drop(columns=[c for c in df if c.endswith(("__redacted", "__english"))]).copy()


def clean_frame(raw, cfg):
    audit = ec.Audit()
    df = ec.normalize_values(ec.drop_structured_pii(match_input(raw, cfg, audit), cfg, audit), cfg, audit)
    df = ec.deduplicate(df, cfg, audit)
    df = parse_input(df, cfg, audit)
    df = standardize_input(df, cfg, audit)
    df = infer_availability(df, cfg, audit)
    df, private = ec.process_text(df, cfg, audit)
    df = derive_release_fields(flag_quality(df, cfg, audit), cfg, audit)
    checks = release_checks(df, private, cfg, audit)
    return ec.Result(df, private, audit, checks)


def run_pipeline(source, schema_path, registry_path=None, filename=None):
    """XLSX/CSV path or bytes -> gated Result. The app and notebook should both use this."""
    cfg = ec.load_config(schema_path, registry_path)
    audit = ec.Audit()
    raw = ec.ingest(source, cfg, audit, filename=filename)
    result = clean_frame(raw, cfg)
    result.audit.steps[:0] = audit.steps
    result.audit.dataset_key, result.audit.source_name = audit.dataset_key, audit.source_name
    return result


# ----------------------------------------------------------------------------------------
# Release gate: blocking errors vs warnings
# ----------------------------------------------------------------------------------------
NOT_ANSWERED = {ec.SKIPPED, ec.DECLINED, ec.UNCLEAR_ASKED, "suspected_not_asked", "not_in_export"}
UNRECOGNISED = {ec.INVALID, ec.UNMAPPED, "partially_mapped"}
FORMULA_START = ("=", "+", "-", "@")


def _id_key(ids):
    """Collision key: '1', '1.0', '01', ' 1' and 'A1'/'a1' are the same respondent to a human."""
    k = ids.astype("string").str.strip().str.casefold().str.replace(r"\.0+$", "", regex=True)
    return k.str.lstrip("0").where(k.str.lstrip("0").ne(""), k)


def _drift_checks(df, cfg, audit):
    """Warnings for answers the cleaner could not read, and optional questions that vanished while
    unrecognised headers are present: both usually mean the export format changed."""
    rows, max_bad = [], cfg.get("max_unrecognised_rate", 0.05)
    for c, spec in cfg["columns"].items():
        st = df.get(c + "__status")
        if st is None or spec["type"] in {"text", "id", "drop"}:
            continue
        answered = ~st.isin(NOT_ANSWERED)
        bad = st.isin(UNRECOGNISED)
        rate = bad.sum() / answered.sum() if answered.any() else 0.0
        rows.append((f"{c}: unrecognised answers ≤ {max_bad:.0%}", rate <= max_bad, "warn",
                     f"{int(bad.sum())}/{int(answered.sum())} ({rate:.0%}); see private mapping review" if rate > max_bad else ""))
    match = next((st for st in audit.steps if st.get("step") == "Match columns"), {})
    absent = [c for c in match.get("missing_optional", []) if cfg["columns"][c]["type"] != "drop"]
    n_unmatched = len(match.get("unmatched_headers", []))
    rows.append(("Optional questions present, or no unrecognised headers", not (absent and n_unmatched), "warn",
                 f"absent: {absent}; {n_unmatched} unrecognised header(s); add synonyms if the wording changed"
                 if absent and n_unmatched else ""))
    return rows


def release_checks(df, private, cfg, audit):
    checks = ec.validate(public_data(df), private, cfg, audit)
    ids = df.response_id.astype("string")
    key = _id_key(ids)
    extra = [("At least one response", len(df) > 0, "block", ""),
             ("Response IDs nonblank", df.response_id.notna().all() and ids.str.strip().ne("").all(), "block", ""),
             ("Response IDs unambiguous ('1' vs '1.0'/'01'/case)",
              key.duplicated(keep=False).sum() == ids.duplicated(keep=False).sum(), "block", ""),
             ("Response IDs not formula-like", not ids.str.startswith(FORMULA_START).fillna(False).any(), "warn",
              "IDs starting with = + - @ can execute when the CSV is opened in a spreadsheet"),
             ("Private rows aligned one-to-one",
              private.response_id.reset_index(drop=True).equals(df.response_id.reset_index(drop=True)), "block", "")]
    for c, spec in cfg["columns"].items():
        if spec["type"] in {"scale", "likert5"} and c in df:
            extra.append((f"{c} value/status consistency", df[c].notna().eq(df[c + "__status"].eq(ec.VALID)).all(), "block", ""))
    extra += _drift_checks(df, cfg, audit)
    extra_df = pd.DataFrame([{"check": k, "pass": bool(v), "severity": sev, "detail": d} for k, v, sev, d in extra])
    return pd.concat([checks, extra_df], ignore_index=True)


def require_ready(checks):
    """Raise on any failed blocking check; return failed warnings (they restrict analyses, not release)."""
    failed = checks[~checks["pass"]]
    blocking = failed[failed.severity.eq("block")]
    if len(blocking):
        raise ValueError("Release blocked: " + "; ".join(blocking.check))
    warned = failed.loc[failed.severity.eq("warn"), "check"].tolist()
    for w in warned:
        warnings.warn(f"Release warning (analyses using this field may be restricted): {w}", stacklevel=2)
    return warned


# ----------------------------------------------------------------------------------------
# Output contract
# ----------------------------------------------------------------------------------------
def _describe(c, cfg):
    cols, pairs = cfg["columns"], cfg["pairs"]
    base, _, suffix = c.partition("__")
    if c in cols:
        spec = cols[c]
        extra = f" ({spec['min']}–{spec['max']})" if spec["type"] == "scale" else ""
        return f"{spec['type']}{extra} answer to: {spec['synonyms'][0].strip()}" + (" [required]" if spec.get("required") else "")
    fixed = {
        "comparison_group": "Student / Nonstudent / Unknown. Student = selected Student (with or without other roles); "
                            "Unknown = blank or partially mapped role without Student.",
        "session_key": "Inferred training session = training date × county ('unknown' when a part is missing). "
                       "Not a verified session roster.",
        "form_version_inferred": "Per optional question: observed / suspected_absent / unknown / not_in_export, "
                                 "inferred from session answer rates; not verified form metadata.",
        "duration_seconds": "completion_time − start_time in seconds; missing if negative or unparseable.",
        "survey_lag_days": "Days from training_date to survey start.",
        "flag_date_inconsistent": "Survey started before the training date or more than max_gap_days after it.",
        "flag_possible_duplicate": "Same answers and timestamps as another row (kept; flagged).",
        "flag_duplicate_id": "response_id shared with another row.",
        "flag_fast": "Quality flag: survey took under the minimum seconds. NA = not assessable (no timing).",
        "flag_straightline": "Quality flag: identical answers across the rating grid. NA = too few answered items.",
        "flag_scale_misread": "Quality flag: response pattern consistent with a reversed scale. NA = not assessable. "
                              "Descriptive, not proof of misunderstanding.",
        "n_quality_flags": "Count of true quality flags; NA when none could be assessed.",
        "n_quality_checks_assessed": "How many of the three quality flags could be assessed.",
        "role__set": "Recognised roles, ';'-separated.",
        "role__n": "Number of recognised roles.",
        "role__has_unmapped": "At least one selected role option was not recognised.",
    }
    if c in fixed:
        return fixed[c]
    if c.startswith("role_") and not suffix:
        return f"Selected role '{c[5:]}'. NA = unknown (role blank or partially mapped and this role not selected)."
    by_suffix = {
        "status": f"Why {base} is or is not usable; values in status_values.",
        "observed_blank": f"{base} was literally blank in the export.",
        "session_answer_rate": f"Share of this session that answered {base}; NA when the session is unknown.",
        "paired_valid": f"Before and after ratings of {base} are both valid.",
        "agree_before": f"{base} 'before' rating ≥ agree threshold; NA unless valid.",
        "agree_after": f"{base} 'after' rating ≥ agree threshold; NA unless valid.",
        "change": f"{base} after − before (retrospective self-report); NA unless paired_valid.",
        "lang": f"Detected language of the {base} comment (heuristic).",
        "category": f"{base} comment class: substantive / none_stated / unclear / blank (heuristic).",
        "has_question_mark": f"Substantive {base} comment contains '?'. Literal indicator, not 'asked a question'.",
        "chars": f"Length of the {base} comment in characters (text itself is private).",
        "privacy": f"Privacy-tool state for the {base} comment.",
    }
    if suffix in by_suffix and (base in cols or base in pairs):
        return by_suffix[suffix]
    raise KeyError(f"Undocumented output column '{c}': add it to release._describe before releasing.")


def _dtype(s):
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    if pd.api.types.is_bool_dtype(s) or (s.dtype == object and s.notna().any()
                                       and s.dropna().map(lambda v: isinstance(v, (bool, np.bool_))).all()):
        return "boolean"
    if pd.api.types.is_integer_dtype(s):
        return "Int64"
    if pd.api.types.is_float_dtype(s):
        return "float64"
    return "string"


def field_dictionary(public, cfg):
    statuses = sorted({v for c in public if c.endswith("__status") for v in public[c].dropna().unique()})
    unknown = [s for s in statuses if s not in STATUS_MEANINGS]
    if unknown:
        raise KeyError(f"Undocumented status values {unknown}: add them to release.STATUS_MEANINGS.")
    return {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "unit": "one row per survey response; no comment text",
        "id": "response_id (string)",
        "required": [c for c, s in cfg["columns"].items() if s.get("required") and c in public],
        "status_values": STATUS_MEANINGS,
        "fields": {c: {"dtype": _dtype(public[c]), "description": _describe(c, cfg)} for c in public},
    }


def load_clean(csv_path, fields_path=None):
    """Read cleaned_<key>.csv with the dtypes recorded in fields_<key>.json."""
    csv_path = Path(csv_path)
    fields_path = Path(fields_path or csv_path.with_name(csv_path.name.replace("cleaned_", "fields_", 1)).with_suffix(".json"))
    spec = json.loads(fields_path.read_text())
    if spec["schema_version"] != OUTPUT_SCHEMA_VERSION:
        raise ValueError(f"Export schema {spec['schema_version']} != loader {OUTPUT_SCHEMA_VERSION}; re-run the cleaner.")
    fields = spec["fields"]
    dates = [c for c, f in fields.items() if f["dtype"] == "datetime"]
    df = pd.read_csv(csv_path, dtype={c: f["dtype"] for c, f in fields.items() if f["dtype"] != "datetime"},
                     parse_dates=dates, keep_default_na=False, na_values=[""])
    if list(df.columns) != list(fields):
        raise ValueError("Export columns do not match its field dictionary.")
    return df


def safe_audit(result):
    review = result.audit.review_table()
    failed = result.checks[~result.checks["pass"]]
    return {"rows": len(result.data),
            "blocking_errors": failed.loc[failed.severity.eq("block"), "check"].tolist(),
            "warnings": failed.loc[failed.severity.eq("warn"), "check"].tolist(),
            "checks": result.checks[["check", "pass", "severity"]].to_dict("records"),
            "missingness": {c: result.data[c].value_counts().to_dict() for c in result.data if c.endswith("__status")},
            "review_counts": review.groupby(["vocab", "column"])["count"].sum().reset_index().to_dict("records")
                             if len(review) else [],
            "quality_flags": {c: int(result.data[c].sum()) for c in QUALITY_FLAGS},
            "availability_note": "Inferred from session response rates; not verified form metadata."}


def run_manifest(data_path, schema_path, registry_path, notebook_path=None):
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    manifest = {"output_schema_version": OUTPUT_SCHEMA_VERSION,
                "input_sha256": sha(data_path), "schema_sha256": sha(schema_path), "registry_sha256": sha(registry_path),
                "module_sha256": {m.__name__: sha(m.__file__) for m in [ec, privacy_adapter, sys.modules[__name__]]},
                "packages": {p: importlib.metadata.version(p) for p in PACKAGES}}
    if notebook_path:
        cells = json.loads(Path(notebook_path).read_text())["cells"]
        code = ["".join(c["source"]) for c in cells if c["cell_type"] == "code"]
        manifest["notebook_code_sha256"] = hashlib.sha256(json.dumps(code).encode()).hexdigest()
    manifest["run_key"] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:16]
    return manifest


def write_release(result, out_dir, private_dir, manifest, cfg):
    # Revalidate here; stale or edited results cannot bypass the release gate.
    result.checks = release_checks(result.data, result.private, cfg, result.audit)
    require_ready(result.checks)
    out_dir, private_dir = Path(out_dir), Path(private_dir)
    if out_dir.resolve() == private_dir.resolve():
        raise ValueError("Public and private output folders must differ.")
    public = public_data(result.data)
    dictionary = field_dictionary(public, cfg)  # fails before any file is written if a column is undocumented
    out_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = manifest["run_key"]
    paths = {"cleaned": out_dir / f"cleaned_{key}.csv", "fields": out_dir / f"fields_{key}.json",
             "audit": out_dir / f"audit_{key}.json", "manifest": out_dir / f"manifest_{key}.json"}
    public.to_csv(paths["cleaned"], index=False)
    paths["fields"].write_text(json.dumps(dictionary, indent=2, ensure_ascii=False))
    paths["audit"].write_text(json.dumps(safe_audit(result), indent=2, default=str))
    paths["manifest"].write_text(json.dumps(manifest, indent=2))
    result.private.to_csv(private_dir / f"comments_private_{key}.csv", index=False)
    result.audit.review_table().to_csv(private_dir / f"mapping_review_{key}.csv", index=False)
    (private_dir / f"audit_private_{key}.json").write_text(json.dumps(result.audit.__dict__, indent=2, default=str))
    flags = [c for c in result.private if c.endswith("__distress_flag")]
    result.private[result.private[flags].any(axis=1)].to_csv(private_dir / f"distress_review_{key}.csv", index=False)
    return paths
