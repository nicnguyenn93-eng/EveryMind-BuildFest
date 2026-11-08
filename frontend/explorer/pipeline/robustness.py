"""Recompute headline findings on three versions of the data to show they do not depend on cleaning choices.
Usage: python robustness.py out/everymind_survey_clean.csv out/robustness.csv"""
import sys
import numpy as np, pandas as pd

c = pd.read_csv(sys.argv[1])
rng = np.random.default_rng(42)

def nps(s):
    s = s.dropna()
    return 100 * ((s >= 9).mean() - (s <= 6).mean()) if len(s) else np.nan

def nps_ci(s, B=2000):
    s = s.dropna().values
    if len(s) < 10: return (np.nan, np.nan)
    b = [nps(pd.Series(rng.choice(s, len(s)))) for _ in range(B)]
    return tuple(np.percentile(b, [2.5, 97.5]))

sets = {
    'All rows (raw, n=1299)': c,
    'Recommended (include_in_analysis)': c[c.include_in_analysis],
    'Strict (also drops post<pre, >30-day lag, non-standard labels, out-of-area)':
        c[c.include_in_analysis & ~c.flag_post_below_pre & ~c.flag_long_lag & ~c.delivery_nonstandard_label & c.in_md_service_area],
}
rows = []
def add(finding, metric, f):
    r = {'Finding': finding, 'Metric': metric}
    for k, d in sets.items(): r[k] = f(d)
    rows.append(r)

for k, lab in [('identify', 'Identify MH challenges'), ('describe', 'Describe 988'), ('when', 'Know when to use 988')]:
    add('1-2. Knowledge gain by item', f'{lab}: mean gain (1-5 scale)', lambda d, k=k: d[f'gain_{k}'].mean())
    add('1-2. Knowledge gain by item', f'{lab}: % agree after', lambda d, k=k: 100 * d[f'post_{k}_agree'].mean())
    add('1-2. Knowledge gain by item', f'{lab}: % newly confident', lambda d, k=k: 100 * d[f'newly_confident_{k}'].mean())
add('3. Audience drives satisfaction', 'NPS - students', lambda d: nps(d[d.audience == 'Student'].recommend_0_10))
add('3. Audience drives satisfaction', 'NPS - adults', lambda d: nps(d[d.audience == 'Adult'].recommend_0_10))
for cty in ['Anne Arundel', "Prince George's"]:
    add('3. Audience drives satisfaction', f'NPS - {cty} (all)', lambda d, cty=cty: nps(d[d.county == cty].recommend_0_10))
    add('3. Audience drives satisfaction', f'NPS - {cty} students only', lambda d, cty=cty: nps(d[(d.county == cty) & (d.audience == 'Student')].recommend_0_10))
    add('3. Audience drives satisfaction', f'NPS - {cty} adults only', lambda d, cty=cty: nps(d[(d.county == cty) & (d.audience == 'Adult')].recommend_0_10))
add('4. Engagement matters', 'Spearman: presenter engaged vs call-988 likelihood', lambda d: d[['deliv_engaged_score', 'call988_0_10']].corr('spearman').iloc[0, 1])
add('4. Engagement matters', 'Spearman: presenter engaged vs recommend', lambda d: d[['deliv_engaged_score', 'recommend_0_10']].corr('spearman').iloc[0, 1])
add('4. Engagement matters', 'Spearman: pre-knowledge vs recommend', lambda d: d[['pre_knowledge_index', 'recommend_0_10']].corr('spearman').iloc[0, 1])
add('5. Behavioral intent coverage', '% of respondents asked the call-988 item', lambda d: 100 * (d.call988_status != 'not on form').mean())
add('5. Behavioral intent coverage', 'Mean likelihood to call 988 (0-10), where asked', lambda d: d.call988_0_10.mean())
add('6. Spanish speakers', 'n Spanish speakers (expanded definition)', lambda d: d.spanish_speaker.sum())
add('6. Spanish speakers', 'Knowledge gain index - Spanish speakers', lambda d: d[d.spanish_speaker].knowledge_gain_index.mean())
add('6. Spanish speakers', 'Knowledge gain index - others', lambda d: d[~d.spanish_speaker].knowledge_gain_index.mean())
add('6. Spanish speakers', 'Post knowledge index - Spanish speakers', lambda d: d[d.spanish_speaker].post_knowledge_index.mean())
add('6. Spanish speakers', 'Post knowledge index - others', lambda d: d[~d.spanish_speaker].post_knowledge_index.mean())
add('6. Spanish speakers', '% of Spanish speakers flagged for scale confusion (all rows)', lambda d: 100 * c[c.spanish_speaker].flag_scale_confusion.mean())
add('6. Spanish speakers', '% of others flagged for scale confusion (all rows)', lambda d: 100 * c[~c.spanish_speaker].flag_scale_confusion.mean())
add('7. Open text', '% of non-blank "improve" answers that are questions', lambda d: 100 * d.improve_is_question.sum() / d.improve_has_content.sum())
add('Overall', 'Responses in set', lambda d: len(d))
add('Overall', 'Overall NPS', lambda d: nps(d.recommend_0_10))

out = pd.DataFrame(rows)
out.to_csv(sys.argv[2], index=False)
pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 60)
print(out.round(2).to_string())

rec = sets['Recommended (include_in_analysis)']
print('\n95% bootstrap CIs (recommended set)')
for lab, s in [('Students', rec[rec.audience == 'Student'].recommend_0_10), ('Adults', rec[rec.audience == 'Adult'].recommend_0_10),
               ('AA students', rec[(rec.county == 'Anne Arundel') & (rec.audience == 'Student')].recommend_0_10),
               ('PG students', rec[(rec.county == "Prince George's") & (rec.audience == 'Student')].recommend_0_10)]:
    lo, hi = nps_ci(s); print(f'{lab:12s} n={s.notna().sum():4d} NPS={nps(s):6.1f}  CI [{lo:6.1f}, {hi:6.1f}]')
