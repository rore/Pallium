import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const html = readFileSync(process.argv[2], 'utf8');
const helperStart = html.indexOf('function _hhKv(k, v) {');
const helperEnd = html.indexOf('function renderEffectivenessReports', helperStart);
const renderStart = html.indexOf('function renderReuseCalibration(entry) {');
const renderEnd = html.indexOf('// ──────────────────────────────────────────────────', renderStart);
assert.ok(helperStart >= 0 && helperEnd > helperStart && renderStart >= 0 && renderEnd > renderStart);

function dashboardElement() {
  let innerHTML = '';
  let detailOpen = false;
  return {
    get innerHTML() { return innerHTML; },
    set innerHTML(value) { innerHTML = value; detailOpen = false; },
    querySelector(selector) {
      if (selector !== 'details' || !innerHTML.includes('<details')) return null;
      return {
        get open() { return detailOpen; },
        set open(value) { detailOpen = Boolean(value); },
      };
    },
  };
}
const elements = { 'hh-reuse-kpi': dashboardElement(), 'hh-rdh': dashboardElement(), 'hh-fidelity': dashboardElement() };
const document = { getElementById: id => elements[id] || null };
const dependencies = `
function escapeHtml(str) { return str == null ? '' : String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
function fmtNum(n) { return n == null ? '—' : n.toLocaleString(); }
function _hhStamp() { return ''; }
function formatDateWithRelative(value) { return String(value); }
`;
const source = dependencies + html.slice(helperStart, helperEnd) + html.slice(renderStart, renderEnd) +
  'return { renderHistoricalLookupUsefulness, renderReuseCalibration, renderRawDerivedHybrid, renderDerivationFidelity };';
const { renderHistoricalLookupUsefulness, renderReuseCalibration, renderRawDerivedHybrid, renderDerivationFidelity } = new Function('document', source)(document);

renderReuseCalibration({
  available: true,
  report: { judge_vs_gold: { kappa: 0.75, threshold: 0.70, n: 12, calibrated: true } },
});
assert.match(elements['hh-reuse-kpi'].innerHTML, /do not know yet whether pulled-up history helped/i);
assert.match(elements['hh-reuse-kpi'].innerHTML, /does not show that Pallium improved real work/);
assert.match(elements['hh-reuse-kpi'].innerHTML, /ready for cautious use/);
elements['hh-reuse-kpi'].querySelector('details').open = true;
renderReuseCalibration({
  available: true,
  report: { judge_vs_gold: { kappa: 0.75, threshold: 0.70, n: 12, calibrated: true } },
});
assert.equal(elements['hh-reuse-kpi'].querySelector('details').open, true);

renderHistoricalLookupUsefulness(
  { available: true, last_modified: '2026-02-02', report: {
    window: { since: '2026-01-01', until: '2026-01-31' }, eligibility_n: 12,
    n_eligible_sessions: 9, n_reuse_events: 4, calibration: { kappa: null, n: 0, threshold: null, calibrated: null },
    rungs: { influence: { numerator: 2, denominator: 9, wilson_95: { low: 0.08, high: 0.49 } } },
  } },
  { available: true, last_modified: '2026-02-03', report: {
    n_lookups: 10, n_sampled: 4, n_abandoned: 3, n_labels_written: 6, n_judge_failures: 1,
    seeds: ['rater-a', 'rater-b'], direction_split: { user_directed: 2, agent_decided: 1 },
    cohens_kappa: { kappa: 0.72, rater_pair: 'rater-a/rater-b', n_double_rated: 3 },
    judge_vs_gold: { kappa: 0.81, n: 3, threshold: 0.6, calibrated: true },
  } },
);
assert.match(elements['hh-reuse-kpi'].innerHTML, /eligible sessions[^]*9/);
assert.match(elements['hh-reuse-kpi'].innerHTML, /eligibility threshold[^]*12/);
assert.match(elements['hh-reuse-kpi'].innerHTML, /missing rating slots[^]*1/);
assert.match(elements['hh-reuse-kpi'].innerHTML, /Wilson 95% 0.08–0.49/);
assert.match(elements['hh-reuse-kpi'].innerHTML, /rater-a\/rater-b[^]*3 double-rated/);
assert.match(elements['hh-reuse-kpi'].innerHTML, /reference-set agreement[^]*0.81[^]*3 examples[^]*threshold 0.6/);
assert.match(elements['hh-reuse-kpi'].innerHTML, /validated for cautious interpretation/);
assert.match(elements['hh-reuse-kpi'].innerHTML, /incomplete/i);
renderReuseCalibration({ available: false });
assert.match(elements['hh-reuse-kpi'].innerHTML, /That check has not been run yet/);
renderReuseCalibration({
  available: true,
  report: { judge_vs_gold: { calibrated: false } },
});
assert.match(elements['hh-reuse-kpi'].innerHTML, /not reliable enough yet/);
renderReuseCalibration({ available: true, report: { judge_vs_gold: {} } });
assert.match(elements['hh-reuse-kpi'].innerHTML, /still in progress/);
renderRawDerivedHybrid({
  available: true,
  report: {
    query_count: 28,
    candidate_recovery_aggregate: {
      n_no_evidence: 68,
      counts: { both: 37, raw_only: 279, derived_only: 55, neither: 0 },
    },
    queries: [{ representation_quality: { objects: [{ representation: null }] } }],
  },
});
assert.match(elements['hh-rdh'].innerHTML, /85% of comparisons/);
assert.match(elements['hh-rdh'].innerHTML, /found it in 25%/);
assert.match(elements['hh-rdh'].innerHTML, /recovered more linked evidence/);
assert.match(elements['hh-rdh'].innerHTML, /does not tell us whether either version improved/);
assert.match(elements['hh-rdh'].innerHTML, /Accuracy was not checked in this run/);

renderRawDerivedHybrid({
  available: true,
  report: { candidate_recovery_aggregate: { counts: { raw_only: 1, derived_only: 2 } } },
});
assert.match(elements['hh-rdh'].innerHTML, /compact memories recovered more linked evidence/);
assert.match(elements['hh-rdh'].innerHTML, /number of past lookups was not recorded/);
assert.doesNotMatch(elements['hh-rdh'].innerHTML, /covered 0 past lookups/);

renderRawDerivedHybrid({
  available: true,
  report: { query_count: 2, candidate_recovery_aggregate: { counts: { raw_only: 1, derived_only: 1 } } },
});
assert.match(elements['hh-rdh'].innerHTML, /both recovered the same amount of linked evidence/i);
assert.match(elements['hh-rdh'].innerHTML, /covered 2 past lookups/);
elements['hh-rdh'].querySelector('details').open = true;
renderRawDerivedHybrid({
  available: true,
  report: { query_count: 2, candidate_recovery_aggregate: { counts: { raw_only: 1, derived_only: 1 } } },
});
assert.equal(elements['hh-rdh'].querySelector('details').open, true);

renderDerivationFidelity({
  available: true,
  report: {
    coverage: {
      item_extraction: { coverage_rate: 0.44181577999279453, processed_denominator: 8327 },
      thread_aggregation: { coverage_rate: 0.6166134185303515, processed_denominator: 313 },
    },
    fidelity: { judged_object_count: 25, objects: [{ fidelity: null }] },
  },
});
assert.match(elements['hh-fidelity'].innerHTML, /44% of processed captured items/);
assert.match(elements['hh-fidelity'].innerHTML, /62% of processed conversations/);
assert.match(elements['hh-fidelity'].innerHTML, /This is not a success rate/);
assert.match(elements['hh-fidelity'].innerHTML, /Accuracy was not checked in this run/);

renderRawDerivedHybrid({ available: false });
assert.match(elements['hh-rdh'].innerHTML, /No comparison has been run yet/);
renderDerivationFidelity({ available: false });
assert.match(elements['hh-fidelity'].innerHTML, /No coverage or accuracy check has been run yet/);
renderDerivationFidelity({
  available: true,
  report: {
    coverage: { item_extraction: { coverage_rate: null }, thread_aggregation: { coverage_rate: null } },
    fidelity: { objects: [] },
  },
});
assert.match(elements['hh-fidelity'].innerHTML, /no coverage result yet/i);
assert.doesNotMatch(elements['hh-fidelity'].innerHTML, /0% of processed/);

renderRawDerivedHybrid({
  available: true,
  report: {
    query_count: 1,
    candidate_recovery_aggregate: { counts: { both: 1 } },
    queries: [{ representation_quality: { objects: [
      { representation: { n_samples: 1, misleading: true, usability_mean: 0.75 } },
      { representation: { n_samples: 1, misleading: null, usability_mean: null } },
    ] } }],
  },
});
assert.match(elements['hh-rdh'].innerHTML, /100% of 1 scored memories were marked misleading/);
assert.match(elements['hh-rdh'].innerHTML, /average usefulness was 75%/);
assert.doesNotMatch(elements['hh-rdh'].innerHTML, /50%.*misleading/);

renderDerivationFidelity({
  available: true,
  report: {
    coverage: { item_extraction: { coverage_rate: 0.5 }, thread_aggregation: { coverage_rate: 0.5 } },
    fidelity: { judged_object_count: 2, objects: [
      { fidelity: { n_samples: 1, completeness_mean: 0.8, unsupported_by_context: true, drift: false } },
      { fidelity: { n_samples: 1, completeness_mean: null, unsupported_by_context: null, drift: null } },
    ] },
  },
});
assert.match(elements['hh-fidelity'].innerHTML, /Average completeness was 80%/);
assert.match(elements['hh-fidelity'].innerHTML, /100% of 1 scored memories included unsupported claims/);
assert.match(elements['hh-fidelity'].innerHTML, /0% of 1 scored memories drifted/);
assert.doesNotMatch(elements['hh-fidelity'].innerHTML, /50% of 2 scored memories included unsupported claims/);

const operationalStart = html.indexOf('function renderOperationalSummary() {');
const operationalEnd = html.indexOf('function renderRelay(data) {', operationalStart);
assert.ok(operationalStart >= 0 && operationalEnd > operationalStart);

function operationalElement() {
  return { className: '', hidden: true, innerHTML: '', open: true, textContent: '' };
}
const operationalElements = Object.fromEntries([
  'operational-summary', 'ops-title', 'ops-updated', 'ops-systems', 'ops-issues', 'health-badge',
].map(id => [id, operationalElement()]));
const operationalDocument = { getElementById: id => operationalElements[id] };
const operationalSource = `
let _statusData = null, _queueData = null, _relayData = null;
function escapeHtml(str) { return str == null ? '' : String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
function fmtNum(n) { return n == null ? '—' : n.toLocaleString(); }
function formatUptime(s) { return Math.floor(s) + 's'; }
` + html.slice(operationalStart, operationalEnd) + `
return function render(status, queue, relay) {
  _statusData = status; _queueData = queue; _relayData = relay;
  renderOperationalSummary();
}
`;
const renderOperational = new Function('document', operationalSource)(operationalDocument);
const cleanStatus = {
  ingestion: { status: 'ok', issues: [] }, embedding_provider_ok: true,
  vector_expected: true, vector_index_ready: true, pending_items: 0,
};
const cleanQueue = { status_counts_24h: { failed: 0 } };
const cleanRelay = { status: 'idle', deliveries: { expired_last_24h: 0 } };
renderOperational(cleanStatus, cleanQueue, cleanRelay);
assert.equal(operationalElements['operational-summary'].hidden, false);
assert.equal(operationalElements['ops-title'].textContent, 'Pallium is operating normally');

operationalElements['operational-summary'].open = false;
renderOperational(cleanStatus, cleanQueue, {
  status: 'attention', deliveries: { expired_last_24h: 1 },
});
assert.equal(operationalElements['operational-summary'].hidden, false);
assert.equal(operationalElements['operational-summary'].open, false);
assert.match(operationalElements['ops-title'].textContent, /warnings/i);

renderOperational({ ...cleanStatus, ingestion: { status: 'degraded', issues: [{}] } }, cleanQueue, cleanRelay);
assert.equal(operationalElements['operational-summary'].hidden, false);
assert.equal(operationalElements['operational-summary'].open, false);
assert.equal(operationalElements['ops-title'].textContent, 'Pallium needs attention');


const reuseClassStart = html.indexOf('function reuseClassification(');
const reuseClassEnd = html.indexOf('function reuseEventParams(', reuseClassStart);
assert.ok(reuseClassStart >= 0 && reuseClassEnd > reuseClassStart);
const reuseClassification = new Function(`${html.slice(reuseClassStart, reuseClassEnd)}; return reuseClassification;`)();
assert.equal(reuseClassification({ rung: null }), 'no genuine reuse');
assert.equal(reuseClassification({ rung: 'downstream' }), 'downstream');
assert.equal(reuseClassification({}), 'unlabelled');

const relaySelectionStart = html.indexOf('function selectRelayNode(');
const relaySelectionEnd = html.indexOf('function renderMap(', relaySelectionStart);
assert.ok(relaySelectionStart >= 0 && relaySelectionEnd > relaySelectionStart);
const relaySelection = new Function(`
  let _relay = { selected: 'old', pair: ['old', 'pair'], message: 'old-message' };
  let renders = 0;
  function renderRelay() { renders += 1; }
  function relayFocus() {}
  ${html.slice(relaySelectionStart, relaySelectionEnd)}
  return { selectRelayPair, state: () => _relay, renders: () => renders };
`)();
relaySelection.selectRelayPair('sender\u0000literal', 'recipient"quoted');
assert.deepEqual(relaySelection.state().pair, ['sender\u0000literal', 'recipient"quoted']);
assert.equal(relaySelection.state().selected, null);
assert.equal(relaySelection.state().message, null);
assert.equal(relaySelection.renders(), 1);

const pairStart = html.indexOf('function relayPairSummaries(');
const pairEnd = html.indexOf('function selectRelayNode(', pairStart);
assert.ok(pairStart >= 0 && pairEnd > pairStart);
const { relayPairSummaries, relayConnectionSummaries, relayEdgeGeometry } = new Function(`
  function rdeliveries(message) { return message.edges; }
  ${html.slice(pairStart, pairEnd)}
  return { relayPairSummaries, relayConnectionSummaries, relayEdgeGeometry };
`)();
const pairRows = relayPairSummaries([
  { edges: [{ from: 'a', to: 'b', state: 'pending' }, { from: 'a', to: 'c', state: 'delivered' }] },
  { edges: [{ from: 'a', to: 'b', state: 'delivered' }] },
]);
const ab = pairRows.find(row => row.from === 'a' && row.to === 'b');
assert.equal(ab.count, 2);
assert.deepEqual(ab.states, { pending: 1, delivered: 1 });
const connections = relayConnectionSummaries([...pairRows, { from: 'b', to: 'a', count: 3, states: { delivered: 3 } }]);
const abConnection = connections.find(row => row.a === 'a' && row.b === 'b');
assert.equal(abConnection.forward, 2);
assert.equal(abConnection.backward, 3);
assert.deepEqual(abConnection.forwardStates, { pending: 1, delivered: 1 });
assert.deepEqual(abConnection.backwardStates, { delivered: 3 });
assert.doesNotMatch(relayEdgeGeometry({ x: 50, y: 50 }, { x: 50, y: 50 }, false).path, /NaN/);

const ownerResetStart = html.indexOf('function resetRelayData(');
const ownerResetEnd = html.indexOf('function relaySessionParams(', ownerResetStart);
const ownerLoadStart = html.indexOf('async function loadMoreRelayOwners(');
const ownerLoadEnd = html.indexOf('function relayOwnerOverview(', ownerLoadStart);
assert.ok(ownerResetStart >= 0 && ownerResetEnd > ownerResetStart && ownerLoadStart >= 0 && ownerLoadEnd > ownerLoadStart);
const relayOwnerState = { sessions: [], messages: [], owners: [], generation: 1, ownerNext: 100, ownerLoadKey: null };
const relayOwnerElements = new Map();
const relayOwnerDocument = { getElementById(id) { if (!relayOwnerElements.has(id)) relayOwnerElements.set(id, { textContent: '', innerHTML: '' }); return relayOwnerElements.get(id); } };
let firstOwnerReject;
let ownerRequestCount = 0;
const firstOwnerRequest = new Promise((resolve, reject) => { firstOwnerReject = reject; });
const ownerOverviews = [];
const ownerHarness = new Function('_relay', 'document', 'relayJson', 'relayScopeSnapshot', 'relayOwnerOverview', 'resetRelaySelection', `
  ${html.slice(ownerResetStart, ownerResetEnd)}
  ${html.slice(ownerLoadStart, ownerLoadEnd)}
  return { resetRelayData, loadMoreRelayOwners };
`)(relayOwnerState, relayOwnerDocument, async () => {
  ownerRequestCount++;
  if (ownerRequestCount === 1) return firstOwnerRequest;
  return { owners: [{ actor_ref: 'owner-2' }], has_more: false };
}, () => 'scope', data => ownerOverviews.push(data), () => {});
const staleOwnerLoad = ownerHarness.loadMoreRelayOwners();
assert.ok(relayOwnerState.ownerLoadKey);
relayOwnerState.generation = 2;
ownerHarness.resetRelayData('Refreshing…');
relayOwnerState.ownerNext = 100;
await ownerHarness.loadMoreRelayOwners();
assert.equal(ownerRequestCount, 2);
assert.equal(relayOwnerState.ownerLoadKey, null);
firstOwnerReject(new Error('stale failure'));
await staleOwnerLoad;
assert.equal(relayOwnerState.ownerLoadKey, null);
assert.equal(ownerOverviews.length, 1);

const fitStart = html.indexOf('function relayFitScale(');
const fitEnd = html.indexOf('function zoomRelay(', fitStart);
assert.ok(fitStart >= 0 && fitEnd > fitStart);
const { relayFitScale, relayZoomScale } = new Function(`${html.slice(fitStart, fitEnd)}; return { relayFitScale, relayZoomScale };`)();
const narrowFit = relayFitScale(1100, 680, 382, 440);
assert.ok(narrowFit * 1100 <= 358.001);
assert.ok(narrowFit * 680 <= 416.001);
assert.ok(relayZoomScale(narrowFit, .8) < narrowFit);

assert.doesNotMatch(html, /id="relay-map-tab"|id="relay-messages-tab"/);
assert.doesNotMatch(html, /relay-map-wrap'\)\.style\.display/);
assert.match(html, /Owners keep different people or configurations from sharing Relay names and sessions/);
assert.match(html, /request!==_relay\.generation/);
assert.doesNotMatch(html, /relayActor\.value\s*=\s*_actors\[0\]/);
assert.ok(html.indexOf('id="relay-map-wrap"') < html.indexOf('id="relay-messages"'));
assert.match(html, /data-rfrom=.*data-rto=/);
assert.match(html, /class="edge-line"/);
assert.doesNotMatch(html, /relay-edge(?:\.selected)? path:last-child/);
assert.match(html, /data&&data\.owners&&data\.owners\.length\?data\.owners:_relay\.owners/);
assert.doesNotMatch(html, /<details id="operational-summary"/);
assert.match(html, /Session History source items/);
assert.match(html, /SourceItems are the original prompts, responses, tool results, and notes/);
assert.match(html, /Owner<\/strong> is the person or configuration identity/);
assert.match(html, /Browse or search recorded history/);
assert.match(html, /derivedPanel\.open = derived\.enabled === true/);
assert.ok(html.indexOf("overview.id='overview-panel'") < html.indexOf("relay.id='relay-health-panel'"));
assert.ok(html.indexOf("relay.id='relay-health-panel'") < html.indexOf("history.id='session-history-panel'"));
assert.ok(html.indexOf("history.id='session-history-panel'") < html.indexOf("derived.id='derived-memory-panel'"));
assert.match(html, /source-results-grid/);
assert.match(html, /source-evidence/);
console.log('plain-language dashboard renderers: all cases passed');
