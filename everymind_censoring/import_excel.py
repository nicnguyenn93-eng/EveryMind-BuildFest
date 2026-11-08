"""Export an Excel worksheet to CSV without cleaning or filtering its values."""

import argparse
from contextlib import closing
import csv
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
import tempfile
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "private_data" / "BuildFest_EveryMind_Survey_Data_FULL.xlsx"
DEFAULT_OUTPUT = ROOT / "private_data" / "censoring" / "survey.csv"
DEFAULT_SHEET = "Survey Data"


@dataclass(frozen=True)
class ConversionResult:
    sheet: str
    data_rows: int
    columns: int
    output: Path


def _csv_row(values):
    return ["" if value is None else str(value) for value in values]


def _verify_csv(worksheet, csv_path):
    """Compare every serialized source field, including the header and blank rows."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        expected_rows = worksheet.iter_rows(values_only=True)
        actual_rows = csv.reader(handle, strict=True)
        for number, (expected, actual) in enumerate(
            zip_longest(expected_rows, actual_rows), start=1
        ):
            if expected is None or actual is None:
                raise ValueError("CSV verification failed: the row count changed.")
            if _csv_row(expected) != actual:
                raise ValueError(
                    f"CSV verification failed at worksheet row {number}."
                )


def convert_excel(input_path, output_path, sheet_name=DEFAULT_SHEET):
    """Write and verify a temporary CSV, then atomically replace the destination."""
    source = Path(input_path).expanduser().resolve()
    destination = Path(output_path).expanduser().absolute()
    if source == destination.resolve():
        raise ValueError("The input workbook and output CSV must have different paths.")
    if not source.is_file():
        raise FileNotFoundError(f"Input workbook not found: {source}")

    temporary_path = None
    try:
        with closing(load_workbook(source, read_only=True, data_only=False)) as workbook:
            if sheet_name not in workbook.sheetnames:
                available = ", ".join(workbook.sheetnames)
                raise ValueError(
                    f"Worksheet {sheet_name!r} not found. Available worksheets: {available}"
                )
            worksheet = workbook[sheet_name]
            rows = worksheet.iter_rows(values_only=True)
            header = next(rows, None)
            if header is None or all(value is None or value == "" for value in header):
                raise ValueError(f"Worksheet {sheet_name!r} has no header row.")

            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8-sig",
                newline="",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                writer = csv.writer(handle)
                writer.writerow(_csv_row(header))
                data_rows = 0
                for row in rows:
                    writer.writerow(_csv_row(row))
                    data_rows += 1

            _verify_csv(worksheet, temporary_path)
            result = ConversionResult(sheet_name, data_rows, len(header), destination)

        temporary_path.replace(destination)
        return result
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "-i", type=Path, default=DEFAULT_INPUT,
                        help="Source XLSX workbook (default: private_data survey workbook).")
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT,
                        help="Destination CSV (default: private_data/censoring/survey.csv).")
    parser.add_argument("--sheet", default=DEFAULT_SHEET,
                        help="Worksheet to export (default: Survey Data).")
    args = parser.parse_args(argv)
    try:
        result = convert_excel(args.input, args.output, args.sheet)
    except (OSError, ValueError, KeyError, BadZipFile, InvalidFileException, csv.Error) as error:
        parser.exit(1, f"Import failed: {error}\n")
    print(f"Sheet: {result.sheet}")
    print(f"Data rows: {result.data_rows:,}")
    print(f"Columns: {result.columns}")
    print(f"CSV: {result.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
