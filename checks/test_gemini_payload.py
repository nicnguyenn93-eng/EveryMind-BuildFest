import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gemini_kit.payload_tables import load_payload_tables
from gemini_kit.run_gemini import check_evidence

ROOT = Path(__file__).resolve().parents[1]


def payload(tmp_path):
    obj = dict(schema_version="everymind.analysis.v2", dataset_key="synthetic", audience="Students", status="available",
        semantic_evidence_status="available", quantitative_evidence=[dict(dataset_key="synthetic", audience="Students",
        evidence_id="STUDENTS_TEST", survey_question="Test", value=50, valid_denominator=20)], qualitative_themes=[],
        exploratory_feedback=[dict(source_field="how_can_we_improve", status="exploratory", categories_status="withheld",
                                  categories=None, keyword_matches=[])], limitations=["Synthetic test only"],
        approved_comment_evidence=[dict(comment_evidence_id="C_test", source_field="how_can_we_improve",
            approved_paraphrase="Use practice examples.", theme_ids=["THEME_SCENARIOS"], review_status="approved_privacy_screened")])
    path = tmp_path / "input.json"
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path, obj


def test_default_aggregate_only_and_scope_validation(tmp_path):
    path, obj = payload(tmp_path)
    tables, omitted = load_payload_tables(path)
    assert omitted and "approved_comment_evidence" not in tables
    assert "exploratory_categories" not in tables
    assert "headline" not in tables
    obj["quantitative_evidence"][0]["audience"] = "All respondents"
    path.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(ValueError, match="scope"):
        load_payload_tables(path)


def test_table_citations_and_explicit_approved_comments(tmp_path):
    path, _ = payload(tmp_path)
    tables, omitted = load_payload_tables(path, include_approved_comments=True)
    assert not omitted and "approved_comment_evidence" in tables
    citation = dict(dataset="quantitative_evidence", row=[dict(column="evidence_id", value="STUDENTS_TEST")], column="value", value="50")
    assert check_evidence(citation, tables)[0] == "verified"
    assert check_evidence(dict(citation, value="50.4"), tables)[0] == "value mismatch"
    text = dict(dataset="approved_comment_evidence", row=[dict(column="comment_evidence_id", value="C_test")], column="approved_paraphrase", value="Use practice examples.")
    assert check_evidence(text, tables)[0] == "verified"
    table = tables["quantitative_evidence"][0]
    import pandas as pd
    tables["quantitative_evidence"] = (pd.concat([table, table]), "test")
    assert check_evidence(citation, tables)[0] == "row ambiguous"


def test_payload_dry_run_uses_current_scope_without_api_or_human_findings(tmp_path):
    path, _ = payload(tmp_path)
    out = tmp_path / "results"
    result = subprocess.run([sys.executable, str(ROOT / "gemini_kit/run_gemini.py"), "--payload", str(path),
                             "--dry-run", "--out", str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    prompt = (out / "prompt_stage1.txt").read_text(encoding="utf-8")
    assert "STUDENTS_TEST" in prompt and "## Table: payload_scope" in prompt
    assert "## Table: headline" not in prompt and "1,255 form the analysis set" not in prompt
    assert "Use practice examples." not in prompt
    assert not (out / "prompt_stage2.txt").exists()
    assert "Nothing was sent" in result.stdout
