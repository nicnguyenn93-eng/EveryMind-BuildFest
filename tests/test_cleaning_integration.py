"""Integration boundaries use fictional data and a deterministic redactor."""

import contextlib
import csv
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from everymind_cleaning import everymind_clean as ec, privacy_adapter
from everymind_cleaning.presidio_bridge import PresidioBridge, get_engine
from everymind_cleaning import run_pipeline as runner
from everymind_cleaning.stage_outputs import write_stage_outputs
from everymind_censoring.redact_pii import Detection, Redaction, RedactionError


class FakeEngine:
    versions = {"packages": {"fictional_engine": "1"}, "models": {}}

    def __init__(self):
        self.calls = []

    def redact(self, text, language):
        self.calls.append((text, language))
        value = "ada@example.com"
        if value in text:
            start = text.index(value)
            return Redaction(text.replace(value, "<EMAIL_ADDRESS>"),
                             [Detection("EMAIL_ADDRESS", start, start + len(value), 1.0)])
        return Redaction(text, [])


def fictional_row(**changes):
    row = {"response_id": "007", "start_time": "2026-04-01 12:00:00",
           "completion_time": "2026-04-01 12:02:00", "training_date": "2026-04-01",
           "form_language": "English (United States)\u200e", "role": "Student", "county": "Anne Arundel",
           "recommend": "0", "call_intent": "0", "most_valuable": "I learned to ask for help.", "improve": ""}
    for name, spec in ec.load_config(runner.SCHEMA)["columns"].items():
        if spec["type"] == "likert5":
            row[name] = "Agree"
    row.update(changes)
    return row


def csv_bytes(rows):
    cfg = ec.load_config(runner.SCHEMA)
    columns = [name for name in cfg["columns"] if cfg["columns"][name]["type"] != "drop"]
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([cfg["columns"][name]["synonyms"][0] for name in columns])
    writer.writerows([[row.get(name, "") for name in columns] for row in rows])
    return buffer.getvalue().encode("utf-8-sig")


class CleaningIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.context = privacy_adapter.using()
        self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.engine = FakeEngine()
        self.bridge = PresidioBridge(self.engine)

    def process(self, rows, connect=True):
        if connect:
            privacy_adapter.connect(self.bridge, "fictional test bridge")
        return ec.run_pipeline(csv_bytes(rows), runner.SCHEMA, runner.REGISTRY, filename="fictional.csv")

    def test_batch_order_routing_blanks_and_no_default_language(self):
        texts = ["ada@example.com", " \t\n", "", "Hola ada@example.com"]
        self.assertEqual(["<EMAIL_ADDRESS>", " \t\n", "", "Hola <EMAIL_ADDRESS>"],
                         self.bridge(texts, ["en", "none", "unknown", "es"]))
        self.assertEqual([("ada@example.com", "en"), ("Hola ada@example.com", "es")], self.engine.calls)
        self.assertEqual(4, len(self.bridge.last_review))
        for languages in (["en"], ["en", "unknown"]):
            with self.assertRaises(RedactionError):
                self.bridge(["would scan", "second"], languages)
        self.assertIsNone(self.bridge.last_review)

    def test_engine_is_initialized_once(self):
        get_engine.cache_clear()
        self.addCleanup(get_engine.cache_clear)
        with patch("everymind_cleaning.presidio_bridge.build_redactor", return_value=self.engine) as factory:
            self.assertIs(PresidioBridge().engine, PresidioBridge().engine)
            factory.assert_called_once()

    def test_normalized_offsets_and_verbatim_review(self):
        original = '  “Hola,\r\nAda” 😊 ada@example.com  '
        result = self.process([fictional_row(most_valuable=original, improve=" \t\r\n")])
        review = result.privacy_review.set_index("field")
        item = review.loc["most_valuable"]
        self.assertEqual(original, item.original_text)
        self.assertEqual(ec.clean_str(original), item.normalized_input)
        detection = json.loads(item.detections)[0]
        self.assertEqual("ada@example.com", item.normalized_input[detection["start"]:detection["end"]])
        self.assertNotIn("ada@example.com", item.redacted_text)
        self.assertEqual(" \t\r\n", review.loc["improve"].original_text)
        self.assertEqual("blank", review.loc["improve"].status)
        self.assertEqual("none", review.loc["improve"].language)
        self.assertEqual("007", item.original_id)
        self.assertEqual(0, result.data.call_intent.iloc[0])
        self.assertTrue(result.checks["pass"].all())
        self.assertNotIn("most_valuable", result.data)
        self.assertNotIn("source_originals", result.data.attrs)
        self.assertNotIn("ada@example.com", json.dumps(result.privacy_summary))

    def test_provenance_does_not_change_deduplication_or_duplicate_id_flags(self):
        original = fictional_row(most_valuable="  I learned to listen.  ")
        result = self.process([original, original.copy(), {},
                               fictional_row(most_valuable="A different answer."),
                               {**original, "response_id": "008"}])
        self.assertEqual(3, len(result.data))
        self.assertEqual([2, 5, 6], result.private.source_row.tolist())
        self.assertEqual([2, 5, 6], result.cleaned_stage.source_row.tolist())
        self.assertEqual([2, 5, 6], result.censored_stage.source_row.tolist())
        self.assertEqual(["007", "007", "008"], result.private.original_id.tolist())
        self.assertEqual(2, int(result.data.flag_duplicate_id.sum()))
        self.assertEqual(2, int(result.data.flag_possible_duplicate.sum()))
        self.assertEqual([2, 2, 5, 5, 6, 6], sorted(result.privacy_review.source_row.tolist()))
        steps = {s["step"]: s for s in result.audit.steps}
        self.assertEqual([4], steps["Ingest"]["removed_source_rows"])
        self.assertEqual([3], steps["Deduplicate"]["removed_source_rows"])

    def test_johns_comment_language_overrides_form_without_changing_form(self):
        result = self.process([fictional_row(most_valuable="La información.", improve="I learned about help.")])
        self.assertEqual("en", result.data.form_language.iloc[0])
        self.assertEqual("es", result.data.most_valuable__lang.iloc[0])
        self.assertEqual("en", result.data.improve__lang.iloc[0])
        self.assertEqual(["es", "en"], [language for _, language in self.engine.calls])
        self.assertEqual(1, result.privacy_summary["form_language_disagreements"])

    def test_unknown_nonblank_language_errors_and_adapter_restores(self):
        with privacy_adapter.using(self.bridge, "prior bridge"):
            with self.assertRaisesRegex(RedactionError, "Unsupported language"):
                self.process([fictional_row(form_language="", most_valuable="xyzzy")])
        self.assertFalse(privacy_adapter.is_connected())
        with privacy_adapter.using(self.bridge, "prior bridge"):
            with self.assertRaises(RuntimeError):
                with privacy_adapter.using(lambda texts, languages: texts, "temporary"):
                    raise RuntimeError("test")
            self.assertEqual("prior bridge", privacy_adapter.tool_name())

    def test_bridge_sanitizes_engine_failures(self):
        with patch.object(self.engine, "redact", side_effect=RuntimeError("raw secret response")):
            with self.assertRaises(RedactionError) as error:
                self.bridge(["raw secret response"], ["en"])
        self.assertNotIn("raw secret", str(error.exception))

    def test_structured_cleaning_is_independent_of_redactor(self):
        rows = [fictional_row(most_valuable="ada@example.com"), fictional_row(response_id="008", call_intent="")]
        baseline = self.process(rows, connect=False)
        integrated = self.process(rows)
        keep = [c for c in baseline.data if not c.endswith(("__redacted", "__privacy"))]
        pd.testing.assert_frame_equal(baseline.data[keep], integrated.data[keep])

    def test_missing_models_dont_touch_prior_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            source.write_bytes(csv_bytes([fictional_row()]))
            sentinel = root / "cleaning" / "prior.csv"
            sentinel.parent.mkdir()
            sentinel.write_bytes(b"prior result")
            with patch.object(runner, "PRIVATE_DATA", root), patch.object(runner, "PresidioBridge", side_effect=RedactionError("models missing")):
                with self.assertRaisesRegex(RedactionError, "models missing"):
                    runner.run(source, sentinel.parent)
            self.assertEqual(b"prior result", sentinel.read_bytes())

    def test_staging_and_finalization_failures_preserve_all_outputs(self):
        result = self.process([fictional_row(most_valuable="ada@example.com")])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = ec.write_outputs(result, root / "outputs", root / "private")
            before = {name: path.read_bytes() for name, path in paths.items()}
            original_replace = Path.replace
            def fail(path, target):
                if path.name.startswith("presidio_summary_"):
                    raise OSError("synthetic replacement failure")
                return original_replace(path, target)
            with patch.object(Path, "replace", fail), self.assertRaises(OSError):
                ec.write_outputs(result, root / "outputs", root / "private")
            self.assertEqual(before, {name: path.read_bytes() for name, path in paths.items()})
            with patch.object(Path, "write_text", side_effect=OSError("disk full")), self.assertRaises(OSError):
                ec.write_outputs(result, root / "outputs", root / "private")
            self.assertEqual(before, {name: path.read_bytes() for name, path in paths.items()})
            self.assertEqual([], list((root / "outputs").glob(".cleaning-*")))
            result.checks.loc[0, "pass"] = False
            with self.assertRaisesRegex(ValueError, "Validation failed"):
                ec.write_outputs(result, root / "outputs", root / "private")
            self.assertEqual(before, {name: path.read_bytes() for name, path in paths.items()})

    def test_csv_and_excel_preserve_same_fields_and_cleaned_values(self):
        from openpyxl import Workbook
        rows = [fictional_row(most_valuable='Unicode ñ 😊, "quoted"\nnext line', call_intent="0")]
        payload = csv_bytes(rows)
        parsed = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"), newline="")))
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Survey Data"
        for row in parsed:
            sheet.append(row)
        buffer = io.BytesIO()
        workbook.save(buffer)
        workbook.close()
        privacy_adapter.connect(self.bridge)
        csv_result = ec.run_pipeline(payload, runner.SCHEMA, runner.REGISTRY, filename="source.csv")
        xlsx_result = ec.run_pipeline(buffer.getvalue(), runner.SCHEMA, runner.REGISTRY, filename="source.xlsx")
        pd.testing.assert_frame_equal(csv_result.data, xlsx_result.data)
        pd.testing.assert_frame_equal(csv_result.privacy_review, xlsx_result.privacy_review)

    def test_cli_custom_input_outputs_and_counts_without_response_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            source.write_bytes(csv_bytes([fictional_row(most_valuable="ada@example.com")]))
            stdout = io.StringIO()
            with patch.object(runner, "PRIVATE_DATA", root), patch.object(runner, "PresidioBridge", return_value=self.bridge), contextlib.redirect_stdout(stdout):
                self.assertEqual(0, runner.main(["--input", str(source), "--output-dir", str(root / "cleaning")]))
            self.assertIn("Data rows: 1", stdout.getvalue())
            self.assertNotIn("ada@example.com", stdout.getvalue())
            self.assertFalse(privacy_adapter.is_connected())
            with patch.object(runner, "PRIVATE_DATA", root), self.assertRaises(RedactionError):
                runner.output_directories("key", root.parent / "outside")

    def test_johns_direct_module_import_and_writer_remain_usable(self):
        program = '''
from pathlib import Path
import tempfile
import pandas as pd
import everymind_clean as ec
import privacy_adapter
with tempfile.TemporaryDirectory() as directory:
    result = ec.Result(pd.DataFrame({"response_id": ["fictional"]}),
                       pd.DataFrame({"response_id": ["fictional"], "x__distress_flag": [False]}),
                       ec.Audit(dataset_key="fictional"), pd.DataFrame({"pass": [True]}))
    paths = ec.write_outputs(result, Path(directory) / "outputs", Path(directory) / "private")
    assert all(path.is_file() for path in paths.values())
'''
        completed = subprocess.run([sys.executable, "-c", program], cwd=runner.PACKAGE,
                                   capture_output=True, text=True)
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_stage_files_preserve_linkage_and_only_censor_comment_values(self):
        rows = [fictional_row(most_valuable='  “Hola”\nada@example.com  '),
                fictional_row(response_id="008", most_valuable="I learned how to call 988.")]
        result = self.process(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "raw" / "source.csv"
            source.parent.mkdir()
            payload = csv_bytes(rows)
            source.write_bytes(payload)
            paths = write_stage_outputs(result, root, source)
            self.assertEqual(source.resolve(), paths["raw_source"])
            self.assertEqual(payload, source.read_bytes())
            self.assertEqual("cleaned", paths["cleaned"].relative_to(root).parts[0])
            self.assertEqual("censoring", paths["censored"].relative_to(root).parts[0])
            self.assertNotIn("analysis_ready", paths)
            self.assertFalse((root / "analysis").exists())
            def read(path):
                with path.open(newline="") as handle:
                    return list(csv.DictReader(handle))
            clean, censored = [read(paths[name]) for name in ("cleaned", "censored")]
            self.assertEqual(list(clean[0]), list(censored[0]))
            self.assertIn("ada@example.com", clean[0]["most_valuable"])
            self.assertNotIn("ada@example.com", censored[0]["most_valuable"])
            for before, after in zip(clean, censored):
                for key in ("source_row", "original_id", "response_id"):
                    self.assertEqual(before[key], after[key])
                for key in before:
                    if key not in ("most_valuable", "improve"):
                        self.assertEqual(before[key], after[key])
            self.assertEqual("007", clean[0]["original_id"])
            self.assertEqual("0.0", clean[0]["call_intent"])
            manifest = json.loads(paths["manifest"].read_text())
            self.assertEqual(["raw", "cleaned", "censored"], [stage["stage"] for stage in manifest["stages"]])
            self.assertIn("cleaned", paths["guide"].read_text())

    def test_stage_publication_rolls_back_all_folders(self):
        rows = [fictional_row(most_valuable="ada@example.com")]
        result = self.process(rows)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = parent / "source.csv"
            source.write_bytes(csv_bytes(rows))
            root = parent / "private_data"
            paths = write_stage_outputs(result, root, source)
            self.assertNotEqual(source.resolve(), paths["raw_source"])
            previous = {name: path.read_bytes() for name, path in paths.items()}
            result.privacy_summary["test_attempt"] = 2
            replace = Path.replace
            def fail_guide(path, destination):
                if path.name == "README.md":
                    raise OSError("synthetic publication failure")
                return replace(path, destination)
            with patch.object(Path, "replace", fail_guide), self.assertRaises(OSError):
                write_stage_outputs(result, root, source)
            self.assertEqual(previous, {name: path.read_bytes() for name, path in paths.items()})
            self.assertEqual([], list(root.glob(".stages-*")))

    def test_stage_publication_rejects_changed_source_and_pending_privacy(self):
        rows = [fictional_row()]
        pending = self.process(rows, connect=False)
        integrated = self.process(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            source.write_bytes(csv_bytes(rows))
            with self.assertRaisesRegex(ValueError, "snapshots are required"):
                write_stage_outputs(pending, root, source)
            source.write_bytes(b"changed source")
            with self.assertRaisesRegex(ValueError, "source changed"):
                write_stage_outputs(integrated, root, source)
            self.assertFalse((root / "cleaned").exists())


@unittest.skipUnless(os.environ.get("RUN_PRESIDIO_INTEGRATION") == "1", "Set RUN_PRESIDIO_INTEGRATION=1 for installed-model checks.")
class OfflineInstalledIntegrationTests(unittest.TestCase):
    def test_john_pipeline_with_real_models_offline_on_cpu(self):
        import spacy
        from thinc.api import get_current_ops
        rows = [fictional_row(most_valuable="Me llamo María García y mi correo es ada@example.com."),
                fictional_row(response_id="008", form_language="Español (México)",
                               most_valuable="My name is Alice Johnson and my email is ada@example.com.")]
        get_engine.cache_clear()
        self.addCleanup(get_engine.cache_clear)
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Network attempted")), \
             patch.object(socket.socket, "connect_ex", side_effect=AssertionError("Network attempted")), \
             patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS attempted")), \
             patch.object(spacy.cli, "download", side_effect=AssertionError("Download attempted")), \
             patch.object(spacy, "require_gpu", side_effect=AssertionError("GPU attempted")):
            bridge = PresidioBridge()
            with privacy_adapter.using(bridge):
                result = ec.run_pipeline(csv_bytes(rows), runner.SCHEMA, runner.REGISTRY, filename="fictional.csv")
            self.assertEqual("NumpyOps", type(get_current_ops()).__name__)
            self.assertEqual(["es", "en"], result.data.most_valuable__lang.tolist())
            self.assertTrue(result.data.most_valuable__redacted.str.contains("<EMAIL_ADDRESS>").all())
            self.assertEqual(2, result.privacy_summary["changed"])


if __name__ == "__main__":
    unittest.main()
