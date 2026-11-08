"""Aggregate the cleaned survey into small, privacy-safe CSVs for the dashboard.
Usage: python build_datasets.py <everymind_survey_clean.csv> <out_dir>
Only group-level numbers leave this script; open text appears only as short example quotes."""
import sys, re
from pathlib import Path
import numpy as np, pandas as pd

src, out = sys.argv[1], Path(sys.argv[2]); out.mkdir(exist_ok=True)
allc = pd.read_csv(src)
c = allc[allc.include_in_analysis].copy()
rng = np.random.default_rng(7)

def nps(s):
    s = s.dropna(); return 100 * ((s >= 9).mean() - (s <= 6).mean()) if len(s) else np.nan
def ci(s, B=2000):
    s = s.dropna().values
    if len(s) < 10: return (np.nan, np.nan)
    b = [100 * ((x >= 9).mean() - (x <= 6).mean()) for x in (rng.choice(s, len(s)) for _ in range(B))]
    return tuple(np.percentile(b, [2.5, 97.5]))
def save(df, name): df.to_csv(out / f'{name}.csv', index=False); print(name, df.shape)

# ---------- headline ----------
save(pd.DataFrame([{
    'responses_total': len(allc), 'responses_used': len(c), 'sessions': c.session_id.nunique(),
    'first_training': c.training_date.min(), 'last_training': c.training_date.max(),
    'nps_overall': round(nps(c.recommend_0_10), 1),
    'pct_know_when_after': round(100 * c.post_when_agree.mean(), 1),
    'pct_describe_newly_confident': round(100 * c.newly_confident_describe.mean(), 1),
    'pct_call_item_asked': round(100 * (allc.call988_status != 'not on form').mean(), 1),
    'call_item_answered': int(c.call988_0_10.notna().sum()),
    'pct_students': round(100 * (c.audience == 'Student').mean(), 1),
    'spanish_speakers': int(c.spanish_speaker.sum()),
}]), 'headline')

# ---------- knowledge ----------
ITEMS = [('identify', 'Identify mental health challenges'), ('describe', 'Describe 988 and how it works'), ('when', 'Know when to use 988')]
rows = []
for k, lab in ITEMS:
    rows.append({'item': lab, 'pre_mean': round(c[f'pre_{k}_score'].mean(), 2), 'post_mean': round(c[f'post_{k}_score'].mean(), 2),
                 'gain': round(c[f'gain_{k}'].mean(), 2), 'pre_agree_pct': round(100 * c[f'pre_{k}_agree'].mean(), 1),
                 'post_agree_pct': round(100 * c[f'post_{k}_agree'].mean(), 1),
                 'newly_confident_pct': round(100 * c[f'newly_confident_{k}'].mean(), 1),
                 'already_confident_pct': round(100 * (c[f'pre_{k}_score'] >= 4).mean(), 1), 'n': int(c[f'gain_{k}'].notna().sum())})
save(pd.DataFrame(rows), 'knowledge')
LV = {1: 'Strongly disagree', 2: 'Disagree', 3: 'Neutral', 4: 'Agree', 5: 'Strongly agree'}
rows = []
for k, lab in ITEMS:
    for t, tl in [('pre', 'Before'), ('post', 'After')]:
        vc = c[f'{t}_{k}_score'].value_counts(normalize=True)
        for lv, name in LV.items():
            rows.append({'item': lab, 'moment': tl, 'level': lv, 'level_label': name, 'pct': round(100 * vc.get(lv, 0), 1)})
save(pd.DataFrame(rows), 'knowledge_dist')
# knowledge gain by audience
rows = []
for a in ['Student', 'Adult']:
    d = c[c.audience == a]
    for k, lab in ITEMS:
        rows.append({'audience': a, 'item': lab, 'pre_mean': round(d[f'pre_{k}_score'].mean(), 2), 'post_mean': round(d[f'post_{k}_score'].mean(), 2),
                     'gain': round(d[f'gain_{k}'].mean(), 2), 'n': len(d)})
save(pd.DataFrame(rows), 'knowledge_by_audience')

# ---------- satisfaction by group ----------
rows = []
def grp(kind, label, d):
    s = d.recommend_0_10; lo, hi = ci(s)
    rows.append({'kind': kind, 'group': label, 'n': int(s.notna().sum()), 'nps': round(nps(s), 1),
                 'ci_low': round(lo, 1) if lo == lo else None, 'ci_high': round(hi, 1) if hi == hi else None,
                 'promoters_pct': round(100 * (s >= 9).sum() / max(s.notna().sum(), 1), 1),
                 'passives_pct': round(100 * s.between(7, 8).sum() / max(s.notna().sum(), 1), 1),
                 'detractors_pct': round(100 * (s <= 6).sum() / max(s.notna().sum(), 1), 1),
                 'mean_recommend': round(s.mean(), 2), 'gain_index': round(d.knowledge_gain_index.mean(), 2)})
grp('overall', 'Everyone', c)
grp('audience', 'Adults', c[c.audience == 'Adult'])
for r in ['Student', 'School staff', 'Caregiver/parent', 'Community member', 'Multiple roles']: grp('role', r, c[c.role == r])
for cty in ['Anne Arundel', "Prince George's", 'Montgomery', "Queen Anne's"]: grp('county', cty, c[c.county == cty])
for cty in ['Anne Arundel', "Prince George's"]:
    for a in ['Student', 'Adult']: grp('county_audience', f'{cty} · {a}s', c[(c.county == cty) & (c.audience == a)])
save(pd.DataFrame(rows), 'satisfaction')
# audience mix per county (explains the county gap)
mix = c[c.county.isin(['Anne Arundel', "Prince George's", 'Montgomery', "Queen Anne's"])].groupby('county').agg(
    n=('id', 'size'), student_pct=('audience', lambda s: round(100 * (s == 'Student').mean(), 1))).reset_index()
save(mix, 'county_mix')

# ---------- drivers ----------
rows = []
for lv in [1, 2, 3, 4, 5]:
    d = c[c.deliv_engaged_score == lv]
    rows.append({'engaged_level': lv, 'engaged_label': LV[lv], 'n': len(d), 'n_call': int(d.call988_0_10.notna().sum()),
                 'mean_call': round(d.call988_0_10.mean(), 2) if d.call988_0_10.notna().sum() >= 5 else None,
                 'mean_recommend': round(d.recommend_0_10.mean(), 2) if len(d) >= 5 else None})
save(pd.DataFrame(rows), 'engagement')
rows = []
for col, lab in [('deliv_engaged_score', 'Presenter engaged participants'), ('deliv_knew_score', 'Presenter knew the subject'),
                 ('deliv_organized_score', 'Training was well organized'), ('post_knowledge_index', 'Knowledge after training'),
                 ('knowledge_gain_index', 'Knowledge gained'), ('pre_knowledge_index', 'Knowledge before training')]:
    for o, ol in [('call988_0_10', 'Likelihood to call 988'), ('recommend_0_10', 'Likelihood to recommend')]:
        d = c[[col, o]].dropna()
        rows.append({'factor': lab, 'outcome': ol, 'spearman': round(d.corr('spearman').iloc[0, 1], 2), 'n': len(d)})
save(pd.DataFrame(rows), 'drivers')

# ---------- trend ----------
c['quarter'] = pd.PeriodIndex(pd.to_datetime(c.training_date), freq='Q').astype(str)
t = c.dropna(subset=['training_date']).groupby('quarter').agg(
    n=('id', 'size'), student_pct=('audience', lambda s: round(100 * (s == 'Student').mean(), 1)),
    gain_index=('knowledge_gain_index', 'mean'), post_index=('post_knowledge_index', 'mean')).reset_index()
t['nps'] = [round(nps(c[c.quarter == q].recommend_0_10), 1) for q in t.quarter]
t['nps_students'] = [round(nps(c[(c.quarter == q) & (c.audience == 'Student')].recommend_0_10), 1) if ((c.quarter == q) & (c.audience == 'Student')).sum() >= 20 else None for q in t.quarter]
t['nps_adults'] = [round(nps(c[(c.quarter == q) & (c.audience == 'Adult')].recommend_0_10), 1) if ((c.quarter == q) & (c.audience == 'Adult')).sum() >= 20 else None for q in t.quarter]
st = c[c.audience == 'Student'].dropna(subset=['training_date']).groupby('quarter').agg(gain_students=('knowledge_gain_index', 'mean'), pre_students=('pre_knowledge_index', 'mean'), n_students=('id', 'size')).round(2).reset_index()
t = t.merge(st, on='quarter', how='left')
t.loc[t.n_students.fillna(0) < 20, ['gain_students', 'pre_students']] = None
t['gain_index'] = t.gain_index.round(2); t['post_index'] = t.post_index.round(2)
save(t, 'trend')

# ---------- sessions ----------
s = c.groupby('session_id').agg(training_date=('training_date', 'first'), county=('county', 'first'), n=('id', 'size'),
        student_pct=('audience', lambda x: round(100 * (x == 'Student').mean(), 0)),
        mean_recommend=('recommend_0_10', 'mean'), gain_index=('knowledge_gain_index', 'mean'),
        engaged=('deliv_engaged_score', 'mean')).reset_index()
s['nps'] = [round(nps(c[c.session_id == i].recommend_0_10), 1) for i in s.session_id]
s = s[s.n >= 10].copy()
s['audience'] = np.where(s.student_pct >= 80, 'Mostly students', np.where(s.student_pct <= 20, 'Mostly adults', 'Mixed'))
for col in ['mean_recommend', 'gain_index', 'engaged']: s[col] = s[col].round(2)
save(s.sort_values('training_date'), 'sessions')

# ---------- open text themes ----------
LEARN = {
 'Anyone can call, for any reason': r"anyone|any ?one can|everyone|not (?:just|only)|doesn.?t have to|don.?t have to|any reason|anything|no matter|lonely|company|not a crisis|who can call|for someone else|more than suicide|only (?:have to )?call for|any mental health|bad day|several reasons|any (?:kind|type)",
 'How 988 works (call, text, chat)': r"how (?:it|988|the line|the hotline|the service) works?|how to (?:use|call|contact|reach|connect)|\btext|chat|what (?:988|it) is|service work|explained how|wait time",
 'Free, confidential, always open': r"free|confiden|anonym|24/?7|24 hours|any ?time|always (?:available|open)|all times|every day",
 'When to use 988': r"when to (?:use|call|reach)|when (?:you|someone|i|people) (?:should|can|need|are|feel)|overwhelmed",
 'Help exists; you are not alone': r"not alone|help (?:is|exists)|there is help|resource|someone (?:to|who|that|can) (?:talk|listen)|listen|there for|count on|get help|ask for help|receive help|people (?:who|that) can help|there are people|mental health matters",
 'How to help someone else': r"help (?:others|someone|a friend|people|my|them|other)|friend|family|children|son\b|kids|support (?:someone|others)|recommend",
 'Recognizing signs of a crisis': r"sign|recogni|identif|symptom|warning|detect|notice|risk factor|protective|attention to",
 'The difference between 988 and 911': r"911",
 'Facts and statistics': r"statistic|percent|%|number of|rate|#1|reason people call|how many|facts",
}
IMPROVE = {
 'Praise; no change needed': r"good|great|perfect|amazing|nothing to change|fine|well done|keep (?:it|doing|up)|loved|liked|excellent|complete|awesome|helpful|informative|thank|exceptional|exeptional",
 'More interactive and engaging': r"interact|engag|activit|game|fun|boring|hands.?on|discussion|prize|kahoot|involv|participat|speak|ask questions",
 'More depth and content': r"more lessons|more about|learn more|more (?:information|info|detail)|in depth|deeper|further detail",
 'Reach more people': r"more (?:people|schools|families|homes|students|places)|every school|all schools|share|sharing|reach|spread|other students|flier|poster|compañeros|others",
 'More real examples and practice': r"example|stor(?:y|ies)|scenario|real (?:life|situation|world)|practic|demonstrat|role.?play",
 'Visuals and video': r"video|visual|illustrat|picture|slide|graphic",
 'Length and pacing': r"shorter|too long|longer|more time|less time|quick|faster|slower|pace|pressed for time",
 'How to help a friend': r"help (?:my )?friends?|talk with (?:my )?friends|how they can help|help (?:a|my) friend|helpa friend",
 'Language access': r"translat|traslat|language|spanish|español",
}
QUESTIONS = {
 'How a call works and what happens next': r"happen|police|911|track|confiden|anonym|parent|location|send|record|disconnect|de-?escalat|process|handled|wait|limit|how (?:does )?it (?:actually )?work|look like|conversation|calls (?:usually )?go|times you can call|call service|text or chat|warm.?line",
 'Scale and statistics': r"how many|how often|per (?:day|year)|a day|in a day|statistic|number of|rate|percent|saved|success",
 'Who answers and how they are trained': r"who (?:answers|picks|is on|are the|works)|counselor|operator|trained|training do|qualif|staff|work(?:s)? (?:at|for|there)|job|hired|become|volunteer|tired",
 'Mental health and helping someone': r"suicide|self.?harm|depress|anxiety|why do|help (?:a|my|someone|people)|tell (?:someone|people)|friend|signs?|want help|somebody",
 'History and funding': r"start|created|founded|how long|fund|paid|money|cost|been around|invent",
}
PREFERRED_QUOTES = {
 'Anyone can call, for any reason': "You don't have to be an adult to call",
 'How 988 works (call, text, chat)': 'The texting capability and the option to call with someone',
 'Free, confidential, always open': 'The responders will respond 24/7 365/ And they are trained professionals in crisis deescalation.',
 'When to use 988': 'When to call 988 and how to contact them.',
 'Help exists; you are not alone': 'I learned that asking for help is really important.',
 'How to help someone else': "i learned that you can call about a friend's mental health, not just yours",
 'Recognizing signs of a crisis': "I've learned the importance of observing behaviors of friends because there are signs that show if thy need help",
 'The difference between 988 and 911': 'Call 988 for mental issues, call 911 for physical issues',
 'Facts and statistics': 'Only 13% of people know about 988',
 'Praise; no change needed': 'Honestly, nothing! The pacing was great and it was very helpful.',
 'More interactive and engaging': 'Maybe an interactive portion. Like a quick game (Kahoot for example) to engage everyone a little more.',
 'More depth and content': 'I would like to learn more on what the calls are like',
 'Reach more people': 'Being able to reach families who are going through this process.',
 'More real examples and practice': 'Give examples and maybe a youth explaining their experience with 988 or mobile crisis.',
 'Visuals and video': 'Maybe make a video like visual of someone using 988.',
 'Length and pacing': "I wish we weren't pressed for time and we could do more",
 'How to help a friend': 'I want to learn more about being able to help my friends better',
 'Language access': 'having traslators for those who might prefer hearing it in their language.',
 'How a call works and what happens next': 'when will the police be involved',
 'Scale and statistics': 'how many workers/counselors does 988 have?',
 'Who answers and how they are trained': 'How could you become a counselor? Is there a camp/class you could take?',
 'Mental health and helping someone': 'How can I help people use it if needed?',
 'History and funding': 'When was 988 created and who decided to create it?',
}
def themes(texts, book, name):
    rows = []
    hit_any = pd.Series(False, index=texts.index)
    for th, pat in book.items():
        m = texts.fillna('').str.contains(pat, case=False, regex=True); hit_any |= m
        ex = texts[m & texts.str.len().between(25, 140)]
        quote = ex.sample(1, random_state=3).iloc[0] if len(ex) else (texts[m].iloc[0] if m.any() else '')
        pq = PREFERRED_QUOTES.get(th)
        if pq is not None:
            assert (texts[m].str.strip() == pq).any(), f'quote not in theme: {th}'
            quote = pq
        rows.append({'theme': th, 'n': int(m.sum()), 'pct': round(100 * m.mean(), 1), 'example': quote.strip()})
    rows.append({'theme': 'Not matched by keywords', 'n': int((~hit_any).sum()), 'pct': round(100 * (~hit_any).mean(), 1), 'example': ''})
    df = pd.DataFrame(rows); df.insert(0, 'question', name); df['base_n'] = len(texts)
    return df
L = c[c.learned_has_content].learned_english
I = c[c.improve_has_content & ~c.improve_is_question].improve_english
Q = c[c.improve_is_question].improve_english
th = pd.concat([themes(L, LEARN, 'Most valuable thing learned'), themes(I, IMPROVE, 'Suggestions to improve'),
                themes(Q, QUESTIONS, 'Questions asked in the improve box')])
save(th, 'themes')
imp = c.improve_text.notna()
save(pd.DataFrame([
    {'answer_type': 'Left blank', 'n': int((~imp).sum())},
    {'answer_type': 'Non-answer ("nothing", "idk")', 'n': int(c.improve_is_nonanswer.sum())},
    {'answer_type': 'Asked a question', 'n': int(c.improve_is_question.sum())},
    {'answer_type': 'Gave a suggestion or comment', 'n': int((c.improve_has_content & ~c.improve_is_question).sum())},
]), 'improve_box')

# ---------- language access ----------
rows = []
for lab, m in [('Spanish speakers', allc.spanish_speaker), ('Everyone else', ~allc.spanish_speaker)]:
    d = allc[m]; dc = c[c.spanish_speaker == (lab == 'Spanish speakers')]
    rows.append({'group': lab, 'n': len(d), 'scale_confusion_pct': round(100 * d.flag_scale_confusion.mean(), 1),
                 'gain_index': round(dc.knowledge_gain_index.mean(), 2), 'post_index': round(dc.post_knowledge_index.mean(), 2),
                 'english_form_pct': round(100 * (d.lang_ui == 'English').mean(), 1)})
save(pd.DataFrame(rows), 'language')

# ---------- measurement coverage ----------
rows = []
for item, col in [('Likelihood to call 988', 'call988_status'), ('Presenter and organization ratings', 'delivery_status')]:
    vc = allc[col].value_counts()
    for st, lab in [('answered', 'Answered'), ('skipped', 'Skipped'), ('not on form', 'Not on the form')]:
        rows.append({'item': item, 'status': lab, 'n': int(vc.get(st, 0)), 'pct': round(100 * vc.get(st, 0) / len(allc), 1)})
for item, col in [('Recommend score', 'recommend_0_10'), ('Knowledge items', 'post_when_score')]:
    a = int(allc[col].notna().sum())
    rows += [{'item': item, 'status': 'Answered', 'n': a, 'pct': round(100 * a / len(allc), 1)},
             {'item': item, 'status': 'Skipped', 'n': len(allc) - a, 'pct': round(100 * (len(allc) - a) / len(allc), 1)},
             {'item': item, 'status': 'Not on the form', 'n': 0, 'pct': 0.0}]
save(pd.DataFrame(rows), 'coverage')

# ---------- data quality ----------
Q_FLAGS = [('flag_speeder', 'Finished in under 20 seconds', 'Excluded'),
           ('flag_scale_confusion', 'Answers contradict each other (likely misread scale)', 'Excluded'),
           ('flag_possible_duplicate', 'Likely double submission', 'Excluded'),
           ('flag_post_below_pre', 'Rated themselves lower after than before', 'Kept'),
           ('flag_long_lag', 'Survey more than 30 days after training', 'Kept'),
           ('delivery_nonstandard_label', 'Answer recoded from a non-standard label', 'Kept')]
save(pd.DataFrame([{'flag': lab, 'n': int(allc[f].sum()), 'decision': dec} for f, lab, dec in Q_FLAGS]), 'quality')
rob = pd.read_csv(Path(src).parent / 'robustness.csv')
rob.columns = ['finding', 'metric', 'all_rows', 'recommended', 'strict']
save(rob, 'robustness')

# ---------- knowing vs intending (behavioral-intent gap) ----------
asked = c[c.call988_0_10.notna()]
rows = []
for lab, d in [('Everyone', asked), ('Students', asked[asked.audience == 'Student']), ('Adults', asked[asked.audience == 'Adult'])]:
    k = d[d.post_when_agree]
    rows.append({'group': lab, 'n_asked': len(d), 'n_know_when': len(k),
                 'high_pct': round(100 * (k.call988_0_10 >= 9).mean(), 1),
                 'mid_pct': round(100 * k.call988_0_10.between(7, 8).mean(), 1),
                 'low_pct': round(100 * (k.call988_0_10 <= 6).mean(), 1)})
ig = pd.DataFrame(rows); save(ig, 'intent_gap')

# ---------- gaps: current value and proposed target for each ----------
kn = pd.read_csv(out / 'knowledge.csv').set_index('item')
sess = pd.read_csv(out / 'sessions.csv')
ib = pd.read_csv(out / 'improve_box.csv').set_index('answer_type').n
lang = pd.read_csv(out / 'language.csv').set_index('group')
neg_share = round(100 * (sess.nps < 0).mean(), 1)
save(pd.DataFrame([
    {'gap_id': 'intent', 'gap': 'Knowing is not intending', 'kind': 'Behavioral intent', 'priority': 'High', 'effort': 'Medium',
     'metric': '% of people who know when to use 988 who rate their chance of calling 9–10', 'current': ig.high_pct[0], 'target': 65, 'unit': '%', 'n': int(ig.n_know_when[0])},
    {'gap_id': 'students', 'gap': 'Students are not engaged', 'kind': 'Delivery', 'priority': 'High', 'effort': 'Medium',
     'metric': 'Student NPS', 'current': round(nps(c[c.audience == 'Student'].recommend_0_10), 1), 'target': 20, 'unit': 'nps', 'n': int(c[c.audience == 'Student'].recommend_0_10.notna().sum())},
    {'gap_id': 'recognition', 'gap': 'Recognizing a crisis lags', 'kind': 'Knowledge', 'priority': 'High', 'effort': 'Low',
     'metric': 'Average gain on "I can identify mental health challenges" (1–5 scale)', 'current': kn.loc['Identify mental health challenges', 'gain'], 'target': 0.8, 'unit': 'pts', 'n': int(kn.loc['Identify mental health challenges', 'n'])},
    {'gap_id': 'measurement', 'gap': 'The survey misses behavior', 'kind': 'Measurement', 'priority': 'High', 'effort': 'Low',
     'metric': '% of surveys that ask how likely people are to call 988', 'current': round(100 * (allc.call988_status != 'not on form').mean(), 1), 'target': 100, 'unit': '%', 'n': len(allc)},
    {'gap_id': 'questions', 'gap': 'Questions go unanswered', 'kind': 'Knowledge', 'priority': 'Medium', 'effort': 'Low',
     'metric': '% of written feedback that is an unanswered question', 'current': round(100 * ib['Asked a question'] / (ib['Asked a question'] + ib['Gave a suggestion or comment']), 1), 'target': 15, 'unit': '%', 'n': int(ib['Asked a question'] + ib['Gave a suggestion or comment'])},
    {'gap_id': 'language', 'gap': 'Spanish speakers get an English form', 'kind': 'Access', 'priority': 'Medium', 'effort': 'Low',
     'metric': '% of Spanish speakers giving contradictory answers', 'current': lang.loc['Spanish speakers', 'scale_confusion_pct'], 'target': 2, 'unit': '%', 'n': int(lang.loc['Spanish speakers', 'n'])},
    {'gap_id': 'sessions', 'gap': 'Quality varies by session', 'kind': 'Delivery', 'priority': 'Emerging', 'effort': 'Low',
     'metric': '% of sessions (10+ responses) with NPS below 0', 'current': neg_share, 'target': round(neg_share / 2, 0), 'unit': '%', 'n': len(sess)},
]), 'gaps')

# ---------- drill-down cube: any path of county -> role -> (session|quarter|language) ----------
# One row per group at every depth. Metrics are blanked below MIN_SHOW so no number
# for a group that small can be read off the page or downloaded from Sources.
MIN_SHOW, MIN_SOLID = 10, 30
c['quarter_lbl'] = c.quarter.str.replace(r'(\d{4})Q(\d)', r'Q\2 \1', regex=True)
c['language_lbl'] = np.where(c.spanish_speaker, 'Spanish speaker', 'English only')

def metrics(d):
    n = len(d)
    r = {'n': n, 'n_call': int(d.call988_0_10.notna().sum()), 'n_deliv': int(d.deliv_engaged_score.notna().sum()),
         'student_pct': round(100 * (d.audience == 'Student').mean(), 1), 'sessions': d.session_id.nunique()}
    if n < MIN_SHOW:
        return {**r, **{k: None for k in ['nps', 'ci_low', 'ci_high', 'mean_recommend', 'gain_index',
                                          'pct_know_when', 'call_mean', 'engaged_mean']}}
    lo, hi = ci(d.recommend_0_10)
    r.update({'nps': round(nps(d.recommend_0_10), 1), 'ci_low': round(lo, 1) if lo == lo else None,
              'ci_high': round(hi, 1) if hi == hi else None,
              'mean_recommend': round(d.recommend_0_10.mean(), 2),
              'gain_index': round(d.knowledge_gain_index.mean(), 2),
              'pct_know_when': round(100 * d.post_when_agree.mean(), 1),
              'call_mean': round(d.call988_0_10.mean(), 2) if d.call988_0_10.notna().sum() >= MIN_SHOW else None,
              'engaged_mean': round(d.deliv_engaged_score.mean(), 2) if d.deliv_engaged_score.notna().sum() >= MIN_SHOW else None})
    return r

ALL = '(all)'
rows = [{'county': ALL, 'role': ALL, 'split_dim': 'none', 'split_val': 'none', **metrics(c)}]
for cty, d in c.groupby('county'):
    rows.append({'county': cty, 'role': ALL, 'split_dim': 'none', 'split_val': 'none', **metrics(d)})
for rl, d in c.groupby('role'):
    rows.append({'county': ALL, 'role': rl, 'split_dim': 'none', 'split_val': 'none', **metrics(d)})
for (cty, rl), d in c.groupby(['county', 'role']):
    rows.append({'county': cty, 'role': rl, 'split_dim': 'none', 'split_val': 'none', **metrics(d)})
for dim, col in [('session', 'session_id'), ('quarter', 'quarter_lbl'), ('language', 'language_lbl')]:
    for keys, d in c.groupby([col]):
        rows.append({'county': ALL, 'role': ALL, 'split_dim': dim, 'split_val': keys[0], **metrics(d)})
    for (cty, v), d in c.groupby(['county', col]):
        rows.append({'county': cty, 'role': ALL, 'split_dim': dim, 'split_val': v, **metrics(d)})
    for (rl, v), d in c.groupby(['role', col]):
        rows.append({'county': ALL, 'role': rl, 'split_dim': dim, 'split_val': v, **metrics(d)})
    for (cty, rl, v), d in c.groupby(['county', 'role', col]):
        rows.append({'county': cty, 'role': rl, 'split_dim': dim, 'split_val': v, **metrics(d)})
cube = pd.DataFrame(rows)
cube['reliability'] = np.where(cube.n >= MIN_SOLID, 'solid', np.where(cube.n >= MIN_SHOW, 'small sample', 'too few'))
save(cube, 'cube')

# county totals for the map (every Maryland jurisdiction, so gaps are visible)
MD_ALL = ['Allegany', 'Anne Arundel', 'Baltimore', 'Baltimore City', 'Calvert', 'Caroline', 'Carroll', 'Cecil',
          'Charles', 'Dorchester', 'Frederick', 'Garrett', 'Harford', 'Howard', 'Kent', 'Montgomery',
          "Prince George's", "Queen Anne's", 'Somerset', "St. Mary's", 'Talbot', 'Washington', 'Wicomico', 'Worcester']
have = cube[(cube.role == ALL) & (cube.split_dim == 'none')].set_index('county')
save(pd.DataFrame([{'county': m, 'n': int(have.at[m, 'n']) if m in have.index else 0,
                    'sessions': int(have.at[m, 'sessions']) if m in have.index else 0} for m in MD_ALL]), 'md_coverage')
