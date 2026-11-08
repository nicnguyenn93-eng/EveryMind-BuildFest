# EveryMind local survey preparation

Run Netra's connected frontend locally with `python -m pip install -r requirements-web.txt`
and `python -m everymind_web`, then open **http://127.0.0.1:8000**. Existing censored
datasets and new raw Excel/CSV uploads use the same pipeline. Charts and map use
the selected censored export; Gemini explicitly receives statistics and censored written responses, without manual comment approval.
See [local web/API setup and contract](docs/local_web_api.md).

John's `everymind_cleaning` package is the primary pipeline. It reads Excel or
CSV directly, cleans the structured survey data, and calls the existing local
Presidio engine through its privacy adapter. The standalone Excel converter and
full-CSV Presidio baseline remain available for comparison. No LLM is called by
the integrated command.

The published workflow consists of command-line tools and the analysis notebook.
The earlier Streamlit mock UI and placeholder report/PDF modules are removed.
The frontend lives in [`frontend/`](frontend/README.md): a five-step page (Upload, Check, Findings,
Actions, Summary) served with live, censored data by `python -m everymind_web`. It embeds no survey
figures. Rebuild it with `python frontend/build_site.py`.

Code is organized into `everymind_cleaning/` (John's primary pipeline) and
`everymind_censoring/` (our import and Presidio utilities). Data is kept in
Git-ignored stage folders under `private_data/`: `raw/`, `cleaned/`, and `censoring/`,
with supporting audits in `reports/`. Earlier mixed-layout outputs are retained in `archive/`.

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

## Primary workflow: inspect each stage

Place the workbook in `private_data/raw/`, then run from the repository root:

```bash
python -m everymind_cleaning.run_pipeline
```

John's reader accepts Excel directly. CSV input is optional:

```bash
python -m everymind_cleaning.run_pipeline --input private_data/raw/survey.csv --output-dir private_data
```

Each completed run writes these stages, grouped by its source-file hash prefix:

| Order | Folder | Contents |
| --- | --- | --- |
| 0 | `private_data/raw/` | Original workbook or CSV, unchanged. External inputs are copied here for traceability. |
| 1 | `private_data/cleaned/<key>/` | `cleaned_<key>.csv`: John's standardized values and normalized **uncensored** comments, immediately before Presidio. |
| 2 | `private_data/censoring/<key>/` | `censored_<key>.csv`: John's complete result with Presidio text in `__redacted` columns, classification, quality flags, derived values, and linkage. Includes the summary and private before/after reviews. |
| — | `private_data/reports/<key>/` | Cleaning audit, unknown-label review, private distress review, and `manifest.json` listing stage order, files, counts, and hashes. |

On the supplied survey, raw contains 1,299 rows and 20 columns, cleaned has
1,299 rows and 62 columns, and censored has 1,299 rows and 90 columns: John's
88-column release result plus `source_row` and `original_id`. Shared structured
values match between cleaned and censored. The censored export contains no
uncensored comment columns. John's release safeguards preserve unknown roles,
inferred question availability, and unassessable quality checks explicitly.

`private_data/README.md` links to the latest completed run. The stage CSVs share
`source_row`, `original_id`, and `response_id`; use these to trace a response
through normalization, duplicate removal, and censoring. `source_row` counts
logical source records from 2 after the header. Removed rows are listed in the
audit. Provenance is excluded from John's duplicate comparisons.

The cleaned stage still contains uncensored text. Verbatim source comments are
retained in the raw input and the censoring stage's private files; the cleaned
stage contains John's normalized text. Detection offsets refer to
`normalized_input` in the review CSV. Compare each cleaned comment with its
corresponding `__redacted` column in the censored CSV. John's core `Result.data`
and notebook analysis logic remain available. An existing 51-column censored
export and its manifest/guide are archived under `archive/censoring_schema_v1/`
when the full result replaces it. No separate analysis stage is created.
The subsequent 77-to-90-column release migration archives the previous stage
files and companions under `archive/before_release_v1/` before replacing them.
See [cleaning release safeguards](everymind_cleaning/README.md#cleaning-release-safeguards).

The cleaner detects English/Spanish separately for each comment using the local
Lingua detector, then runs exactly one matching Presidio model. Text detection
overrides the form language at a confidence score of at least 0.80, configured in
`everymind_cleaning/schema.json` as `text.language_confidence_threshold`.
Uncertain, ambiguous, and nonlinguistic answers use the form language and receive
a private review flag. Mixed comments use their dominant language. Presidio
models and rules are unchanged; no translation or LLM hook is enabled.
See [language routing and review fields](everymind_cleaning/README.md#language-routing)
for fallback and failure behavior.

All blocking checks and CSV/JSON verification finish before the stage files are published.
Ordinary replacement errors restore prior outputs across stage folders. Abrupt
OS/process termination during multi-file publication is not an atomic transaction.
All stages are local review data with IDs and metadata retained; redacted text
still requires review. Existing results from the earlier mixed layout are in
`private_data/archive/previous_censoring/`. Standalone Presidio results are kept
separately in `private_data/censoring/baseline/`.

Use a separate output root for concurrent experiments or another agent's runs,
for example `--output-dir private_data/language_experiments`. Each root has its
own raw/cleaned/censoring folders and manifests, avoiding shared result replacement.

See [everymind_cleaning/README.md](everymind_cleaning/README.md) for the notebook
and Python interfaces, and [INTEGRATION_REVIEW.md](INTEGRATION_REVIEW.md) for
compatibility checks and remaining detection problems.

## Convert the survey

Place `BuildFest_EveryMind_Survey_Data_FULL.xlsx` in `private_data/raw/`, then run:

```bash
python everymind_censoring/import_excel.py
```

This reads the `Survey Data` worksheet and writes `private_data/raw/survey.csv`.
The command prints the sheet name, data-row count, column count, and output path.
The supplied workbook has 1,299 data rows and 20 columns.

To use another workbook, worksheet, or destination:

```bash
python everymind_censoring/import_excel.py --input private_data/raw/another.xlsx --sheet "Survey Data" --output private_data/raw/another.csv
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
python everymind_censoring/redact_pii.py
```

This reads `private_data/raw/survey.csv` and creates:

- `private_data/censoring/baseline/survey_presidio.csv`: the full CSV with only the two comment
  fields redacted. All other fields, original IDs, headers, and row order stay
  unchanged. Empty and whitespace-only comments stay exactly as written and
  bypass detection.
- `private_data/censoring/baseline/survey_presidio.review.csv`: one row for each comment field,
  including blank and unchanged comments. It contains the original text,
  redacted text, original ID, English/Spanish routing code, field name, status,
  and a JSON array of detection types, original-text offsets, and scores.
  `source_row` is the logical CSV record number, starting at 2 after the header;
  offsets are zero-based Python character indices with an exclusive end.
- `private_data/censoring/baseline/survey_presidio.summary.json`: row/comment counts, mutually
  exclusive changed/unchanged/blank counts, scanned counts, detections by type
  and language, and package/model versions. It contains no original responses
  or matched identifiers. Detections can overlap; the anonymizer resolves them
  when replacing text, so detection counts do not equal replacement counts.

To use another source or output stem:

```bash
python everymind_censoring/redact_pii.py --input private_data/raw/another.csv --output private_data/censoring/baseline/another_presidio.csv
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

Install the development dependencies and run John's ten original cleaning checks:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest everymind_cleaning/checks -q
```

Set `EVERYMIND_DATA` to test another workbook. These checks temporarily isolate
the privacy adapter and restore its previous connection; they do not repeatedly
run the large models. The normal integration tests use fictional data and a fake
redactor, including normalization, provenance, duplicate IDs, and output rollback.

Tests use temporary synthetic workbooks and do not require the real survey.
The Presidio pipeline tests use a deterministic fake engine so model downloads
are unnecessary. After installing the models, also run the opt-in model check:

```bash
RUN_PRESIDIO_INTEGRATION=1 python -m unittest discover -s tests -p test_presidio_models.py -v
RUN_PRESIDIO_INTEGRATION=1 python -m unittest discover -s tests -p test_cleaning_integration.py -v
```

This exercises fictional English and Spanish names, emails, phone numbers,
addresses, schools, contextual identifiers, and harmless survey text. It blocks
DNS/socket connections, model downloads, and GPU activation, and writes detailed
results to `private_data/reports/presidio_synthetic_review.json`. Detection gaps are
recorded for review instead of treating every target as guaranteed detection.

The supplied survey has been processed and checked. See
[BASELINE_REVIEW.md](BASELINE_REVIEW.md) for preservation checks, counts,
synthetic gaps, and the first local comment spot-check. A major observed issue
is that the source language label sometimes differs from the written language.
The standalone historical baseline retains field-based routing; the shared
cleaning pipeline now detects each comment's language and flags its fallbacks.

## Imported analysis tools

Main's descriptive statistics, reviewed-comment evidence, and Gemini citation
kit are included. After the primary pipeline finishes, analyze the censored CSV:

```bash
python cleaned_analysis.py private_data/censoring/72b08ff71ede/censored_72b08ff71ede.csv
```

Use the key printed by your pipeline run for other inputs. The command checks
the v2 manifest and CSV hash, reads no raw/private-original files, and writes
`private_data/reports/<key>/ai_input.json`. Use `--audience Students`,
`--reviews`, `--output` (inside private_data), or `--prepare-review` as needed.
Review packets and private citation maps stay in `censoring/<key>/private/`.
Keyword analysis and fingerprints use censored wording; classification metadata
retains John's upstream decisions. A changed comment cannot inherit a review
fingerprint for its original wording. Analysis dataset keys hash the exact
censored CSV, independently of the source-file key used for folder names.

The legacy `clean.py` loader and synthetic examples remain for compatibility
and regression checks. The primary analysis command rejects raw inputs and old
incomplete exports. The old mock UI and placeholder PDF exporter remain removed.

Run the combined checks with:

```bash
RUN_PRESIDIO_INTEGRATION=1 python -m pytest tests checks everymind_cleaning/checks -q
```

See [analysis handoff](docs/analysis_handoff.md) and
[Gemini kit](gemini_kit/README.md). The provider SDK remains optional;
analysis and prompt dry runs do not call a provider.

## Reporting backend for an independent frontend

Nimi's Gemini reporting code is available without her frontend. Install
`requirements-report.txt`, then use `report_service.get_analysis(...)` and
`report_service.generate_report(...)` with a verified censored CSV. Reports send
aggregate evidence by default and fall back to labeled templates on provider or
validation failures. The primary pipeline dependencies remain unchanged.

See the [frontend/backend contract](docs/frontend_backend_contract.md) for the
Python signatures, credential setup, state handling, and versioned report JSON
schema. A frontend can be developed and merged independently of this backend.
