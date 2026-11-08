"""Local import adapter for the supplied EveryMind survey export."""
import hashlib
import io
import json
from pathlib import Path
import re

import pandas as pd

EXPORT_COLUMNS = json.loads(Path(__file__).with_name("export_columns.json").read_text(encoding="utf-8"))
KNOWLEDGE = [f"q{i}_knowledge" for i in range(1, 7)]
PRESENTER = ["presenter_engagement", "presenter_knowledge", "training_organization"]
COMMENT_FIELDS = ["most_valuable", "how_can_we_improve"]
AGREEMENT = {"strongly disagree": 1, "disagree": 2, "neither agree nor disagree": 3,
             "neutral": 3, "agree": 4, "strongly agree": 5}
ROLE_ALIASES = {"student": "Student", "students": "Student",
                "school staff member": "School staff", "school staff": "School staff",
                "caregiver/parent": "Caregiver/parent",
                "other (e.g., community member)": "Community member", "community member": "Community member"}


def normalize_header(value):
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


def _text(value):
    return "" if pd.isna(value) else str(value).strip()


def _score(value, agreement=False):
    text = normalize_header(_text(value))
    if not text:
        return None, "missing"
    if agreement and text in AGREEMENT:
        return AGREEMENT[text], "valid"
    try:
        number = float(text)
        low, high = (1, 5) if agreement else (0, 10)
        if number.is_integer() and low <= number <= high:
            return int(number), "valid"
    except ValueError:
        pass
    return None, "unmapped"


def load_export(file_bytes: bytes, filename: str):
    """Return dataset key, structural responses, LOCAL private comments, audit.

    Header matching is order/case/whitespace independent. Equivalent CSV/XLSX
    content yields one key; changed source content invalidates that key.
    No files, caches, or provider calls are created here.
    """
    suffix = Path(filename).suffix.lower()
    if suffix == ".xlsx":
        raw = pd.read_excel(io.BytesIO(file_bytes), sheet_name="Survey Data", dtype=object)
    elif suffix == ".csv":
        raw = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8-sig", dtype=object)
    else:
        raise ValueError("Upload an XLSX workbook or UTF-8 CSV export.")
    lookup = {normalize_header(header): key for key, header in EXPORT_COLUMNS.items()}
    lookup.update({key: key for key in EXPORT_COLUMNS})
    columns = [lookup.get(normalize_header(c), normalize_header(c)) for c in raw.columns]
    if len(columns) != len(set(columns)):
        raise ValueError("Duplicate or ambiguous survey columns after header normalization.")
    raw.columns = columns
    missing = [key for key in ["id", *KNOWLEDGE] if key not in raw]
    if missing:
        raise ValueError("Missing required fields: " + "; ".join(f"{k}: {EXPORT_COLUMNS[k]}" for k in missing))
    ids = raw["id"].map(_text)
    if ids.eq("").any():
        raise ValueError("Missing response ID; resolve before loading this export.")
    if ids.duplicated().any():
        raise ValueError("Duplicate response IDs; resolve locally before replacing the active dataset.")
    raw["id"] = ids
    # Hash source content, not filename/container metadata; preserve exact comments.
    canonical = raw.reindex(sorted(raw.columns), axis=1).copy()
    for field in canonical:
        if field in KNOWLEDGE + PRESENTER + ["recommendation", "intent"]:
            def canonical_score(value):
                score, status = _score(value, field in KNOWLEDGE + PRESENTER)
                return str(score) if status == "valid" else (None if status == "missing" else str(value))
            canonical[field] = canonical[field].map(canonical_score)
        else:
            canonical[field] = canonical[field].map(lambda v: None if pd.isna(v) else str(v))
    payload = json.dumps(canonical.to_dict("records"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    key = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    responses = pd.DataFrame({"id": ids})
    if "role" in raw:
        def roles(value):
            return sorted({ROLE_ALIASES.get(normalize_header(token), token.strip())
                           for token in _text(value).split(";") if token.strip()})
        responses["role_membership"] = raw["role"].map(roles)
    else:
        responses["role_membership"] = [[] for _ in range(len(raw))]
    audit = dict(total_rows=len(raw), unique_responses=len(raw), columns_mapped=list(raw.columns),
                 dataset_key=key, missing_optional=[k for k in EXPORT_COLUMNS if k not in raw],
                 has_optional_intent="intent" in raw, invalid_counts={}, missing_counts={})
    for field in KNOWLEDGE + PRESENTER + ["recommendation", "intent"]:
        if field not in raw:
            continue
        values = raw[field].map(lambda v: _score(v, field in KNOWLEDGE + PRESENTER))
        responses[field] = pd.Series([v[0] for v in values], index=raw.index, dtype=object)
        responses[f"{field}_status"] = [v[1] for v in values]
        audit["invalid_counts"][field] = int(responses[f"{field}_status"].eq("unmapped").sum())
        audit["missing_counts"][field] = int(responses[f"{field}_status"].eq("missing").sum())
    for field in ["language", "county"]:
        if field in raw:
            responses[field] = raw[field].map(lambda v: _text(v) or None)
    for field in ["start_time", "completion_time", "training_date"]:
        if field in raw:
            parsed = pd.to_datetime(raw[field], errors="coerce", format="mixed")
            responses[field] = parsed.map(lambda v: None if pd.isna(v) else (v.date().isoformat() if field == "training_date" else v.isoformat()))
            audit["invalid_counts"][field] = int((parsed.isna() & raw[field].map(_text).ne("")).sum())
    private = []
    for i, row in raw.iterrows():
        for field in COMMENT_FIELDS:
            if field not in raw:
                continue
            original = "" if pd.isna(row[field]) else str(row[field])
            private.append(dict(private_record_key=f"{row['id']}:{field}", response_id=row["id"],
                                source_field=field, role_membership=responses.at[i, "role_membership"],
                                language=_text(row.get("language", "")) or None, original_text=original,
                                content_fingerprint=hashlib.sha256(original.encode("utf-8")).hexdigest(),
                                reviewer_status="pending", approved_paraphrase=None, theme_ids=[]))
    audit["private_comment_records"] = len(private)
    return key, responses, pd.DataFrame(private), audit
