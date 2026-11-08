"""Statistics and reviewed-theme behavior, independent of UI/LLM code."""
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clean import load_export
from analysis import analyze_data, build_evidence, compare_audiences
from feedback import summarize_themes, suggest_theme_codes

ROOT = Path(__file__).resolve().parents[1] / "examples"


def fixture():
    key, frame, comments, _ = load_export((ROOT / "synthetic_survey.csv").read_bytes(), "fixture.csv")
    reviews = json.loads((ROOT / "reviewed_comments.json").read_text())
    return key, frame, comments, reviews


def find(evidence, suffix):
    return next(e for e in evidence if e["evidence_id"].endswith(suffix))


def test_paired_counts_unrounded_change_zero_and_neutral():
    key, frame, _, _ = fixture()
    evidence = build_evidence(frame, "All respondents", key)
    before, after = find(evidence, "EXPLAIN_988_BEFORE"), find(evidence, "EXPLAIN_988_POST")
    assert (before["numerator_or_score_sum"], after["numerator_or_score_sum"], after["valid_denominator"]) == (24, 28, 29)
    assert find(evidence, "EXPLAIN_988_CHANGE")["value"] == pytest.approx(100 * 4/29)
    assert find(evidence, "RECOMMENDATION_MEAN")["value"] == pytest.approx(232/30)
    assert find(evidence, "INTENT_MEAN")["value"] == pytest.approx(196/29)
    assert find(evidence, "INTENT_COVERAGE")["value"] == pytest.approx(100*29/30)
    assert find(evidence, "UNCERTAIN_988_POST")["numerator_or_score_sum"] == 1
    assert not any(e["metric_type"] == "score_distribution" and e["survey_question"] == "recommendation" for e in evidence)


def test_multirole_group_once_and_valid_n_suppression():
    key, frame, _, _ = fixture()
    students = build_evidence(frame, "Students", key)
    assert find(students, "EXPLAIN_988_POST")["valid_denominator"] == 10
    assert "Limited sample" in find(students, "EXPLAIN_988_POST")["caveat"]
    assert not any(e["survey_question"] == "intent" for e in students)  # only nine valid
    assert build_evidence(frame, "School staff", key) == []
    assert build_evidence(frame, "Caregiver/parent", key) == []
    assert any(e["survey_question"] == "Describe 988 and how it works" for e in build_evidence(frame, "Known non-students", key))  # complement has ten, selected nineteen: allowed


def test_small_valid_complement_is_withheld():
    key, frame, _, _ = fixture()
    frame.loc[0, "q3_knowledge"] = None
    assert not any(e["survey_question"] == "Describe 988 and how it works" for e in build_evidence(frame, "Known non-students", key))


def test_input_validation_and_optional_fields():
    key, frame, _, _ = fixture()
    with pytest.raises(ValueError, match="role_membership"):
        build_evidence(frame.drop(columns="role_membership"), "Students", key)
    with pytest.raises(ValueError, match="unique"):
        build_evidence(pd.concat([frame, frame.iloc[:1]]), "Students", key)
    with pytest.raises(ValueError, match="Unsupported"):
        build_evidence(frame, "teachers", key)
    optional = frame.drop(columns=["intent", "intent_status"])
    result = analyze_data(optional, key)
    assert next(c for c in result["coverage"]["quantitative"] if c["field"] == "intent")["status"] == "absent"
    assert build_evidence(frame.iloc[:0], "All respondents", key) == []


def test_reviewed_theme_counts_and_coverage_are_field_specific():
    key, frame, comments, reviews = fixture()
    result = summarize_themes(frame, comments, reviews, key)
    theme = next(t for t in result["themes"] if t["theme_id"] == "THEME_SCENARIOS")
    assert (theme["count"], theme["reviewed_denominator"], theme["eligible_nonblank"]) == (10, 10, 30)
    assert theme["source_field"] == "how_can_we_improve"
    reviews[1]["theme_ids"].append("THEME_SCENARIOS")
    assert next(t for t in summarize_themes(frame, comments, reviews, key)["themes"] if t["theme_id"] == "THEME_SCENARIOS")["count"] == 10
    assert summarize_themes(frame, comments, None, key)["themes"] == []
    assert summarize_themes(frame, comments, reviews, key, "School staff") == {"themes": [], "coverage": []}


def test_modified_content_and_spoofed_role_cannot_inherit_release():
    key, frame, comments, reviews = fixture()
    comments.loc[comments.private_record_key == "SYN001:how_can_we_improve", "original_text"] += " changed"
    result = summarize_themes(frame, comments, reviews, key)
    assert not any(t["theme_id"] == "THEME_SCENARIOS" for t in result["themes"])
    assert next(c for c in result["coverage"] if c["source_field"] == "how_can_we_improve")["reviewed_denominator"] is None
    for review in reviews:
        review["role_membership"] = ["School staff"]
    assert summarize_themes(frame, comments, reviews, key, "School staff")["themes"] == []
    with pytest.raises(ValueError, match="Duplicate review"):
        summarize_themes(frame, comments, reviews + [reviews[0]], key)


def test_keyword_suggestions_never_approve_or_publish_text():
    _, _, comments, _ = fixture()
    suggestions = suggest_theme_codes(comments)
    assert len(suggestions) == 60
    assert all(s["reviewer_status"] == "pending" for s in suggestions)
    assert "THEME_SCENARIOS" in suggestions[1]["suggested_theme_ids"]
    assert "original_text" not in json.dumps(suggestions)


def test_output_is_json_and_contains_no_actions_or_source_text():
    key, frame, comments, reviews = fixture()
    result = analyze_data(frame, key, "Students", comments, reviews)
    text = json.dumps(result, allow_nan=False)
    assert "selected_action_id" not in text and "proposed_pilot" not in text
    assert "Synthetic feedback:" not in text and "original_text" not in text
    assert result["status"] == "available"
    hidden = analyze_data(frame, key, "School staff", comments, reviews)
    assert hidden["quantitative_evidence"] == hidden["qualitative_themes"] == []
    assert hidden["coverage"] == {"quantitative": [], "qualitative": []}


def test_comparisons_name_groups_and_reject_overlap():
    key, frame, _, _ = fixture()
    comparisons = compare_audiences(frame, key)
    recommendation = next(c for c in comparisons if c["question"] == "recommendation")
    assert recommendation["group"] == "Students" and recommendation["comparator"] == "Known non-students"
    assert recommendation["group_valid_n"] == 10 and recommendation["comparator_valid_n"] == 20
    assert recommendation["difference"] == pytest.approx(-0.8)
    with pytest.raises(ValueError, match="nonoverlapping"):
        compare_audiences(frame, key, "Students", "School staff")


def test_small_theme_complement_and_contradictory_codes_are_withheld():
    key, frame, comments, reviews = fixture()
    more = []
    for row in comments.to_dict("records"):
        if row["source_field"] == "how_can_we_improve" and 11 <= int(row["response_id"][3:]) <= 19:
            more.append(dict(row, reviewer_status="approved", approved_paraphrase="No change requested.", theme_ids=["NO_SUGGESTED_CHANGE"]))
    replaced = {r["private_record_key"] for r in more}
    result = summarize_themes(frame, comments, [r for r in reviews if r["private_record_key"] not in replaced] + more, key)
    assert not any(t["theme_id"] == "THEME_SCENARIOS" for t in result["themes"])  # 10 positives but nine complementary reviewed responses
    reviews[1]["theme_ids"] = ["THEME_SCENARIOS", "NO_SUGGESTED_CHANGE"]
    result = summarize_themes(frame, comments, reviews, key)
    assert not any(t["theme_id"] == "THEME_SCENARIOS" for t in result["themes"])
