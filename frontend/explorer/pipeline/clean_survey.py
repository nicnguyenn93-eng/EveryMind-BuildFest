"""
EveryMind 988 Training Survey - cleaning pipeline
Usage:  python clean_survey.py <raw_survey.xlsx> <output_dir> [translations.json]

Principles
  * Never delete a response. Questionable rows are FLAGGED and a recommended
    `include_in_analysis` column is provided, so every finding can be re-run
    with and without them.
  * Never invent answers that were not given. Values are only recovered when the
    respondent's intent is unambiguous (spelling variants, a non-standard label
    for the top of the scale, a training date provable from the same session).
  * Every change is written to the cleaning log with the number of rows affected.
"""
import sys, re, json
from pathlib import Path
import numpy as np
import pandas as pd

RAW_COLS = ['id', 'start', 'end', 'lang_ui', 'role_raw', 'tdate_raw', 'county_raw',
            'post_identify', 'post_describe', 'post_when',
            'pre_identify', 'pre_describe', 'pre_when',
            'deliv_engaged', 'deliv_knew', 'deliv_organized',
            'recommend_0_10', 'call988_0_10', 'learned_raw', 'improve_raw']
KNOW = ['identify', 'describe', 'when']
DELIV = ['deliv_engaged', 'deliv_knew', 'deliv_organized']
LIKERT = {'strongly disagree': 1, 'disagree': 2, 'neither agree nor disagree': 3,
          'neither agree or disagree': 3, 'agree': 4, 'strongly agree': 5}
NONSTANDARD = {'very agree': 5, 'satisfied': 4}   # only appear on delivery items, Apr 2026 form
MD_COUNTIES = {'Anne Arundel', "Prince George's", 'Montgomery', "Queen Anne's"}
NON_ANSWER = re.compile(r"^\W*(nothing( really)?|none|no|nope|na|n/?a|idk|i don.?t know|not sure|"
                        r"no questions?|i have no questions?|i don.?t have any questions?|no se|no sé|"
                        r"nada|no se / idk|\.|-)\W*$", re.I)
ES_WORDS = re.compile(r"\b(que|el|los|las|para|ayuda|ayudar|hay|puedo|muy|bien|todo|personas|con|"
                      r"una|sobre|nada|gracias|más|mas|aprendi|aprendí|como|cuando|numero|número|"
                      r"llamar|niños|familia|nuestros|capacitacion|capacitación|fue|estaba)\b", re.I)
EN_WORDS = re.compile(r"\b(the|and|to|you|can|how|what|is|it|of|when|that|i|call|help)\b", re.I)

log = []
def note(step, detail, n):
    log.append({'Step': len(log) + 1, 'Action': step, 'Detail': detail, 'Rows affected': int(n)})

def clean_str(s):
    if pd.isna(s): return np.nan
    s = str(s).replace('\xa0', ' ').replace('‎', '').strip()
    s = re.sub(r'\s+', ' ', s)
    return s if s else np.nan

def is_spanish(t):
    if pd.isna(t): return False
    es, en = len(ES_WORDS.findall(t)), len(EN_WORDS.findall(t))
    return es >= 2 and es > en or (es >= 1 and en == 0 and len(t.split()) <= 4 and es == len(t.split()) - 0)

def main(raw, outdir, trans_path=None):
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    df = pd.read_excel(raw)
    assert df.shape[1] == 20, f'expected 20 columns, got {df.shape[1]}'
    df.columns = RAW_COLS
    n0 = len(df); note('Load', f'Read {n0} responses x 20 columns', n0)

    # ---------- 1. whitespace / invisible characters ----------
    obj = df.select_dtypes(include=['object', 'string']).columns
    before = df[obj].astype(object).astype(str).values
    for c in obj: df[c] = df[c].map(clean_str)
    note('Strip invisible characters', 'Removed non-breaking spaces, left-to-right marks and extra whitespace '
         'from every text field (e.g. "Strongly agree\\xa0", "Montgomery\\xa0")',
         (before != df[obj].astype(object).astype(str).values).any(axis=1).sum())
    df['lang_ui'] = df['lang_ui'].map(lambda x: 'Spanish' if str(x).lower().startswith('esp') else 'English')

    # ---------- 2. timestamps ----------
    df['survey_start'] = pd.to_datetime(df['start']); df['survey_end'] = pd.to_datetime(df['end'])
    df['duration_sec'] = (df.survey_end - df.survey_start).dt.total_seconds()
    df['survey_date'] = df.survey_start.dt.normalize()

    # ---------- 3. county ----------
    def county(c):
        c = str(c).lower()
        for k, v in [('anne arundel', 'Anne Arundel'), ('prince', "Prince George's"), ('montgomery', 'Montgomery'),
                     ('queen', "Queen Anne's"), ('fairfax', 'Fairfax'), ('harris', 'Harris')]:
            if k in c: return v
        return 'Unknown'
    df['county'] = df.county_raw.map(county)
    note('Standardize county', f'{df.county_raw.nunique()} free-text spellings collapsed to {df.county.nunique()} counties '
         '(e.g. "Montgomery County with NAMI MC" -> Montgomery). Montgomery grows from 28 to 34 usable rows.',
         (df.county_raw != df.county).sum())
    df['state'] = df.county.map(lambda c: 'MD' if c in MD_COUNTIES else {'Fairfax': 'VA', 'Harris': 'TX'}.get(c, ''))
    df['in_md_service_area'] = df.county.isin(MD_COUNTIES)
    note('Flag out-of-area', 'Fairfax (VA) and Harris (TX) kept but flagged in_md_service_area = False', (~df.in_md_service_area).sum())

    # ---------- 4. role (multi-select) ----------
    roles = {'Student': 'is_student', 'School staff member': 'is_school_staff',
             'Caregiver/parent': 'is_caregiver_parent', 'Other (e.g., community member)': 'is_community_member'}
    sets = df.role_raw.map(lambda r: {x.strip() for x in str(r).split(';') if x.strip()})
    for k, col in roles.items(): df[col] = sets.map(lambda s: k in s)
    short = {'Student': 'Student', 'School staff member': 'School staff', 'Caregiver/parent': 'Caregiver/parent',
             'Other (e.g., community member)': 'Community member'}
    df['role'] = sets.map(lambda s: short[next(iter(s))] if len(s) == 1 else 'Multiple roles')
    df['audience'] = np.where(df.role == 'Student', 'Student', np.where(~df.is_student, 'Adult', 'Mixed'))
    note('Standardize role', f'{df.role_raw.nunique()} raw multi-select strings (trailing ";" variants) -> 5 roles + '
         'one TRUE/FALSE column per role + audience (Student / Adult / Mixed)', (df.role_raw.str.endswith(';') | (sets.map(len) > 1)).sum())

    # ---------- 5. training date: parse, fix, recover ----------
    df['training_date'] = pd.to_datetime(df.tdate_raw, errors='coerce')
    df['training_date_status'] = np.where(df.training_date.isna(), 'missing', 'as reported')
    lag = (df.survey_date - df.training_date).dt.days
    bad = df.index[lag < 0]
    for i in bad:   # survey cannot start before the training; look for the same county session that day
        same = df[(df.county == df.at[i, 'county']) & (df.training_date == df.at[i, 'survey_date'])]
        if len(same):
            df.at[i, 'training_date'] = df.at[i, 'survey_date']; df.at[i, 'training_date_status'] = 'corrected'
    note('Correct impossible training date', 'Survey started the day BEFORE the reported training date; set to the '
         'same-county session held on the survey date', (df.training_date_status == 'corrected').sum())
    for i in df.index[df.training_date.isna()]:   # recover from respondents of the same county surveyed within 2 hours
        t, c = df.at[i, 'survey_start'], df.at[i, 'county']
        near = df[(df.county == c) & df.training_date.notna() & ((df.survey_start - t).abs() <= pd.Timedelta('2h'))]
        if len(near) >= 3 and near.training_date.nunique() == 1:
            df.at[i, 'training_date'] = near.training_date.iloc[0]; df.at[i, 'training_date_status'] = 'imputed from session'
    note('Recover missing training date', 'Filled only when >=3 respondents from the same county finished the survey '
         'within 2 hours and all reported the same training date', (df.training_date_status == 'imputed from session').sum())
    note('Leave training date missing', 'No same-session neighbours to recover from', df.training_date.isna().sum())
    df['survey_lag_days'] = (df.survey_date - df.training_date).dt.days
    df['training_month'] = df.training_date.dt.to_period('M').astype(str).replace('NaT', np.nan)
    df['session_id'] = df.training_date.dt.strftime('%Y-%m-%d').fillna('unknown-date') + ' | ' + df.county
    df['session_size'] = df.groupby('session_id').id.transform('size')

    # ---------- 6. Likert -> numbers ----------
    for k in KNOW:
        for t in ['pre', 'post']:
            df[f'{t}_{k}_score'] = df[f'{t}_{k}'].str.lower().map(LIKERT)
    df['delivery_nonstandard_label'] = False
    for c in DELIV:
        low = df[c].str.lower()
        df[c + '_score'] = low.map(LIKERT)
        ns = low.isin(NONSTANDARD)
        df.loc[ns, c + '_score'] = low[ns].map(NONSTANDARD); df.loc[ns, 'delivery_nonstandard_label'] = True
    note('Recode non-standard delivery labels', '"Very agree" -> 5 and "Satisfied" -> 4. These came from a different form '
         'version used in April 2026 (sessions 4/9-4/23). Previously unusable; flagged so they can be excluded in a sensitivity check.',
         df.delivery_nonstandard_label.sum())

    # ---------- 7. derived knowledge metrics ----------
    for k in KNOW:
        df[f'gain_{k}'] = df[f'post_{k}_score'] - df[f'pre_{k}_score']
        df[f'post_{k}_agree'] = df[f'post_{k}_score'] >= 4
        df[f'pre_{k}_agree'] = df[f'pre_{k}_score'] >= 4
        df[f'newly_confident_{k}'] = (df[f'pre_{k}_score'] <= 3) & (df[f'post_{k}_score'] >= 4)
    df['pre_knowledge_index'] = df[[f'pre_{k}_score' for k in KNOW]].mean(axis=1)
    df['post_knowledge_index'] = df[[f'post_{k}_score' for k in KNOW]].mean(axis=1)
    df['knowledge_gain_index'] = df.post_knowledge_index - df.pre_knowledge_index
    df['delivery_index'] = df[[c + '_score' for c in DELIV]].mean(axis=1)
    note('Derive scores', 'Numeric 1-5 scores, per-item gain (post - pre), "agree" (4-5) flags, newly-confident flags, '
         'knowledge indexes and delivery index', n0)

    # ---------- 8. 0-10 items + was-it-asked ----------
    df['recommend_0_10'] = pd.to_numeric(df.recommend_0_10, errors='coerce')
    df['call988_0_10'] = pd.to_numeric(df.call988_0_10, errors='coerce')
    df['nps_group'] = pd.cut(df.recommend_0_10, [-1, 6, 8, 10], labels=['Detractor', 'Passive', 'Promoter']).astype(str).replace('nan', np.nan)
    def asked(col):   # an item was "on the form" for a session if >=50% of that session answered it
        rate = df.groupby('session_id')[col].transform(lambda s: s.notna().mean())
        return rate >= 0.5
    df['call988_asked'] = asked('call988_0_10'); df['delivery_asked'] = asked('deliv_engaged')
    df['call988_status'] = np.select([df.call988_0_10.notna(), df.call988_asked], ['answered', 'skipped'], 'not on form')
    df['delivery_status'] = np.select([df[DELIV].notna().any(axis=1), df.delivery_asked], ['answered', 'skipped'], 'not on form')
    note('Separate "not asked" from "skipped"', 'Call-988 item: ' + ', '.join(f'{k} {v}' for k, v in df.call988_status.value_counts().items())
         + '. These blanks are a survey-version change, NOT non-response, and are not imputed.', (df.call988_status != 'answered').sum())
    note('Separate "not asked" from "skipped"', 'Delivery items: ' + ', '.join(f'{k} {v}' for k, v in df.delivery_status.value_counts().items()),
         (df.delivery_status != 'answered').sum())

    # ---------- 9. open text ----------
    trans = json.loads(Path(trans_path).read_text()) if trans_path and Path(trans_path).exists() else {}
    for f in ['learned', 'improve']:
        t = df[f + '_raw']
        df[f + '_text'] = t
        df[f + '_is_nonanswer'] = t.notna() & t.str.match(NON_ANSWER)
        df[f + '_has_content'] = t.notna() & ~df[f + '_is_nonanswer']
        df[f + '_word_count'] = t.fillna('').str.split().str.len()
        df[f + '_language'] = np.where(t.isna(), '', np.where([f'{i}|{f}' in trans or is_spanish(x) for i, x in zip(df.id, t)], 'Spanish', 'English'))
        df[f + '_english'] = [trans.get(f'{i}|{f}', x if lg != 'Spanish' else np.nan) for i, x, lg in zip(df.id, t, df[f + '_language'])]
        df[f + '_translated'] = [f'{i}|{f}' in trans for i in df.id]
        note(f'Open text: {f}', f'{t.notna().sum()} responses; {df[f + "_is_nonanswer"].sum()} non-answers flagged; '
             f'{(df[f + "_language"] == "Spanish").sum()} Spanish ({df[f + "_translated"].sum()} translated to English)',
             (df[f + '_language'] == 'Spanish').sum())
    df['improve_is_question'] = df.improve_text.fillna('').str.contains(r'\?|^(?:how|what|why|who|when|where|is|are|do|does|can)\b', case=False, regex=True)
    note('Flag questions in improve box', 'Respondents who used "How can we improve" to ask a question - a signal of unanswered content', df.improve_is_question.sum())
    df['spanish_speaker'] = (df.lang_ui == 'Spanish') | (df.learned_language == 'Spanish') | (df.improve_language == 'Spanish')
    note('Identify Spanish speakers', f'Survey-language column shows {(df.lang_ui == "Spanish").sum()}; including people who '
         f'wrote in Spanish on the English form gives {df.spanish_speaker.sum()}', df.spanish_speaker.sum() - (df.lang_ui == 'Spanish').sum())

    # ---------- 10. quality flags ----------
    post = df[[f'post_{k}_score' for k in KNOW]]; allitems = pd.concat([post, df[[f'pre_{k}_score' for k in KNOW]]], axis=1)
    df['flag_speeder'] = df.duration_sec < 20
    df['flag_all_post_strongly_disagree'] = (post == 1).all(axis=1)
    pos_text = df.learned_has_content & ~df.learned_text.fillna('').str.contains(r"didn.?t learn|nothing|nada", case=False)
    df['flag_scale_confusion'] = df.flag_all_post_strongly_disagree & (
        (df.recommend_0_10 >= 8) | (df.delivery_index >= 4.5) | pos_text)
    df['flag_straightline_all_1'] = (allitems == 1).all(axis=1) & (df[[c + '_score' for c in DELIV]].fillna(1) == 1).all(axis=1)
    df['flag_post_below_pre'] = (post.values < df[[f'pre_{k}_score' for k in KNOW]].values).any(axis=1)
    df['flag_long_lag'] = df.survey_lag_days > 30
    content = ['role_raw', 'county_raw'] + [f'{t}_{k}' for t in ['post', 'pre'] for k in KNOW] + DELIV + \
              ['recommend_0_10', 'call988_0_10', 'learned_raw', 'improve_raw']
    srt = df.sort_values('survey_start'); key = srt[content].astype(object).where(srt[content].notna(), '').astype(str).agg('|'.join, axis=1)
    prev_t = srt.groupby(key).survey_start.shift()
    df['flag_possible_duplicate'] = ((srt.survey_start - prev_t) <= pd.Timedelta('10min')).reindex(df.index).fillna(False)
    for f, d in [('flag_speeder', 'Completed in under 20 seconds'),
                 ('flag_all_post_strongly_disagree', '"Strongly disagree" on all three after-training items'),
                 ('flag_scale_confusion', 'All after-training items "Strongly disagree" BUT recommend >=8, delivery >=4.5 or a positive comment - '
                  'contradiction suggests the scale was misread'),
                 ('flag_straightline_all_1', 'Every Likert answer is 1 (Strongly disagree)'),
                 ('flag_post_below_pre', 'Rated knowledge LOWER after training than before on at least one item'),
                 ('flag_long_lag', 'Survey taken more than 30 days after training (recall risk)'),
                 ('flag_possible_duplicate', 'Identical answers to an earlier response from the same session within 10 minutes')]:
        note('Quality flag', f'{f}: {d}', df[f].sum())
    df['include_in_analysis'] = ~(df.flag_speeder | df.flag_scale_confusion | df.flag_possible_duplicate)
    note('Recommended analysis set', 'include_in_analysis = not (speeder OR scale confusion OR possible duplicate). '
         'Other flags are kept for review; nothing is deleted.', df.include_in_analysis.sum())

    # ---------- output ----------
    order = (['id', 'survey_start', 'survey_end', 'duration_sec', 'survey_date', 'training_date', 'training_date_status',
              'survey_lag_days', 'training_month', 'session_id', 'session_size', 'county', 'state', 'in_md_service_area',
              'role', 'audience', 'is_student', 'is_school_staff', 'is_caregiver_parent', 'is_community_member',
              'lang_ui', 'spanish_speaker'] +
             [f'{t}_{k}_score' for k in KNOW for t in ['pre', 'post']] + [f'gain_{k}' for k in KNOW] +
             [f'{t}_{k}_agree' for k in KNOW for t in ['pre', 'post']] + [f'newly_confident_{k}' for k in KNOW] +
             ['pre_knowledge_index', 'post_knowledge_index', 'knowledge_gain_index'] +
             [c + '_score' for c in DELIV] + ['delivery_index', 'delivery_status', 'delivery_nonstandard_label',
              'recommend_0_10', 'nps_group', 'call988_0_10', 'call988_status'] +
             [f'{f}_{s}' for f in ['learned', 'improve'] for s in ['text', 'english', 'language', 'translated', 'is_nonanswer', 'has_content', 'word_count']] +
             ['improve_is_question'] + [c for c in df.columns if c.startswith('flag_')] + ['include_in_analysis'])
    clean = df[order].copy()
    clean.to_csv(outdir / 'everymind_survey_clean.csv', index=False)
    pd.DataFrame(log).to_csv(outdir / 'cleaning_log.csv', index=False)
    return clean, pd.DataFrame(log)

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
