# Gemini analysis kit: EveryMind 988 training survey

Asks Google Gemini to analyze the cleaned survey data **on its own**, then compare its conclusions with the human (manual) analysis. Every number Gemini cites is checked automatically against the data.

## What's inside

| File | What it is |
|---|---|
| `run_gemini.py` | Runs the two stages, checks citations, writes the report |
| `prompts/system_prompt.md` | Gemini's role and background: EveryMind, 988, adolescent help-seeking, evaluation methods, and the rules it must follow |
| `prompts/stage1_blind.md` | Stage 1 task: independent analysis, without seeing our conclusions |
| `prompts/stage2_compare.md` | Stage 2 task: compare with the human findings and critique our targets |
| `prompts/worked_examples.md` | Three worked examples (from a made-up CPR training, not this data) showing the citation format, careful wording and confidence calibration expected |
| `prompts/human_findings.md` | Our manual conclusions, shown to Gemini only in stage 2 |
| `data/` | 25 aggregate tables with one-line descriptions (`.desc`). No individual responses, no respondent wording, no groups under 10 people |
| `build_ai_data.py`, `theme_codebook.py` | Rebuild `data/` from a new cleaned survey export |

## Run it

### Use the current censored-analysis payload

The legacy kit reads CSV tables. The new `--payload` adapter accepts `everymind.analysis.v2` JSON and converts only the current payload into in-memory citation tables. It does not mix in the bundled 1,255-response analysis or its human findings. Payload mode defaults to blind stage only; comparison mode is blocked until a current-cohort human comparison is integrated.

From Git Bash at the repository root, inspect the exact request without any API call:

```bash
python cleaned_analysis.py private_data/censoring/72b08ff71ede/censored_72b08ff71ede.csv
python gemini_kit/run_gemini.py \
  --payload private_data/reports/72b08ff71ede/ai_input.json \
  --dry-run --out private_data/reports/72b08ff71ede/gemini_dry_run
```

Use the source key printed by the primary pipeline for a different input. Open `private_data/reports/<key>/gemini_dry_run/prompt_stage1.txt`. Quantitative rows are cited by `evidence_id`; approved theme rows by `source_field` plus `theme_id`. Withheld counts are not restored. Keyword signals remain explicitly exploratory. The current single-audience payload has no county/session/trend/correlation/NPS/robustness tables; the prompt must state those gaps rather than invent them. This is sufficient for a narrower descriptive summary, not all questions the legacy kit can ask.

Approved paraphrases are excluded by default to preserve this kit's aggregate-only/free-account workflow. If privacy-screened approvals exist and the chosen provider/account terms permit that content, explicitly add `--include-approved-comments`; then `approved_comment_evidence` is a citable table keyed by opaque `comment_evidence_id`. Original comments and the private lineage map are never included. The current real-data payload has no approved paraphrases, so it cannot yet support semantic summaries of what respondents meant.

After reviewing the dry run, install `gemini_kit/requirements.txt`, choose a model available to your account using `--model`, configure the key privately, and remove `--dry-run` to make a real call. No live provider/model/account verification is implied by a successful dry run. The supplied default model name has not been verified in this integration. A real run sends data externally and may incur account usage charges.

Citation checks now require one uniquely identified row and the actual supplied numeric value (not the previous 1% tolerance). They validate cited table cells; they do not establish that prose, causal claims, uncited numbers, recommendations, or predictions are correct. Human review and stronger report validation remain necessary.

### Legacy bundled-table workflow

1. Get a free API key at <https://aistudio.google.com/apikey>.
2. Install Python 3.10 or newer, then in this folder:
   ```
   pip install -r requirements.txt
   ```
3. Set the key:
   - Windows (PowerShell): `$env:GEMINI_API_KEY="your-key"`
   - Mac/Linux: `export GEMINI_API_KEY="your-key"`
4. Run:
   ```
   python run_gemini.py --runs 3
   ```
   It takes three to six minutes. Open `results/ai_report.md` when it finishes.

Useful options:
- `--dry-run` writes the exact prompts to `results/` without calling Gemini. Read them first.
- `--runs 3` repeats the independent analysis three times and reports which findings appear every time (recommended; `--runs 1` is faster).
- `--stage blind` runs only the independent analysis; `--stage compare` reuses a saved stage 1.
- `--model gemini-3.5-flash-lite` if the default model is rate-limited or not on your free tier. The default is `gemini-3.6-flash`; check <https://aistudio.google.com/docs/models> for current names.
- `--thinking low|medium|high` sets how long the model reasons (default `high`; ignored by models that don't support it).

## Why it's built this way

- **Blind first, then compare.** If Gemini saw our conclusions first it would tend to repeat them. Stage 1 sees only the data; stage 2 sees both and is told to disagree where the data supports it. Agreement reached independently is stronger evidence than agreement after seeing our answer.
- **Structured output with citations.** Gemini must return JSON in a fixed shape. Every number has to name the table, row, column and value, so the script can check it.
- **Automatic citation check.** `verification.csv` lists each cited number as `verified`, `value mismatch`, `row not found`, `row ambiguous` or `unknown table`. Findings with unverified numbers are flagged in the report. Report this rate in the AI Process Appendix; it's direct evidence that AI output was checked rather than trusted.
- **Worked examples (few-shot prompting).** The system prompt includes three examples: a group difference explained by who attended, a tempting claim held to low confidence because the sample is small, and a recommendation tied to a finding with a measurable target. They come from a **made-up** CPR-training survey with tables named `example_…`, so they teach the format and the caution level without giving Gemini any answers about the real data. A citation to an `example_` table would fail the citation check.
- **Consistency across runs.** AI output varies from run to run. With `--runs 3`, the script groups findings from different runs that cite the same table cells (plain overlap counting, no AI) and labels each one *stable* (every run), *recurring* (two or more runs) or *one-off*. Results are in `consistency.csv` and at the top of the report. In step 2, Gemini is told to weigh stable findings more heavily. Report stable findings as the AI's conclusions and treat one-offs as leads at most.
- **Domain context in the prompt.** The system prompt gives Gemini current 988 facts (including the July 2025 end of the LGBTQ+ "press 3" option, which a participant asked about), adolescent help-seeking research, the Theory of Planned Behavior, the "then-test" bias in retrospective before/after ratings, and safe-messaging rules for writing about suicide.
- **Confidence rules.** Gemini must rate each finding high/moderate/low using stated criteria (sample size, consistency, robustness), and give predictions only at the program level, never about individuals.

## Privacy

On Google's free tier, prompts and responses may be used to improve Google's products and may be read by human reviewers; Google asks users not to send sensitive or personal information there. This kit therefore sends **only aggregate tables**: no row-level data, no open-answer wording, and no group smaller than 10 people. Read `results/prompt_stage1.txt` from a `--dry-run` to see exactly what is sent.

Don't add raw responses or open answers to `data/` while using a free key. Google's API terms also require users to be 18 or older.

## Updating with new survey data

```
python build_ai_data.py path/to/everymind_survey_clean.csv path/to/dashboard_data data
python run_gemini.py
```
The cleaned CSV comes from the cleaning scripts (`clean_survey.py`); the dashboard tables from `build_datasets.py`.
