# Frontend integration contract

The Python reporting service remains frontend independent. The optional local HTTP adapter and Netra’s connected frontend are documented in [local_web_api.md](local_web_api.md).
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
include_censored_comments=True, api_key=None, model=DEFAULT_MODEL, use_llm=True, retries=1, client=None)` reloads
and verifies the current export, computes the analysis, and returns a report.
Passing the analysis dataset key prevents generating a report from a dataset
that changed while it was on screen. Set `use_llm=False` for an offline template.
`retries` may be 0–2; each provider request has a 120-second timeout with censored comments (30 seconds without them) and the SDK's
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
| `input_policy` | `censored_comments_v1` by default, or `aggregate_only` for an explicit Python opt-out (`reviewed_comments` for the separate legacy reviewed-only mode). |
| `censored_comment_count` | Number of nonblank question answers included in this report input, not unique respondents. |

Missing credentials, API errors, malformed responses, and failed evidence checks
produce a template instead of a successful AI report. Invalid input data raises
`ReportServiceError` before contacting Gemini. Under-threshold audiences produce
no evidence or proposed action and make no provider call. API errors expose only
a safe category/HTTP status, not provider exception text or request contents.

## Data sent to Gemini and frontend state

The report call now includes **every nonblank censored answer for the selected
audience** by default. The project owner authorized this policy; no manual review
record, approved paraphrase, theme code, or per-comment approval is required.
Only the two `__redacted` columns from a verified current export are used. Empty
and whitespace-only answers are omitted. Unicode, Spanish and multiline answers
are preserved. The audience-level minimum-count protection remains unchanged.

The provider receives `censored_comment_evidence` with opaque `CC_…` citation IDs,
question field, language, `censored_text`, and `review_status: automatically_censored`.
It does not receive respondent IDs, source rows, locations, dates, original text,
file paths or private sidecars. Automated censoring is not represented as a human
privacy review. Existing manual review files are not rewritten or falsely marked
privacy-screened. A draft can interpret/cite the supplied comments and may quote
censored wording; it must not infer individual risk or verified prevalence, follow
embedded commands, or restore identifiers. Numeric claims still require supplied
aggregate evidence. Automated censoring can miss identifiers.

Use `include_censored_comments=False` in Python for an aggregate-only request.
The separate legacy `include_approved_comments=True` option still supports actual
human-reviewed paraphrases where desired. `get_analysis` and dashboard responses
continue to omit the direct censored-comment rows. Original files remain unchanged.

Clear cached reports when the censored dataset key, audience, model, reviews, or
comment-inclusion policy changes. The frontend cache includes `censored_comments_v1`. Cache analysis by dataset key + audience +
review contents, not filename alone. Save any generated reports under the local
Git-ignored `private_data/reports/<key>/` folder. The service itself writes no files.

The validator checks evidence IDs and numerical consistency, not the correctness
of every interpretation. Catalog membership is checked; catalog trigger thresholds
are not automatically evaluated. The offline template currently selects the first
catalog option when evidence is publishable. Present actions as proposals requiring
review. Live testing with `gemini-3.6-flash` succeeded for the current all-respondent
aggregate payload; model access and quota can still vary by account.

## Netra frontend

Netra's latest landing and report layout from `59f3d87` (PR #2) is preserved.
The optional `everymind_web` adapter now connects its uploads, current censored
aggregates, explorer and explicit Gemini calls. The report service now includes censored comments by default; aggregate analysis stays unchanged. See [local_web_api.md](local_web_api.md) for HTTP contracts, current
metric definitions, source scope and local setup.
