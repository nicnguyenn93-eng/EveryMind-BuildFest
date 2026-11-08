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
`private_data/censoring/72b08ff71ede/outputs/integration_verification.json`.
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
