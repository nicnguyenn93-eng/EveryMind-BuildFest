# EveryMind local survey preparation

Convert the original Excel survey into a verified CSV. This repository currently
contains an Excel converter and a local Presidio baseline for reviewing possible
identifiers in written responses. Neither script calls an LLM.

## Setup

Use Python 3.11 (the tested version). From the repository root:

```bash
python -m venv .venv
```

Activate it on macOS/Linux with `source .venv/bin/activate`, or on Windows
PowerShell with `.\.venv\Scripts\Activate.ps1`. Then install the pinned packages:

```bash
python -m pip install -r requirements.txt
```

For redaction, install both pinned spaCy 3.8.0 models during setup. These are
large downloads (about 970 MB combined):

```bash
python -m pip install -r requirements-models.txt
```

The baseline uses `presidio-analyzer==2.2.366`, `presidio-anonymizer==2.2.366`,
`spacy==3.8.11`, and `tldextract==5.4.0`. It runs both language models on the CPU.
The redaction script checks both model versions before processing and fails
with a setup instruction if either is absent or has the wrong version.

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

## Run the Presidio baseline

```bash
python scripts/redact_pii.py
```

This reads `private_data/survey.csv` and creates:

- `private_data/survey_presidio.csv`: the full CSV with only the two comment
  fields redacted. All other fields, original IDs, headers, and row order stay
  unchanged. Empty and whitespace-only comments stay exactly as written and
  bypass detection.
- `private_data/survey_presidio.review.csv`: one row for each comment field,
  including blank and unchanged comments. It contains the original text,
  redacted text, original ID, English/Spanish routing code, field name, status,
  and a JSON array of detection types, original-text offsets, and scores.
  `source_row` is the logical CSV record number, starting at 2 after the header;
  offsets are zero-based Python character indices with an exclusive end.
- `private_data/survey_presidio.summary.json`: row/comment counts, mutually
  exclusive changed/unchanged/blank counts, scanned counts, detections by type
  and language, and package/model versions. It contains no original responses
  or matched identifiers. Detections can overlap; the anonymizer resolves them
  when replacing text, so detection counts do not equal replacement counts.

To use another source or output stem:

```bash
python scripts/redact_pii.py --input private_data/another.csv --output private_data/another_presidio.csv
```

Every output must stay inside `private_data/`. The script prevents overwriting
the source or using output symlinks. Both CSVs use UTF-8 with a BOM and standard
CSV quoting, including embedded newlines.

The required columns are `Id`, `Language`, and the two exact comment headers:

- `What was the most valuable thing you learned during the training?` followed
  by the source header's nonbreaking space (`U+00A0`).
- `How can we improve this training in the future?`

All input headers, row widths, and language values are checked before detection.
The language labels `English (United States)` and `Español (México)` route to
`en` and `es`; short codes and the corresponding language names also work.
Direction marks and surrounding whitespace are ignored for routing only. A
missing/unsupported language produces an error even if its comments are blank.

Models are loaded locally without auto-download or GPU activation. Presidio's
built-in recognizers, thresholds, NER mappings, ignore list, and default entity
placeholders are retained. Email validation uses tldextract's bundled public
suffix snapshot with remote updates and its disk cache disabled. There are no
custom recognizers, allowlists, GLiNER, or analytical cleaning steps.

Processing and read-back verification finish before any result is replaced.
Ordinary replacement errors roll back previously replaced outputs. Three files
cannot be published as one atomic filesystem operation, so abrupt termination
during final replacement can interrupt publication. Processing failures leave
existing results intact. Terminal output contains counts and paths only.

These are **local review files**: the full CSV retains IDs, dates, geography,
and other metadata, and the review CSV contains the original comments.
Presidio can miss identifiers and redact useful content. Review and a separate
decision about LLM input are still needed before sending data to an LLM.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests use temporary synthetic workbooks and do not require the real survey.
The Presidio pipeline tests use a deterministic fake engine so model downloads
are unnecessary. After installing the models, also run the opt-in model check:

```bash
RUN_PRESIDIO_INTEGRATION=1 python -m unittest discover -s tests -p test_presidio_models.py -v
```

This exercises fictional English and Spanish names, emails, phone numbers,
addresses, schools, contextual identifiers, and harmless survey text. It blocks
DNS/socket connections, model downloads, and GPU activation, and writes detailed
results to `private_data/presidio_synthetic_review.json`. Detection gaps are
recorded for review instead of treating every target as guaranteed detection.

The supplied survey has been processed and checked. See
[BASELINE_REVIEW.md](BASELINE_REVIEW.md) for preservation checks, counts,
synthetic gaps, and the first local comment spot-check. A major observed issue
is that the source language label sometimes differs from the written language;
this baseline preserves the requested field-based routing.
