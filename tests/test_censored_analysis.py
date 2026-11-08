"""Censored-file handoff tests using fictional records and a deterministic redactor."""

import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
from unittest.mock import patch

import pandas as pd
import pytest

import cleaned_analysis as ca
from everymind_cleaning import everymind_clean as ec, privacy_adapter
from everymind_cleaning.censored_data import CensoredExportError, load_censored_export
from everymind_cleaning.presidio_bridge import PresidioBridge
from everymind_cleaning.stage_outputs import write_stage_outputs
from everymind_cleaning import run_pipeline as runner
from test_cleaning_integration import FakeEngine, csv_bytes, fictional_row


@pytest.fixture
def exported(tmp_path):
    root = tmp_path / "private_data"
    source = root / "raw" / "source.csv"
    source.parent.mkdir(parents=True)
    rows = [fictional_row(response_id=f"{i:04d}", role="Student" if i < 20 else "Other (e.g., community member)",
                          recommend="0" if i == 0 else "8", call_intent="" if i == 1 else "0",
                          most_valuable="Clear explanation of 988. ada@example.com",
                          improve="Add a practice call scenario." if i % 20 < 10 else "Adjust the pacing.")
            for i in range(40)]
    source.write_bytes(csv_bytes(rows))
    with privacy_adapter.using(PresidioBridge(FakeEngine())):
        result = ec.run_pipeline(source, runner.SCHEMA, runner.REGISTRY)
    paths = write_stage_outputs(result, root, source)
    return load_censored_export(paths["censored"])


def rewrite(export, change):
    """Model a newly published export, updating its manifest alongside the file."""
    with export.path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    header = list(rows[0])
    change(header, rows)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=header)
    writer.writeheader()
    writer.writerows(rows)
    export.path.write_text(stream.getvalue(), newline="")
    stage = next(s for s in export.manifest["stages"] if s["stage"] == "censored")
    stage.update(sha256=hashlib.sha256(export.path.read_bytes()).hexdigest(), columns=len(header), column_names=header)
    stage["column_types"] = {c: stage["column_types"].get(c, "object") for c in header}
    export.manifest_path.write_text(json.dumps(export.manifest))


def approvals(export):
    _, comments = ca.adapt_cleaned(export.data)
    packet = ca.prepare_review_packet(comments)
    for record in packet:
        if record["source_field"] == "most_valuable":
            paraphrase, themes = "Clear explanation of 988.", ["THEME_988_KNOWLEDGE"]
        elif "scenario" in record["original_text"]:
            paraphrase, themes = "Add practice scenarios.", ["THEME_SCENARIOS"]
        else:
            paraphrase, themes = "Adjust the pacing.", ["THEME_PACING"]
        record.update(reviewer_status="approved", privacy_screened=True,
                      approved_paraphrase=paraphrase, theme_ids=themes,
                      approved_paraphrase_fingerprint=hashlib.sha256(paraphrase.encode()).hexdigest())
    return packet


def test_csv_scalars_keep_false_flags_ids_zero_and_missing(exported):
    data = exported.data
    assert data.response_id.iloc[0] == data.original_id.iloc[0] == "0000"
    assert data.role_student.dtype == bool and data.role_other.dtype == bool
    assert data.role_student.sum() == data.role_other.sum() == 20
    assert not data.role_staff.any() and not data.role_caregiver.any()
    assert data.call_intent.iloc[0] == data.recommend.iloc[0] == 0
    assert pd.isna(data.call_intent.iloc[1])
    assert data.call_intent__status.iloc[1] == ec.SKIPPED
    responses, comments = ca.adapt_cleaned(data)
    assert responses.role_membership.iloc[0] == ["Student"]
    assert responses.role_membership.iloc[-1] == ["Community member"]
    assert not comments.original_text.str.contains("ada@example.com", regex=False).any()


def test_analysis_never_reopens_sources_or_private_originals(exported):
    shutil.rmtree(exported.root / "raw")
    shutil.rmtree(exported.path.parent / "private")
    with patch.object(ec, "run_pipeline", side_effect=AssertionError("Re-ingestion attempted")), \
         patch("everymind_cleaning.presidio_bridge.build_redactor", side_effect=AssertionError("Model loading attempted")):
        payload = ca.run(exported.path)
    text = json.dumps(payload, allow_nan=False)
    assert "ada@example.com" not in text and "response_id" not in text and "original_text" not in text
    assert payload["schema_version"] == "everymind.analysis.v2"
    assert payload["dataset_key"] == exported.dataset_key
    assert payload["approved_comment_evidence"] == []


def test_csv_unicode_multiline_quotes_and_content_identity(exported):
    value = 'Unicode ñ 😊, "quoted"\nnext line <EMAIL_ADDRESS>'
    rewrite(exported, lambda header, rows: rows[0].update(most_valuable__redacted=value))
    updated = load_censored_export(exported.path)
    assert updated.data.most_valuable__redacted.iloc[0] == value
    assert updated.dataset_key != exported.dataset_key
    assert ca.run(updated.path)["dataset_key"] == updated.dataset_key


@pytest.mark.parametrize("change", [
    lambda header, rows: rows[0].update(role_student="not a boolean"),
    lambda header, rows: rows[0].update(most_valuable__privacy="pending"),
    lambda header, rows: rows[0].update(call_intent="invalid numeric"),
    lambda header, rows: rows[0].update(most_valuable__lang="unsupported"),
    lambda header, rows: rows[1].update(source_row=rows[0]["source_row"]),
])
def test_invalid_scalars_pending_comments_and_linkage_fail(exported, change):
    rewrite(exported, change)
    with pytest.raises(CensoredExportError, match="run_pipeline"):
        load_censored_export(exported.path)


def test_raw_old_incomplete_and_tampered_exports_are_rejected(exported):
    with pytest.raises(CensoredExportError, match="run_pipeline"):
        ca.run(exported.root / "raw" / "source.csv")
    with pytest.raises(CensoredExportError, match="run_pipeline"):
        ca.run(exported.root / "raw" / "source.xlsx")
    exported.path.write_bytes(exported.path.read_bytes() + b"\n")
    with pytest.raises(CensoredExportError, match="inconsistent"):
        load_censored_export(exported.path)
    exported.manifest["schema_version"] = "everymind.stages.v1"
    exported.manifest_path.write_text(json.dumps(exported.manifest))
    with pytest.raises(CensoredExportError, match="outdated"):
        load_censored_export(exported.path)


def test_missing_optional_columns_and_duplicate_ids(exported):
    def remove_optional(header, rows):
        removed = [c for c in header if c.startswith("most_valuable__") or c in ("call_intent", "call_intent__status")]
        for column in removed:
            header.remove(column)
            for row in rows:
                row.pop(column)
    rewrite(exported, remove_optional)
    result = ca.run(exported.path)
    assert next(row for row in result["coverage"]["quantitative"] if row["field"] == "intent")["status"] == "absent"
    rewrite(load_censored_export(exported.path), lambda header, rows: rows[1].update(response_id=rows[0]["response_id"]))
    with pytest.raises(ValueError, match="unique"):
        ca.run(exported.path)


def test_fingerprints_and_approvals_bind_censored_text(exported):
    reviews = approvals(exported)
    lineage = {}
    payload = ca.run(exported.path, "Students", reviews, lineage_out=lineage)
    assert len(payload["approved_comment_evidence"]) == len(lineage) == 40
    assert "ada@example.com" not in json.dumps(payload)
    reviews[0]["content_fingerprint"] = hashlib.sha256(b"Clear explanation of 988. ada@example.com").hexdigest()
    payload = ca.run(exported.path, "Students", reviews)
    assert not any(c["source_field"] == "most_valuable" for c in payload["approved_comment_evidence"])
    assert len(payload["approved_comment_evidence"]) == 20


def test_cli_defaults_are_private_and_packet_remains_pending(exported, monkeypatch, capsys):
    monkeypatch.setattr(ca, "PRIVATE_DATA", exported.root)
    assert ca.main([str(exported.path), "--prepare-review"]) == 0
    stdout = capsys.readouterr().out
    assert "Censored rows: 40" in stdout and "ada@example.com" not in stdout
    output = exported.root / "reports" / exported.source_key / "ai_input.json"
    before = output.read_bytes()
    packet_path = exported.path.parent / "private" / "comment_review_pending.json"
    packet = json.loads(packet_path.read_text())
    assert len(packet) == 80 and not (exported.root / "analysis").exists()
    assert "ada@example.com" not in packet_path.read_text()
    assert all(r["reviewer_status"] == "pending" and r["privacy_screened"] is False for r in packet)
    with pytest.raises(SystemExit) as error:
        ca.main([str(exported.path), "--prepare-review"])
    assert error.value.code == 1 and output.read_bytes() == before


def test_analysis_publication_rolls_back_payload_and_private_companions(exported, monkeypatch):
    monkeypatch.setattr(ca, "PRIVATE_DATA", exported.root)
    first = ca.publish_analysis(exported, ca.run(exported.path), lineage={})
    previous = first["payload"].read_bytes()
    lineage, packet = {}, []
    payload = ca.run(exported.path, reviews=approvals(exported), lineage_out=lineage, review_packet_out=packet)
    replace = Path.replace
    def fail_lineage(path, destination):
        if path.name == "lineage.json":
            raise OSError("synthetic publication failure")
        return replace(path, destination)
    with patch.object(Path, "replace", fail_lineage), pytest.raises(OSError):
        ca.publish_analysis(exported, payload, lineage=lineage, packet=packet)
    assert first["payload"].read_bytes() == previous
    assert not (exported.path.parent / "private" / "comment_review_pending.json").exists()
    assert not list(exported.root.glob(".analysis-*"))


def test_analysis_output_cannot_escape_or_overwrite_stage_files(exported, monkeypatch):
    monkeypatch.setattr(ca, "PRIVATE_DATA", exported.root)
    payload = ca.run(exported.path)
    for destination in [exported.root.parent / "outside.json", exported.manifest_path]:
        with pytest.raises(ValueError, match="private_data"):
            ca.publish_analysis(exported, payload, lineage={}, output_path=destination)


def test_analysis_outputs_cannot_collide_with_private_review_packet(exported, monkeypatch):
    monkeypatch.setattr(ca, "PRIVATE_DATA", exported.root)
    destination = exported.path.parent / "private" / "comment_review_pending.json"
    payload = ca.run(exported.path)
    for packet in (None, []):
        with pytest.raises(ValueError, match="distinct|pending review"):
            ca.publish_analysis(exported, payload, lineage={}, packet=packet, output_path=destination)
    assert not destination.exists()


@pytest.mark.parametrize("invalid", ["types", "outputs"])
def test_malformed_manifest_types_are_clear_errors(exported, invalid):
    if invalid == "types":
        next(s for s in exported.manifest["stages"] if s["stage"] == "censored")["column_types"]["source_row"] = None
    else:
        exported.manifest["outputs"] = []
    exported.manifest_path.write_text(json.dumps(exported.manifest))
    with pytest.raises(CensoredExportError, match="run_pipeline"):
        load_censored_export(exported.path)
