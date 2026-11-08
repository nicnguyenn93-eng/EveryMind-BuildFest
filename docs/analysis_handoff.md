# Analysis handoff from the censored export

## Run the local workflow

John's cleaner and the existing local Presidio engine prepare the three stages:

```bash
python -m everymind_cleaning.run_pipeline
python cleaned_analysis.py private_data/censoring/72b08ff71ede/censored_72b08ff71ede.csv
```

Use the source-file key printed by your run for other inputs. The original
workbook/CSV stays in `private_data/raw/`, the pre-Presidio checkpoint in
`cleaned/<key>/`, and the full result in `censoring/<key>/`. On the supplied
survey these contain 1,299 records: 20 raw columns, 51 cleaned columns, and 77
censored columns. The last table preserves John's 75-column result, including
language/classification metadata, quality flags and derived values, plus
`source_row` and `original_id`. Original comments are not included there.

The analysis command reads only that CSV and its v2 manifest. It rejects raw
inputs, the old incomplete censored export, changed files whose hashes do not
match, and pending privacy processing. It does not reopen source files, load
models, translate, or call an AI provider. An old export can be regenerated
with the primary command above; the previous 51-column censored file and its
manifest/guide are archived during that upgrade.

The default output is `private_data/reports/<key>/ai_input.json`. Retained
options are `--audience` (default `All respondents`), `--reviews`, `--output`
(inside private_data), and `--prepare-review`. Terminal output contains counts
and paths only. JSON and private companion files are staged and verified before
publication; ordinary replacement failures restore existing outputs. Abrupt
termination during multi-file publication is not an atomic transaction.

## Data contract

`load_censored_export(path)` validates the stage manifest, file hash, row/column
counts and schema, then restores numeric, boolean and datetime scalars. IDs
remain strings, `False` remains false, and numeric zero is distinct from blank.
Missing optional score or comment fields disable their corresponding analyses.
Duplicate or missing response IDs fail analysis; they are not silently removed
or replaced, even when John's cleaner has retained and flagged them.

`adapt_cleaned(data)` maps the full censored result into the existing analysis
contract: unique nonblank `id`, canonical `role_membership`, numeric knowledge
scores 1–5, and recommendation/intent scores 0–10 with status fields. No private
original-comment argument is accepted. Comment records use `__redacted` text
with John's upstream category and language metadata. The legacy internal key
`original_text` now means the current censored wording. Original-length and
classification metadata retain John's upstream calculations.

```python
from pathlib import Path
from cleaned_analysis import run
payload = run(Path("private_data/censoring/72b08ff71ede/censored_72b08ff71ede.csv"),
              audience="Students")
```

The JSON schema remains `everymind.analysis.v2`. The payload includes quantitative
evidence, reviewed themes, explicitly exploratory feedback, coverage, limitations,
and optionally approved comment evidence. Its dataset key is `censored-sha256:`
plus the full hash of the censored CSV, so different processed exports cannot
share an analysis identity merely because their raw input was identical. The
folder key continues to identify the source file. Respondent IDs, raw comments,
source filenames, distress flags and private lineage maps are not included.

The legacy `clean.py` loader, export configuration and K3 synthetic examples are
retained for existing regression tests and compatibility. They are not the
primary analysis entry point. The mock UI and report/PDF stubs remain excluded.

## Comment review and approved evidence

Both keyword analysis and review fingerprints use censored wording. This can
change keyword counts compared with analysis of originals. Approvals for changed
wording cannot inherit the previous source fingerprint; review the current text.
Presidio processing does not imply approval or perfect identifier detection.

```bash
python cleaned_analysis.py private_data/censoring/72b08ff71ede/censored_72b08ff71ede.csv --prepare-review
```

This creates `censoring/<key>/private/comment_review_pending.json`, containing
censored text and IDs for local review. It refuses to overwrite an existing
packet. All records start pending with `privacy_screened=false`, empty theme
IDs and no approved paraphrase. Verbatim originals remain separately available
in raw inputs and existing local Presidio review files for staff inspection;
analysis does not read those files.

A reviewer checks meaning and remaining direct/indirect identifiers, selects
valid `theme_ids`, writes a safe `approved_paraphrase`, marks
`reviewer_status="approved"` and `privacy_screened=true`, and records the SHA-256
of that exact paraphrase in `approved_paraphrase_fingerprint`. Preserve the
current censored-text `content_fingerprint`. Save approved reviews privately:

```bash
python cleaned_analysis.py private_data/censoring/72b08ff71ede/censored_72b08ff71ede.csv --reviews private_data/censoring/72b08ff71ede/private/comment_review_approved.json
```

Only current ID/field/content matches and explicitly screened paraphrases are
eligible. Edited paraphrases without renewed approval, absent screening, unknown
or wrong-field themes and suppressed theme counts remain excluded. No approval
is inferred from a keyword match. Substantive themes may overlap; no-change and
unclear codes must stand alone. Missing comments are not no-change responses.
`codebook.json` remains the initial coding guide rather than a claim about the
dataset's actual themes. English keyword matches remain unreviewed signals.

Eligible examples carry opaque `comment_evidence_id` values. Their local maps
are written as `censoring/<key>/private/ai_lineage_<payload-hash>.json`, where the
hash uses canonical JSON (sorted keys, Python's default ASCII encoding, no NaNs).
Keep the map with its specific payload; never send it to the provider. Selection
remains the first qualifying approved records in review-file order, capped at
50 examples per field. Examples are illustrative; use reviewed aggregate theme
counts for frequency claims. No real comments are automatically approved.

## Statistical definitions retained from main

- Each knowledge topic uses its own valid before/post pairs. Agreement is 4 or 5;
  percentage-point changes use unrounded proportions. The three topics remain
  identifying challenges, describing 988, and knowing when to use 988.
- Recommendation and intent means retain valid zeros and exclude missing,
  unmapped, out-of-range and noninteger values. Coverage uses valid answers
  divided by audience size.
- Neutral on either post-988 item is distinct from below agreement, which also
  includes disagreement. Both items must be valid for these measures.
- Students includes anyone with Student membership once. Known non-students
  requires a recognized non-student role and excludes Student membership.
  Comparisons require nonoverlapping groups and cite both groups' evidence IDs.
- Publication requires at least ten valid respondents and protects small valid
  complements. Samples of 10–29 are labeled limited. Theme positives, complements
  and related coverage may be withheld; absent/withheld does not mean zero.
- Reviewed themes use fingerprint-matched approved comments and reviewed
  denominators. They do not estimate prevalence among all respondents. Stateless
  suppression does not prevent combining many historical or overlapping releases.

All findings remain descriptive retrospective self-report. Do not infer causal
effects, significance, retention predictions or theme/intent correlations from
separate aggregates. Analysis supplies evidence and does not choose actions.

## Gemini handoff and verification

```bash
python gemini_kit/run_gemini.py --payload private_data/reports/72b08ff71ede/ai_input.json --dry-run --out private_data/reports/72b08ff71ede/gemini_dry_run
RUN_PRESIDIO_INTEGRATION=1 python -m pytest tests checks everymind_cleaning/checks -q
```

Payload mode uses only the current cohort and defaults to the blind stage. It
must not mix in bundled historical tables or human findings from another cohort.
Approved paraphrases remain excluded from Gemini by default; explicit opt-in and
appropriate reviewed content are still required. The SDK is optional, and dry
runs make no provider call. No live model, account or API-key validation is part
of this integration. Citation checks verify cited table values, not the accuracy
of every statement, interpretation or proposed recommendation.
