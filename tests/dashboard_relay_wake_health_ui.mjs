import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const html = readFileSync(process.argv[2], 'utf8');
const start = html.indexOf('function renderRelayWakeHealth(wake) {');
const end = html.indexOf('async function fetchRelaySummary()', start);
assert.ok(start >= 0 && end > start, 'shipped wake-health renderer is present');
const fetchEnd = html.indexOf('// Render: status', end);
assert.ok(fetchEnd > end, 'shipped Relay summary fetch is present');

const element = { textContent: '', className: 'relay-note green', innerHTML: '' };
const document = { getElementById: id => id === 'relay-wake-health' ? element : null };
const api = new Function('document', `
  function fmtNum(value) { return value == null ? '—' : String(value); }
  function formatUptime(value) { return String(value) + 's'; }
  ${html.slice(start, end)}
  return { renderRelayWakeHealth };
`)(document);

api.renderRelayWakeHealth({
  assessment: 'codex_scheduling_only', state: 'usable', reason: 'recovery_running',
  eligible_pending_count: 2, oldest_pending_age_seconds: 9,
  pending_evidence: 'complete', unresolved_uncertain_count: 1,
});
assert.match(element.textContent, /Codex scheduling: usable/);
assert.match(element.textContent, /2 eligible pending deliveries/);
assert.match(element.textContent, /automatic retry is held/);
assert.match(element.textContent, /do not resend/);
assert.equal(element.innerHTML, '', 'status is rendered as text, not HTML');
assert.match(element.className, /green/);

api.renderRelayWakeHealth({
  assessment: 'codex_scheduling_only', state: 'usable', reason: 'recovery_running',
  eligible_pending_count: 2, pending_evidence: 'complete', unresolved_uncertain_count: 0,
  reservations: { reserved: 0, accepted: 2, uncertain: 0 },
});
assert.doesNotMatch(element.textContent, /retry is held|unresolved uncertain/);

api.renderRelayWakeHealth({
  assessment: 'codex_scheduling_only', state: 'degraded', reason: 'recovery_not_running',
  eligible_pending_count: 0, pending_evidence: 'complete', unresolved_uncertain_count: 0,
});
assert.match(element.textContent, /recovery task is not running/);
assert.doesNotMatch(element.textContent, /retry is held|unresolved delivery uncertainty/);

api.renderRelayWakeHealth({
  assessment: 'codex_scheduling_only', state: 'degraded', reason: 'authority_uninitialized',
  eligible_pending_count: null, pending_evidence: 'unavailable',
  unresolved_uncertain_count: null,
});
assert.match(element.textContent, /durable authority is not initialized/);
assert.match(element.textContent, /Eligible pending deliveries: unknown/);
assert.match(element.textContent, /Unresolved delivery uncertainty: unknown/);
assert.doesNotMatch(element.className, /green/);

api.renderRelayWakeHealth({
  assessment: 'codex_scheduling_only', state: 'unknown', reason: 'authority_unavailable',
  eligible_pending_count: 0, pending_evidence: 'complete', unresolved_uncertain_count: 0,
});
assert.match(element.textContent, /durable authority could not be read/);

api.renderRelayWakeHealth(null);
assert.match(element.textContent, /Codex scheduling: unknown/);
assert.doesNotMatch(element.className, /green/);
assert.match(html, /fetch\('\/status\?include_relay_wake=false'\)/);
assert.doesNotMatch(html.slice(start, fetchEnd), /setInterval\(|setTimeout\(/);

const statusStart = html.indexOf('async function fetchStatus()');
const statusEnd = html.indexOf('// ──────────────────────────────────────────────────', statusStart);
assert.ok(statusStart >= 0 && statusEnd > statusStart, 'shipped status fetch is present');
let wakeWrites = 0;
const cycleTarget = { _text: '', className: '', innerHTML: '' };
Object.defineProperty(cycleTarget, 'textContent', {
  get() { return this._text; },
  set(value) { this._text = String(value); wakeWrites += 1; },
});
const elements = new Map();
const cycleDocument = { getElementById(id) {
  if (id === 'relay-wake-health') return cycleTarget;
  if (!elements.has(id)) elements.set(id, { textContent: '', className: '', classList: { add() {}, remove() {} } });
  return elements.get(id);
} };
const urls = [];
const responseBodies = {
  '/status?include_relay_wake=false': {},
  '/dashboard/api/relay/summary': { relay_wake: {
    assessment: 'codex_scheduling_only', state: 'usable', reason: 'recovery_running',
    eligible_pending_count: 1, oldest_pending_age_seconds: 3,
    pending_evidence: 'complete', unresolved_uncertain_count: 0,
  } },
};
const cycle = new Function('document', 'fetchImpl', 'urls', 'responseBodies', `
  let _statusData = null, _relayData = null;
  function fetch(url) { urls.push(url); return fetchImpl(url); }
  function renderStatus() {} function renderSinceRestart() {} function renderOperationalSummary() {}
  function renderRelaySummary(data) { renderRelayWakeHealth(data.relay_wake); }
  function fmtNum(value) { return value == null ? '—' : String(value); }
  function formatUptime(value) { return String(value) + 's'; }
  ${html.slice(start, end)}
  ${html.slice(statusStart, statusEnd)}
  ${html.slice(end, fetchEnd)}
  return { fetchStatus, fetchRelaySummary };
`)(cycleDocument, async url => ({
  ok: true,
  async json() { return responseBodies[url]; },
}), urls, responseBodies);
await cycle.fetchStatus();
await cycle.fetchRelaySummary();
assert.deepEqual(urls, [
  '/status?include_relay_wake=false',
  '/dashboard/api/relay/summary',
]);
assert.equal(wakeWrites, 1, 'the summary cycle renders wake evidence exactly once');
assert.match(cycleTarget.textContent, /Codex scheduling: usable/);

async function failedFetch(fetchImpl) {
  const target = { textContent: 'previous green', className: 'relay-note green', innerHTML: '' };
  const doc = { getElementById: id => id === 'relay-wake-health' ? target : null };
  const run = new Function('document', 'fetchImpl', `
    let _relayData = { relay_wake: { state: 'usable' } };
    function fetch(url) { return fetchImpl(url); }
    function fmtNum(value) { return value == null ? '—' : String(value); }
    function formatUptime(value) { return String(value) + 's'; }
    function renderOperationalSummary() {}
    function renderRelaySummary(data) { renderRelayWakeHealth(data.relay_wake); }
    ${html.slice(start, fetchEnd)}
    return { fetchRelaySummary, relayData: () => _relayData };
  `)(doc, fetchImpl);
  await run.fetchRelaySummary();
  assert.equal(run.relayData(), null);
  assert.match(target.textContent, /Codex scheduling: unknown/);
  assert.doesNotMatch(target.className, /green/);
}

await failedFetch(async () => ({ ok: false, status: 503 }));
await failedFetch(async () => { throw new Error('network failure'); });
await failedFetch(async () => ({ ok: true, json: async () => { throw new Error('invalid JSON'); } }));

console.log('relay wake-health dashboard: all cases passed');
