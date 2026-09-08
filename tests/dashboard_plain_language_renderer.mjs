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

renderOperational(cleanStatus, { status_counts_24h: { failed: 1 } }, cleanRelay);
assert.match(operationalElements['ops-title'].textContent, /warnings/i);
assert.doesNotMatch(operationalElements['ops-title'].textContent, /needs attention/i);

renderOperational({ ...cleanStatus, ingestion: { status: 'degraded', issues: [{}] } }, cleanQueue, cleanRelay);
assert.equal(operationalElements['operational-summary'].hidden, false);
assert.equal(operationalElements['operational-summary'].open, false);
assert.equal(operationalElements['ops-title'].textContent, 'Pallium needs attention');


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
const { relayPairSummaries, relayConnectionSummaries, relayEdgeGeometry, relayLayout, relayPositions, relayClampPoint } = new Function(`
  function rdeliveries(message) { return message.edges; }
  ${html.slice(pairStart, pairEnd)}
  return { relayPairSummaries, relayConnectionSummaries, relayEdgeGeometry, relayLayout, relayPositions, relayClampPoint };
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
const twoNodeLayout = relayLayout(['a', 'b'], []);
assert.equal(twoNodeLayout.positions.a.y, twoNodeLayout.height / 2);
assert.equal(twoNodeLayout.positions.b.y, twoNodeLayout.height / 2);
const tenNodeLayout = relayLayout(Array.from({ length: 10 }, (_, index) => 'n' + index), []);
const tenPositions = Object.values(tenNodeLayout.positions);
for (let i = 0; i < tenPositions.length; i++) for (let j = i + 1; j < tenPositions.length; j++) assert.ok(Math.abs(tenPositions[i].x - tenPositions[j].x) >= 156 || Math.abs(tenPositions[i].y - tenPositions[j].y) >= 68);
const savedPositions = {}, movedNodes = new Set();
relayPositions(['a', 'b'], relayLayout(['a', 'b'], []), savedPositions, movedNodes);
const pagedLayout = relayLayout(['a', 'b', 'c'], []);
relayPositions(['a', 'b', 'c'], pagedLayout, savedPositions, movedNodes);
const pagedPositions = Object.values(pagedLayout.positions);
for (let i = 0; i < pagedPositions.length; i++) for (let j = i + 1; j < pagedPositions.length; j++) assert.ok(Math.abs(pagedPositions[i].x - pagedPositions[j].x) >= 156 || Math.abs(pagedPositions[i].y - pagedPositions[j].y) >= 68);
movedNodes.add('a'); savedPositions.a = { x: 123, y: 123 };
const manualLayout = relayLayout(['a', 'b', 'c', 'd'], []);
relayPositions(['a', 'b', 'c', 'd'], manualLayout, savedPositions, movedNodes);
assert.deepEqual(manualLayout.positions.a, { x: 123, y: 123 });
assert.deepEqual(relayClampPoint({ x: -50, y: 900 }, 760, 430), { x: 78, y: 396 });

const endpointMergeStart = html.indexOf('function rememberRelayEndpoints(');
const endpointMergeEnd = html.indexOf('function relayContainerLabel(', endpointMergeStart);
assert.ok(endpointMergeStart >= 0 && endpointMergeEnd > endpointMergeStart);
const endpointState = { endpointSessions: {} };
const endpointMerge = new Function('state', `
  let _relay = state;
  function rf(value, names, fallback = 'unknown') { for (const name of names) if (value && value[name] != null && value[name] !== '') return String(value[name]); return fallback; }
  function rid(message, side) { return rf(message, side === 'from' ? ['sender_endpoint_id'] : ['recipient_endpoint_id']); }
  ${html.slice(endpointMergeStart, endpointMergeEnd)}
  return rememberRelayEndpoints;
`)(endpointState);
endpointMerge({
  endpoint_sessions: [{ id: 'known', runtime: 'codex', session_ref: 'one' }],
  messages: [{ sender_endpoint_id: 'known', actor_ref: 'owner', deliveries: [{ recipient_endpoint_id: 'paged', recipient_runtime: 'claude-code', recipient_session_ref: 'two', recipient_container_ref: 'workspace' }] }],
});
assert.equal(endpointState.endpointSessions.known.session_ref, 'one');
assert.equal(endpointState.endpointSessions.paged.session_ref, 'two');
assert.doesNotMatch(html, /Unresolved session/);
assert.match(html, /if\(session\._snapshot\).*name changes are disabled/);
const visibleSessionsStart = html.indexOf('function rsessionName(');
const visibleSessionsEnd = html.indexOf('function renderRelaySessions(', visibleSessionsStart);
const visibleSessions = new Function('state', 'search', `
  let _relay = state;
  function scoped() { return search; }
  function rf(value, names, fallback = 'unknown') { for (const name of names) if (value && value[name] != null && value[name] !== '') return String(value[name]); return fallback; }
  function rid(message, side) { return rf(message, side === 'from' ? ['sender_endpoint_id'] : ['recipient_endpoint_id']); }
  ${html.slice(visibleSessionsStart, visibleSessionsEnd)}
  return relayVisibleSessions();
`)({
  sessions: [{ id: 'known', runtime: 'codex', session_ref: 'one' }],
  endpointSessions: endpointState.endpointSessions,
  messages: [{ sender_endpoint_id: 'known', deliveries: [{ recipient_endpoint_id: 'paged', state: 'delivered' }] }],
  showAllSessions: false,
}, 'two');
assert.deepEqual(visibleSessions.map(session => session.id), ['paged']);
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

assert.match(html, /request!==_relay\.generation/);
assert.doesNotMatch(html, /id="relay-actor-filter"/);
assert.ok(html.indexOf('id="relay-map-wrap"') < html.indexOf('id="relay-messages"'));
assert.match(html, /data-rfrom=.*data-rto=/);
assert.match(html, /class="edge-line"/);
assert.doesNotMatch(html, /relay-edge(?:\.selected)? path:last-child/);

assert.doesNotMatch(html, /<details id="operational-summary"/);
assert.match(html, /Session History source items/);
assert.match(html, /SourceItems are the original prompts, responses, tool results, and notes/);
assert.match(html, /Type to narrow the workspace list/);
assert.match(html, /Browse or search recorded history/);
assert.match(html, /derivedPanel\.open = derived\.enabled === true/);
assert.ok(html.indexOf("overview.id='overview-panel'") < html.indexOf("relay.id='relay-health-panel'"));
assert.ok(html.indexOf("relay.id='relay-health-panel'") < html.indexOf("history.id='session-history-panel'"));
assert.ok(html.indexOf("history.id='session-history-panel'") < html.indexOf("derived.id='derived-memory-panel'"));
assert.match(html, /source-results-grid/);
assert.match(html, /source-divider/);
assert.doesNotMatch(html, /Open Relay workspace/);
assert.match(html, /data-roi-enabled="false"/);
assert.match(html, /align-items:start/);
assert.match(html, /relay-map-hint[^>]*>Drag background to pan · drag boxes to arrange/);
assert.match(html, /overflow:hidden[^}]*cursor:grab/);
assert.match(html, /mapFitPending/);
assert.match(html, /nodePositions/);
assert.match(html, /onpointerdown=event=>/);
assert.match(html, /relayUpdateMapPositions\(svg\)/);
assert.match(html, /point=\{\.\.\.\(_relay\.nodePositions\[item\.dataset\.rnode\]/);
assert.doesNotMatch(html, /_relay\.nodePositions\[dragging\.id\][^;]*;renderMap\(messages,false\)/);
assert.match(html, /if\(_relay\.message\).*relay-session-detail/);
assert.match(html, /class=\"time\">.*time/);
const sourceRaceElements = Object.fromEntries([
  'source-container', 'source-actor', 'source-query', 'source-thread', 'source-type',
  'source-role', 'source-agent', 'source-status', 'source-rows', 'source-detail',
  'source-prev', 'source-next', 'source-page', 'source-context', 'source-context-result',
].map(id => [id, { value: '', innerHTML: '', textContent: '', disabled: false, className: '', querySelectorAll: () => [] }]));
sourceRaceElements['source-container'].value = 'workspace-a';
sourceRaceElements['source-actor'].value = 'owner-a';
const sourceRaceDocument = { getElementById: id => sourceRaceElements[id] || null };
const pendingSourceReads = [];
function deferredSourceFetch(url) {
  return new Promise(resolve => pendingSourceReads.push({
    url: String(url),
    answer: body => resolve({ ok: true, status: 200, json: async () => body }),
  }));
}
const sourceFlowStart = html.indexOf('function sourceParams()');
const sourceFlowEnd = html.indexOf('function relayLifecycle()', sourceFlowStart);
assert.ok(sourceFlowStart >= 0 && sourceFlowEnd > sourceFlowStart);
const sourceFlow = new Function('document', 'fetch', `
let _sourceOffset=0,_sourceSelected=null,_sourceSelectedScope=null,_sourceFacets={containers:[],actors:[]},_sourceGeneration=0,_sourceDetailGeneration=0;const _sourcePage=25;
function scoped(id){return(document.getElementById(id)||{}).value||''}
function escapeHtml(value){return String(value == null ? '' : value)}
function esc(value){return escapeHtml(value)}
function formatDate(value){return String(value || '')}
${html.slice(sourceFlowStart, sourceFlowEnd)}
return {fetchSources,sourceDetail,sourceContext,setOffset:value=>{_sourceOffset=value}};
`)(sourceRaceDocument, deferredSourceFetch);

const ownerARead = sourceFlow.fetchSources();
sourceRaceElements['source-actor'].value = 'owner-b';
const ownerBRead = sourceFlow.fetchSources();
pendingSourceReads[1].answer({ items: [], total: 0 });
await ownerBRead;
assert.match(sourceRaceElements['source-status'].textContent, /owner-b/);
pendingSourceReads[0].answer({ items: [], total: 8 });
await ownerARead;
assert.match(sourceRaceElements['source-status'].textContent, /owner-b/);

sourceFlow.setOffset(0);
const firstPageRead = sourceFlow.fetchSources();
sourceFlow.setOffset(25);
const secondPageRead = sourceFlow.fetchSources();
pendingSourceReads[3].answer({ items: [], total: 30 });
await secondPageRead;
assert.equal(sourceRaceElements['source-page'].textContent, '26–25 of 30');
pendingSourceReads[2].answer({ items: [], total: 30 });
await firstPageRead;
assert.equal(sourceRaceElements['source-page'].textContent, '26–25 of 30');

const firstDetailRead = sourceFlow.sourceDetail('first');
const secondDetailRead = sourceFlow.sourceDetail('second');
pendingSourceReads[5].answer({ source: { id: 'second', content: 'second detail', actor_ref: 'owner-b', container_ref: 'workspace-a' } });
await secondDetailRead;
assert.match(sourceRaceElements['source-detail'].innerHTML, /second detail/);
pendingSourceReads[4].answer({ source: { id: 'first', content: 'first detail', actor_ref: 'owner-b', container_ref: 'workspace-a' } });
await firstDetailRead;
assert.doesNotMatch(sourceRaceElements['source-detail'].innerHTML, /first detail/);

const staleContextRead = sourceFlow.sourceContext('second');
sourceRaceElements['source-container'].value = 'workspace-b';
pendingSourceReads[6].answer({ items: [{ content: 'workspace-a context' }] });
await staleContextRead;
assert.doesNotMatch(sourceRaceElements['source-context-result'].innerHTML, /workspace-a context/);

sourceRaceElements['source-container'].value = 'workspace-c';
sourceRaceElements['source-actor'].value = '';
const allOwnersRead = sourceFlow.fetchSources();
const allOwnersRequest = pendingSourceReads.at(-1);
assert.doesNotMatch(allOwnersRequest.url, /actor_ref=/);
allOwnersRequest.answer({ items: [], total: 0 });
await allOwnersRead;
assert.match(sourceRaceElements['source-status'].textContent, /across all owners/);
const viewSwitchStart = html.indexOf('const _VIEWS =');
const viewSwitchEnd = html.indexOf('function openExpiredRelay', viewSwitchStart);
assert.ok(viewSwitchStart >= 0 && viewSwitchEnd > viewSwitchStart);
function viewElement(hidden = false) {
  const values = new Set(hidden ? ['hidden'] : []);
  return { classList: { toggle: (name, on) => on ? values.add(name) : values.delete(name), contains: name => values.has(name) }, setAttribute() {} };
}
const viewElements = {
  'view-operational': viewElement(false), 'view-relay': viewElement(true), 'view-how-it-helps': viewElement(true),
  'tab-operational': viewElement(false), 'tab-relay': viewElement(false), 'tab-evaluation': viewElement(false),
};
let evaluationLoads = 0;
const switchDashboardView = new Function('document', 'window', 'history', 'DASHBOARD_ROI_ENABLED', 'fetchRelay', 'fetchEffectivenessReports', `
  ${html.slice(viewSwitchStart, viewSwitchEnd)}
  return switchView;
`)({ getElementById: id => viewElements[id] || null }, { location: { hash: '' }, scrollTo() {} }, { replaceState() {} }, true, () => {}, () => { evaluationLoads += 1; });
switchDashboardView('evaluation');
assert.equal(viewElements['view-how-it-helps'].classList.contains('hidden'), false);
assert.equal(viewElements['view-operational'].classList.contains('hidden'), true);
assert.equal(evaluationLoads, 1);
console.log('plain-language dashboard renderers: all cases passed');
