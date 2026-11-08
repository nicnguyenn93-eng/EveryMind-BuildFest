"""Frontend contract and provider boundary, using fictional censored exports."""

import copy
import json
from pathlib import Path
import shutil

import pytest

import report
import report_service as service
from test_censored_analysis import exported, approvals, rewrite  # noqa: F401


class FakeClient:
    def __init__(self, *, error=None):
        self.models = self
        self.error = error
        self.prompts = []
        self.closed = False

    def generate_content(self, *, model, contents, config):
        self.prompts.append(contents)
        if self.error:
            raise self.error
        payload = json.loads(contents.split('```json\n', 1)[1].split('\n```', 1)[0])
        change = next(e for e in payload['quantitative_evidence']
                      if e['evidence_id'].endswith('EXPLAIN_988_CHANGE'))
        result = {
            'summary': [{'text': f"Describing 988 changed by {change['display_value']} "
                                   f"among {change['valid_denominator']} respondents.",
                         'evidence_ids': [change['evidence_id']]}],
            'proposed_recommendations': [{
                'action_id': 'ACT_PILOT_ROLEPLAY', 'pilot': 'Propose practice calls.',
                'evidence_ids': [change['evidence_id']], 'proposed_staff_owner': 'Proposed owner',
                'follow_up_measure': 'Practice-call completion in a future pilot.',
                'uncertainty': 'These ratings do not establish causes or pilot effectiveness.'}],
            'limitations': ['Retrospective self-report; descriptive, not causal.'],
        }
        return type('Response', (), {'parsed': None, 'text': json.dumps(result)})()

    def close(self):
        self.closed = True


def test_analysis_and_offline_report_need_only_censored_files(exported, monkeypatch):
    shutil.rmtree(exported.root / 'raw')
    shutil.rmtree(exported.path.parent / 'private')
    monkeypatch.setattr(report, '_make_client', lambda key: pytest.fail('Offline report requested a client'))
    payload = service.get_analysis(exported.path)
    result = service.generate_report(exported.path, expected_dataset_key=payload['dataset_key'], use_llm=False)
    assert payload['schema_version'] == 'everymind.analysis.v2'
    assert result['schema_version'] == 'everymind.report.v1'
    assert result['mode'] == 'template'
    assert result['dataset_key'] == payload['dataset_key'] == exported.dataset_key
    assert payload['approved_comment_evidence'] == []
    assert 'ada@example.com' not in json.dumps([payload, result], allow_nan=False)


def test_live_flow_uses_censored_current_analysis_and_aggregate_default(exported):
    client = FakeClient()
    result = service.generate_report(exported.path, reviews=approvals(exported), client=client, retries=0)
    assert result['mode'] == 'llm'
    assert result['staff_owner'] == 'Training Lead'
    sent = json.loads(client.prompts[0].split('```json\n', 1)[1].split('\n```', 1)[0])
    assert sent['approved_comment_evidence'] == []
    assert 'ada@example.com' not in client.prompts[0]
    assert 'response_id' not in client.prompts[0] and 'original_text' not in client.prompts[0]
    assert result['model'] == report.DEFAULT_MODEL
    assert not client.closed  # A caller-owned client stays available for reuse.


def test_approved_comments_require_explicit_opt_in_and_current_approvals(exported):
    client = FakeClient()
    service.generate_report(exported.path, reviews=approvals(exported), include_approved_comments=True,
                            client=client, retries=0)
    assert 'Clear explanation of 988.' in client.prompts[0]
    assert 'ada@example.com' not in client.prompts[0]
    client = FakeClient()
    service.generate_report(exported.path, include_approved_comments=True, client=client, retries=0)
    sent = json.loads(client.prompts[0].split('```json\n', 1)[1].split('\n```', 1)[0])
    assert sent['approved_comment_evidence'] == []


def test_changed_censored_data_rejects_stale_frontend_selection(exported):
    previous_key = service.get_analysis(exported.path)['dataset_key']
    rewrite(exported, lambda header, rows: rows[0].update(improve__redacted='New censored wording.'))
    client = FakeClient()
    with pytest.raises(service.ReportServiceError, match='changed'):
        service.generate_report(exported.path, expected_dataset_key=previous_key, client=client)
    assert client.prompts == []


def test_raw_tampered_and_duplicate_inputs_stop_before_api(exported):
    client = FakeClient()
    with pytest.raises(service.ReportServiceError, match='run_pipeline'):
        service.generate_report(exported.root / 'raw/source.csv', client=client)
    rewrite(exported, lambda header, rows: rows[1].update(response_id=rows[0]['response_id']))
    with pytest.raises(service.ReportServiceError, match='unique response IDs'):
        service.generate_report(exported.path, client=client)
    exported.path.write_bytes(exported.path.read_bytes() + b'\n')
    with pytest.raises(service.ReportServiceError, match='inconsistent'):
        service.generate_report(exported.path, client=client)
    assert client.prompts == []


@pytest.mark.parametrize('options', [
    {'audience': 'unsupported'}, {'use_llm': 'False'}, {'include_approved_comments': 'False'},
    {'retries': -1}, {'retries': True}, {'retries': 3}, {'model': ''},
])
def test_invalid_frontend_options_fail_before_api(exported, options):
    client = FakeClient()
    with pytest.raises(service.ReportServiceError):
        service.generate_report(exported.path, client=client, **options)
    assert client.prompts == []


def test_provider_failure_does_not_expose_key_or_request_body(exported):
    secret = 'synthetic-secret-must-not-appear'
    client = FakeClient(error=RuntimeError(f'429 key={secret} body=ada@example.com'))
    result = service.generate_report(exported.path, api_key=secret, client=client, retries=0)
    assert result['mode'] == 'template' and '429' in result['fallback_reason']
    text = json.dumps(result)
    assert secret not in text and 'ada@example.com' not in text


def test_missing_key_is_an_explicit_template(exported, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    result = service.generate_report(exported.path, retries=0)
    assert result['mode'] == 'template'
    assert result['fallback_reason'] == 'No Gemini API key configured.'


def test_withheld_audience_has_no_recommendation_or_provider_call(exported):
    client = FakeClient()
    result = service.generate_report(exported.path, 'School staff', client=client)
    assert result['mode'] == 'template' and result['evidence_ids'] == []
    assert result['proposed_action_id'] is None and result['proposed_action'] is None
    assert result['staff_owner'] is None and result['follow_up_measure'] is None
    assert result['proposed_recommendations'] == [] and client.prompts == []


def test_owned_provider_client_is_closed(exported, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(report, '_make_client', lambda key: client)
    result = service.generate_report(exported.path, api_key='synthetic-key', retries=0)
    assert result['mode'] == 'llm' and client.closed


def test_template_uses_unrounded_values_for_percentage_point_change():
    evidence = json.loads((service.CATALOG_PATH.parent / 'examples/evidence.json').read_text())
    rows = copy.deepcopy([r for r in evidence if r['audience'] == 'Students'])
    before = next(r for r in rows if r['evidence_id'] == 'STUDENTS_EXPLAIN_988_BEFORE')
    post = next(r for r in rows if r['evidence_id'] == 'STUDENTS_EXPLAIN_988_POST')
    before.update(value=100 / 3, display_value='33.3%')
    post.update(value=200 / 3, display_value='66.7%')
    catalog = json.loads(service.CATALOG_PATH.read_text())
    result = report.draft_report(rows, catalog, use_llm=False)
    assert any('+33.3 percentage-point' in block for block in result['summary_blocks'])
    assert all('+33.4 percentage-point' not in block for block in result['summary_blocks'])


def test_cross_scope_comment_evidence_is_rejected():
    payload = dict(dataset_key='current', audience='Students', quantitative_evidence=[], qualitative_themes=[],
                   approved_comment_evidence=[dict(dataset_key='previous', review_status='approved_privacy_screened')])
    with pytest.raises(ValueError, match='scope'):
        report.safe_payload(payload, True)


def test_published_json_schema_matches_the_runtime_boundary(exported):
    schema = json.loads((Path(service.__file__).parent / 'schemas/report.v1.schema.json').read_text())
    assert schema == service.ReportResult.model_json_schema()
    result = service.generate_report(exported.path, use_llm=False)
    service.ReportResult.model_validate_json(json.dumps(result, allow_nan=False))
