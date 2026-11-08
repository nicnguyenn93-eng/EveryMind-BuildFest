# EveryMind survey cleaning pipeline

John's schema, mappings, ingestion, cleaning, and analysis notebook remain the
primary implementation. The team's existing local Presidio engine is connected
through `privacy_adapter.py`; its detection rules have not been tuned here.

## Setup and run

Use Python 3.11 and the repository's virtual environment. From the repository root:

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-models.txt
python -m everymind_cleaning.run_pipeline
```

The command reads `private_data/raw/BuildFest_EveryMind_Survey_Data_FULL.xlsx` directly.
It also supports `--input private_data/raw/survey.csv` and
`--output-dir private_data`. Generated files must stay in `private_data/`.
Both CPU models must already be installed; runtime never downloads them.

For the optional notebook and analysis dependencies:

```bash
python -m pip install -r everymind_cleaning/requirements-analysis.txt
jupyter notebook everymind_cleaning/cleaning_pipeline.ipynb
```

The notebook imports the same release safeguards and package adapter, connects Presidio, and uses the
same input and output defaults as the command. John's updated analysis code is
retained. Saved outputs were cleared so old, disconnected results are not shown
as current. No translation or LLM suggestion hook is enabled.

## Stage outputs

The default data root is `private_data/`. Each run keeps a source-file hash key:

- `raw/`: unmodified workbook/CSV. Inputs outside this folder are copied into `raw/<key>/`.
- `cleaned/<key>/cleaned_<key>.csv`: standardized fields and normalized, uncensored comments before the privacy tool.
- `censoring/<key>/censored_<key>.csv`: John's full release result with `__redacted` comments, classifications, nullable quality flags, derived fields, and two linkage columns (90 columns on this dataset). The cleaned checkpoint has 62 columns; shared structured fields and row order match.
- `reports/<key>/`: cleaning audit, mapping review, private distress-review subset, and a manifest with stage paths, counts, hashes, and linkage columns.

Presidio's summary sits beside the censored CSV. Its private/ subfolder contains
`comments_private_<key>.csv` and `presidio_review_<key>.csv`, including original
and normalized comments, selected language, redacted text, and detections.
Offsets refer to normalized input (zero-based Python characters, exclusive end).
The source-row and ID columns let you compare retained records across stages;
removed blank/duplicate rows are recorded in the audit. They do not affect deduplication.

`private_data/README.md` links to the latest completed run. The notebook uses the
same publisher. The three-stage command creates no separate analysis export;
John's existing notebook analysis code and in-memory `Result.data` are retained.
`cleaned_analysis.py` reads the full censored CSV directly; its JSON goes under
`reports/<key>/` and its pending review/citation files under `censoring/<key>/private/`.
It never reopens the source or private-original sidecars. Its fingerprints use
censored wording. Older 51-column censored exports are archived during migration;
rerun the primary pipeline if the reader reports an outdated export/manifest.
Earlier mixed-layout results are preserved in `archive/previous_censoring/`.
Standalone full-CSV Presidio runs use `censoring/baseline/` separately.

All blocking checks and staging verification must succeed before publication. Low answer
rates and unrecognized values produce field-specific warnings. Ordinary
replacement errors restore existing files across folders. Sudden termination
is not a multi-file atomic transaction. Inputs are never replaced. All stages
retain local information: uncensored comments remain in raw/cleaned/private files,
and censored text still needs review. No LLM call is enabled.

## Python interface

```python
from everymind_cleaning import release, presidio_bridge
from everymind_cleaning.run_pipeline import SCHEMA, REGISTRY

presidio_bridge.connect()
result = release.run_pipeline(source, SCHEMA, REGISTRY, filename="export.xlsx")
release.require_ready(result.checks)
result.data, result.private, result.audit, result.checks
result.privacy_review, result.privacy_summary
result.cleaned_stage, result.censored_stage
```

`ec.write_outputs` remains available for the older combined layout. The CLI
and notebook use `write_stage_outputs` for the stage folders above.

## Cleaning release safeguards

The CLI and web upload jobs use `release.run_pipeline`, wrapping John's core steps.
Duplicate/ambiguous headers, missing or conflicting IDs, row misalignment, and
value/status inconsistencies block publication. The publisher revalidates a release
result before staging files. The older `everymind_clean.run_pipeline` remains a
core-only comparison entry point.

Exact, alias, and human-approved label matches are applied. Fuzzy and contains
matches are suggestions for private review. Standard Spanish Likert labels are
approved in the mapping registry. Numeric scores require whole values or the two
supported endpoint labels; a Likert code plus label must agree. Multi-select roles
accept comma or pipe separators only when all parts map. Unknown memberships stay
nullable, and `comparison_group` preserves an explicit Unknown category.

Dates require ISO 8601; UTC offsets are removed while preserving local wall-clock
time. CSV ingestion supports UTF-8/UTF-16/cp1252 and comma/semicolon/tab separators,
while retaining logical source-row provenance across blank records.

`form_version_inferred` replaces `form_version`. Optional-question blanks retain
observed-blank and session-answer-rate fields; `suspected_not_asked` is an inference,
not verified form metadata. Unassessable quality checks are NA, and
`n_quality_checks_assessed` records how many were possible.

The stage manifest records release version, combined configuration hash, module
hashes, and warning names. Previous 77-column outputs and their companion files are
preserved under `archive/before_release_v1/` during migration. No new data stage is
introduced. John's separate comment-free `release.write_release` / `load_clean`
contract remains available for standalone consumers; the primary workflow uses
the existing verified, rollback-capable stage publisher.

The original result fields, pipeline arguments, and batch adapter contract are
retained. `PresidioBridge` loads the shared models once per process. Blank texts
return unchanged, including John's `none` language tag. Nonblank texts require
`en` or `es`; unresolved values stop processing rather than defaulting to English.

## Language routing

Each normalized comment is classified independently by the cached, offline
`lingua-language-detector==2.1.1` English/Spanish detector. The highest score must
be at least `text.language_confidence_threshold` in `schema.json` (default 0.80,
valid range greater than 0.5 through 1). A confident text result overrides the
form language without changing the original or standardized form-language field.
Scores compare English with Spanish; they are not measured accuracy guarantees
and do not establish support for other languages.

Uncertain responses use the form language and are flagged for review. Number-only,
punctuation-only, contact-only, and ambiguous answers (`no`, `N/A`, `na`, `ok`)
also use this fallback. Contacts and numbers are removed only from the detector's
working input; Presidio receives the complete normalized comment. Blanks retain
`none` and bypass Presidio. A nonblank response without confident detection or a
valid English/Spanish fallback cannot produce a completed censored export.
Detector setup/runtime failures stop processing without publishing results.

Mixed comments use their dominant language and exactly one Presidio model;
there is no splitting or second-model pass. No translation or model retraining
is involved. The standalone historical censoring command is unchanged.

The private review retains `language` as the effective model choice and adds:

| Field | Meaning |
| --- | --- |
| `detected_language` | Leading detector candidate, or `unknown`/`none` without evidence. |
| `language_confidence` | Candidate score, including below-threshold scores; empty without evidence. |
| `language_source` | `text`, `form_fallback`, `blank`, or `unresolved`. |
| `language_review_required` | True for every fallback or unresolved response. |

The privacy summary records `language_fallbacks`, `language_review_required`,
counts by `language_sources`, and `language_detector` package/version, supported
languages, and threshold. Existing disagreement counts remain available. Routing
diagnostics appear in review files, without adding columns to stage exports.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m pytest tests checks everymind_cleaning/checks -q
RUN_PRESIDIO_INTEGRATION=1 python -m unittest discover -s tests -p test_cleaning_integration.py -v
```

`EVERYMIND_DATA` overrides the real workbook used by John's ten checks. They run
with isolated fake/disconnected adapters and restore any previous connection.
The opt-in integration check blocks network, downloads, and GPU activation.
