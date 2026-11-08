import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cleaned_analysis import adapt_cleaned, build_ai_input


def synthetic():
    rows, private = [], []
    for i in range(40):
        rows.append(dict(response_id=str(i), role_student=i < 20, role_staff=False,
            role_caregiver=False, role_other=i >= 20, role__status="valid",
            identify_before=2, identify_after=4, describe_before=2, describe_after=4,
            when_before=3, when_after=5, recommend=8, call_intent=0,
            most_valuable__category="substantive", most_valuable__lang="en",
            improve__category="substantive", improve__lang="en"))
        private.append(dict(response_id=str(i), most_valuable="Clear explanation of 988. PERSON_CANARY_728 jane@example.com",
            improve="Add a practice call scenario." if i % 20 < 10 else "Adjust the pacing."))
    return pd.DataFrame(rows), pd.DataFrame(private)


def test_cleaning_adapter_and_aggregate_payload_no_text_or_identity():
    data, private = synthetic()
    responses, comments = adapt_cleaned(data, private)
    result = build_ai_input(responses, comments, "test-key", "Students")
    text = json.dumps(result, allow_nan=False)
    assert "PERSON_CANARY" not in text and "jane@example.com" not in text
    assert "original_text" not in text and "response_id" not in text
    assert result["qualitative_themes"] == []
    improve = next(f for f in result["exploratory_feedback"] if f["source_field"] == "how_can_we_improve")
    scenario = next(t for t in improve["keyword_matches"] if t["theme_id"] == "THEME_SCENARIOS")
    assert scenario["count"] == 10 and scenario["scanned_denominator"] == 20
    assert scenario["review_status"] == "unreviewed_keyword_match"
    assert result["schema_version"] == "everymind.analysis.v1"
    assert all("action" not in key for key in result)


def test_small_counts_categories_and_language_are_withheld():
    data, private = synthetic()
    # Only nine student scenario requests; the remainder has another topic.
    private.loc[0, "improve"] = "Adjust the pacing."
    responses, comments = adapt_cleaned(data, private)
    result = build_ai_input(responses, comments, "key", "Students")
    improve = result["exploratory_feedback"][1]
    assert not any(t["theme_id"] == "THEME_SCENARIOS" for t in improve["keyword_matches"])
    # One missing answer makes the whole disjoint category breakdown unsafe.
    data.loc[0, "improve__category"] = "blank"
    responses, comments = adapt_cleaned(data, private)
    improve = build_ai_input(responses, comments, "key", "Students")["exploratory_feedback"][1]
    assert improve["categories"] is None
    # Patterns cannot classify Spanish comments as English thematic evidence.
    data["improve__lang"] = "es"
    responses, comments = adapt_cleaned(data, private)
    improve = build_ai_input(responses, comments, "key")["exploratory_feedback"][1]
    assert improve["keyword_matches"] == [] and improve["scanned_denominator"] is None


def test_entire_small_audience_returns_no_exploratory_counts():
    data, private = synthetic()
    data.loc[:8, "role_staff"] = True
    responses, comments = adapt_cleaned(data, private)
    assert build_ai_input(responses, comments, "key", "School staff")["exploratory_feedback"] == []
