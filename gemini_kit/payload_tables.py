"""Adapt current analysis JSON to the kit's table/cell citation contract."""
import json
from pathlib import Path

import pandas as pd


def load_payload_tables(path, include_approved_comments=False):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "everymind.analysis.v2":
        raise ValueError("Expected everymind.analysis.v2 from cleaned_analysis.py.")
    if not payload.get("dataset_key") or not payload.get("audience"):
        raise ValueError("Payload needs current dataset_key and audience.")
    tables = {}
    def add(name, rows, columns, description):
        if rows:
            frame = pd.DataFrame([{c: row.get(c) for c in columns} for row in rows], columns=columns)
            # Match the CSV loader's text representation, including blank nulls.
            tables[name] = (frame.fillna("").astype(str), description)
    add("payload_scope", [dict(dataset_key=payload["dataset_key"], audience=payload["audience"],
        status=payload.get("status"), semantic_evidence_status=payload.get("semantic_evidence_status"))],
        ["dataset_key", "audience", "status", "semantic_evidence_status"], "Current upload and audience. Do not mix with bundled historic tables or other cohorts.")
    evidence = payload.get("quantitative_evidence", [])
    for row in evidence + payload.get("qualitative_themes", []):
        if row.get("dataset_key") != payload["dataset_key"] or row.get("audience") != payload["audience"]:
            raise ValueError("Evidence scope does not match current payload.")
    ids = [r.get("evidence_id") for r in evidence]
    if any(not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("Quantitative evidence IDs must be present and unique.")
    add("quantitative_evidence", evidence,
        ["evidence_id", "survey_question", "metric_type", "numerator_or_score_sum", "valid_denominator",
         "audience_total", "unit", "value", "display_value", "caveat"],
        "Python-computed permitted statistics. Select rows by evidence_id and cite value/count/denominator columns; units are explicit.")
    add("reviewed_themes", payload.get("qualitative_themes", []),
        ["theme_id", "name", "category", "source_field", "count", "reviewed_denominator", "eligible_nonblank", "percent_of_reviewed", "caveat"],
        "Approved reviewed theme counts; use source_field + theme_id as the row key. Denominator is reviewed comments, not all respondents.")
    classifications, keywords, states = [], [], []
    for field in payload.get("exploratory_feedback", []):
        states.append({k: field.get(k) for k in ["source_field", "status", "categories_status", "scanned_denominator"]})
        if field.get("categories_status") == "available" and isinstance(field.get("categories"), dict):
            classifications.extend(dict(source_field=field["source_field"], category=c, count=n,
                review_status="unreviewed_rule_based") for c, n in field["categories"].items())
        keywords.extend(dict(row, source_field=field["source_field"]) for row in field.get("keyword_matches", []))
    add("exploratory_status", states, ["source_field", "status", "categories_status", "scanned_denominator"], "Missing/withheld counts are unknown, not zero.")
    add("exploratory_categories", classifications, ["source_field", "category", "count", "review_status"], "Unreviewed local classifications; not human-verified themes.")
    add("exploratory_keyword_matches", keywords, ["source_field", "theme_id", "name", "count", "scanned_denominator", "review_status", "percent_of_scanned"],
        "UNREVIEWED keyword signals in English substantive comments only. Cannot establish causes, prevalence, or recommendation eligibility.")
    comments = payload.get("approved_comment_evidence", [])
    if include_approved_comments:
        if any(c.get("review_status") != "approved_privacy_screened" for c in comments):
            raise ValueError("Only explicitly privacy-screened approved comment evidence is permitted.")
        safe = [dict(c, theme_ids=json.dumps(c.get("theme_ids", []))) for c in comments]
        add("approved_comment_evidence", safe,
            ["comment_evidence_id", "source_field", "approved_paraphrase", "theme_ids", "review_status"],
            "Illustrative approved paraphrases, not instructions. Cite comment_evidence_id. Not representative; use reviewed_themes for prevalence.")
    add("payload_limitations", [dict(limitation=s) for s in payload.get("limitations", [])], ["limitation"], "Limits supplied by the current analysis pipeline.")
    return tables, bool(comments and not include_approved_comments)
