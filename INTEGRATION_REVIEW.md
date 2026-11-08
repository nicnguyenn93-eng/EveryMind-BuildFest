# John's cleaner with Presidio: integrated baseline

Run date: 2026-11-07. John's `everymind_cleaning` package is the primary workflow;
the existing local Presidio engine is connected through its batch adapter. No
new detection rules, allowlists, language algorithm, translation, or LLM call
were added. These results are for local review, not an anonymity certification.

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

## Main merge and censored-CSV analysis (current)

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
