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
    monkeypatch.setattr(report, '_make_client', lambda key, **options: pytest.fail('Offline report requested a client'))
    payload = service.get_analysis(exported.path)
    result = service.generate_report(exported.path, expected_dataset_key=payload['dataset_key'], use_llm=False)
    assert payload['schema_version'] == 'everymind.analysis.v2'
    assert result['schema_version'] == 'everymind.report.v1'
    assert result['mode'] == 'template'
    assert result['dataset_key'] == payload['dataset_key'] == exported.dataset_key
    assert payload['approved_comment_evidence'] == []
    assert 'ada@example.com' not in json.dumps([payload, result], allow_nan=False)


def test_live_flow_includes_censored_current_comments_by_default(exported):
    client = FakeClient()
    result = service.generate_report(exported.path, reviews=approvals(exported), client=client, retries=0)
    assert result['mode'] == 'llm'
    assert result['staff_owner'] == 'Training Lead'
    sent = json.loads(client.prompts[0].split('```json\n', 1)[1].split('\n```', 1)[0])
    assert sent['approved_comment_evidence'] == []
    assert len(sent['censored_comment_evidence'])==80
    assert result['input_policy']=='censored_comments_v1' and result['censored_comment_count']==80
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
    {'audience': 'unsupported'}, {'use_llm': 'False'}, {'include_approved_comments': 'False'}, {'include_censored_comments': 'False'},
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
    monkeypatch.setattr(report, '_make_client', lambda key, **options: client)
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


class CommentClient(FakeClient):
    def generate_content(self, *, model, contents, config):
        self.prompts.append(contents)
        payload=json.loads(contents.split('```json\n',1)[1].split('\n```',1)[0])
        comment=next(c for c in payload['censored_comment_evidence'] if c['source_field']=='how_can_we_improve')
        result={
            'summary':[{'text':'Written feedback requests practical scenarios.', 'evidence_ids':[comment['comment_evidence_id']]}],
            'proposed_recommendations':[{'action_id':'ACT_PILOT_ROLEPLAY','pilot':'Propose practice scenarios.',
                'evidence_ids':[comment['comment_evidence_id']],'proposed_staff_owner':'Training lead',
                'follow_up_measure':'Review future feedback on practice opportunities.',
                'uncertainty':'A feedback observation does not establish prevalence or effectiveness.'}],
            'limitations':['Retrospective self-report; descriptive, not causal. Comments are automatically censored, not human-reviewed.']}
        return type('Response',(),{'parsed':None,'text':json.dumps(result)})()


def test_censored_comments_are_citable_without_any_manual_reviews(exported):
    client=CommentClient()
    result=service.generate_report(exported.path,client=client,retries=0)
    assert result['mode']=='llm' and result['summary'][0]['evidence_ids'][0].startswith('CC_')
    assert result['censored_comment_count']==80
    sent=json.loads(client.prompts[0].split('```json\n',1)[1].split('\n```',1)[0])
    assert all(c['review_status']=='automatically_censored' for c in sent['censored_comment_evidence'])
    assert all(set(c)=={'comment_evidence_id','source_field','language','censored_text','review_status'} for c in sent['censored_comment_evidence'])
    assert '<EMAIL_ADDRESS>' in client.prompts[0]
    for private in ('ada@example.com','response_id','original_id','source_row','original_text'):
        assert private not in client.prompts[0]


def test_censored_comments_preserve_languages_unicode_multiline_and_audience(exported):
    rewrite(exported,lambda _,rows:(rows[0].update(most_valuable__redacted='Explicación clara, "útil"\n<PERSON>',most_valuable__lang='es'),
                                  rows[1].update(improve__redacted='   ',improve__privacy='blank'),
                                  rows[20].update(improve__redacted='ONLY_NONSTUDENT_FEEDBACK')))
    client=CommentClient()
    result=service.generate_report(exported.path,'Students',client=client,retries=0)
    sent=json.loads(client.prompts[0].split('```json\n',1)[1].split('\n```',1)[0])
    comments=sent['censored_comment_evidence']
    assert result['censored_comment_count']==len(comments)==39
    assert any(c['language']=='es' and c['censored_text']=='Explicación clara, "útil"\n<PERSON>' for c in comments)
    assert 'ONLY_NONSTUDENT_FEEDBACK' not in client.prompts[0]
    assert len({c['comment_evidence_id'] for c in comments})==39


def test_aggregate_only_option_and_aggregate_dashboard_still_omit_comment_rows(exported):
    client=FakeClient()
    result=service.generate_report(exported.path,include_censored_comments=False,client=client,retries=0)
    sent=json.loads(client.prompts[0].split('```json\n',1)[1].split('\n```',1)[0])
    assert sent['censored_comment_evidence']==[]
    assert result['input_policy']=='aggregate_only' and result['censored_comment_count']==0
    assert 'censored_comment_evidence' not in service.get_analysis(exported.path)


def test_censored_citations_change_with_the_current_export(exported):
    from censored_comment_evidence import build_censored_comment_evidence
    from everymind_cleaning.censored_data import load_censored_export
    before=build_censored_comment_evidence(exported,'All respondents')
    assert before==build_censored_comment_evidence(exported,'All respondents')
    rewrite(exported,lambda _,rows:rows[0].update(improve__redacted='Different censored feedback.'))
    after=build_censored_comment_evidence(load_censored_export(exported.path),'All respondents')
    assert not ({c['comment_evidence_id'] for c in before}&{c['comment_evidence_id'] for c in after})


def test_censored_comment_scope_and_duplicate_ids_are_validated(exported):
    from censored_comment_evidence import build_censored_comment_evidence
    payload=service.get_analysis(exported.path)
    comments=build_censored_comment_evidence(exported,'Students')
    payload['censored_comment_evidence']=comments
    with pytest.raises(ValueError,match='scope'):report.safe_payload(payload,False,True)
    comments=build_censored_comment_evidence(exported,'All respondents')
    payload['censored_comment_evidence']=comments+[comments[0]]
    with pytest.raises(ValueError,match='invalid'):report.safe_payload(payload,False,True)


def test_censored_report_does_not_open_sources_or_original_comment_files(exported):
    shutil.rmtree(exported.root/'raw')
    shutil.rmtree(exported.path.parent/'private')
    client=CommentClient()
    result=service.generate_report(exported.path,client=client,retries=0)
    assert result['mode']=='llm' and result['censored_comment_count']==80


def test_comment_requests_get_a_longer_bounded_sdk_timeout(exported,monkeypatch):
    from google import genai
    options=[]
    def factory(**kwargs):
        options.append(kwargs['http_options'])
        return CommentClient() if len(options)==1 else FakeClient()
    monkeypatch.setattr(genai,'Client',factory)
    result=service.generate_report(exported.path,api_key='synthetic-key',retries=0)
    assert result['mode']=='llm'
    result=service.generate_report(exported.path,api_key='synthetic-key',include_censored_comments=False,retries=0)
    assert result['mode']=='llm'
    assert [o['timeout'] for o in options]==[120000,30000]
    assert all(o['retry_options']['attempts']==1 for o in options)
