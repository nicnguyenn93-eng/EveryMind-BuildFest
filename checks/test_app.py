"""End-to-end app check: upload the synthetic export, pick an audience, generate a report.

Streamlit's AppTest cannot drive file uploads, so the uploader is replaced with one that
returns the synthetic export, and Gemini is replaced with a fake client (no key needed).
"""
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
pytest.importorskip("streamlit")
import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import report  # noqa: E402
from checks.test_report import FakeClient  # noqa: E402

EXPORT = ROOT / "examples" / "synthetic_survey.xlsx"


class Upload(io.BytesIO):
    name = EXPORT.name


def answer_for(payload_text):
    """A valid Gemini answer that cites real evidence from the prompt."""
    sent = json.loads(payload_text.split("```json\n", 1)[1].split("\n```", 1)[0])
    change = next(e for e in sent["quantitative_evidence"] if e["evidence_id"].endswith("EXPLAIN_988_CHANGE"))
    return {
        "summary": [{"text": f"Agreement on describing 988 changed by {change['display_value']} "
                             f"among {int(change['valid_denominator'])} respondents.",
                     "evidence_ids": [change["evidence_id"]]}],
        "proposed_recommendations": [{"action_id": "ACT_PILOT_ROLEPLAY", "pilot": "Add practice calls.",
                                      "evidence_ids": [change["evidence_id"]], "proposed_staff_owner": "x",
                                      "follow_up_measure": "80% complete the practice call.", "uncertainty": "Small sample."}],
        "limitations": ["Retrospective self-report; descriptive, not causal."],
    }


class PromptAwareClient(FakeClient):
    def generate_content(self, model, contents, config):
        self.prompts.append(contents)
        from checks.test_report import FakeResp
        return FakeResp(answer_for(contents))


@pytest.fixture
def app(monkeypatch):
    data = EXPORT.read_bytes()
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: Upload(data))
    monkeypatch.setattr(report, "_make_client", lambda key: PromptAwareClient({}))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)


def test_upload_analyze_and_generate_llm_report(app):
    app.run()
    assert not app.exception
    assert any("30 responses" in s.value for s in app.success)
    assert app.selectbox[0].value == "All respondents"
    app.button[0].click().run()  # Generate report
    assert not app.exception
    assert any("AI-drafted report" in s.value for s in app.success), [w.value for w in app.warning]
    assert "Launch a 988 Scenario Roleplay Pilot" in " ".join(m.value for m in app.markdown)


def test_small_audience_is_withheld(app):
    app.run()
    app.selectbox[0].set_value("School staff").run()
    assert not app.exception
    assert any("withheld for privacy" in w.value for w in app.warning)
