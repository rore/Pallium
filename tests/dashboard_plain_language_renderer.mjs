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
`;
const source = dependencies + html.slice(helperStart, helperEnd) + html.slice(renderStart, renderEnd) +
  'return { renderReuseCalibration, renderRawDerivedHybrid, renderDerivationFidelity };';
const { renderReuseCalibration, renderRawDerivedHybrid, renderDerivationFidelity } = new Function('document', source)(document);

renderReuseCalibration({
  available: true,
  report: { judge_vs_gold: { kappa: 0.75, threshold: 0.70, n: 12, calibrated: true } },
});
assert.match(elements['hh-reuse-kpi'].innerHTML, /do not know yet whether pulled-up memory helped/i);
assert.match(elements['hh-reuse-kpi'].innerHTML, /does not show that Pallium improved real work/);
assert.match(elements['hh-reuse-kpi'].innerHTML, /ready for cautious use/);
elements['hh-reuse-kpi'].querySelector('details').open = true;
renderReuseCalibration({
  available: true,
  report: { judge_vs_gold: { kappa: 0.75, threshold: 0.70, n: 12, calibrated: true } },
});
assert.equal(elements['hh-reuse-kpi'].querySelector('details').open, true);

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
assert.equal(operationalElements['operational-summary'].hidden, true);

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

console.log('plain-language dashboard renderers: all cases passed');
