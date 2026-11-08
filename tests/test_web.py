"""Local HTTP integration against fictional censored records; never calls a provider."""
import json
import shutil
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from everymind_web.aggregates import Dashboard, release_partition
from everymind_web.server import create_app
from everymind_web.store import DatasetStore
from test_censored_analysis import exported, rewrite  # noqa: F401
from test_cleaning_integration import csv_bytes, fictional_row, FakeEngine
from everymind_cleaning import everymind_clean as cleaner, privacy_adapter
from everymind_cleaning.presidio_bridge import PresidioBridge
from everymind_cleaning.stage_outputs import write_stage_outputs
from everymind_cleaning import run_pipeline as runner

HEADERS = {'X-EveryMind-Request': '1', 'Origin': 'http://localhost'}


def test_dashboard_uses_censored_only_and_preserves_metric_units(exported):
    shutil.rmtree(exported.root / 'raw')
    shutil.rmtree(exported.path.parent / 'private')
    value = Dashboard(exported).for_audience('All respondents')
    row = value['cube'][0]
    assert value['summaries']['(all)']['n'] == 40
    assert row['nps'] == pytest.approx(-2.5)  # one zero, 39 eights; no promoters
    assert row['mean_recommend'] == 7.8
    assert row['n_call'] == 39 and row['call_mean'] == 0
    assert row['nps'] != row['mean_recommend']
    text = json.dumps(value, allow_nan=False)
    for private in ('ada@example.com', 'response_id', 'original_id', 'source_row', 'original_text', 'most_valuable__redacted'):
        assert private not in text


def test_small_county_and_secondary_cell_are_withheld(exported):
    rewrite(exported, lambda _, rows: [r.update(county='Montgomery' if i < 25 else ('Anne Arundel' if i < 37 else 'Rare place')) for i,r in enumerate(rows)])
    from everymind_cleaning.censored_data import load_censored_export
    value = Dashboard(load_censored_export(exported.path)).for_audience('All respondents')
    assert value['summaries']['Montgomery']['n'] == 25
    assert value['summaries']['Anne Arundel']['n'] is None
    assert value['summaries']['Other surveyed locations']['n'] is None
    assert 'Rare place' not in json.dumps(value)
    assert release_partition({'big': 25, 'middle': 12, 'small': 3}, {'big':True,'middle':True,'small':True}) == {'big'}


def test_http_contract_and_local_only_security(exported):
    with TestClient(create_app(private_root=exported.root, key_loader=lambda _: 'synthetic-secret'), base_url='http://localhost') as c:
        listing=c.get('/api/datasets').json()['datasets']
        assert len(listing)==1 and listing[0]['rows']==40
        ds=listing[0]
        result=c.get(f"/api/datasets/{ds['dataset_id']}/dashboard").json()
        assert result['dataset_key']==exported.dataset_key
        assert c.get('/api/status').json()['ai_configured'] is True
        assert 'synthetic-secret' not in json.dumps([listing,result,c.get('/api/status').json()])
        assert c.get('/private_data/gemini_secrets.toml').status_code==404
        assert c.get('/api/status',headers={'Host':'evil.example'}).status_code==400
        assert c.post('/api/reports',json={}).status_code==403
        assert c.post('/api/reports',headers={**HEADERS,'Origin':'https://evil.example'},json={}).status_code==403
        assert c.get('/api/status').headers['cache-control']=='no-store'
        assert c.get(f"/api/datasets/{ds['dataset_id']}/dashboard?audience=Unknown").status_code==400


def test_report_has_wider_scope_and_includes_censored_comments(exported):
    from report_service import generate_report
    reporter=Mock(wraps=generate_report)
    with TestClient(create_app(private_root=exported.root, reporter=reporter, key_loader=lambda _: None),base_url='http://localhost') as c:
        ds=c.get('/api/datasets').json()['datasets'][0]
        body=dict(dataset_id=ds['dataset_id'], expected_dataset_key=ds['dataset_key'], use_llm=False, audience='Students', input_policy='censored_comments_v1')
        result=c.post('/api/reports',headers=HEADERS,json=body)
        assert result.status_code==200
        assert result.json()['scope']=='All surveyed locations · Students'
        assert result.json()['report']['mode']=='template'
        assert reporter.call_args.args==(exported.path, 'Students')
        assert reporter.call_args.kwargs['include_censored_comments'] is True
        assert result.json()['report']['censored_comment_count']==40
        assert result.json()['report']['input_policy']=='censored_comments_v1'
        assert c.post('/api/reports',headers=HEADERS,json={**body,'county':'Montgomery'}).status_code==422
        assert c.post('/api/reports',headers=HEADERS,json={**body,'use_llm':'False'}).status_code==422
        assert c.post('/api/reports',headers=HEADERS,json={**body,'include_approved_comments':True}).status_code==422


def test_stale_dataset_rejected_before_provider(exported):
    reporter=Mock(side_effect=AssertionError('No provider allowed'))
    with TestClient(create_app(private_root=exported.root,reporter=reporter),base_url='http://localhost') as c:
        ds=c.get('/api/datasets').json()['datasets'][0]
        c.get(f"/api/datasets/{ds['dataset_id']}/dashboard")
        exported.path.write_bytes(exported.path.read_bytes()+b'\n')
        assert c.get(f"/api/datasets/{ds['dataset_id']}/dashboard").status_code==409
        assert c.post('/api/reports',headers=HEADERS,json=dict(dataset_id=ds['dataset_id'],expected_dataset_key=ds['dataset_key'],input_policy='censored_comments_v1')).status_code==409
        reporter.assert_not_called()


def wait_job(c, token):
    for _ in range(100):
        value=c.get('/api/jobs/'+token).json()
        if value['status'] != 'processing': return value
        time.sleep(.01)
    pytest.fail('Local processing did not finish')


def test_upload_runs_cleaning_and_returns_new_censored_handle(exported):
    def pipeline(source, root):
        with privacy_adapter.using(PresidioBridge(FakeEngine())):
            result=cleaner.run_pipeline(source,runner.SCHEMA,runner.REGISTRY)
        return result,write_stage_outputs(result,root,source)
    store=DatasetStore(exported.root,pipeline=pipeline)
    payload=csv_bytes([fictional_row(response_id=f'new{i}',most_valuable='ada@example.com') for i in range(30)])
    with TestClient(create_app(private_root=exported.root,store=store),base_url='http://localhost') as c:
        result=c.post('/api/uploads',headers=HEADERS,files={'file':('survey.csv',payload,'text/csv')})
        assert result.status_code==202
        job=wait_job(c,result.json()['job_id'])
        assert job['status']=='ready' and job['dataset']['rows']==30
        assert job['dataset']['dataset_id'] != exported.sha256
        result=c.get(f"/api/datasets/{job['dataset']['dataset_id']}/dashboard")
        assert result.json()['summaries']['(all)']['n']==30
        assert 'ada@example.com' not in result.text
        assert any(p.read_bytes()==payload for p in (exported.root/'raw/uploads').glob('*/*.csv'))
        assert exported.path.read_bytes()  # Previous dataset remains available.


def test_failed_upload_keeps_previous_data_and_sanitizes_errors(exported):
    before=exported.path.read_bytes()
    def fail(*args): raise RuntimeError('SECRET ada@example.com')
    store=DatasetStore(exported.root,pipeline=fail)
    with TestClient(create_app(private_root=exported.root,store=store),base_url='http://localhost') as c:
        assert c.post('/api/uploads',headers=HEADERS,files={'file':('script.exe',b'x')}).status_code==400
        result=c.post('/api/uploads',headers=HEADERS,files={'file':('bad.csv',b'bad file')})
        job=wait_job(c,result.json()['job_id'])
        assert job['status']=='failed' and 'SECRET' not in json.dumps(job) and 'ada@example.com' not in json.dumps(job)
    assert exported.path.read_bytes()==before


def test_optional_display_fields_do_not_break_current_dataset(exported):
    omitted={'training_date','presenter_engaged','presenter_engaged__status','recommend','recommend__status','call_intent','call_intent__status'}
    def remove(header, rows):
        header[:]=[name for name in header if name not in omitted]
        for row in rows:
            for name in omitted: row.pop(name,None)
    rewrite(exported,remove)
    from everymind_cleaning.censored_data import load_censored_export
    value=Dashboard(load_censored_export(exported.path)).for_audience('All respondents')
    row=value['cube'][0]
    assert row['n']==40 and row['nps'] is row['call_mean'] is row['engaged_mean'] is None
    json.dumps(value,allow_nan=False)


def test_display_metric_protects_small_valid_complement(exported):
    def change(_, rows):
        for i,row in enumerate(rows):
            row['county']='Montgomery' if i < 25 else ('Anne Arundel' if i < 37 else 'Rare place')
            if 25 <= i < 39:
                for name in ('identify_before','identify_after','describe_before','describe_after','when_before','when_after'):
                    row[name]=''
                    row[name+'__status']='skipped'
    rewrite(exported,change)
    from everymind_cleaning.censored_data import load_censored_export
    value=Dashboard(load_censored_export(exported.path)).for_audience('All respondents')
    root=value['cube'][0]
    county=next(row for row in value['cube'] if row['county']=='Montgomery' and row['role']=='(all)' and row['split_dim']=='none')
    assert root['gain_index'] is not None
    assert county['gain_index'] is None


def test_old_report_page_must_reload_before_new_comment_payload(exported):
    reporter=Mock(side_effect=AssertionError('Stale UI must not call the provider'))
    with TestClient(create_app(private_root=exported.root,reporter=reporter),base_url='http://localhost') as c:
        ds=c.get('/api/datasets').json()['datasets'][0]
        result=c.post('/api/reports',headers=HEADERS,json=dict(dataset_id=ds['dataset_id'],expected_dataset_key=ds['dataset_key']))
        assert result.status_code==409 and 'Reload' in result.json()['detail']
        reporter.assert_not_called()
