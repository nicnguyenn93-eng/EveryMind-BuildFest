# K3 synthetic handoff v2: actual export format

All records and comments are invented. The input now mirrors the supplied workbook's exact 20 headers, column order, text agreement scale, semicolon-separated roles, and two comment fields. `export_columns.json` records the verified header mapping without real responses. `clean.load_export` produces the normalized structural records; evidence, reviews, and reports remain expected handoff examples, not implemented app results.

## Input and definitions

`synthetic_survey.csv` and `synthetic_survey.xlsx` contain the same 30 unique responses; the workbook sheet is `Survey Data`. Headers start in row 1. CSV is UTF-8. Raw knowledge values are text, including `Neither agree nor disagree`. The importer maps them to 1=Strongly disagree, 2=Disagree, 3=Neutral, 4=Agree, 5=Strongly agree. Each score has a `_status` field (`valid`, `missing`, or `unmapped`); invalid and missing scores are null, while status preserves their distinction. SYN030 includes an unusual presenter rating (`Very agree`), which remains unmapped and is audited. The before/post mapping below refers to internal fields, not raw header names.

| Pair | Recalled before | Post-training |
|---|---|---|
| Identify challenges | q1_knowledge | q2_knowledge |
| Explain 988 | q3_knowledge | q4_knowledge |
| Know when to use 988 | q5_knowledge | q6_knowledge |

The raw `Are you a....?` field uses semicolon-separated membership, including `School staff member`; normalized `role_membership` is a sorted array using `School staff`. Students means membership in `Student`, counted once. Known non-students means a known role set without Student. SYN001 is both Student and School staff. There are ten students, nine School staff, and twenty known non-students. Role groups overlap and must not be added together. County/date values are synthetic; dates use ISO format. Recommendation and intent use 0-10, with zero valid and blanks missing. SYN001 has zero on both; SYN002 has blank intent.

Agreement uses only valid 1-5 recalled/post pairs for the same question. Explain 988 has 29 valid pairs overall: SYN030 has missing recalled knowledge, so its post score must also be excluded. Students: before 5/10, after 9/10, change 40.0 percentage points. All respondents: before 24/29, after 28/29, change 13.8 percentage points (calculate from unrounded proportions). Intent coverage is 29/30.

## Output records

- `normalized_responses.json`: structural records, retaining optional fields and role arrays.
- `reviewed_comments.json`: 60 local review records, with response ID, field, exact-text UTF-8 SHA-256 fingerprint, role array, language, status, paraphrase, and theme IDs. Synthetic approvals cover both fields for SYN001-SYN010; remaining 40 records are pending. Pending originals remain in the input, and have no approved paraphrase. Changing content invalidates approval; match ID + field + fingerprint together.
- `audit.json`: import counts, missing/unmapped counts, dataset key, and fixture expectations. The key is SHA-256 of canonicalized source records: headers are mapped and sorted, valid scores have stable numeric representations, and comment text remains exact. Equivalent CSV/XLSX inputs share a key; changed content under the same filename produces a new one.
- `evidence.json`: allowed example evidence rows for paired explain-988 agreement. These are selected examples, not a complete metrics inventory.
- `theme_summary.json`: reviewed scenario-request counts and field coverage. Each response counts once per field. All ten reviewed student improvement comments request scenarios; the complementary reviewed count is zero. The all-respondent review is a selected sample (10/30), not a prevalence estimate. Both thematic counts and complements require privacy checks in production.
- `report.json`: template report using current dataset/audience evidence IDs and the existing roleplay action ID. The pilot is supported by ten reviewed requests for scenarios, not by a score threshold. The existing action catalog must be corrected during G1 integration. Use `follow_up_measure` consistently; this replaces the older `follow-up_measure` spelling.
- `privacy_expectations.json`: no School staff statistics, search paraphrases, or theme counts may be released. This synthetic input intentionally exposes all raw fixtures to developers; these files are not public app outputs.

The examples are the v2 handoff record shapes. Import validation is implemented; downstream privacy, calculations, review import, report validation, and UI integration remain necessary. Importing the fixture sets all comments pending. `reviewed_comments.json` separately represents simulated approvals, never automatic approval of a fresh upload.

## Load and verify (Roles 2-4)

From the repository root, using the environment described in the main README:

```powershell
.\.venv\Scripts\python.exe examples/load_k3.py
.\.venv\Scripts\python.exe -m pytest checks/test_k3_fixture.py -q
```

Use `.venv/bin/python` on macOS/Linux (or `venv` instead of `.venv` for an existing environment). The loader returns ordinary JSON-compatible records; it does not call unfinished production modules. In Python, call `from examples.load_k3 import load_examples` then `records = load_examples()`.

Role 2 starts with reviewed comments and theme summaries. Role 3 starts with evidence, themes, and report. Role 4 starts with evidence and report for rendering and PDF work. To read the raw inputs, use `pandas.read_csv(...)` or `pandas.read_excel(..., sheet_name="Survey Data")`.

To exercise the real import adapter locally:

```python
from pathlib import Path
from clean import load_export
path = Path("examples/synthetic_survey.xlsx")
dataset_key, responses, private_comments, audit = load_export(path.read_bytes(), path.name)
```

`private_comments` contains original text and is for local review only. Do not send it to a provider or render it as approved feedback. The importer does not apply public-output suppression. The Streamlit app still displays mocks and does not call this importer yet.

## Receiving review

K3's receiving-person signoff is still open. Each teammate should run the loader and checks, confirm their module accepts the fields/types, and record initials plus any disagreements below. Do not mark these on someone else's behalf.

| Receiver | Load/examples confirmed | Initials / date / disagreements |
|---|---|---|
| Role 2 | Pending | |
| Role 3 | Pending | |
| Role 4 | Pending | |
