# John's cleaner with Presidio: integrated baseline

Original integration run date: 2026-11-07. John's `everymind_cleaning` package is
the primary workflow, with the local Presidio engine connected through its batch
adapter. The original integration kept its language heuristic; the later Lingua
update is described below. Presidio rules and allowlists remain unchanged, and
no translation or provider call is enabled. These are local review results.

## Language routing verification (`language-fix`)

The shared cleaner now uses pinned, offline Lingua 2.1.1 with English and Spanish
only, a configured 0.80 confidence threshold, and one Presidio model per comment.
All form fallbacks are explicitly flagged in the private review. Detector
failures stop processing instead of silently reverting to the form language.
The historical integration results below retain their original routing policy.

The comparison retained all 1,299 records, all 2,598 comment review entries, all
cleaned values, verbatim originals, row linkage, and source hashes. CSV/workbook
results match. A complete real-model workbook run used blocked network, model
downloads, and GPU activation. Identical-input replay of its detections was used
for subsequent format parity checks, avoiding duplicate model inference.
After incorporating the censored-analysis integration, the same comparison
passes with the 51-column cleaned checkpoint and 77-column censored result.
Analysis reads the language-fixed export successfully with raw/private-original
file access and network connections blocked (15 quantitative evidence rows).
Final combined verification: **106 tests and 67 subtests passed**, including
John's ten real-data cleaning checks and installed-model checks. Runtime DNS and
socket connections were blocked throughout the combined test run. The isolated
environment also passes `pip check`.

| Routing measure | Previous heuristic | Lingua routing |
| --- | ---: | ---: |
| Nonblank comments | 1,714 | 1,714 |
| Form-language disagreements | 102 | 103 |
| Form-language fallbacks | 129 (unmarked) | 102 (flagged) |
| Changed comment language | — | 3 |

Local text review covered the 102 previous disagreements, 129 previous
fallbacks, and every changed route: 231 distinct review entries. Two previously
missed Spanish responses now select Spanish. One clear Spanish comment scores
below the required threshold and falls back to the form's English language;
it is flagged for review. The threshold has not been tuned to these examples.

Routing and PII results are assessed separately. Of the three rerouted comments,
two have different redacted output: one unnecessary PERSON removal disappears,
while the flagged Spanish fallback gains an unnecessary LOCATION removal under
the English model. The third rerouted comment has identical output. All
unchanged routes have identical detections and redactions. Overall changed
comment and detection counts remain 76 and 83; those totals do not measure
accuracy. The local review is an agent assessment, not an independently labeled
gold standard. Model retraining and general PII-rule tuning remain separate work.

Detailed comparisons, per-case review assessments, source hashes, and candidate
stage files are Git-ignored under `private_data/language_fix_validation/` in the
original checkout. Existing production outputs are not replaced by this check.

## Preservation and compatibility

- Merged John’s commit `2e36b53` into `security-check` with Git ancestry preserved.
- The integrated workbook run retained 1,299 records and produced John's 75
  cleaned/derived columns. All 20 of John's per-run validation checks passed.
- Executed the original `johnDev` code separately and compared its entire
  cleaning-only table with the updated cleaning-only pipeline: values, dtypes,
  and column order were identical. Original private columns were identical too.
- Compared the published integrated CSV against original John results: all 71
  columns other than the two redacted text columns and two privacy-status columns
  were identical. The privacy columns change because the adapter is connected.
- Original John's CSV and workbook ingestion produced identical cleaned results.
- Calling likelihood retained 293 recorded scores, 1,006 missing values, and four
  valid zeros. Source workbook and source CSV SHA-256 hashes are unchanged.
- Verified every one of the 2,598 review records against the verbatim source,
  original ID, normalized input, published replacement, and detection offsets.
- Notebook analysis code is unchanged. All 51 code cells parse; only setup and
  ingestion/output-path code changed. Stale saved outputs were cleared. The
  optional full statistical-analysis section was not executed as part of this
  integration validation.

The detailed local verification report is at
`private_data/archive/previous_censoring/72b08ff71ede/outputs/integration_verification.json`.
Raw-text reviews are in the same run's `private/` directory and remain Git-ignored.

The code utilities now live in `everymind_censoring/` (renamed from `scripts/`).
Generated CSVs, baseline reviews, and the integrated run folders are grouped
under `private_data/censoring/`; the original workbook remains in `private_data/`.
All seventeen existing data files were checked by SHA-256 across the move and
retained identical contents. The converter was also rerun successfully using
its new default output path.
The full suite was rerun after the rename: 46 tests and thirteen subtests passed,
including the installed-model checks and John's cleaning checks.

## Comparison with the standalone Presidio baseline

| Measure | Standalone | Integrated |
| --- | ---: | ---: |
| Comment fields | 2,598 | 2,598 |
| Nonblank comments scanned | 1,714 | 1,714 |
| Changed by Presidio | 136 | 76 |
| Unchanged nonblank | 1,578 | 1,638 |
| Blank | 884 | 884 |
| Detections, including overlaps | 160 | 83 |

John's existing heuristic routed 102 nonblank comments differently from their
form language. It selected English for 1,586 and Spanish for 128 comments;
884 normalized blanks used `none` and bypassed detection. This is per-comment
routing, rather than assigning one model to both comments from the form label.

John's normalization changed 318 comment fields before detection. The review
keeps the verbatim original separately; detection offsets always refer to the
normalized input. Presidio change counts compare replacement against normalized
input, so normalization is not incorrectly counted as redaction.

Sixty-two previously changed comments became unchanged, seventy-four stayed
changed, and two previously unchanged comments became changed. Counts are not a
measure of accuracy: both normalization and existing language routing differ
from the standalone workflow.

## Representative observations

- Two previously identified Spanish false positives now remain intact: a
  Spanish article mistaken for a location, and an ordinary request-for-help
  phrase mistaken for a person. John routed these comments to Spanish.
- The service-availability expression `24/7` is still removed as `DATE_TIME` in
  an English comment. Presidio's existing rule selection is unchanged.
- The previously identified missed presenter name remains in one English
  comment while the organization website is replaced. Connecting the cleaner
  does not resolve this name-detection miss.
- A typo in one correctly Spanish-routed comment is still labeled `PERSON`.
  Per-comment routing does not eliminate model false positives.
- Public-resource-number handling has not changed. Phone-shaped strings are
  still detected, and overlapping bank/license labels can also occur.

The next iteration can address these problems individually using the integrated
review files. This integration deliberately makes no accuracy claim.

## Verification commands

```bash
python -m unittest discover -s tests -v
python -m pytest everymind_cleaning/checks -q
RUN_PRESIDIO_INTEGRATION=1 python -m pytest tests everymind_cleaning/checks -q
```

Tests cover batch alignment, blanks, unknown languages, model initialization,
normalized offsets, Unicode/multiline CSV and workbook parity, provenance across
blank-row and duplicate removal, duplicate IDs, adapter restoration, legacy
direct-module writing, and output preservation on failures. Installed-model
checks block network connections, downloads, and GPU activation.

Final combined run: **46 tests passed**, including both installed-model offline
checks and John's ten cleaning checks (plus thirteen unittest subtests).

## Three-stage layout verification before the main merge

The earlier verification above describes the original combined export and is
retained in the archive. At this checkpoint, runs published separate raw, cleaned, and censored
stages under private_data/, with audits and manifests in
reports/. Cleaned/censored tables have the same schema and differ only in comment
values. Both retain source-row and original-ID linkage. John's Result.data
retains its original schema; no separate analysis stage is published.
See the repository README and the generated
private_data/README.md for the current paths.

The real three-stage run retained all 1,299 source records. Raw remains 20
columns; cleaned and censored each have 51 columns, including linkage. All
non-comment values match between the two stage CSVs, and shared structured
fields match the previous John pipeline result. All 2,598 review entries align
with the original source text, normalized cleaned text, and censored text.
The same 76 comment fields changed as before; 1,638 nonblank comments were
unchanged and 884 were blank. All 293 calling-likelihood scores, 1,006 blanks,
and four valid zeros remain. These counts do not measure detection accuracy.

The workbook and lossless raw CSV retain their original hashes; every CSV
field was compared against the workbook. All 17 earlier artifacts remain
available with matching hashes at their new or archived locations. Stage-file
hashes match the manifest, and all private data files are Git-ignored. Detailed
local checks are in
`private_data/reports/72b08ff71ede/stage_verification.json`.

Verification: the combined suite passed **49 tests and 13 subtests**, including
John's ten real-data cleaning checks and installed English/Spanish model checks
with network, downloads, and GPU use blocked. Stage-specific checks cover row
linkage after duplicate removal, comment-only changes, source mutation rejection,
and rollback across folders on a late publication failure. All 51 notebook code
cells parse, saved outputs are empty, and the existing analysis cells remain
unchanged. The optional analysis notebook was not executed.

## Main merge and censored-CSV analysis (before the language merge)

Merged `origin/main` at `1a71d0e` into `security-check` with merge checkpoint
`8f6cfaf`; integration checkpoint `26267a8` connects its analysis to the censored
export. Main's statistics, feedback calculations, codebook and semantic approval
rules are unchanged. The legacy loader/configuration and synthetic fixtures were
restored for compatibility; the old mock UI and report/PDF stubs remain excluded.
The existing pinned runtime is retained, with an explicit Pydantic dependency for
citation schemas. `pip check` reports no broken requirements. The Gemini SDK is
still optional.

The raw → cleaned → censoring flow retains 1,299 records. Raw remains 20 columns,
the pre-Presidio checkpoint remains 51, and the censored CSV is now 77: John's full
75-column result plus source-row and original-ID linkage. Every field of its
75-column core matches the earlier integrated result. All shared structured
values, all 2,598 review entries and the original source hashes match. The same
76 comment fields changed, with 83 detections, 1,638 unchanged nonblank comments
and 884 blanks. Calling likelihood retains 293 scores, 1,006 blanks and four
zeros. Detection counts still do not measure accuracy.

The v2 stage manifest records column names, scalar types and file hashes. The
analysis reader restores booleans/numbers without losing IDs or zeros and rejects
raw, old, incomplete, changed or pending exports. Its dataset key hashes the exact
censored CSV. All six audiences produce identical quantitative evidence to main's
original adapter. The real-data keyword counts also match in this run, although
censored wording can change them in other runs. Language routing and analytical
cleaning functions were verified unchanged.

Analysis succeeded with reads of raw/private-original folders and network access
blocked. The generated payload has 15 quantitative evidence rows, no approved
comment evidence, and the unchanged `everymind.analysis.v2` schema. A separate
pending packet contains 1,714 nonblank censored comments; all remain unapproved.
Review fingerprints now bind censored wording. Gemini's current-payload dry run
also succeeded with network/DNS blocked, without historical-cohort tables or
human findings. No provider call was made.

The previous 51-column censored export, manifest and guide are archived under
`private_data/archive/censoring_schema_v1/`. All 29 pre-merge private artifacts
remain available with matching hashes. Real data and generated files remain
Git-ignored, and neither local main nor origin/main was changed. Detailed local
evidence is in `private_data/reports/72b08ff71ede/main_merge_verification.json`.

Final verification passed **94 tests and 13 subtests** across our tests, main's
analysis checks and John's ten real-data checks, including installed EN/ES model
checks with network/download/GPU use blocked. Regression coverage includes typed
CSV round trips, leading-zero IDs, blanks and zeros, optional columns, duplicate
IDs, stale fingerprints, legacy-export archival, rollback across stage and
analysis files, malformed manifests, and conflicting output filenames. The raw
input CLI rejection also preserved the existing real analysis payload. All 51
notebook code cells parse and the existing analysis cells remain unchanged; the
optional analysis notebook was not executed.

A final integrity recheck found the live censored CSV had reverted to the exact
pre-merge 51-column bytes while the v2 manifest still described 77 columns. The
writer was not identified. The stale copy was preserved under
`archive/censored_recovery/`, and the verified 77-column bytes matching both the
manifest and analysis dataset hash were restored. All real-data checks then
passed again. Concurrent experiments should use their own `--output-dir` so
they do not replace the primary run. The reader correctly rejects mismatched
files instead of silently analyzing them.

## Language fix merged into security-check (current)

Merge checkpoint `cde1add` incorporates `language-fix` at `dba48fd` while retaining
our latest analysis verification and parallel-output guidance. Neither main nor
the language-fix branch was modified. The merged code passed **106 tests and 67
subtests** with DNS/socket access blocked throughout; `pip check` also passed.

A fresh CPU run with network, downloads and GPU activation blocked retained
1,299 records and the 51/77-column stage schemas. Its censored CSV exactly matches
the language branch's reviewed candidate. All shared structured values, original
form-language answers, raw sources, cleaned data and private-original linkage
are unchanged. The calling-likelihood scores still include all four valid zeros.
All six audiences retain identical quantitative evidence.

Of 1,714 nonblank comments, 1,612 route from text and 102 use a flagged form-language
fallback; 884 blanks bypass Presidio. Three effective language choices changed,
with two resulting text replacements changed. Unchanged routes retain identical
detections and replacements. Changed comments remain 76 and detections remain 83;
these totals are not accuracy measurements. Inspection of the three changed
routes confirms two Spanish corrections and one Spanish response incorrectly
falling back to English at a 0.672 score, below the 0.80 threshold. That case is
explicitly flagged; threshold tuning and mixed-language handling remain future work.

The active analysis JSON, all 1,714 pending censored-text review records, and the
Gemini prompt dry run were refreshed without provider calls. All 65 pre-merge
private artifacts remain available with matching hashes; the 15 active stage,
analysis and review files were archived under `archive/pre_language_fix/` before
replacement. Data remains Git-ignored. The current verification report is
`private_data/reports/72b08ff71ede/language_merge_verification.json`.

## Main publication scope

The publication retains the integrated cleaning, Presidio, per-comment language
routing, censored-data analysis, and optional Gemini command-line tools. The old
Streamlit mock UI and placeholder report/PDF modules remain removed. A frontend
will need a separate integration with the processed outputs.

Pre-publication verification confirms the live censored export has 1,299 rows
and 77 columns and matches its manifest and analysis dataset hash. The raw
workbook, raw CSV, and cleaned checkpoint hashes are unchanged. Real survey data
and private review outputs remain ignored and untracked by Git.
The complete suite passed again with DNS/socket access blocked: 106 tests and
67 subtests, including the installed English/Spanish Presidio model checks and
John's cleaning checks. Dependency validation reports no broken requirements.

## Nimi reporting backend integration

The local merge checkpoint `703d4eb` preserves `origin/nimi-branch` at `ca3aa95`.
The following checkpoint `1d12a6b` removes Nimi's Streamlit app and UI tests from
the final tree so a separately developed frontend can merge independently.
`79e64b6` connects the reporting code through `report_service.py`, restores its
action catalog, and publishes the `everymind.report.v1` JSON schema and frontend
contract. Primary pipeline dependency pins are retained; the optional provider
SDK is installed with `requirements-report.txt` and adds no frontend framework.

The service reads the full censored CSV and matching manifest, rejects stale
dataset selections, and returns ordinary analysis/report dictionaries. It does
not rerun cleaning, initialize Presidio, or read original-comment sidecars.
Provider requests use allowlisted aggregate evidence by default. Including
paraphrases still requires explicit opt-in and matching human/privacy approval.
Missing keys, API failures and invalid model responses yield labeled templates;
withheld audiences receive no proposed action and cause no provider call.

Integration fixes align the reporting prompt with evidence-ID citations rather
than the separate Gemini kit's table/cell schema, calculate template differences
from unrounded values, bound request timeouts/retries, close owned clients, and
sanitize provider errors. Numeric consistency checks are not semantic validation.
Catalog membership is enforced, but catalog thresholds remain metadata rather
than automatically evaluated eligibility rules; the offline template selects the
first catalog option when evidence is publishable. These limits are documented
for the frontend owner.

The combined suite passed **134 tests and 67 subtests** with DNS/socket access
blocked, including the existing cleaning and installed EN/ES model checks. The
real 1,299-row, 77-column export also passed six audience flows with fake Gemini
clients and the offline template path, while raw/private-original reads and all
network calls were blocked. Current analysis matches the saved analysis JSON;
source, stage, manifest and analysis hashes are unchanged. No frontend files or
primary runtime pins differ from the pre-integration `ea85075` state. `pip check`
reports no broken requirements. Details are retained in the ignored
`private_data/reports/72b08ff71ede/nimi_backend_verification.json`.

After explicit authorization for the reviewed outbound payload, two live Gemini
requests using `gemini-3.6-flash` succeeded on their first attempt. Each sent the
same 15 aggregate evidence records and zero comments. Both returned `mode=llm`,
passed the report schema and evidence/number checks, and left the censored data
unchanged. The key is absent from outputs and remains in a Git-ignored local file.
The initial live request was blocked by automatic approval review before sending;
the user then explicitly approved the concrete payload and Google Gemini destination.

Live wording review prompted checkpoint `a62d215`: inclusive-OR post-training
metrics mean **at least one** item, and a neutral post-training response does not
establish that the respondent remained neutral over time. The prompt also guards
against inferring student-only findings from all-respondent aggregates. All 28
focused reporting/service tests passed after that prompt change; no analytical
calculations or data schemas changed. Reports remain drafts for semantic review,
especially because the existing catalog's options are student-focused.

Live artifacts are under the ignored `private_data/reports/72b08ff71ede/gemini_live/`
folders `20261108T045249Z` and `20261108T045524Z`. The backend verification JSON
records both successful calls and confirms unchanged hashes of the raw inputs,
cleaned/censored stages, manifest, and saved analysis. The frontend branch
`origin/netra-frontend` at `3dacc98` was inspected without merging it; a read-only
merge preview found no textual conflicts with this backend integration. Its
static HTML/build-time data workflow still needs a separate connection to the
Python service, as described in the frontend/backend contract.

During publication, a normal push was rejected because main had advanced to
`1e0f8d8`, which publishes Netra's frontend through PR #1. Checkpoint `bc1bdd4`
merges that concurrent main update without conflicts. All `frontend/` files
remain byte-identical to the upstream publication, and Nimi's `app.py` and UI
tests remain excluded. The current main tree contains Netra's static frontend
alongside the reporting backend; a dynamic HTTP or build-time data connection is
still a separate step. Primary runtime dependency pins remain unchanged.
The combined 134-test / 67-subtest suite passed again after this merge with all
DNS/socket access blocked. No additional live calls were needed because the
backend and its approved aggregate payload were unchanged by the upstream merge.
