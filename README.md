# EveryMind survey CSV import

Convert the original Excel survey into a verified CSV. This repository currently
contains only the converter and its tests.

## Setup

Use Python 3.11 or newer. From the repository root:

```bash
python -m venv .venv
```

Activate it on macOS/Linux with `source .venv/bin/activate`, or on Windows
PowerShell with `.\.venv\Scripts\Activate.ps1`. Then install the dependency:

```bash
python -m pip install -r requirements.txt
```

## Convert the survey

Place `BuildFest_EveryMind_Survey_Data_FULL.xlsx` in `private_data/`, then run:

```bash
python scripts/import_excel.py
```

This reads the `Survey Data` worksheet and writes `private_data/survey.csv`.
The command prints the sheet name, data-row count, column count, and output path.
The supplied workbook has 1,299 data rows and 20 columns.

To use another workbook, worksheet, or destination:

```bash
python scripts/import_excel.py --input private_data/another.xlsx --sheet "Survey Data" --output private_data/another.csv
```

The converter preserves the original headers, column order, all rows, whitespace,
Unicode, and written responses. Blank cells become empty fields; zeros remain
zeros. It uses UTF-8 with a BOM for Excel compatibility, and standard CSV quoting
preserves commas, quotation marks, and embedded newlines. CSV stores text rather
than Excel cell types or formatting; nonempty cell values use Python's `str()`
representation, including any formula expressions.

Every field is read back and compared with the source before the CSV replaces
an existing output. The workbook is never modified. Missing files or worksheets
produce an error without replacing an existing CSV.

Keep real inputs and outputs in `private_data/`, which is ignored by Git.
The source workbook and generated CSV are local files and are not included in
the repository. The converter does not print individual responses.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests use temporary synthetic workbooks and do not require the real survey.
