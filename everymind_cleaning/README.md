# EveryMind survey cleaning pipeline

## Run
```
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
mkdir data && cp /path/to/BuildFest_EveryMind_Survey_Data_FULL.xlsx data/
jupyter notebook cleaning_pipeline.ipynb            # Run All
python -m pytest checks -q                          # 10 test runs
```

## Files
| File | Purpose |
|---|---|
| `everymind_clean.py` | The pipeline. The notebook and the Streamlit app both import this. |
| `schema.json` | Column contract: header synonyms, types, vocabularies, thresholds. Edit this when the form changes. |
| `mapping_registry.json` | Human-approved label mappings, reused on every run. |
| `privacy_adapter.py` | Stub that calls the team privacy tool. Connect it with `privacy_adapter.connect(redact)`. |
| `pipeline_checks.py` | Generalization test runs (also used by `checks/test_cleaning.py`). |
| `cleaning_pipeline.ipynb` | One notebook: Part 1 cleaning walkthrough, Part 2 the Team 25 analysis on the cleaned data. |

## Outputs
- `outputs/cleaned_<key>.csv`: analysis-ready data with no raw comments
- `outputs/audit_report_<key>.md`: what every step changed
- `outputs/mapping_review_<key>.csv`: unknown labels for a person to approve
- `outputs/analysis_<key>.csv`: Part 2's analysis table (cleaned data renamed to the analysis columns, keyword theme flags, no text)
- `outputs/figures/`: Part 2 figures
- `private/`: raw comments and distress flags. This folder is git-ignored and must never be shared.

## Use in the app
```python
import everymind_clean as ec
result = ec.run_pipeline(uploaded_bytes, "schema.json", "mapping_registry.json", filename=upload.name)
result.data, result.audit.to_markdown(), result.checks
```
