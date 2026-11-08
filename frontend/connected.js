/* Local-API plumbing for the stepper frontend. Live data only; no provider credentials in the browser.
   Globals it relies on (defined by the page script): SEL, DATA, ALL, AUDIENCES, el, clear, go, syncChrome,
   renderCheck, refresh, pzInit, renderActions, setReport, PICKED, RECS. */
window.Live = (() => {
  const state = { active: false, file: null, dataset: null, dashboard: null, status: null, processing: false };
  const AUD = { all: 'All respondents', student: 'Students', adult: 'Known non-students' };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const $ = (id) => document.getElementById(id);

  async function api(path, options = {}) {
    const response = await fetch('/api/' + path, { ...options, headers: { 'X-EveryMind-Request': '1', ...(options.headers || {}) } });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === 'string' ? body.detail : 'The local request failed. Check the selected file and try again.');
    }
    return response.json();
  }
  function say(message, where = $('fileout')) { where.append(el('p', 'verdict err', message)); }
  function loadStep(msg, sub, progress) {
    $('loadmsg').textContent = msg; $('loadsub').textContent = sub || ''; $('loadfill').style.width = progress + '%';
  }
  async function busy(message, work, where) {
    if (state.processing) return false;
    state.processing = true; $('loader').hidden = false;
    loadStep(message, 'Processing on this computer.', 40);
    try { return (await work()) !== false; }
    catch (e) { say(e.message, where); return false; }
    finally { state.processing = false; $('loader').hidden = true; syncChrome(); }
  }

  async function init() {
    const controls = ['pick', 'file', 'usedemo'].map($);
    controls.forEach((c) => { c.disabled = true; });
    try {
      if (!/^https?:$/.test(location.protocol)) throw new Error('local server required');
      state.status = await api('status');
      if (state.status.input_policy !== 'censored_comments_v1') throw new Error('restart the server');
    } catch {
      $('fileout').replaceChildren(el('p', 'verdict err', 'Start the local server: run python -m everymind_web, then open http://127.0.0.1:8000.'));
      return;
    }
    controls.forEach((c) => { c.disabled = false; });
    state.active = true;
    $('gen-ai').disabled = !state.status.ai_configured;
    if ($('gen-ai').disabled) $('gen-ai').title = 'Configure the Gemini key on the local server; never enter it into the page.';
  }

  function useFile(file) {
    if (!/\.(xlsx|csv)$/i.test(file.name) || !file.size || file.size > state.status.max_upload_bytes) throw new Error('Choose a nonempty .xlsx or .csv export up to 25 MB.');
    Object.assign(state, { file, dataset: null, dashboard: null });
  }

  async function chooseExisting() {
    $('fileout').replaceChildren();
    await busy('Finding verified censored datasets', async () => {
      const { datasets } = await api('datasets');
      if (!datasets.length) throw new Error('No completed censored dataset found. Load a raw export to process it.');
      const pick = (d) => { Object.assign(state, { dataset: d, file: null, dashboard: null }); loadSource(d.label, null); };
      const select = el('select'); select.setAttribute('aria-label', 'Existing censored dataset');
      datasets.forEach((d, i) => { const o = el('option', null, `${d.label} · ${d.rows ?? 'withheld'} responses`); o.value = i; select.append(o); });
      const use = el('button', 'btn', 'Use this dataset'); use.type = 'button'; use.onclick = () => pick(datasets[Number(select.value)]);
      $('fileout').append(select, ' ', use);
    });
  }

  async function loadDashboard() {
    state.dashboard = await api(`datasets/${state.dataset.dataset_id}/dashboard?audience=${encodeURIComponent(AUD[SEL.audience])}`);
    if (!(state.dashboard.summaries[SEL.county] || {}).n) SEL.county = ALL;
    DATA.cube = { rows: state.dashboard.cube };
  }
  function resetReport() {
    DATA.report = DATA.payload = undefined; RECS.length = 0; PICKED.clear(); renderActions();
    $('gen-note').textContent = `Scope: ${AUD[SEL.audience]} across all surveyed locations. Gemini receives statistics and automatically censored written responses when requested; the county filter applies to Findings.`;
  }
  function show() { pzInit(); refresh(); }

  /* Run on first entry to Findings: process an uploaded file, then load the dashboard. Resolves true when ready. */
  async function build() {
    if (!state.active || (!state.file && !state.dataset)) return false;
    return busy(state.file ? 'Cleaning and censoring the export' : 'Reading the censored dataset', async () => {
      if (state.file) {
        const body = new FormData(); body.append('file', state.file);
        const job = await api('uploads', { method: 'POST', body });
        let r;
        do { await sleep(700); r = await api(`jobs/${job.job_id}`); loadStep('Cleaning and censoring the export', r.message, 60); } while (r.status === 'processing');
        if (r.status !== 'ready') throw new Error(r.message);
        Object.assign(state, { dataset: r.dataset, file: null });
        SEL.info = null; renderCheck();
      }
      SEL.audience = 'all'; SEL.county = ALL;
      await loadDashboard(); resetReport(); show();
    }, $('check-body'));
  }

  async function setAudience(key) {
    const prev = SEL.audience;
    const ok = await busy('Updating the audience', async () => { SEL.audience = key; await loadDashboard(); resetReport(); show(); });
    if (!ok) { SEL.audience = prev; refresh(); }
  }

  async function generate(useLlm) {
    const note = $('gen-note'), buttons = [$('gen-ai'), $('gen-off')];
    if (!state.dashboard) return;
    const dataset = state.dataset.dataset_id, key = state.dashboard.dataset_key, audience = AUD[SEL.audience];
    buttons.forEach((b) => { b.disabled = true; });
    note.textContent = useLlm ? 'Requesting a Gemini draft… temporary errors are retried up to three times.' : 'Building the offline template…';
    try {
      const envelope = await api('reports', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dataset_id: dataset, audience, expected_dataset_key: key,
          use_llm: useLlm, input_policy: 'censored_comments_v1' }) });
      if (state.dataset?.dataset_id !== dataset || state.dashboard?.dataset_key !== key || AUD[SEL.audience] !== audience) return;
      const r = envelope.report;
      const previous = DATA.report?.report || DATA.report;
      if (useLlm && r.mode !== 'llm' && previous?.mode === 'llm') {
        note.textContent = `${r.fallback_reason || 'Gemini is temporarily unavailable.'} The previous draft for this dataset and audience is retained.`;
        return;
      }
      setReport(envelope, { ...state.dashboard.full_analysis, censored_comment_evidence: envelope.cited_comment_evidence || [] });
      note.textContent = `${envelope.scope} · ${r.censored_comment_count} automatically censored written responses · `
        + (r.mode === 'llm' ? `Gemini draft (${r.model}); staff review required.` : 'Offline template; staff review required.')
        + (r.fallback_reason ? ' ' + r.fallback_reason : '');
    } catch (e) { if (state.dataset?.dataset_id === dataset && AUD[SEL.audience] === audience) note.textContent = e.message; }
    finally { buttons[0].disabled = !state.status.ai_configured; buttons[1].disabled = false; }
  }

  function syncExplorer() {
    const frame = $('explorer-frame');
    const url = `explorer/explorer_standalone.html?dataset=${state.dataset.dataset_id}&audience=${encodeURIComponent(AUD[SEL.audience])}`;
    document.querySelectorAll('a[href^="explorer/explorer_standalone.html"]').forEach((a) => { a.href = url; });
    const target = new URL(url, location.href).href;
    if (frame.src !== target) { frame.src = target; return; }
    try { const EX = frame.contentWindow.EX; if (EX && frame.contentWindow.EXLIVE) EX.set({ mcounty: SEL.county, mrole: ALL }); } catch { /* the load handler retries */ }
  }
  window.addEventListener('message', (event) => {
    const d = state.dashboard;
    if (event.origin !== location.origin || event.source !== $('explorer-frame').contentWindow || !d
      || !['everymind-county', 'everymind-ready'].includes(event.data && event.data.type)
      || event.data.dataset_key !== d.dataset_key || event.data.audience !== d.audience) return;
    if (event.data.type === 'everymind-ready') { syncExplorer(); return; }
    const county = event.data.county;
    if (county !== SEL.county && d.counties.some((c) => c.key === county && c.available)) { SEL.county = county; refresh(); }
  });

  return { state, get active() { return state.active; }, get dashboard() { return state.dashboard; },
    init, useFile, chooseExisting, build, setAudience, generate, syncExplorer };
})();
