"""Deterministic pipeline tests; no model download or real survey data required."""

import contextlib
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import redact_pii as pii


class FakeRedactor:
    versions = {"packages": {"test_engine": "1"}, "models": {}}

    def __init__(self):
        self.calls = []

    def redact(self, text, language):
        self.calls.append((text, language))
        marker = "ada@example.com"
        if marker in text:
            start = text.index(marker)
            return pii.Redaction(
                text.replace(marker, "<EMAIL_ADDRESS>"),
                [pii.Detection("EMAIL_ADDRESS", start, start + len(marker), 1.0)],
            )
        return pii.Redaction(text, [])


class RedactPiiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.private = Path(self.directory.name) / "private_data"
        self.private.mkdir()
        self.root_patch = patch.object(pii, "PRIVATE_DATA", self.private)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.source = self.private / "survey.csv"
        self.output = self.private / "survey_presidio.csv"
        self.paths = (self.output, self.output.with_suffix(".review.csv"), self.output.with_suffix(".summary.json"))
        self.header = ["Id", "Language", "numeric", *pii.COMMENT_FIELDS, "metadata"]
        self.engine = FakeRedactor()

    def write_source(self, rows, header=None):
        with self.source.open("w", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerows([header or self.header, *rows])

    def run_redaction(self):
        return pii.redact_csv(self.source, self.output, redactor_factory=lambda: self.engine)

    def existing_outputs(self):
        previous = {}
        for path in self.paths:
            path.write_bytes(b"existing result\n")
            previous[path] = path.read_bytes()
        return previous

    def assert_outputs_preserved(self, previous):
        for path, content in previous.items():
            self.assertEqual(content, path.read_bytes())
        self.assertEqual([], list(self.private.glob(".presidio-*")))

    def test_full_round_trip_and_audit_preserve_fields_blanks_and_source(self):
        rows = [
            ["007", "English (United States)\u200e", "0", 'Olá, "Ada"\r\nEmail ada@example.com 😊', " \t\r\n", "untouched@example.com"],
            ["008", "Español (México)", "", "Aprendí sobre el apoyo.", "", "same metadata"],
        ]
        self.write_source(rows)
        before = hashlib.sha256(self.source.read_bytes()).digest()
        summary, paths = self.run_redaction()
        self.assertEqual(self.paths, paths)
        with self.output.open(encoding="utf-8-sig", newline="") as handle:
            result = list(csv.reader(handle))
        expected = [row.copy() for row in rows]
        expected[0][3] = expected[0][3].replace("ada@example.com", "<EMAIL_ADDRESS>")
        self.assertEqual([self.header, *expected], result)
        self.assertTrue(self.output.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(before, hashlib.sha256(self.source.read_bytes()).digest())
        self.assertEqual([(rows[0][3], "en"), (rows[1][3], "es")], self.engine.calls)
        with paths[1].open(encoding="utf-8-sig", newline="") as handle:
            review = list(csv.DictReader(handle))
        self.assertEqual(4, len(review))
        self.assertEqual("2", review[0]["source_row"])
        self.assertEqual("007", review[0]["original_id"])
        self.assertEqual(rows[0][3], review[0]["original_text"])
        detection = json.loads(review[0]["detections"])[0]
        self.assertEqual("ada@example.com", rows[0][3][detection["start"]:detection["end"]])
        self.assertEqual({"entity_type", "start", "end", "score"}, set(detection))
        self.assertEqual("blank", review[1]["status"])
        self.assertEqual("[]", review[1]["detections"])
        self.assertEqual(1, summary["changed"])
        self.assertEqual(1, summary["unchanged"])
        self.assertEqual(2, summary["blank"])
        self.assertEqual({"EMAIL_ADDRESS": 1}, summary["detections_by_entity_type"])
        self.assertEqual(1, summary["by_language"]["en"]["detections"]["EMAIL_ADDRESS"])
        self.assertEqual(2, summary["by_language"]["es"]["comments"])
        self.assertEqual(summary, json.loads(paths[2].read_text()))
        for secret in ("ada@example.com", "untouched@example.com", "Aprendí", "007"):
            self.assertNotIn(secret, paths[2].read_text())

    def test_all_languages_validate_before_engine_creation_even_on_blank_comments(self):
        for label in ("", "   ", "French", "English-ish"):
            with self.subTest(label=label):
                self.write_source([["1", "en", "0", "would scan", "", ""], ["2", label, "0", "", "", ""]])
                previous = self.existing_outputs()
                with patch.object(pii, "build_redactor") as factory:
                    with self.assertRaisesRegex(pii.RedactionError, "Language at source row 3"):
                        pii.redact_csv(self.source, self.output, redactor_factory=factory)
                    factory.assert_not_called()
                self.assert_outputs_preserved(previous)

    def test_language_aliases_and_direction_marks(self):
        for label in ("en", " EN ", "English", "English (United States)\u200e"):
            self.assertEqual("en", pii.language_code(label, 2))
        for label in ("es", "Español", "Español (México)\u200f"):
            self.assertEqual("es", pii.language_code(label, 2))

    def test_required_headers_duplicates_and_row_width(self):
        cases = [
            (["Id", "Language", *pii.COMMENT_FIELDS[:1]], [], "Missing required headers"),
            ([*self.header, "Id"], [], "unique column names"),
            (self.header, [["1", "en"]], "column count"),
            ([name.rstrip() for name in self.header], [], "Missing required headers"),
        ]
        for header, rows, message in cases:
            with self.subTest(message=message):
                self.write_source(rows, header)
                previous = self.existing_outputs()
                with self.assertRaisesRegex(pii.RedactionError, message):
                    self.run_redaction()
                self.assert_outputs_preserved(previous)

    def test_output_must_be_private_csv_and_cannot_overwrite_source(self):
        self.write_source([])
        for destination in (self.source, self.private.parent / "public.csv", self.private / "result.xlsx"):
            with self.subTest(destination=destination):
                with self.assertRaises(pii.RedactionError):
                    pii.redact_csv(self.source, destination, redactor_factory=lambda: self.engine)
        # The input can also collide with a derived review filename.
        self.source.rename(self.private / "survey_presidio.review.csv")
        with self.assertRaisesRegex(pii.RedactionError, "overwrite the source"):
            pii.redact_csv(self.private / "survey_presidio.review.csv", self.output)

    def test_missing_input_preserves_outputs(self):
        previous = self.existing_outputs()
        with self.assertRaisesRegex(pii.RedactionError, "Input CSV not found"):
            self.run_redaction()
        self.assert_outputs_preserved(previous)

    def test_missing_or_wrong_model_versions_fail_before_loading(self):
        for version in (None, "3.7.0"):
            with self.subTest(version=version):
                self.write_source([["1", "en", "0", "hello", "", ""]])
                previous = self.existing_outputs()
                side_effect = pii.metadata.PackageNotFoundError if version is None else None
                with patch.object(pii.metadata, "version", return_value=version, side_effect=side_effect):
                    with self.assertRaisesRegex(pii.RedactionError, "requirements-models.txt"):
                        pii.redact_csv(self.source, self.output)
                self.assert_outputs_preserved(previous)

    def test_processing_failure_does_not_echo_text_or_replace_any_result(self):
        self.write_source([["1", "en", "0", "first comment", "private text", ""]])
        previous = self.existing_outputs()
        def failing(text, language):
            if text == "private text":
                raise RuntimeError("private text in exception")
            return pii.Redaction(text, [])
        self.engine.redact = failing
        with self.assertRaisesRegex(pii.RedactionError, "source row 2") as raised:
            self.run_redaction()
        self.assertNotIn("private text", str(raised.exception))
        self.assert_outputs_preserved(previous)

    def test_staging_failure_preserves_all_existing_results(self):
        self.write_source([])
        previous = self.existing_outputs()
        with patch.object(pii, "write_csv", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.run_redaction()
        self.assert_outputs_preserved(previous)

    def test_finalization_error_rolls_back_prior_replacement(self):
        self.write_source([])
        previous = self.existing_outputs()
        original_replace = Path.replace
        def fail_review(path, destination):
            if path.name == self.paths[1].name:
                raise OSError("synthetic replacement failure")
            return original_replace(path, destination)
        with patch.object(Path, "replace", fail_review):
            with self.assertRaises(OSError):
                self.run_redaction()
        self.assert_outputs_preserved(previous)

    def test_successful_rerun_replaces_three_outputs(self):
        self.write_source([])
        previous = self.existing_outputs()
        summary, _ = self.run_redaction()
        self.assertEqual(0, summary["comments"])
        for path, content in previous.items():
            self.assertNotEqual(content, path.read_bytes())

    def test_cli_prints_counts_paths_only_and_uses_custom_paths(self):
        self.write_source([["1", "es", "0", "comentario secreto", "", ""]])
        stdout = io.StringIO()
        with patch.object(pii, "build_redactor") as unused:
            # Inject at the pipeline boundary; model integration is tested separately.
            real_redact_csv = pii.redact_csv
            def with_fake(source, destination):
                return real_redact_csv(source, destination, redactor_factory=lambda: self.engine)
            with patch.object(pii, "redact_csv", side_effect=with_fake), contextlib.redirect_stdout(stdout):
                self.assertEqual(0, pii.main(["--input", str(self.source), "--output", str(self.output)]))
            unused.assert_not_called()
        self.assertIn("Data rows: 1; columns: 6", stdout.getvalue())
        self.assertNotIn("comentario secreto", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
