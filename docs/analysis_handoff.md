# Analysis handoff on nic-branch

## Single JSON input for the AI owner

### Semantic comment evidence (schema v2)

Keyword counts alone are insufficient for interpreting what respondents mean. The payload now includes `approved_comment_evidence`: privacy-screened, approved paraphrases carrying opaque `comment_evidence_id`, source field, and publishable theme IDs. Raw comments, response IDs and fingerprints remain local. The reporting AI can summarize and propose evidence-cited recommendations from this input; analysis modules themselves do not choose actions or call a provider. Recommendations remain proposed, not proven effective or formally approved.

Prepare the actual local comments for review with:

```bash
python cleaned_analysis.py "C:/Users/nickn/Downloads/BuildFest_EveryMind_Survey_Data_FULL.xlsx" \
  --prepare-review --output everymind_cleaning/outputs/ai_input.json
```

This creates `everymind_cleaning/private/comment_review_pending.json`, containing original comments for local review only. It never auto-approves text and refuses to overwrite an existing packet. Apply the team's privacy screening and check meaning, names, places and indirect identifiers. Enter a safe `approved_paraphrase`, appropriate `theme_ids`, `reviewer_status="approved"`, `privacy_screened=true`, and the SHA-256 of that exact paraphrase in `approved_paraphrase_fingerprint`. Preserve the source `content_fingerprint`. Save the reviewed version privately, then run:

```bash
python cleaned_analysis.py "C:/Users/nickn/Downloads/BuildFest_EveryMind_Survey_Data_FULL.xlsx" \
  --reviews everymind_cleaning/private/comment_review_approved.json \
  --output everymind_cleaning/outputs/ai_input.json
```

The paraphrase fingerprint binds approval to the exact reviewed wording; it does not detect identifiers itself. The operator remains responsible for privacy and meaning approval. Edited source text, edited paraphrases without renewed approval, absent screening, wrong fields, and suppressed themes are excluded. Only comments belonging to publishable approved themes can be included. At most 50 qualifying examples per field are sent, in review-file order; metadata describes this illustrative sample. Use the separate reviewed theme counts for frequency, not the number of selected examples. Other themes can be added to the codebook after review rather than forcing comments into initial categories.

Every run that releases paraphrases writes a separate `ai_lineage_*.json` under the ignored private folder, linking opaque citation IDs to current local records. Keep the lineage file with that specific AI payload; never send it to the provider. Do not put outbound payloads containing paraphrases in shared folders without checking the approved release. No real comments have been approved by this code, and no provider call has been made.

Run `cleaned_analysis.py` to execute John's cleaner, map its cleaned contract, and create one aggregate-only JSON file. From Git Bash at the repository root:

```bash
python cleaned_analysis.py "C:/Users/nickn/Downloads/BuildFest_EveryMind_Survey_Data_FULL.xlsx" \
  --audience "All respondents" \
  --output everymind_cleaning/outputs/ai_input.json
```

Use `--audience Students` for student evidence. Optionally supply `--reviews path/to/local_reviews.json` for genuine approved reviews that match John's current private text fingerprints. Do not use the synthetic review file for real data. This runner does not send anything externally and does not write original comments. Keep generated real-data output in the ignored outputs directory.

The payload has a stable `schema_version`, current dataset key/audience, quantitative evidence, approved `qualitative_themes`, and separate `exploratory_feedback`. The latter contains field-specific rule-based category counts and unreviewed English keyword matches in substantive comments. Category breakdowns and positive keyword counts/complements below ten are withheld. An empty result does not mean that no such themes exist. Review sampling, meaning verification, other languages, negation, and privacy screening still need human work.

For integration in Python:

```python
from pathlib import Path
from cleaned_analysis import run
payload = run(Path("path/to/survey.xlsx"), audience="Students")
# AI owner serializes this whole object into their provider's input:
import json
provider_input_text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
```

No raw text, respondent IDs, input filenames, distress flags, or credentials are included. Schema v2 can include explicitly approved privacy-screened paraphrases as described above. Codebook names are fixed project labels. `interpretation_rules` prohibit treating unreviewed signals as verified prevalence, causal explanations, recommendation eligibility, or statistical significance. The AI owner must preserve these distinctions and validate its response. This interface supplies evidence; it neither calls AI nor selects recommendations.

`analysis.py` owns descriptive statistics and the combined analysis object. `feedback.py` owns local coding suggestions and reviewed thematic counts. Neither module calls an LLM or chooses actions. `metrics.py` is a compatibility import pointing to `analysis.build_evidence`; it contains no competing calculations. The current Streamlit interface remains a separate mock and has not been wired to these modules.

## Input contract with John

Pass the normalized responses DataFrame and dataset key from `clean.load_export`, not raw full-question headers. Required structural fields are a unique nonblank `id` and `role_membership` (a list of canonical roles per respondent). Knowledge is numeric 1-5, recommendation/intent numeric 0-10, and invalid/missing scores are null. If a score has a `_status` column, only `valid` entries are used. Role aliases must be normalized upstream; a missing role column fails instead of silently reporting everyone as students. Missing optional score columns disable that analysis. Unknown role labels do not establish known non-student membership.

| Topic | Recalled before | Post/current |
|---|---|---|
| Identify challenges | q1_knowledge | q2_knowledge |
| Describe 988 | q3_knowledge | q4_knowledge |
| Know when to use 988 | q5_knowledge | q6_knowledge |

```python
from pathlib import Path
import json
from clean import load_export
from analysis import analyze_data, compare_audiences
from feedback import suggest_theme_codes

path = Path("examples/synthetic_survey.xlsx")
key, responses, private_comments, audit = load_export(path.read_bytes(), path.name)
reviews = json.loads(Path("examples/reviewed_comments.json").read_text())
result = analyze_data(responses, key, "Students", private_comments, reviews)
comparison = compare_audiences(responses, key)  # Students vs Known non-students
private_suggestions = suggest_theme_codes(private_comments)
```

Develop against `examples/normalized_responses.json` if John's cleaner is unavailable. Load it with `pd.DataFrame(json.loads(...))` and use the corresponding `examples/audit.json` dataset key. When John's cleaner returns this same contract, pass its outputs to these functions and rerun the checks. Real-file integration still needs the team's independent review.

## Quantitative definitions

- Each knowledge topic uses its own valid before/post pairs. Agreement is 4 or 5. Percentage-point change uses unrounded proportions; it is not relative percentage growth or statistical significance.
- Recommendation and intent means include valid zero and exclude missing/unmapped/out-of-range/noninteger values. Coverage is valid answers divided by audience size. Score distributions are withheld when a positive cell or complement is below ten.
- Both post-988 items must be valid to calculate the neutral-on-either measure. A separate below-agreement measure includes disagreement as well as neutral; these must have different labels.
- Students includes anyone with Student membership, counted once. Known non-students requires a recognized non-student membership and excludes anyone with Student membership. Role groups overlap; do not add their totals together.
- `compare_audiences` names both groups, values, valid sample sizes, and evidence IDs. It rejects overlapping groups and returns only pairs of publishable metrics. Resolve its evidence IDs by building evidence for each of its two named audiences.

## Open-ended analysis workflow

Analyze the two fields separately. `codebook.json` is the initial guide with definitions and keyword patterns: valuable explanations/988 knowledge; requested scenarios, pacing, accessibility; no suggested change; unclear; other reviewed content. The old empty `codebook.csv` is not used. This is a starting guide, not an assertion that these are the actual dataset's themes. Refine it after reviewing a documented sample that includes students and non-students in both fields.

1. Run local `suggest_theme_codes` to prepare pending coding suggestions. No matching keyword does not mean unclear, and negation or praise can trigger a false suggestion. Suggestions contain IDs/fingerprints rather than text and must remain private.
2. A human checks the original response locally, corrects theme IDs, and supplies a safe paraphrase. `reviewer_status="approved"` certifies meaning and privacy review. Language/translation uncertainties stay pending. Include response ID, source field, exact-content SHA-256 fingerprint, approved paraphrase, and theme IDs in the review JSON. See the synthetic review records for the format.
3. `summarize_themes` matches approvals by current response ID + field + fingerprint. It uses current response roles, not role claims in the review file. Modified comments, unknown/wrong-field theme IDs, and missing paraphrases do not inherit approval. Duplicate review entries fail for local resolution.
4. A response may have multiple substantive themes, each counted once per field. Explicit no-change and unclear codes must stand alone. Blank comments are missing, not no-change. No-change, unclear, and other content have distinct codes/categories.
5. Publish approved theme counts alongside reviewed denominator and eligible nonblank coverage. Reviewed samples are not automatically representative; percentages refer to reviewed comments. With no approvals, the result has no themes. No raw text or paraphrase is returned in the aggregate output.

Presidio/other identifier screening and manual privacy review belong before approval; they are not implemented here. Private suggestions do not bypass that process. No semantic clustering, sentiment classifier, automated theme approval, or chatbot is included in this branch.

## Privacy and interpretation

Quantitative results require at least ten valid respondents, and subgroup results are withheld if their remaining valid complement contains one to nine people. Ten to twenty-nine is labeled limited. Entire small audiences return no counts or themes. Theme positives, negative complements, and related reviewed coverage are withheld when subtraction could expose one to nine responses. Coverage breakdowns are withheld together if a positive missing/pending/reviewed cell is too small. These conservative rules can suppress otherwise useful detail.

The output is intended for one audience at a time. These stateless functions cannot prevent combining old outputs, arbitrary cohort subsets, or many overlapping releases. Frontend/export owners must enforce current dataset/audience lineage and control repeated releases. Do not present the mock UI as evidence that these protections are integrated.

All findings are descriptive retrospective self-report. Do not infer causation, score stagnation over time, retention, or a theme/intent correlation from separate aggregate counts. Recommendations belong to `report.py` and are absent from the result.

## Run and verify

Windows PowerShell (use `venv` instead of `.venv` if that is your installed environment):

```powershell
.\.venv\Scripts\python.exe -m pytest checks -q
.\.venv\Scripts\python.exe analysis.py examples/synthetic_survey.xlsx --audience Students --reviews examples/reviewed_comments.json
```

On macOS/Linux replace the executable with `.venv/bin/python`. Without `--reviews`, comments remain pending and no themes are released. The command prints aggregate JSON to the terminal and writes no files. For private inputs, do not redirect it into a shared folder without reviewing the aggregate release.

Output keys: `dataset_key`, `audience`, `status`, `quantitative_evidence`, `qualitative_themes`, `coverage`, `limitations`. There are no action IDs or recommended pilots. A withheld/empty audience intentionally does not distinguish its exact size.

Local source verification reproduced all three original agreement count pairs at n=1,299, recommendation means 7.22 (n=1,051 students) versus 9.38 (n=215 known non-students), and intent coverage 293/1,299. Real responses were not committed. These checks are implementation verification, not independent teammate signoff.
