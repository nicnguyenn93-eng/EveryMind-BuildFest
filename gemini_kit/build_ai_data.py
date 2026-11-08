"""Build the aggregate-only data package Gemini will see.

Usage:
  python build_ai_data.py <everymind_survey_clean.csv> <dashboard_data_dir> <out_dir>

Copies the dashboard's summary tables and adds extra breakdowns for the AI to explore.
Every table is aggregated; any group with fewer than MIN_N people is dropped, so no
individual response or small identifiable group leaves your computer.
"""
import sys, shutil, re
from pathlib import Path
import numpy as np, pandas as pd

MIN_N = 10
src, dash_dir, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)

# 1. dashboard tables (gaps.csv holds OUR conclusions and targets -> kept apart for stage 2 only)
DASH_DESC = {
 'headline': 'Overall totals and headline rates for the analysis set (one row).',
 'knowledge': 'Per knowledge item: mean 1-5 score before (recalled after training) and after, mean gain, % agreeing (4-5) before/after, % newly confident (<=3 before, >=4 after), % already confident before.',
 'knowledge_dist': 'Percent of respondents at each agreement level (1 Strongly disagree ... 5 Strongly agree), before and after, per knowledge item.',
 'knowledge_by_audience': 'Mean before/after scores and gain for students vs adults, per knowledge item.',
 'satisfaction': 'Net Promoter Score (NPS = % rating 9-10 minus % rating 0-6 on "would recommend") by group, with 95% bootstrap interval, promoter/passive/detractor shares, mean recommend score and mean knowledge gain index.',
 'county_mix': 'Share of respondents in each Maryland county who were students.',
 'engagement': 'Mean likelihood to call 988 and mean likelihood to recommend, by answer to "The presenter engaged the participants" (1-5). n_call = respondents asked the call question.',
 'drivers': 'Spearman rank correlations between delivery/knowledge measures and the two outcomes (call 988, recommend).',
 'trend': 'By training quarter: respondents, % students, NPS overall/students/adults, mean knowledge gain and after-score, student gain and student before-score (blank where fewer than 20 people).',
 'sessions': 'One row per training session (training date + county) with 10+ responses: size, % students, mean recommend, mean knowledge gain, mean engagement rating, NPS.',
 'themes': 'Keyword-coded themes in open answers for three prompts; pct = share of answers matching the theme; base_n = answers coded. "Not matched by keywords" = no theme matched.',
 'improve_box': 'How respondents used the "How can we improve this training?" box.',
 'intent_gap': 'Among respondents who agree they know when to use 988 AND were asked the call question: % likely (9-10), maybe (7-8), unlikely (0-6) to call 988.',
 'language': 'Spanish speakers (survey in Spanish or answers written in Spanish) vs everyone else: % giving contradictory answers (all "Strongly disagree" on learning yet high recommend/praise), knowledge gain and after-score, % who received the English form.',
 'coverage': 'Whether each question was answered, skipped, or not on the respondent\'s version of the form (the form changed between sessions).',
 'quality': 'Quality flags from data cleaning and whether flagged responses are in the analysis set.',
 'robustness': 'Headline metrics recomputed on all responses, the recommended analysis set, and a strict set. Agreement across columns = robust to cleaning choices.',
}
for f in dash_dir.glob('*.csv'):
    if f.stem == 'gaps':
        shutil.copy(f, out / '_human_gaps.csv'); continue
    df = pd.read_csv(f)
    if f.stem == 'themes': df = df.drop(columns=['example'])   # no respondent wording leaves your computer
    df.to_csv(out / f.name, index=False)
    (out / f'{f.stem}.desc').write_text(DASH_DESC.get(f.stem, ''))

c = pd.read_csv(src)
c = c[c.include_in_analysis].copy()
ITEMS = {'identify': 'Identify mental health challenges', 'describe': 'Describe 988 and how it works', 'when': 'Know when to use 988'}

def nps(s):
    s = s.dropna(); return round(100 * ((s >= 9).mean() - (s <= 6).mean()), 1) if len(s) else np.nan

def save(df, name, desc):
    df.to_csv(out / f'{name}.csv', index=False)
    (out / f'{name}.desc').write_text(desc)
    print(f'{name}: {df.shape}')

# 2. who is in the data
ct = c.groupby(['county', 'role']).size().reset_index(name='n')
save(ct[ct.n >= MIN_N], 'ai_role_by_county', 'Number of respondents for each county and role combination (groups under 10 omitted).')

# 3. call-988 intent by group (only respondents whose form had the question)
rows = []
asked = c[c.call988_0_10.notna()]
for dim in ['audience', 'role', 'county', 'spanish_speaker']:
    for g, d in asked.groupby(dim):
        if len(d) < MIN_N: continue
        s = d.call988_0_10
        rows.append({'dimension': dim, 'group': str(g), 'n': len(d), 'mean_call': round(s.mean(), 2), 'median_call': s.median(),
                     'pct_9_10': round(100 * (s >= 9).mean(), 1), 'pct_0_6': round(100 * (s <= 6).mean(), 1)})
for k, lab in ITEMS.items():
    for v, d in asked.groupby(f'post_{k}_score'):
        if len(d) < MIN_N: continue
        s = d.call988_0_10
        rows.append({'dimension': f'post score: {lab}', 'group': str(int(v)), 'n': len(d), 'mean_call': round(s.mean(), 2), 'median_call': s.median(),
                     'pct_9_10': round(100 * (s >= 9).mean(), 1), 'pct_0_6': round(100 * (s <= 6).mean(), 1)})
save(pd.DataFrame(rows), 'ai_call_intent_by_group',
     'Likelihood to call 988 (0-10) by group, only for the respondents whose form asked it. pct_9_10 = likely; pct_0_6 = unlikely. '
     '"post score" rows split people by their after-training agreement (1-5) with each knowledge item.')

# 4. delivery ratings by audience / county
rows = []
for dim in ['audience', 'county']:
    for g, d in c[c.delivery_status == 'answered'].groupby(dim):
        if len(d) < MIN_N: continue
        r = {'dimension': dim, 'group': g, 'n': len(d)}
        for col, lab in [('deliv_engaged_score', 'engaged'), ('deliv_knew_score', 'knew_subject'), ('deliv_organized_score', 'organized')]:
            r[f'{lab}_mean'] = round(d[col].mean(), 2); r[f'{lab}_pct_agree'] = round(100 * (d[col] >= 4).mean(), 1)
        rows.append(r)
save(pd.DataFrame(rows), 'ai_delivery_by_group', 'Presenter/organization ratings (1-5) by audience and county; pct_agree = share answering 4 or 5.')

# 5. knowledge by role and county
rows = []
for dim in ['role', 'county']:
    for g, d in c.groupby(dim):
        if len(d) < MIN_N: continue
        for k, lab in ITEMS.items():
            rows.append({'dimension': dim, 'group': g, 'item': lab, 'n': len(d), 'pre_mean': round(d[f'pre_{k}_score'].mean(), 2),
                         'post_mean': round(d[f'post_{k}_score'].mean(), 2), 'gain': round(d[f'gain_{k}'].mean(), 2),
                         'post_pct_strongly_agree': round(100 * (d[f'post_{k}_score'] == 5).mean(), 1),
                         'pct_rated_lower_after': round(100 * (d[f'gain_{k}'] < 0).mean(), 1)})
save(pd.DataFrame(rows), 'ai_knowledge_by_group', 'Knowledge self-ratings (1-5) before (recalled) and after training, by role and by county.')

# 6. recommend score distribution by audience
rows = []
for g, d in c.groupby('audience'):
    if len(d) < MIN_N: continue
    vc = d.recommend_0_10.value_counts(normalize=True)
    for v in range(11): rows.append({'audience': g, 'score': v, 'pct': round(100 * vc.get(v, 0), 1)})
save(pd.DataFrame(rows), 'ai_recommend_distribution', 'Distribution of "how likely to recommend" (0-10) by audience, as % of that audience.')

# 7. open-answer themes by audience (counts only - no text)
src_themes = pd.read_csv(dash_dir / 'themes.csv')
import importlib.util
spec = importlib.util.spec_from_file_location('bd', Path(__file__).parent / 'theme_codebook.py')
cb = importlib.util.module_from_spec(spec); spec.loader.exec_module(cb)
rows = []
for qname, mask, col, book in [('Most valuable thing learned', c.learned_has_content, 'learned_english', cb.LEARN),
                               ('Suggestions to improve', c.improve_has_content & ~c.improve_is_question, 'improve_english', cb.IMPROVE),
                               ('Questions asked in the improve box', c.improve_is_question, 'improve_english', cb.QUESTIONS)]:
    for aud in ['Student', 'Adult']:
        t = c[mask & (c.audience == aud)][col].fillna('')
        if len(t) < MIN_N: continue
        for th, pat in book.items():
            m = t.str.contains(pat, case=False, regex=True)
            rows.append({'question': qname, 'audience': aud, 'theme': th, 'n': int(m.sum()), 'pct_of_answers': round(100 * m.mean(), 1), 'base_n': len(t)})
save(pd.DataFrame(rows), 'ai_themes_by_audience', 'Keyword-coded themes in the open answers, split by students and adults. Counts only; one answer can match several themes.')
