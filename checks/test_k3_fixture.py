"""Independent checks of K3 handoff data; not production privacy certification."""
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1] / "examples"


def read(name):
    return json.loads((ROOT / f"{name}.json").read_text(encoding="utf-8"))


def test_csv_xlsx_and_normalized_records_agree():
    csv = pd.read_csv(ROOT / "synthetic_survey.csv")
    xlsx = pd.read_excel(ROOT / "synthetic_survey.xlsx", sheet_name="Survey Data")
    pd.testing.assert_frame_equal(csv, xlsx)
    assert len(csv) == csv.id.nunique() == 30
    normalized = read("normalized_responses")
    for raw, response in zip(csv.to_dict("records"), normalized):
        assert response["role_membership"] == raw["role"].split(";")
        for field, value in response.items():
            if field != "role_membership":
                assert pd.isna(raw[field]) if value is None else raw[field] == value
    assert normalized[0]["intent"] == normalized[0]["recommendation"] == 0
    assert normalized[1]["intent"] is None
    assert sum("Student" in r["role_membership"] for r in normalized) == 10
    assert sum("School staff" in r["role_membership"] for r in normalized) == 9


def test_paired_evidence_and_current_report_lineage():
    rows = read("normalized_responses")
    key = "sha256:" + hashlib.sha256((ROOT / "synthetic_survey.csv").read_bytes()).hexdigest()
    evidence = read("evidence")
    for e in evidence:
        selected = [r for r in rows if e["audience"] == "All respondents" or "Student" in r["role_membership"]]
        paired = [r for r in selected if r["q3_knowledge"] in range(1, 6) and r["q4_knowledge"] in range(1, 6)]
        field = "q3_knowledge" if e["evidence_id"].endswith("BEFORE") else "q4_knowledge"
        count = sum(r[field] in (4, 5) for r in paired)
        assert e["dataset_key"] == key
        assert e["valid_denominator"] == len(paired) >= 10
        assert e["audience_total"] == len(selected)
        assert e["numerator_or_score_sum"] == count
        assert e["display_value"] == f"{100 * count / len(paired):.1f}%"
        assert "limited sample" in e["caveat"]
    report = read("report")
    assert report["dataset_key"] == key
    for identifier in report["evidence_ids"]:
        assert any(e["evidence_id"] == identifier and e["audience"] == report["audience"] for e in evidence)
    assert read("privacy_expectations")["school_staff"]["evidence"] == []
    assert all(e["audience"] != "School staff" for e in evidence)
    schema = json.loads((ROOT.parent / "schema.json").read_text(encoding="utf-8"))
    assert schema["evidence_row_schema"] == evidence[0]
    assert schema["reviewed_comment_schema"] == read("reviewed_comments")[0]
    assert schema["report_schema"] == report


def test_review_identity_coverage_and_action_support():
    raw = pd.read_csv(ROOT / "synthetic_survey.csv").set_index("id")
    comments = read("reviewed_comments")
    assert len(comments) == len({c["private_record_key"] for c in comments}) == 60
    assert sum(c["reviewer_status"] == "approved" for c in comments) == 20
    for comment in comments:
        text = raw.loc[comment["response_id"], comment["source_field"]]
        assert comment["content_fingerprint"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert comment["role_membership"] == raw.loc[comment["response_id"], "role"].split(";")
        if comment["reviewer_status"] == "pending":
            assert comment["approved_paraphrase"] is None and comment["theme_ids"] == []
    for theme in read("theme_summary"):
        selected = [c for c in comments if c["source_field"] == theme["source_field"] and
                    (theme["audience"] == "All respondents" or "Student" in c["role_membership"])]
        reviewed = [c for c in selected if c["reviewer_status"] == "approved"]
        positive = {c["response_id"] for c in reviewed if theme["theme_id"] in c["theme_ids"]}
        assert theme["eligible_nonblank"] == len(selected)
        assert theme["reviewed_denominator"] == len(reviewed)
        assert theme["theme_positive"] == len(positive) == 10
    assert read("report")["proposed_action_id"] == "ACT_PILOT_ROLEPLAY"
