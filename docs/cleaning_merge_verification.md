# John's cleaning merge — 2026-11-08

Merged `origin/johnDev` through `2fb084d` into `main`, retaining its ancestry.
The three imported commits add a release contract, robustness checks, and approved
standard Spanish Likert mappings. John's branch stays unchanged.

The primary CLI, web upload jobs, and notebook now use the release safeguards with
the existing Presidio adapter and raw → cleaned → censoring stage publisher.
The Python/HTTP analysis and report interfaces, frontend layout, language routing,
Presidio models, and Gemini handoff remain compatible.

## Integration decisions

- Retained source-row provenance across blank CSV records and exact duplicates.
- Added package-compatible imports and removed working-directory changes from
  John's new tests so the repository's suites share one adapter instance.
- Kept the existing verified publication and rollback mechanism. Release results
  are revalidated before files are staged; failed blocking checks preserve outputs.
  Low answer rates and format-drift warnings are recorded separately.
- Updated analysis to accept nullable boolean role flags. An unknown role stays
  unknown; known Student selection remains usable on a partially mapped response.
- Incorporated John's notebook updates, connected its publication to the stage
  folders, and kept keyword analysis on censored comments.
- Archived previous stage files and companions under `archive/before_release_v1/`
  during the 77-to-90-column migration. All survey files stay Git-ignored.

## Real-data comparison

| Check | Result |
| --- | --- |
| Retained responses | 1,299, with identical source-row and ID linkage |
| Raw / cleaned / censored columns | 20 / 62 / 90 |
| Calling scores | 293 recorded, 1,006 blanks, including 4 valid zeros |
| Censored written answers | 1,714; wording unchanged in both fields |
| Report statistics | All 15 unchanged except their dataset identity |
| Source workbook | SHA-256 unchanged |
| Release warnings on this workbook | None |
| Blocking/warning release checks | 54 of 54 passed |

The release schema adds 14 fields and replaces `form_version` with
`form_version_inferred`. Its availability fields preserve observed blanks and
session answer rates. Previously inferred `not_asked` statuses become
`suspected_not_asked`: 970 calling blanks and 119 blanks in each of the three
presenter/organization items. These are inferences from answer rates, not verified
form metadata. Unassessable straightline and scale-misread flags become NA on 160
and 152 rows respectively. No response is removed for these flags.

The completed censored CSV hashes to
`5b72c7f6493b220b5b19d50f9029c06ceb7922f348c44bb7c3dfca1e818a0b66`.
Dataset-bound comment evidence IDs and cached reports therefore change even though
the censored wording is identical. Historical saved Gemini previews retain their
original dataset identity; fresh requests use the newly selected export.

## Verification

- Full offline suite: **424 passed, 67 subtests passed**, including John's ten
  real-export checks, 257 synthetic release/robustness tests, the new primary-path
  release tests, and installed English/Spanish Presidio model checks.
- New tests cover strict score/date parsing, nullable and partial roles, warning
  publication, blank/colliding IDs, migration rollback, revalidation of edited
  results, and frontend aggregates from the released schema.
- Real workbook conversion and offline report generation ran with socket and DNS
  access blocked. The report retained all 1,714 censored answers.
- Compiled all 52 notebook code cells. Executed the 20 code cells through cleaning,
  release publication, notebook regression checks, and the analysis adapter against
  the real workbook with networking disabled. Later plots and targeting models
  retain John's implementation.
- Installed the documented optional notebook dependencies; `pip check` passed.

Private comparison, notebook logs, and publication details are saved under
`private_data/verification/john_merge/20261108T063401Z/`.

Reproduce the primary workflow from the repository root:

```bash
python -m everymind_cleaning.run_pipeline
RUN_PRESIDIO_INTEGRATION=1 python -m pytest tests checks everymind_cleaning/checks -q
```

Existing valid exports remain readable. Rerun the primary command after pulling
these changes to apply the new cleaning semantics to a teammate's local data.
