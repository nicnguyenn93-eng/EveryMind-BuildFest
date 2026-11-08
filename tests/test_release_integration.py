"""John's release safeguards through the primary cleaning/censoring/API path."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from cleaned_analysis import adapt_cleaned, run as analyze
from everymind_cleaning import everymind_clean as ec, privacy_adapter, release
from everymind_cleaning import run_pipeline as runner
from everymind_cleaning.censored_data import load_censored_export
from everymind_cleaning.presidio_bridge import PresidioBridge
from everymind_cleaning.stage_outputs import write_stage_outputs
from everymind_web.aggregates import Dashboard
from test_cleaning_integration import FakeEngine, csv_bytes, fictional_row


def source_file(root, rows):
    source = root / "raw" / "source.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(csv_bytes(rows))
    return source


def run_primary(root, source):
    with patch.object(runner, "PRIVATE_DATA", root):
        return runner.run(source, root, bridge=PresidioBridge(FakeEngine()))


def test_primary_uses_strict_parsing_nullable_roles_and_release_gate(tmp_path):
    root = tmp_path / "private_data"
    rows = [fictional_row(response_id=f"{i:04d}", role="Student", most_valuable="Clear explanation of 988.")
            for i in range(20)]
    rows[0].update(role="Teacher;Caregiver/parent", recommend="1e1", call_intent="0",
                   completion_time="", training_date="03/04/2026")
    rows[1].update(role="", recommend="0")
    source = source_file(root, rows)
    before = source.read_bytes()
    result, paths = run_primary(root, source)
    data = load_censored_export(paths["censored"]).data
    assert result.release_config is not None
    assert pd.isna(data.recommend.iloc[0]) and data.recommend__status.iloc[0] == "invalid"
    assert data.call_intent.iloc[0] == data.recommend.iloc[1] == 0
    assert pd.isna(data.training_date.iloc[0]) and pd.isna(data.flag_fast.iloc[0])
    assert data.role__status.iloc[0] == "partially_mapped"
    assert pd.isna(data.role_student.iloc[0]) and data.role_caregiver.iloc[0]
    assert data.comparison_group.iloc[:2].tolist() == ["Unknown", "Unknown"]
    responses, _ = adapt_cleaned(data)
    assert responses.role_membership.iloc[:2].tolist() == [[], []]
    assert analyze(paths["censored"])["status"] == "available"
    assert Dashboard(load_censored_export(paths["censored"])).for_audience("All respondents")["dataset_key"]
    assert source.read_bytes() == before


def test_missing_ratings_warn_without_blocking_primary_publication(tmp_path):
    root = tmp_path / "private_data"
    source = source_file(root, [fictional_row(response_id=str(i), identify_after="" if i else "Agree")
                                for i in range(10)])
    with pytest.warns(UserWarning, match="identify_after valid rate"):
        result, paths = run_primary(root, source)
    failed = result.checks.loc[~result.checks["pass"]]
    assert failed.severity.eq("warn").all()
    assert load_censored_export(paths["censored"]).data.identify_after.notna().sum() == 1


@pytest.mark.parametrize("ids", [["", "2"], ["001", "1"], ["a1", "A1"]])
def test_release_blockers_cannot_publish_over_existing_outputs(tmp_path, ids):
    root = tmp_path / "private_data"
    source = source_file(root, [fictional_row(response_id="001"), fictional_row(response_id="002")])
    _, paths = run_primary(root, source)
    before = {name: path.read_bytes() for name, path in paths.items() if name != "raw_source"}
    source.write_bytes(csv_bytes([fictional_row(response_id=ids[0]), fictional_row(response_id=ids[1])]))
    with pytest.raises(ValueError, match="Release blocked"):
        run_primary(root, source)
    assert before == {name: paths[name].read_bytes() for name in before}


def test_release_schema_migration_archives_previous_stages_and_rolls_back(tmp_path):
    root = tmp_path / "private_data"
    source = source_file(root, [fictional_row(response_id="001"), fictional_row(response_id="002")])
    with privacy_adapter.using(PresidioBridge(FakeEngine())):
        previous = ec.run_pipeline(source, runner.SCHEMA, runner.REGISTRY)
        updated = release.run_pipeline(source, runner.SCHEMA, runner.REGISTRY)
    paths = write_stage_outputs(previous, root, source)
    before = {name: path.read_bytes() for name, path in paths.items()}
    original_replace = Path.replace

    def fail_manifest(path, destination):
        if path.name == "manifest.json":
            raise OSError("synthetic failure")
        return original_replace(path, destination)

    with patch.object(Path, "replace", fail_manifest), pytest.raises(OSError):
        write_stage_outputs(updated, root, source)
    assert before == {name: paths[name].read_bytes() for name in before}
    assert not any(path.is_file() for path in (root / "archive").rglob("*"))
    published = write_stage_outputs(updated, root, source)
    for name, contents in before.items():
        if name != "raw_source":
            assert published["archive_" + name].read_bytes() == contents
    manifest = json.loads(published["manifest"].read_text())
    assert manifest["cleaning_release"]["schema_version"] == release.OUTPUT_SCHEMA_VERSION
    assert manifest["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert load_censored_export(published["censored"]).data.response_id.tolist() == ["001", "002"]


def test_edited_result_is_revalidated_before_staging(tmp_path):
    root = tmp_path / "private_data"
    source = source_file(root, [fictional_row()])
    with privacy_adapter.using(PresidioBridge(FakeEngine())):
        result = release.run_pipeline(source, runner.SCHEMA, runner.REGISTRY)
    result.data.loc[0, "response_id"] = ""
    result.censored_stage.loc[0, "response_id"] = ""
    result.cleaned_stage.loc[0, "response_id"] = ""
    with pytest.raises(ValueError, match="Validation failed"):
        write_stage_outputs(result, root, source)
    assert not (root / "censoring").exists()
