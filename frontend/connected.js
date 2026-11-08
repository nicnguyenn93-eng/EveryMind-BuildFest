/* HTTP/data plumbing for Netra's existing layout. No provider credentials in the browser. */
window.Live = (() => {
  const state = {active: false, file: null, dataset: null, dashboard: null, status: null, reports: new Map()};
  const audiences = {all: 'All respondents', student: 'Students', adult: 'Known non-students'};
  const node = (tag, cls, text) => {
    const e = document.createElement(tag); if (cls) e.className = cls;
    if (text != null) e.textContent = String(text); return e;
  };
  async function api(path, options = {}) {
    const response = await fetch('/api/' + path, {...options, headers: {
      'X-EveryMind-Request': '1', ...(options.headers || {})}});
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === 'string' ? body.detail : 'The local request failed. Check the selected file and try again.');
    }
    return response.json();
  }
  function error(message) {
    const target = document.getElementById('report').hidden ? fileOut : document.getElementById('ctxpills');
    target.append(node('p', 'verdict err', message));
  }
  async function busy(message, work) {
    if (state.processing) return;
    state.processing = true;
    loader.hidden = false; buildBtn.disabled = true;
    loadStep(message, 'Processing on this computer. Gemini requests include statistics and censored comments when requested.', 40);
    try { return await work(); }
    catch (e) { error(e.message); }
    finally { state.processing = false; loader.hidden = true; syncGate(); }
  }
  async function init() {
    const controls = ['pick','file','usedemo','build'].map(id => document.getElementById(id));
    controls.forEach(control => control.disabled = true);
    document.getElementById('lede').textContent = 'Connecting to the local censored-data pipeline…';
    try {
      if (!/^https?:$/.test(location.protocol)) throw new Error('Local server required');
      state.status = await api('status');
      if (state.status.input_policy !== 'censored_comments_v1') throw new Error('Restart the local server to load the current report input policy.');
    } catch {
      document.getElementById('lede').textContent = 'Start or restart the local EveryMind server to use the current report inputs.';
      fileOut.replaceChildren(node('p','verdict err','Run python -m everymind_web from the repository, then open http://127.0.0.1:8000. Historical prepared tables are not substituted for current data.'));
      return;
    }
    controls.forEach(control => control.disabled = false);
    state.active = true;
    document.querySelector('.intake h2').textContent = 'A reading of the post-training survey';
    document.querySelector('.purpose .card li:last-child').textContent =
      'Cleaning and censoring run on this computer through the local API. Gemini receives statistics and censored written responses only when requested.';
    const gets = document.querySelectorAll('.purpose .card:nth-child(3) li');
    gets[0].textContent = 'Current headline figures and findings calculated from the selected censored export.';
    gets[1].textContent = 'An optional Gemini draft with cited evidence, proposed actions, owners and follow-up measures.';
    document.querySelector('.purpose .card:nth-child(2) li:nth-child(2)').textContent = 'John’s ingestion validates required survey headers and language routing before publishing outputs.';
    document.querySelector('.purpose .card:nth-child(2) li:last-child').textContent = 'A SHA-256 of the censored export ties all charts and report requests to an exact processed dataset.';
    document.querySelector('#insights .secthead .muted').textContent = 'Descriptive findings for the current audience and county. Each chart shows its valid denominator. Missing or withheld values are unknown.';
    document.querySelector('footer .wrap').textContent = 'Current verified censored data → local aggregate analysis → optional Gemini draft. Raw → cleaned → censoring checkpoints remain local under private_data. Censored comments are authorized for Gemini; automated redaction is not a human review.';
    document.querySelector('.privacy').textContent =
      'Your upload is saved locally under private_data/raw, then cleaned and censored. Charts use that completed censored export. Respondent IDs stay local. An explicit Gemini request sends aggregate statistics and nonblank censored comments to Google. Generated drafts may quote censored wording; the API key stays on this computer.';
    document.getElementById('usedemo').textContent = 'No export to hand? Use an existing censored dataset instead';
    document.getElementById('lede').textContent =
      'Load a survey export, or choose an existing censored dataset. Every chart, finding and map will use the same selected dataset.';
    document.querySelector('#recs .secthead .muted').textContent =
      'Generate a draft from current statistics and censored written responses. Its scope is the selected audience across all surveyed locations, including when the map is filtered to a county. Proposed actions require review.';
    document.querySelector('#method .card:nth-child(2) ul').replaceChildren(...[
      'Retrospective self-report is descriptive, not causal; before-scores are recalled after training.',
      'This convenience sample does not represent all Maryland residents. The map covers Maryland; totals include other surveyed locations.',
      'Censored comments are sent to Gemini under project authorization without manual approval. Automated redaction can miss identifiers; qualitative interpretations remain drafts.',
      'NPS intervals, correlations, trends and historical robustness results are not calculated by this live adapter.'
    ].map(t => node('li', null, t)));
    AUDIENCES.adult.label = 'Known non-students';
    AUDIENCES.adult.short = 'Known non-students';
    syncGate();
  }
  async function handleFile(file) {
    if (!state.active) return error('Start the local EveryMind server before loading a survey.');
    if (state.processing) return;
    if (!file) return;
    state.file = null; state.dataset = null; state.dashboard = null; SEL.source = null;
    fileOut.replaceChildren();
    if (!/\.(xlsx|csv)$/i.test(file.name) || !file.size || file.size > state.status.max_upload_bytes) {
      error('Choose a nonempty .xlsx or .csv survey export up to 25 MB.'); syncGate(); return;
    }
    // Raw files are checked by John's ingestion, which also handles quoted/multiline CSV.
    state.file = file; SEL.source = 'a new survey export';
    fileOut.append(node('p', 'verdict ok', 'File selected: ' + file.name),
      node('p', 'cap muted', 'Generate the report to run local cleaning → censoring → analysis. The server validates the survey schema.'));
    syncGate();
  }
  async function chooseExisting() {
    if (!state.active) return error('Start the local EveryMind server to load a current censored dataset.');
    await busy('Finding verified censored datasets', async () => {
      const {datasets} = await api('datasets');
      if (!datasets.length) throw new Error('No completed censored dataset found. Load a raw export to process it.');
      const choose = d => {state.dataset = d; state.file = null; state.dashboard = null;
        SEL.source = d.label; syncGate();};
      fileOut.replaceChildren(node('p', 'verdict ok', 'Using an existing censored dataset'));
      const select = node('select'); select.setAttribute('aria-label', 'Existing censored dataset');
      datasets.forEach((d, i) => {const o = node('option', null, `${d.label} · ${d.rows ?? 'withheld'} responses`); o.value = i; select.append(o);});
      select.addEventListener('change', () => choose(datasets[Number(select.value)]));
      fileOut.append(select); choose(datasets[0]);
    });
  }
  async function loadDashboard() {
    state.dashboard = await api(`datasets/${state.dataset.dataset_id}/dashboard?audience=${encodeURIComponent(audiences[SEL.audience])}`);
    if (!state.dashboard.summaries[SEL.county]?.n) SEL.county = ALL;
  }
  async function build() {
    if (!state.active || (!state.file && !state.dataset)) return;
    await busy(state.file ? 'Cleaning and censoring the export' : 'Reading the censored dataset', async () => {
      if (state.file) {
        const body = new FormData(); body.append('file', state.file);
        const job = await api('uploads', {method: 'POST', body});
        let result;
        do {
          await sleep(700); result = await api(`jobs/${job.job_id}`);
          loadStep('Cleaning and censoring the export', result.message, 60);
        } while (result.status === 'processing');
        if (result.status !== 'ready') throw new Error(result.message);
        state.dataset = result.dataset; state.file = null;
      }
      SEL.audience = 'all'; SEL.county = ALL; SEL.source = state.dataset.label;
      await loadDashboard(); render();
      document.getElementById('intake').hidden = true;
      document.getElementById('report').hidden = false;
      document.getElementById('topnav').hidden = false;
      window.scrollTo({top: 0});
    });
  }
  function figure(d, suffix) {return d.quantitative_evidence.find(e => e.evidence_id.endsWith(suffix));}
  function render() {
    if (!state.dashboard) return;
    const d = state.dashboard, S = d.summaries[SEL.county], A = audiences[SEL.audience];
    const where = SEL.county === ALL ? 'All surveyed locations' : SEL.county;
    clear('ctxpills').append(node('b', null, 'This report:'), ...[A, where, `${S.n ?? 'Withheld'} responses`, state.dataset.label].map(t => node('span', 'pill', t)));
    const vc = clear('viewctl');
    function group(label, options, chosen, callback) {
      const box = node('div', 'ctl'); box.append(node('span', 'lab', label));
      options.forEach(o => {const b = node('button', null, o.label); b.type = 'button';
        b.disabled = o.disabled; b.setAttribute('aria-pressed', String(o.key === chosen));
        b.onclick = () => callback(o.key); box.append(b);}); vc.append(box);
    }
    group('Showing', Object.entries(audiences).map(([key, label]) => ({key, label})), SEL.audience, async key => {
      const previous = SEL.audience;
      await busy('Updating the audience', async () => {try {SEL.audience = key; await loadDashboard(); render();} catch(e) {SEL.audience = previous; throw e;}});
    });
    group('In', d.counties.filter(c => c.key === ALL || c.n !== 0).map(c => ({...c, disabled: !c.available})), SEL.county,
      key => {SEL.county = key; render();});
    document.getElementById('glance-title').textContent = `${A} · ${where}`;
    document.getElementById('glance-note').textContent = 'Current verified censored export. All retained rows are included. Groups and valid denominators below the reporting threshold are withheld; 10–29 is a small sample.';
    const C = d.cube.find(r => r.county === SEL.county && r.role === ALL && r.split_dim === 'none');
    const show = (v, format = n0) => v == null ? '—' : format(v);
    const tiles = [
      [show(S.n), 'responses in this group', 'Retained records; quality flags do not automatically exclude rows'],
      [show(S.sessions), 'training sessions', 'Distinct local session keys'],
      [show(C.pct_know_when, pct), 'know when to use 988', 'Agreement after training, among valid paired answers'],
      [show(C.gain_index, v => sgn(v, 2)), 'knowledge gain index', 'Change in mean available before/after items, 1–5 scale'],
      [show(C.nps, sgn), 'NPS', '% rating recommendation 9–10 minus % rating 0–6; no CI calculated'],
      [show(C.n_call == null || !S.n ? null : 100 * C.n_call / S.n, pct), 'answered likelihood to call', `${show(C.n_call)} recorded valid scores; blanks do not establish whether the item was shown`]
    ];
    const th = clear('tiles'); tiles.forEach(([v,l,s]) => {const c=node('div','tile'); c.append(node('div','v num',v),node('div','l',l),node('div','s',s));th.append(c);});
    document.getElementById('insights-title').textContent = `Current findings · ${A} · ${where}`;
    const cards = clear('insights-cards');
    for (const [slug, label] of [['IDENTIFY_CHALLENGES', 'Identify mental health challenges'], ['EXPLAIN_988','Describe 988'], ['WHEN_988','Know when to use 988']]) {
      const pre = figure(S, slug + '_BEFORE'), post = figure(S, slug + '_POST'), change = figure(S, slug + '_CHANGE');
      const c=node('div',slug === 'IDENTIFY_CHALLENGES' ? 'card wide' : 'card'); c.append(node('p','kicker','Knowledge'),node('span','scope',`${A} · ${where}`),node('h3',null,label));
      if (pre && post && change) {
        c.append(node('p',null,`Agreement changed from ${pre.display_value} to ${post.display_value} (${change.display_value}).`));
        const viz=node('div','viz'); barChart(viz,[{name:'Before (recalled)',value:pre.value,label:pre.display_value,tone:'muted'}, {name:'After',value:post.value,label:post.display_value,tone:'green'}],{max:100}); c.append(viz);
        c.append(node('p','foot',`${pre.valid_denominator} valid pairs. ${change.caveat}`));
      } else c.append(node('p',null,'Insufficient publishable paired answers. Withheld values are unknown, not zero.'));
      cards.append(c);
    }
    for (const [suffix,label] of [['RECOMMENDATION_MEAN','Willingness to recommend'],['INTENT_MEAN','Stated likelihood to call 988']]) {
      const item=figure(S,suffix), c=node('div','card'); c.append(node('p','kicker','Recorded scores'), node('h3',null,label),
        node('p',null,item ? `${item.display_value} / 10 among ${item.valid_denominator} valid recorded scores.` : 'Insufficient publishable scores.'),
        node('p','foot',item?.caveat || 'Missing and withheld values are unknown.')); cards.append(c);
    }
    const comments=node('div','card wide');comments.append(node('p','kicker','Written responses'),node('h3',null,'Censored feedback is included'),
      node('p',null,'Gemini receives the nonblank Presidio-censored responses for the selected audience without a manual approval step. Respondent IDs and original-comment files stay local. Interpretations cite opaque comment IDs and remain drafts.')); cards.append(comments);
    renderRecommendations();
    clear('method-list').append(...[
      `Dataset fingerprint: ${d.dataset_key}. Every chart and the explorer use this same censored export.`,
      'Knowledge agreement uses valid before/after pairs, with agree defined as 4 or 5. Changes are percentage points.',
      'The knowledge gain index is the mean difference between each respondent’s available before and after item averages (1–5). Missing items may differ between averages.',
      'NPS is calculated from valid recommendation scores; no confidence interval is calculated here.',
      'Audiences use cleaned role flags. Known non-students means recorded staff/caregiver/community roles without a student flag; it is not an age classification.',
      'Explorer role groups are exclusive; multiple roles are grouped together. Finer splits may be omitted to protect small groups. Rings describe displayed groups only.'
    ].map(t=>node('li',null,t)));
    clear('quality-list').append(...['John’s cleaning and language decisions are preserved. No additional exclusions are applied by this interface.',
      'Empty, skipped, invalid and nonstandard scores retain their source status; only valid scores enter metrics.',
      'Censored responses are eligible for Gemini under project authorization. They are labeled automatically censored, without claiming human privacy review. API and model errors return a labeled template or a clear failure.'
    ].map(t=>node('li',null,t)));
    document.getElementById('map-note').textContent = 'The same censored dataset and selected audience drive this explorer. Click counties to inspect local statistics. Grey means no publishable figure. Fine splits and rings omit protected groups; Gemini always keeps the wider audience scope.';
    document.getElementById('coverage-line').textContent = d.counties.filter(c=>c.key !== ALL && c.available).map(c=>`${c.label}: ${c.n}`).join(' · ') + '. Small groups and secondary cells may be withheld.';
    syncExplorer();
  }
  function renderRecommendations() {
    const host=clear('recs-list'), audience=audiences[SEL.audience];
    const cacheKey=state.dataset.dataset_id+'|'+audience+'|'+state.status.input_policy;
    const scope=node('p','scope wideview',`${audience} · All surveyed locations · county filter does not apply`);
    const actions=node('div','legend'), ai=node('button','btn','Send statistics and censored comments to Google Gemini'), offline=node('button','btn ghost','Generate offline template');
    ai.type=offline.type='button'; actions.append(ai,offline); host.append(scope,actions);
    const output=node('div'); host.append(output);
    const display = envelope => {
      output.replaceChildren(); const r=envelope.report;
      output.append(node('p','kicker',r.mode==='llm' ? `Gemini draft · ${r.model} · review required` : (r.fallback_reason === 'LLM disabled' ? 'Offline template · review required' : 'Gemini draft unavailable · local template')));
      output.append(node('p','cap muted',`${r.censored_comment_count ?? 0} censored written responses in the report input · automatic censoring, no manual review`));
      if (r.provider_attempts) output.append(node('p','cap muted',`Gemini attempts: ${r.provider_attempts}${r.provider_http_status ? ' · final HTTP status: '+r.provider_http_status : ''}`));
      if (r.fallback_reason) output.append(node('p','cap muted',r.fallback_reason));
      if (r.summary.length) r.summary.forEach(finding => {
        output.append(node('p',null,finding.text),node('p','cap muted','Evidence: '+finding.evidence_ids.join(', ')));
      });
      else r.summary_blocks.forEach(t=>output.append(node('p',null,t)));
      r.proposed_recommendations.forEach((rec,i)=>{
        const c=node('div','rec'), body=node('div','body');c.append(node('div','idx',i+1),body);
        body.append(node('h3',null,rec.proposed_action),node('p',null,rec.pilot));
        const dl=node('dl');[['Evidence',rec.evidence_ids.join(', ')],['Owner',rec.proposed_staff_owner],['How we would know',rec.follow_up_measure],['Uncertainty',rec.uncertainty]].forEach(([k,v])=>dl.append(node('dt',null,k),node('dd',null,v)));body.append(dl);output.append(c);
      });
      if (!r.proposed_recommendations.length && r.proposed_action) output.append(node('p',null,`Proposed action: ${r.proposed_action}. Owner: ${r.staff_owner}. Follow-up: ${r.follow_up_measure}.`));
      output.append(node('p','foot',r.limitations));
    };
    const cached = state.reports.get(cacheKey+'|llm') || state.reports.get(cacheKey+'|offline');
    if (cached) display(cached);
    else output.append(node('p','cap muted','No draft generated for this audience yet. The Gemini request includes statistics and censored comments for this audience; respondent IDs stay local.'));
    ai.disabled=!state.status.ai_configured;
    if (ai.disabled) ai.title='Configure the Gemini key on the local server; never enter it into the page.';
    const generate=async use_llm=>{
      ai.disabled=offline.disabled=true;output.replaceChildren(node('p','cap muted',use_llm?'Requesting a Gemini draft… Temporary service errors are retried automatically, up to three attempts within a three-minute generation window.':'Building an offline template…'));
      try {
        const envelope=await api('reports',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset_id:state.dataset.dataset_id,audience,expected_dataset_key:state.dashboard.dataset_key,input_policy:state.status.input_policy,use_llm})});
        if (envelope.report.mode === 'llm' || !use_llm) state.reports.set(cacheKey+(use_llm?'|llm':'|offline'),envelope);
        display(envelope);
      } catch(e) {output.replaceChildren(node('p','verdict err',e.message));}
      finally {ai.disabled=!state.status.ai_configured;offline.disabled=false;}
    };
    ai.onclick=()=>generate(true);offline.onclick=()=>generate(false);
  }
  function syncExplorer() {
    const frame=document.getElementById('explorer-frame');
    const url=`explorer/explorer_standalone.html?dataset=${state.dataset.dataset_id}&audience=${encodeURIComponent(audiences[SEL.audience])}`;
    document.querySelectorAll('a[href^="explorer/explorer_standalone.html"]').forEach(a=>a.href=url);
    const target=new URL(url,location.href).href;
    if (frame.src !== target) {frame.src=target;return;}
    try {
      const EX=frame.contentWindow.EX;
      if (EX && frame.contentWindow.EXLIVE) EX.set({mcounty:SEL.county,mrole:ALL});
    } catch { /* iframe load handler retries */ }
  }
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== document.getElementById('explorer-frame').contentWindow
      || !['everymind-county','everymind-ready'].includes(event.data?.type) || !state.dashboard
      || event.data.dataset_key !== state.dashboard.dataset_key || event.data.audience !== state.dashboard.audience) return;
    if (event.data.type === 'everymind-ready') {syncExplorer(); return;}
    const county = event.data.county;
    if (county !== SEL.county && state.dashboard.counties.some(c => c.key === county && c.available)) {
      SEL.county = county; render();
    }
  });
  return {state,get active(){return state.active;},get dashboard(){return state.dashboard;},init,handleFile,chooseExisting,build,render,syncExplorer};
})();
