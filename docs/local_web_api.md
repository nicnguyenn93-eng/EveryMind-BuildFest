# Local frontend and API

Netra's landing page, upload card, loading overlay, report sections, map and rings
are preserved. The local API supplies their current data and the existing Gemini
report service. There is no public deployment or frontend API key.

```bash
python -m pip install -r requirements-web.txt
python -m everymind_web
# Open http://127.0.0.1:8000
```

Install the English/Spanish Presidio models described in the root README before
processing new uploads. Existing censored datasets do not initialize the models.
`--port 8001` selects another local port. The server binds only to loopback.

Choose an existing censored dataset, or select a raw Excel/CSV export up to 25 MB.
Generate the report runs local ingestion → cleaning → censoring for an upload,
then displays aggregate findings. Upload bytes are retained under
`private_data/raw/uploads/<source-sha256>/upload.xlsx` or `upload.csv`. Existing
stage conventions and verified publication/rollback remain unchanged. Failed
jobs retain their raw upload and previous completed results; no partial result
is offered. Processing jobs are serialized because the privacy adapter has
process-level state. Jobs are in memory; after a server restart select the
completed dataset or resubmit the source. Excel ingestion uses John's sheet rules.

The entire connected view uses one verified censored CSV/manifest. The old prepared
1,255-response tables are not used as a fallback. Opening index.html without the
local API displays startup instructions and disables analysis controls. Static
historical explorer assets remain in the repository for comparison; the connected
page passes a current dataset handle to the explorer, including its new-tab link.

## HTTP contract

The server's `/docs` exposes typed request documentation. All API responses have
`Cache-Control: no-store`. Dataset handles are CSV SHA-256 values, never local paths.
POSTs require `X-EveryMind-Request: 1`; browser Origins must match the local page.
No cross-origin CORS access is enabled. Only the frontend directory is served.
This is a single-user local tool, not an authenticated hosted API.

| Method and path | Result |
| --- | --- |
| `GET /api/status` | Model, boolean credential availability, upload limit and audience choices. No key. |
| `GET /api/datasets` | Verified current censored datasets, handles, safe counts and schema widths. |
| `POST /api/uploads` | Multipart `file` (raw `.xlsx`/`.csv`); returns processing job ID (202). |
| `GET /api/jobs/{job_id}` | Processing/ready/failed; ready includes the censored dataset handle. |
| `GET /api/datasets/{sha}/dashboard?audience=All%20respondents` | `dataset_key`, audience, full analysis, county options/summaries, explorer cube and interpretation notes. |
| `POST /api/reports` | `{dataset_id, audience, expected_dataset_key, use_llm, input_policy:"censored_comments_v1"}` → `{scope, report}`. Report uses `everymind.report.v1`. |

A changed or inconsistent dataset handle returns 409 before any provider call.
Raw/checkpoint/old incomplete exports are not offered. Invalid requests return a
clear error; processing exceptions omit raw text and identifiers. Frontend data
and model prose are rendered as text, not executable markup.

## Metrics and scope

Every retained structured row is included; the adapter adds no analytical exclusion.
Knowledge agreement and calling/recommendation evidence use existing analysis
rules, score statuses and minimum valid counts. Zero scores remain valid.

NPS is **100 × (share recommending 9–10 minus share recommending 0–6)** among
valid recommend scores. It is not the mean score. No confidence interval is
calculated by this adapter. The gain index preserves the frontend's difference
between each respondent's mean available after items and mean available before
items (1–5), averaged over valid differences. Missing items may differ between
these averages. This is distinct from agreement change in percentage points.
These extra display metrics do not change the existing Gemini evidence schema.

The map covers Maryland; audience totals include all surveyed locations. Rare
non-Maryland labels are combined. Small county groups and complements are
withheld; an additional county may be withheld to protect a small combined
remainder. Finer role/session/quarter/form-language partitions are omitted when
a nonempty child has fewer than ten responses. Roles in the explorer are
exclusive, with multiple roles grouped together; audience membership in analysis
retains the existing overlap rules. Rings describe displayed groups only and can
omit protected portions. Session labels are ordinal labels, not schools or raw
session keys. Form-language splits describe recorded form language, not detected
comment language. Null metrics are unknown, never zero.

The report controls use **Known non-students** instead of treating role as measured
age. Clicking a county updates local findings; the optional Gemini request always
covers the selected audience across **all surveyed locations**. This scope is
shown beside the generation buttons. A county is not accepted in report requests.

## Gemini

Use `GEMINI_API_KEY` / `GOOGLE_API_KEY`, or the ignored local
`private_data/gemini_secrets.toml` with `GEMINI_API_KEY = "..."`. Never put the key
in frontend code. No request is made on upload, page load or county/audience
selection. The explicit **Send statistics and censored comments to Google Gemini**
button sends the current aggregate evidence and every nonblank answer from the
selected audience's two censored written-response columns. No manual approval,
review-file record or theme code is required under the project owner's instruction.
Responses are labeled automatically censored, not human-reviewed. Only opaque
citation IDs, question fields, languages and censored text accompany the statistics;
respondent IDs, individual metadata, original files and private sidecars stay local.
Generated drafts may quote censored wording. Existing numerical/citation validation
and template fallback remain in place. Censoring may still miss identifiers.

The report body includes `input_policy: "censored_comments_v1"`, obtained from
`GET /api/status`. An older page which still describes aggregate-only requests
receives a reload error before any provider call. This is a contract-version check,
not a per-comment approval step. The report JSON adds `input_policy` and
`censored_comment_count`. The cache key includes the input policy along with the
dataset hash and audience, so an old aggregate-only draft is not reused.

The offline button never calls the provider. Each browser retains its generated
report by dataset hash and audience for that page session; a new processed hash
cannot inherit the previous report. Request failures and template mode are visible.
Generated text is a draft requiring review; validation does not establish the
correctness of every interpretation or recommendation.

## Verification checkpoint (2026-11-08)

- Latest upstream Netra commit `59f3d87` was already merged by PR #2 (`beb3972`).
  Local main fast-forwarded to it before integration; a final fetch found no newer UI commit.
- Full regression with socket/DNS networking disabled: **143 tests passed and 67
  subtests passed**, including English/Spanish model integration and John's checks.
- HTTP tests cover current censored-only reads, actual new synthetic upload processing,
  source preservation on failures, safe errors, stale handles, local Origin/Host
  restrictions, strict booleans, optional fields, zero scores, and minimum-count protection.
- Real selected export: **1,299 rows × 77 columns**, **293** valid calling scores.
  Original workbook, cleaned checkpoint and censored CSV hashes remained unchanged.
- Browser checks passed for existing-dataset selection, original-workbook upload
  (reusing its verified completed result), county/audience switching, county selection
  surviving iframe loading, map-to-report synchronization, rings and offline reporting.
- One live request through the page returned `mode: llm` with `gemini-3.6-flash`.
  It used the exact previously approved 15 aggregate records (no comments/IDs),
  confirmed against the saved preview and request-prompt SHA-256
  `526086eee739f33af1063b0cd6393f826230c71987c65f94ec74c90d1ce1a574`.
  Montgomery was selected locally, but the returned evidence retained all-respondent
  totals of 1,299. The key stayed on the server.
- Existing recommendation limitation: the action catalog has student-focused options
  and the offline template picks its first option when evidence is available. A
  non-student report can therefore propose a student action. Catalog eligibility and
  semantic suitability still need review; API wiring does not fix that business logic.

The earlier aggregate-only local report screenshot is kept in the ignored
`private_data/reports/72b08ff71ede/web_integration/` folder. No private outputs,
credentials or source data are committed. These integration checkpoints are local;
publishing is separate.

## Censored-comment policy update

Manual comment approval was removed at the project owner's request. The full
current export provides **1,714 nonblank written answers** (1,063 most-valuable;
651 improvement), including 1,585 English and 129 Spanish answers. These are
answers to two questions, not 1,714 unique respondents. Nothing is sampled or
truncated. Preview artifacts are ignored under
`private_data/reports/72b08ff71ede/censored_comments_preview/`.

The direct comment handoff is isolated from the legacy manually reviewed theme/
paraphrase workflow. The latter remains available for audited analysis without
blocking Gemini's access to the current censored responses.
