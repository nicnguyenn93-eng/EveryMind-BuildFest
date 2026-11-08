# EveryMind survey cleaning pipeline

John's schema, mappings, ingestion, cleaning, and analysis notebook remain the
primary implementation. The team's existing local Presidio engine is connected
through `privacy_adapter.py`; its detection rules have not been tuned here.

## Setup and run

Use Python 3.11 and the repository's virtual environment. From the repository root:

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-models.txt
python -m everymind_cleaning.run_pipeline
```

The command reads `private_data/BuildFest_EveryMind_Survey_Data_FULL.xlsx` directly.
It also supports `--input private_data/survey.csv` and
`--output-dir private_data/cleaning`. Generated files must stay in `private_data/`.
Both CPU models must already be installed; runtime never downloads them.

For the optional notebook and analysis dependencies:

```bash
python -m pip install -r everymind_cleaning/requirements-analysis.txt
jupyter notebook everymind_cleaning/cleaning_pipeline.ipynb
```

The notebook imports the same package adapter, connects Presidio, and uses the
same input and output defaults as the command. Its existing analysis code is
retained. Saved outputs were cleared so old, disconnected results are not shown
as current. No translation or LLM suggestion hook is enabled.

## Outputs

Under `private_data/cleaning/<dataset-key>/` (source SHA-256 prefix):

- `outputs/cleaned_<key>.csv`: John's structured/derived data and redacted comments.
- `outputs/audit_report_<key>.md`: cleaning steps, dropped rows, and quality flags.
- `outputs/mapping_review_<key>.csv`: unknown labels awaiting human decisions.
- `outputs/presidio_summary_<key>.json`: counts, language disagreements, and model/package versions; no comment text or matched identifiers.
- `private/comments_private_<key>.csv`: normalized comments, verbatim `__original` comments, source rows, original IDs, and distress flags.
- `private/distress_review_<key>.csv`: John's subset for local staff review.
- `private/presidio_review_<key>.csv`: one record per retained comment field, including blanks and unchanged comments; source/form/selected language, original and normalized input, replacement text, and detections.

Review offsets refer to **normalized input**, in zero-based Python characters
with an exclusive end. Normalization changes are counted separately from
Presidio changes. `source_row` starts at 2 after the header and counts logical
CSV records, not physical lines in multiline text. Provenance does not affect
John's duplicate rules and is not included in the cleaned table. The notebook's
existing analysis CSV and figures also stay under this run's `outputs/` directory.

All cleaning checks must pass before outputs are published. The output set is
staged and verified before replacement; ordinary replacement errors restore
existing files. Sudden process/OS failure during publication is not a multi-file
atomic transaction. Inputs and existing standalone baseline files are unchanged.

All outputs are local review data. `redacted` means processed, not verified
anonymous. IDs and metadata remain, detections can be wrong, and the private
files contain original responses. Detection counts do not measure accuracy.

## Python interface

```python
from everymind_cleaning import everymind_clean as ec, presidio_bridge
from everymind_cleaning.run_pipeline import SCHEMA, REGISTRY

presidio_bridge.connect()
result = ec.run_pipeline(source, SCHEMA, REGISTRY, filename="export.xlsx")
result.data, result.private, result.audit, result.checks
result.privacy_review, result.privacy_summary
```

The original result fields, pipeline arguments, and batch adapter contract are
retained. `PresidioBridge` loads the shared models once per process. Blank texts
return unchanged, including John's `none` language tag. Nonblank texts require
`en` or `es`; unsupported/unknown values stop processing rather than defaulting
to English. John's existing language heuristic supplies those routing codes.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m pytest everymind_cleaning/checks -q
RUN_PRESIDIO_INTEGRATION=1 python -m unittest discover -s tests -p test_cleaning_integration.py -v
```

`EVERYMIND_DATA` overrides the real workbook used by John's ten checks. They run
with isolated fake/disconnected adapters and restore any previous connection.
The opt-in integration check blocks network, downloads, and GPU activation.
