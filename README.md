# EveryMind 988 Training Insights

Turn Excel/CSV training surveys into local statistics, interactive findings, and an optional Gemini draft with cited evidence.

**Raw survey → cleaning → local Presidio censoring → statistics → five-step frontend.**

## Quickstart

Use **Python 3.11**. No database, cloud deployment, or frontend build step is required.

```bash
git clone https://github.com/nicnguyenn93-eng/EveryMind-BuildFest.git
cd EveryMind-BuildFest
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-web.txt -r requirements-models.txt
```

On Windows, use `py -3.11 -m venv .venv` and activate with `.\.venv\Scripts\Activate.ps1` in PowerShell.
The two local language models are a one-time download of about **1 GB**.

## Add a Gemini API key (optional)

Getting the key is a short Google AI Studio setup; no application code changes are needed:

1. Open [Google AI Studio's API-key page](https://aistudio.google.com/app/apikey) and sign in.
2. Copy your default key, or click **Create API key** and select/create a project.
3. Set it in the same terminal where you will start the app:

```bash
export GEMINI_API_KEY="paste-your-key-here"
```

PowerShell: `$env:GEMINI_API_KEY="paste-your-key-here"`. Restart an already-running server after setting it.
New AI Studio users may already have a default project/key; see [Google's setup guide](https://aistudio.google.com/docs/get-started). Model access, quotas, and billing depend on your Google project.

**No key is needed to explore the data or use the Offline template.** The key stays on the Python server; the frontend never receives it.

## Run and try the included sample

```bash
python -m everymind_web
```

Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)**:

1. **Upload:** choose `examples/synthetic_survey.xlsx` (30 fictional responses), or its CSV equivalent.
2. **Check:** confirm the rows and survey headers; continue to run local cleaning and censoring.
3. **Findings:** explore the pie, audience/county filters, knowledge changes, NPS, and answer coverage.
4. **Actions:** choose **Draft with Gemini** or **Offline template**, inspect evidence, and select actions.
5. **Summary:** review the combined report and download Markdown or use the print dialog to save a PDF.

Real survey responses and credentials are excluded from Git. Use the included sample to reproduce the app, or upload an authorized survey with the same headers. Existing processed datasets can be selected directly.

## How the code fits together

| Code | Responsibility |
| --- | --- |
| `frontend/` | Static five-step UI, charts, action cards, and report export |
| `everymind_web/` | Local FastAPI server, uploads, verified dataset handles, and report endpoints |
| `everymind_cleaning/` | Excel/CSV ingestion, structured cleaning, release checks, and stage publication |
| `everymind_censoring/` | Local English/Spanish Presidio engine and standalone import/redaction tools |
| `cleaned_analysis.py`, `analysis.py` | Descriptive statistics from the completed censored CSV |
| `report_service.py`, `report.py`, `prompts/` | Gemini input, citation/number validation, retries, and offline fallback |

All generated data stays in Git-ignored `private_data/`: **raw → cleaned → censoring**, with audits/manifests under `reports/`. For a command-line run:

```bash
python -m everymind_cleaning.run_pipeline --input examples/synthetic_survey.xlsx
```

Cleaning and censoring make no external requests. Pressing **Draft with Gemini** sends statistics and automatically censored comments for the selected audience to Google. Its scope is **all surveyed locations**, even when Findings is filtered to a county. Original-comment files and respondent IDs remain local. Automated redaction can miss identifiers, and generated recommendations require staff review.

The statistics describe retrospective self-reports; they do not establish causal effects. Missing and withheld values remain unknown, and small groups are suppressed.

## Development and details

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests checks everymind_cleaning/checks -q
python frontend/build_site.py
```

Optional frontend regression checks (Node.js 18+): `node --test frontend/checks/stepper.test.cjs`.

- [Cleaning, language routing, and notebook](everymind_cleaning/README.md)
- [Frontend structure](frontend/README.md)
- [Local HTTP API and metric definitions](docs/local_web_api.md)
- [Python/JSON reporting contract](docs/frontend_backend_contract.md)
