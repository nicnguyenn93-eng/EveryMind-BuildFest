/* Contract regressions for the stepper. Runs with node --test; no browser or packages. */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..');
const page = fs.readFileSync(path.join(root, 'src/index_template.html'), 'utf8');
const deck = fs.readFileSync(path.join(root, 'src/analysis.html'), 'utf8');
const plumbing = fs.readFileSync(path.join(root, 'connected.js'), 'utf8');
const between = (text, a, b) => text.slice(text.indexOf(a), text.indexOf(b, text.indexOf(a)));

function deckContext() {
  const context = vm.createContext({DATA: {}, DK: {}, RECS: [], PICKED: new Set(), renderDeck() {}});
  vm.runInContext(between(deck, 'function dkNorm(', '/* Quotes:')
    + between(deck, 'function dkBuild(', 'function dkFace(')
    + between(deck, 'function setReport(', '</script>'), context);
  return context;
}

test('offline service output produces findings and a selectable catalog action', () => {
  const c = deckContext();
  c.response = {scope: 'All surveyed locations · Students', report: {
    mode: 'template', summary: [], summary_blocks: ['A descriptive finding.'], evidence_ids: ['E1'],
    proposed_recommendations: [], proposed_action: 'Catalog action', proposed_action_id: 'A1',
    staff_owner: 'Training Lead', follow_up_measure: 'A follow-up measure', limitations: 'Not causal.'}};
  c.payload = {quantitative_evidence: [{evidence_id: 'E1', value: 75}]};
  vm.runInContext('setReport(response, payload)', c);
  assert.equal(c.RECS.length, 1);
  assert.equal(c.DATA.report.report.summary[0].text, 'A descriptive finding.');
  assert.match(c.DATA.report.report.proposed_recommendations[0].uncertainty, /template suggestion/i);
});

test('comment-only recommendations retain their censored evidence and action', () => {
  const c = deckContext();
  c.response = {report: {mode: 'llm', summary: [{text: 'A qualitative finding.', evidence_ids: ['CC_1']}],
    proposed_recommendations: [{pilot: 'A proposed pilot', evidence_ids: ['CC_1']}], limitations: 'Illustrative.'}};
  c.payload = {censored_comment_evidence: [{comment_evidence_id: 'CC_1', censored_text: 'More practice, <PERSON>.', source_field: 'how_can_we_improve'}]};
  vm.runInContext('setReport(response, payload); cards = dkBuild()', c);
  assert.equal(c.RECS.length, 1);
  assert.equal(c.cards[0].rows[0].text, 'More practice, <PERSON>.');
});

test('missing citation details never silently remove a proposed action', () => {
  const c = deckContext();
  c.response = {report: {mode: 'llm', summary: [], proposed_recommendations: [{pilot: 'Pilot', evidence_ids: ['CC_missing']}], limitations: 'Draft.'}};
  vm.runInContext('setReport(response, {})', c);
  assert.equal(c.RECS.length, 1);
});

test('separate before/after questions retain their own paired charts', () => {
  const rows = ['IDENTIFY','EXPLAIN'].flatMap((q,i) => [
    {evidence_id:q+'_BEFORE',metric_type:'paired_agreement',value:20+i,survey_question:q},
    {evidence_id:q+'_POST',metric_type:'paired_agreement',value:80+i,survey_question:q}]);
  const c = vm.createContext({DK:{map:Object.fromEntries(rows.map(r=>[r.evidence_id,r]))}, rows,
    dkType:r=>r.metric_type,dkTest:()=>({}),dkCols:()=>[],dkLabel:x=>x,dkF:x=>String(x),
    dkDumbbell:(before,after)=>({before,after})});
  vm.runInContext(between(deck, 'function dkCharts(', '/* ---- the deck ---- */')+'result=dkCharts(rows)', c);
  assert.equal(c.result.length, 2);
  assert.equal(c.result[0].node.before, 20);
  assert.equal(c.result[1].node.after, 81);
});

test('pie proportions retain the full denominator and pool suppressed groups', () => {
  const c = vm.createContext({pzTotal: {n: 1299}, PZ_COLORS: ['teal'], PZ_GREY: 'grey'});
  vm.runInContext(between(page, 'function pzSlices(', 'const pzPt'), c);
  c.input = [{label:'A',r:{n:937}}, {label:'B',r:{n:309}}, {label:'C',r:{n:34}}, {label:'Suppressed',r:{n:null}}];
  vm.runInContext('result = pzSlices({pick: () => input})', c);
  const small = c.result.slices.find(x => x.label === 'C');
  assert.equal(small.share, 34/1299);
  const i = c.result.slices.indexOf(small);
  assert.ok(Math.abs(c.result.bounds[i+1]-c.result.bounds[i]-360*34/1299)<1e-10);
  const withheld = c.result.slices.find(x => x.withheld);
  assert.equal(withheld.n, 19);
  assert.equal(c.result.bounds.at(-1), 360);
});

test('imported filenames and model text are rendered literally', () => {
  const c = vm.createContext({document: {createElement: () => ({})}});
  vm.runInContext(between(page, 'const el =', 'const clear =')
    + "result = el('p', null, '<img src=x onerror=alert(1)> <PERSON> & text')", c);
  assert.equal(c.result.textContent, '<img src=x onerror=alert(1)> <PERSON> & text');
  assert.equal(c.result.innerHTML, undefined);
});

function liveContext() {
  const nodes = Object.fromEntries(['gen-note','gen-ai','gen-off','explorer-frame'].map(x => [x, {textContent:'', disabled:false}]));
  const context = vm.createContext({window: {addEventListener() {}},
    document: {getElementById: id => nodes[id], querySelectorAll: () => []},
    SEL: {audience:'all'}, DATA: {}, setReport(...args) {context.reportArgs = args;},
    fetch: async () => await new Promise(resolve => {context.respond = resolve;})});
  vm.runInContext(plumbing, context);
  const live = context.window.Live;
  Object.assign(live.state, {dataset:{dataset_id:'hash'}, dashboard:{dataset_key:'key', full_analysis:{}}, status:{ai_configured:true}});
  return {context, live, nodes};
}

test('a late report cannot overwrite a new audience selection', async () => {
  const {context:c, live} = liveContext();
  const pending = live.generate(true);
  c.SEL.audience = 'student';
  c.respond({ok:true, json: async () => ({report:{mode:'llm'}})});
  await pending;
  assert.equal(c.reportArgs, undefined);
});

test('a transient provider fallback retains an existing successful draft', async () => {
  const {context:c, live, nodes} = liveContext();
  c.DATA.report = {report:{mode:'llm'}};
  const pending = live.generate(true);
  c.respond({ok:true, json: async () => ({report:{mode:'template',fallback_reason:'HTTP 503'}})});
  await pending;
  assert.equal(c.reportArgs, undefined);
  assert.match(nodes['gen-note'].textContent, /previous draft.*retained/);
});
