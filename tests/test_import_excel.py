"""Conversion and output-preservation checks using synthetic workbooks only."""

import csv
from datetime import datetime
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from everymind_censoring.import_excel import _verify_csv, convert_excel


SCRIPT = Path(__file__).resolve().parents[1] / "everymind_censoring" / "import_excel.py"


class ImportExcelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "input.xlsx"
        self.output = self.root / "output.csv"

    def make_workbook(self, rows, sheet="Survey Data"):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = sheet
        for row in rows:
            worksheet.append(row)
        workbook.save(self.source)
        workbook.close()
        # Escape literal CR characters so both XML parser backends read the
        # intended CRLF cell text instead of normalizing it to LF on reopen.
        with ZipFile(self.source) as archive:
            parts = [(info, archive.read(info)) for info in archive.infolist()]
        with ZipFile(self.source, "w") as archive:
            for info, content in parts:
                if info.filename == "xl/worksheets/sheet1.xml":
                    content = content.replace(b"\r", b"&#13;")
                archive.writestr(info, content)

    def read_output(self):
        with self.output.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.reader(handle))

    def test_exact_round_trip_preserves_special_text_zero_and_blank_rows(self):
        header = ["Id", " Question\u00a0 ", "Rating", "Blank", "Role", "Date"]
        first = ["001", '  Español café 🧠\u200e, "yes"\r\nsecond line  ',
                 0, None, "Student;Caregiver/parent;", "2026-10-21"]
        blank = [None] * len(header)
        last = ["003", "NA", 10, "", " School staff member; ",
                datetime(2026, 10, 22, 14, 8, 9)]
        self.make_workbook([header, first, blank, last])
        original_hash = hashlib.sha256(self.source.read_bytes()).digest()

        result = convert_excel(self.source, self.output)

        self.assertEqual(self.read_output(), [
            header,
            ["001", first[1], "0", "", first[4], "2026-10-21"],
            [""] * len(header),
            ["003", "NA", "10", "", last[4], "2026-10-22 14:08:09"],
        ])
        self.assertTrue(self.output.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual((result.data_rows, result.columns), (3, 6))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), original_hash)
        self.assertFalse(list(self.root.glob(".output.csv.*.tmp")))

    def test_missing_input_keeps_existing_output(self):
        self.output.write_bytes(b"previous CSV")
        with self.assertRaisesRegex(FileNotFoundError, "Input workbook not found"):
            convert_excel(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b"previous CSV")

    def test_missing_sheet_keeps_existing_output(self):
        self.make_workbook([["Id"], ["SYN001"]], sheet="Another sheet")
        self.output.write_bytes(b"previous CSV")
        with self.assertRaisesRegex(ValueError, "Available worksheets: Another sheet"):
            convert_excel(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b"previous CSV")

    def test_same_input_and_output_is_rejected(self):
        self.make_workbook([["Id"], ["SYN001"]])
        original = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, "different paths"):
            convert_excel(self.source, self.source)
        self.assertEqual(self.source.read_bytes(), original)

    def test_verification_failure_keeps_existing_output_and_removes_temporary_file(self):
        self.make_workbook([["Id"], ["SYN001"]])
        self.output.write_bytes(b"previous CSV")

        def corrupt_then_verify(worksheet, csv_path):
            csv_path.write_text("Id\r\nSYN999\r\n", encoding="utf-8-sig")
            _verify_csv(worksheet, csv_path)

        with patch("everymind_censoring.import_excel._verify_csv", side_effect=corrupt_then_verify):
            with self.assertRaisesRegex(ValueError, "verification failed at worksheet row 2"):
                convert_excel(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b"previous CSV")
        self.assertFalse(list(self.root.glob(".output.csv.*.tmp")))

    def test_empty_sheet_is_rejected(self):
        self.make_workbook([])
        with self.assertRaisesRegex(ValueError, "no header row"):
            convert_excel(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_cli_accepts_custom_paths_and_sheet_without_printing_responses(self):
        self.make_workbook([["Id", "Text"], ["SYN001", "PRIVATE_TEST_RESPONSE"]],
                           sheet="Another sheet")
        self.output = self.root / "nested" / "output.csv"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--input", str(self.source),
             "--output", str(self.output), "--sheet", "Another sheet"],
            capture_output=True, text=True, check=False, cwd=self.root,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("Sheet: Another sheet", result.stdout)
        self.assertIn("Data rows: 1", result.stdout)
        self.assertIn("Columns: 2", result.stdout)
        self.assertIn(str(self.output), result.stdout)
        self.assertNotIn("SYN001", result.stdout)
        self.assertNotIn("PRIVATE_TEST_RESPONSE", result.stdout)
        self.assertEqual(self.read_output()[1], ["SYN001", "PRIVATE_TEST_RESPONSE"])

    def test_cli_missing_input_returns_clear_error(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--input", str(self.source),
             "--output", str(self.output)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Input workbook not found", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.output.exists())

    def test_successful_rerun_replaces_existing_csv(self):
        self.make_workbook([["Id", "Rating"], ["SYN001", 0]])
        self.output.write_bytes(b"previous CSV")
        convert_excel(self.source, self.output)
        self.assertEqual(self.read_output(), [["Id", "Rating"], ["SYN001", "0"]])


if __name__ == "__main__":
    unittest.main()
