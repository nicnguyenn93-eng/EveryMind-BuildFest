# Frontend integration contract

The reporting backend has no frontend framework or HTTP-server dependency.
Nimi's Streamlit application is excluded. A frontend developed from main at
`ea85075` can add its own app files and use the two functions in
`report_service.py`. Importing the module does not call Gemini.

## Install and prepare data

```bash
python -m pip install -r requirements-report.txt
python -m everymind_cleaning.run_pipeline
```

The existing raw → cleaned → censoring workflow is unchanged. Generating a new
censored export needs the separately installed English/Spanish models. Reading
an existing export and generating a report need no model initialization.

Both functions require the full censored CSV under `censoring/<key>/` and its
matching `reports/<key>/manifest.json`. They check the manifest, exact CSV hash,
schema, types, and response IDs. They reject raw files, cleaned checkpoints,
incomplete older exports, and altered files. They never read original-comment
sidecars or rerun ingestion/redaction.

## Python interface

```python
from report_service import get_analysis, generate_report, ReportServiceError

path = "private_data/censoring/<key>/censored_<key>.csv"
audience = "All respondents"

try:
    analysis = get_analysis(path, audience)
    # Call generate_report only when the user requests a report.
    result = generate_report(
        path,
        audience,
        expected_dataset_key=analysis["dataset_key"],
        api_key=your_backend_secret,
        model="gemini-3.6-flash",
    )
except ReportServiceError as error:
    show_input_error(str(error))
```

`get_analysis(censored_path, audience="All respondents", *, reviews=None)` returns
the existing `everymind.analysis.v2` dictionary. Important fields are:

| Field | Use |
| --- | --- |
| `dataset_key` | `censored-sha256:<64 hex characters>`; identifies the exact processed CSV. |
| `audience` | Exact selected audience. Choices come from `analysis.AUDIENCES`. |
| `status` | Availability/withholding status of the analysis. |
| `quantitative_evidence` | Publishable metric records, display values, denominators, and evidence IDs. |
| `qualitative_themes` | Approved aggregate theme counts, where available. |
| `approved_comment_evidence` | Current privacy-screened human-approved paraphrases; empty by default. |
| `exploratory_feedback` | Local unreviewed classifications/keyword counts; label these as exploratory. |
| `coverage`, `limitations`, `interpretation_rules` | Context needed to interpret results. |

`generate_report(censored_path, audience="All respondents", *,
expected_dataset_key=None, reviews=None, include_approved_comments=False,
api_key=None, model=DEFAULT_MODEL, use_llm=True, retries=1, client=None)` reloads
and verifies the current export, computes the analysis, and returns a report.
Passing the analysis dataset key prevents generating a report from a dataset
that changed while it was on screen. Set `use_llm=False` for an offline template.
`retries` may be 0–2; each provider request has a 30-second timeout and the SDK's
additional retries are disabled. Caller-supplied clients remain caller-owned.

API credentials may be passed directly or configured in `GEMINI_API_KEY` /
`GOOGLE_API_KEY` in the backend environment. This module does not load `.env`
automatically. Keys are absent from prompts, outputs, and fallback messages.

## Report JSON

The machine-readable contract is [report.v1.schema.json](../schemas/report.v1.schema.json),
generated from `report_service.ReportResult`. Both functions return ordinary
JSON-compatible dictionaries, with no DataFrames, NaN, dates, or row identifiers.

| Field | Type / behavior |
| --- | --- |
| `schema_version` | Always `everymind.report.v1`. |
| `dataset_key`, `audience` | Match the current analysis. |
| `mode` | `llm` or `template`; render the mode visibly. |
| `summary_blocks` | List of report paragraphs. |
| `summary` | Structured AI findings, each with `text` and `evidence_ids`; empty for templates. |
| `evidence_ids` | IDs supporting summary findings; resolve them against the current analysis. |
| `proposed_action_id`, `proposed_action` | Catalog option; null when evidence is withheld/unavailable. |
| `staff_owner`, `follow_up_measure` | Proposed follow-up; null when evidence is unavailable. |
| `proposed_recommendations` | Detailed AI proposals with supporting IDs, pilot, owner, measure, and uncertainty. |
| `limitations` | Report limitations as a string. |
| `model` | Model name for an AI report; null for a template. |
| `fallback_reason` | Safe explanation for a template; null for a successful AI draft. |

Missing credentials, API errors, malformed responses, and failed evidence checks
produce a template instead of a successful AI report. Invalid input data raises
`ReportServiceError` before contacting Gemini. Under-threshold audiences produce
no evidence or proposed action and make no provider call. API errors expose only
a safe category/HTTP status, not provider exception text or request contents.

## Data sent to Gemini and frontend state

The report call sends allowlisted aggregate evidence and approved aggregate themes
by default. It excludes exploratory keyword output, original/censored comment
rows, local IDs, file paths, and private sidecars. Passing human review records to
`get_analysis` does not itself enable sending paraphrases. For that, also pass
`include_approved_comments=True` to `generate_report`; exact censored-content
fingerprints and explicit privacy-screened approvals must still match.

Clear cached reports when the censored dataset key, audience, model, reviews, or
comment-inclusion setting changes. Cache analysis by dataset key + audience +
review contents, not filename alone. Save any generated reports under the local
Git-ignored `private_data/reports/<key>/` folder. The service itself writes no files.

The validator checks evidence IDs and numerical consistency, not the correctness
of every interpretation. Catalog membership is checked; catalog trigger thresholds
are not automatically evaluated. The offline template currently selects the first
catalog option when evidence is publishable. Present actions as proposals requiring
review. Live testing with `gemini-3.6-flash` succeeded for the current all-respondent
aggregate payload; model access and quota can still vary by account.

## Compatibility note for the separate frontend

`origin/netra-frontend` at `3dacc98` was checked without merging its files. It is
a static HTML site with a Python build step, rather than a Python UI. Its upload
screen validates a raw workbook locally in the browser, while its displayed
figures come from prebuilt `gemini_kit/data/` tables and a separate explorer cube.
Uploading a file there does not run the current cleaning/censoring/report service.

The frontend owner can use this Python interface during a build step, or add a
small backend HTTP adapter for dynamic reports. No HTTP server or endpoint is
included in this integration. The current service supports the audiences in
`analysis.AUDIENCES`; it does not yet provide the frontend's county filter/cube
contract or an automatic mapping for its `Adults` label. Keep uploaded/current
dataset results separate from the prebuilt demo tables until that wiring exists.
A read-only three-way merge preview against this backend found no textual
conflicts. Neither frontend branch nor frontend files were modified.
