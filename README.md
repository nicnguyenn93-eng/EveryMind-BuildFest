# EveryMind Training Improvement Assistant

Local Streamlit application being built for the EveryMind training feedback workflow.

**Status: initial scaffold, not a working analysis tool.** The current interface displays hardcoded example metrics, feedback, and reports regardless of the uploaded file. The PDF download is a placeholder and is not a valid executive PDF. Do not use these outputs as survey findings or submission evidence.

## Quick setup

Install Python 3.11 and Git. Clone this team's repository using its GitHub URL, then open a terminal in the cloned `everymind-assistant` folder.

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

macOS / Linux (with Python 3.11 installed):

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

Open the local URL printed by Streamlit (normally `http://localhost:8501`). Stop the server with Ctrl+C. These commands do not require activating the environment. No API key is needed for the current mock interface; provider integration is not implemented. Python 3.11 is the suggested team baseline; a clean-machine installation has not yet been verified.

## Team modules

| File | Responsibility / current state |
|---|---|
| `app.py` | Streamlit UI scaffold; backend imports are commented out. |
| `clean.py`, `export_columns.json` | Actual-export XLSX/CSV import, text-score normalization, role membership, private comments, duplicate-ID rejection, and audit. Not yet connected to the UI; county alias mapping remains. |
| `analysis.py` | Descriptive paired knowledge statistics, recommendation/intent, coverage, group comparisons, and combined analysis JSON. See [analysis handoff](docs/analysis_handoff.md). |
| `cleaned_analysis.py`, `comment_evidence.py` | Runs John's cleaner and generates AI-input JSON with statistics, exploratory counts, and explicitly approved privacy-screened paraphrases; private review and citation lineage remain local. |
| `metrics.py` | Compatibility import for `analysis.build_evidence`. |
| `feedback.py`, `codebook.json` | Local pending coding suggestions and fingerprint-matched, reviewed theme counts. Search and identifier screening remain separate work. |
| `report.py`, `action_catalog.json`, `prompts/` | Report stub and draft action rules; validation, provider, and fallback remain. |
| `export_pdf.py` | PDF generation stub. |
| `schema.json` | K3 v2 export-compatible example records, consistent with `examples/`; downstream modules still need to adopt these contracts. |
| `checks/` | K3 fixture consistency checks; production regression tests remain to be written. |
| `examples/` | K3 synthetic CSV/XLSX inputs, expected output records, loader, and receiving-review checklist. See [K3 handoff](examples/README.md). |

## Updating and checking work

Commit or otherwise preserve local edits before pulling teammates' changes. After updating code, rerun the dependency installation command above if `requirements.txt` changed, then restart Streamlit.

Run checks on Windows with:

```powershell
.\.venv\Scripts\python.exe -m pytest checks -q
```

On macOS/Linux use `.venv/bin/python -m pytest checks -q`. Tests cover export import and K3 fixture consistency, including CSV/XLSX equivalence, reordered headers, optional columns, duplicate IDs, score statuses, and content changes. Full app calculations, audience scoping, privacy suppression, report validation, and offline behavior still need regression tests before release. See [case alignment](docs/case_alignment.md) for official requirements and current gaps.

## Local data and secrets

Keep real survey exports in `uploads/` or `private_data/`, review sheets in `private_review_files/`, and local credentials in `.env` or `.streamlit/secrets.toml`. These locations, virtual environments, and model caches are ignored by Git. The application does not currently load `.env` or call a provider. Never commit real comments, identifiers, API keys, or private review data; inspect `git diff --cached` before pushing. Use synthetic data for shared fixtures.

## Next integration priorities

1. Agree on consistent input, evidence, reviewed-comment, and report contracts.
2. Integrate the tested import and analysis modules; finish county aliases and review privacy behavior across the app's outputs.
3. Connect real evidence to the UI and invalidate reports on upload or audience changes.
4. Implement reviewed local search, evidence-based action eligibility, report validation/fallback, and a real one-page PDF.
5. Verify the live-provider path, clean-machine setup, and release checks before preparing final deliverables.
