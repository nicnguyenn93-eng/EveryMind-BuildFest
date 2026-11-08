"""Report drafting: checks and fallback, using a fake Gemini client (no API key needed)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import report  # noqa: E402

EVIDENCE = json.loads((ROOT / "examples" / "evidence.json").read_text(encoding="utf-8"))
CATALOG = json.loads((ROOT / "action_catalog.json").read_text(encoding="utf-8"))
STUDENTS = [e for e in EVIDENCE if e["audience"] == "Students"]

GOOD = {
    "summary": [{
        "text": "Agreement that students can explain 988 rose from 50.0% to 90.0%, a 40.0 point change (9 of 10).",
        "evidence_ids": ["STUDENTS_EXPLAIN_988_BEFORE", "STUDENTS_EXPLAIN_988_POST"],
    }],
    "proposed_recommendations": [{
        "action_id": "ACT_PILOT_ROLEPLAY", "pilot": "Add two practice-call scenarios to the student session.",
        "evidence_ids": ["STUDENTS_EXPLAIN_988_POST"], "proposed_staff_owner": "Someone else",
        "follow_up_measure": "At least 80% of students complete the practice-call checklist.",
        "uncertainty": "Ten students; retrospective ratings.",
    }],
    "limitations": ["Retrospective self-report; descriptive, not causal.", "Only 10 students."],
}


class FakeResp:
    def __init__(self, payload):
        self.parsed, self.text = None, json.dumps(payload)


class FakeClient:
    def __init__(self, *answers, error=None):
        self.answers, self.error, self.prompts = list(answers), error, []
        self.models = self

    def generate_content(self, model, contents, config):
        self.prompts.append(contents)
        if self.error:
            raise self.error
        return FakeResp(self.answers.pop(0) if len(self.answers) > 1 else self.answers[0])


def test_valid_answer_becomes_llm_report():
    r = report.draft_report(STUDENTS, CATALOG, client=FakeClient(GOOD), retries=0)
    assert r["mode"] == "llm" and r["fallback_reason"] is None
    assert r["staff_owner"] == "Training Lead"  # from the catalog, not the model
    for key in ("dataset_key", "audience", "summary_blocks", "evidence_ids", "proposed_action_id",
                "follow_up_measure", "limitations"):
        assert key in r


@pytest.mark.parametrize("change", [
    {"proposed_recommendations": [dict(GOOD["proposed_recommendations"][0], action_id="ACT_MADE_UP")]},
    {"summary": [{"text": "Agreement rose to 95.0%.", "evidence_ids": ["STUDENTS_EXPLAIN_988_POST"]}]},
    {"summary": [{"text": "Agreement rose.", "evidence_ids": ["NOT_A_RECORD"]}]},
    {"limitations": ["Small sample."]},
])
def test_bad_answer_falls_back_to_template(change):
    r = report.draft_report(STUDENTS, CATALOG, client=FakeClient({**GOOD, **change}), retries=0)
    assert r["mode"] == "template" and r["fallback_reason"]


def test_retry_recovers_from_one_bad_answer():
    bad = {**GOOD, "limitations": ["Small sample."]}
    r = report.draft_report(STUDENTS, CATALOG, client=FakeClient(bad, GOOD), retries=1)
    assert r["mode"] == "llm"


def test_api_error_falls_back_with_numbers():
    r = report.draft_report(STUDENTS, CATALOG, client=FakeClient(error=RuntimeError("429 quota")), retries=0)
    assert r["mode"] == "template" and "429" in r["fallback_reason"]
    assert "+40.0 percentage-point" in r["summary_blocks"][0]


def test_payload_comments_off_by_default_and_small_groups_dropped():
    tiny = dict(STUDENTS[0], evidence_id="STUDENTS_TINY", valid_denominator=4)
    payload = dict(schema_version="everymind.analysis.v2", dataset_key=STUDENTS[0]["dataset_key"], audience="Students",
                   quantitative_evidence=STUDENTS + [tiny], qualitative_themes=[],
                   approved_comment_evidence=[dict(comment_evidence_id="C_1", source_field="how_can_we_improve",
                                                   approved_paraphrase="Add a practice call.", theme_ids=[],
                                                   review_status="approved_privacy_screened")])
    client = FakeClient(GOOD)
    report.draft_report_from_payload(payload, CATALOG, client=client, retries=0)
    assert "STUDENTS_TINY" not in client.prompts[0] and "Add a practice call." not in client.prompts[0]
    client = FakeClient(GOOD)
    report.draft_report_from_payload(payload, CATALOG, client=client, retries=0, include_approved_comments=True)
    assert "Add a practice call." in client.prompts[0]


def test_wrong_scope_is_rejected():
    payload = dict(schema_version="everymind.analysis.v2", dataset_key="other", audience="Students",
                   quantitative_evidence=STUDENTS)
    with pytest.raises(ValueError, match="scope"):
        report.draft_report_from_payload(payload, CATALOG, client=FakeClient(GOOD))


class SequenceClient(FakeClient):
    def generate_content(self, model, contents, config):
        self.prompts.append(contents)
        result = self.answers.pop(0)
        if isinstance(result, Exception):
            raise result
        return FakeResp(result)


def provider_error(status):
    from google.genai.errors import ClientError, ServerError
    error_class = ServerError if status >= 500 else ClientError
    return error_class(status, {'error': {'code':status, 'status':'UNAVAILABLE',
        'message':'synthetic-secret respondent ada@example.com'}})


def test_503_retries_same_request_and_recovers(monkeypatch):
    sleeps = []
    monkeypatch.setattr(report.time, 'sleep', sleeps.append)
    monkeypatch.setattr(report.random, 'uniform', lambda *args: 0)
    client = SequenceClient(provider_error(503), provider_error(503), GOOD)
    result = report.draft_report(STUDENTS, CATALOG, client=client, retries=2)
    assert result['mode']=='llm' and result['provider_attempts']==3
    assert result['provider_http_status'] is None
    assert len(client.prompts)==3 and len(set(client.prompts))==1
    assert sleeps==[2,4]


def test_exhausted_503_has_specific_safe_reason_and_logs(monkeypatch, caplog):
    monkeypatch.setattr(report.time,'sleep',lambda seconds:None)
    client=FakeClient(error=provider_error(503))
    result=report.draft_report(STUDENTS,CATALOG,client=client,retries=2)
    assert result['mode']=='template' and result['provider_attempts']==3 and result['provider_http_status']==503
    assert 'temporarily overloaded or unavailable' in result['fallback_reason']
    assert 'credentials' not in result['fallback_reason'] and 'quota' not in result['fallback_reason']
    for text in (json.dumps(result),caplog.text):
        assert 'synthetic-secret' not in text and 'ada@example.com' not in text


@pytest.mark.parametrize('status',[400,401,403,404])
def test_permanent_errors_are_not_retried(status,monkeypatch):
    monkeypatch.setattr(report.time,'sleep',lambda seconds:pytest.fail('Permanent error was retried'))
    client=FakeClient(error=provider_error(status))
    result=report.draft_report(STUDENTS,CATALOG,client=client,retries=2)
    assert result['mode']=='template' and result['provider_attempts']==1
    assert result['provider_http_status']==status and len(client.prompts)==1


def test_provider_retry_after_is_respected_without_long_blocking(monkeypatch):
    sleeps=[]
    monkeypatch.setattr(report.time,'sleep',sleeps.append)
    error=provider_error(503)
    error.response=type('Response',(),{'headers':{'retry-after':'6'}})()
    client=SequenceClient(error,GOOD)
    assert report.draft_report(STUDENTS,CATALOG,client=client,retries=2)['mode']=='llm'
    assert sleeps==[6]
    error.response.headers['retry-after']='120'
    client=FakeClient(error=error)
    result=report.draft_report(STUDENTS,CATALOG,client=client,retries=2)
    assert result['provider_attempts']==1 and sleeps==[6]


def test_generation_deadline_limits_retry_timeout(monkeypatch):
    clock=[0]
    timeouts=[]
    monkeypatch.setattr(report.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(report.time,'sleep',lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    monkeypatch.setattr(report.random,'uniform',lambda *args:0)
    def timeout(client,model,system,prompt,*,timeout_ms):
        timeouts.append(timeout_ms)
        clock[0]+=timeout_ms/1000
        raise TimeoutError('synthetic-secret request body')
    monkeypatch.setattr(report,'_call_gemini',timeout)
    result=report.draft_report(STUDENTS,CATALOG,client=FakeClient(GOOD),retries=2,request_timeout_ms=120000)
    assert timeouts==[120000,58000] and clock[0]==180
    assert result['provider_attempts']==2 and result['mode']=='template'
    assert 'synthetic-secret' not in json.dumps(result)
