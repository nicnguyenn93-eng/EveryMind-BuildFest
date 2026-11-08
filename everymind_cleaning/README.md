# EveryMind survey cleaning pipeline

## Run
```
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
mkdir data && cp /path/to/BuildFest_EveryMind_Survey_Data_FULL.xlsx data/
jupyter notebook cleaning_pipeline.ipynb            # Run All
python -m pytest checks -q                          # 10 real-export runs + 6 synthetic contract tests
```

## Files
| File | Purpose |
|---|---|
| `everymind_clean.py` | Core cleaning steps. |
| `release.py` | Release gate (blocking errors vs warnings), output contract, `load_clean`. The notebook and the app should both use `release.run_pipeline`. |
| `schema.json` | Column contract: header synonyms, types, vocabularies, thresholds. Edit this when the form changes. |
| `mapping_registry.json` | Human-approved label mappings, reused on every run. |
| `privacy_adapter.py` | Stub that calls the team privacy tool. Connect it with `privacy_adapter.connect(redact)`. |
| `pipeline_checks.py` | Generalization test runs (also used by `checks/test_cleaning.py`). |
| `checks/test_release.py`, `checks/fixtures.py` | Synthetic round-trip and release-gate tests; no real data needed. |
| `cleaning_pipeline.ipynb` | One notebook: Part 1 cleaning walkthrough, Part 2 the Team 25 analysis on the cleaned data. |

## Outputs (one run = one `<run_key>`)
- `outputs/cleaned_<key>.csv`: **the downstream table**. One row per response, no comment text: IDs, role flags,
  `comparison_group`, before/after ratings, `*__paired_valid`, `*__change`, `*__status`, nullable quality flags, `session_key` (date × county).
- `outputs/fields_<key>.json`: schema version, dtype and meaning of every column, status values.
- `outputs/audit_<key>.json`: checks split into `blocking_errors` and `warnings`, missingness and review counts (no raw values).
- `outputs/manifest_<key>.json`: hashes of input, schema, registry, code; package versions.
- `outputs/figures_<key>/`: Part 2 figures.
- `private/`: raw comments, mapping review, distress flags, full audit. Git-ignored; never share.

**Blocking** (nothing is written): blank/duplicate IDs, duplicate or ambiguous headers, privacy checks, row alignment,
value/status mismatch, out-of-range values. **Warning** (export allowed, affected analyses restricted): a required
rating answered by fewer than 90% of rows (`min_valid_rate` in `schema.json`).
Labels are applied only on exact/alias/approved matches; contains/fuzzy matches go to the review queue as suggestions.
Dates must be ISO 8601 (`dates.format` in `schema.json`); anything else is marked invalid.

## Read the export
```python
from release import load_clean
df = load_clean("outputs/cleaned_<key>.csv")   # applies fields_<key>.json dtypes; never use bare pd.read_csv
```

## Use in the app
```python
import release
result = release.run_pipeline(uploaded_bytes, "schema.json", "mapping_registry.json", filename=upload.name)
release.require_ready(result.checks)   # raises on blocking errors, returns warnings
```
