<!-- agent-workflow:start -->
**Outcome:**
Allow the Relay dashboard to deep-link to and select an exact session by canonical endpoint_id.

**Target:**
Pallium Relay dashboard.

**Scope:**
Dashboard hash/view initialization, Relay session selection/loading behavior, and focused dashboard/UI tests if implementation confirms they are needed; likely `app/dashboard.html` plus `tests/dashboard_plain_language_renderer.mjs` or a focused UI harness.

**Constraints:**
No unrelated product changes; preserve ordinary #relay and #operational behavior; no API change unless discovery proves the existing response lacks canonical endpoint_id; read-only behavior remains read-only.

**Completion criteria:**
When visiting `/dashboard#relay?session=<percent-encoded endpoint_id>`, the dashboard selects the exact matching session (including outside the initial page/default scope), survives reload and browser navigation, and reports malformed/not-found targets without mutating state.

**Risk:** Routine

**Complexity:** Simple

**Reason:**
Intended implementation and test surfaces are blue-zone dashboard/UI and test files; no API, persistence, security, or boundary changes are planned.

**Approach:**
Use the existing read-only `/dashboard/api/relay/sessions` projection and browser state. Parse only `#relay?session=<encoded endpoint_id>`, select after the initial load, and page through the same filtered session endpoint when the target is not present; report malformed/not-found targets in the existing Relay status area without changing ordinary hashes or sending/waking.

**Verification:**
Run the workflow checker and focused read-only inspection; implementation follow-up should add focused dashboard tests for direct visit/reload/back-forward, page traversal, unchanged ordinary hashes, malformed/not-found targets, escaping, and no mutation.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Setup complete; isolated branch created from origin/main. Discovery and plan are recorded below. Pre-edit redline classified intended dashboard/test paths BLUE with no checkpoints or boundary violations. Workflow checker passes. No product, test, or documentation files have been edited.

## Discovery

- Dashboard is served at `GET /dashboard` (`app/dashboard.py:240`); view state is client-side hash-only. Existing `_initViewFromHash` accepts exact `#operational`, `#relay`, and optional `#evaluation`; any query-bearing hash currently falls back to Operations. `switchView` uses `history.replaceState`, and `hashchange` re-runs initialization, so direct visit/reload/back-forward must be handled there without replacing `#relay?session=...` with plain `#relay`.
- Relay setup calls `fetchRelay(true)` on entering Relay. The initial session request is `/dashboard/api/relay/sessions?limit=100&offset=0` with current lifecycle/runtime/container filters; `loadMoreRelaySessions()` pages the same endpoint. Selection is local via `selectRelaySession(id, authoritative)`, and `renderRSession()` escapes metadata through `esc`/`escapeHtml`. No deep-link state exists today.
- `/dashboard/api/relay/sessions` returns `id` (the `RelaySessionRecord.id`, which is the canonical endpoint ID) but not a separate `endpoint_id`; `app/dashboard.py:_dashboard_relay_session` is the projection. `/dashboard/api/relay/messages` exposes `sender_endpoint_id`/`recipient_endpoint_id` and `endpoint_sessions` keyed as `id`. `/relay/work-refs/participants` already exposes canonical `endpoint_id` through `storage/sqlite_relay.py:_session_view` and `RelayWorkRefParticipantResponse`; no API change is necessary.
- Existing focused UI checks are Node scripts: `tests/dashboard_plain_language_renderer.mjs` extracts renderer/view code, while `tests/dashboard_work_ref_ui.mjs` exercises `selectRelaySession` and participant opening. `tests/test_dashboard.py` covers read-only route shape/pagination/filtering and verifies session IDs, but no hash deep-link behavior. `app/dashboard.html` is blue-zone UI; tests are blue; no API/persistence/security/boundary surface is intended.
- Smallest compatible route contract: `/dashboard#relay?session=<percent-encoded canonical endpoint_id>`. Plain `#relay` and `#operational` remain unchanged. A valid target should be selected after initial data load; if absent from the first page, continue bounded session pagination under the current default scope (or make target lookup explicit if filters would exclude it), then show a clear not-found message without selection/mutation. Malformed/not-found targets show a clear status and leave selection unchanged. IDs and status text use existing escaped rendering; no send/wake or POST path is involved.

## Plan

1. Extend the existing hash parser/init and Relay load completion with a single pending canonical endpoint target, preserving ordinary hashes and history behavior.
2. Resolve a target by exact endpoint ID, including later session pages, then call `selectRelaySession` only after a matching read-only session is present; avoid alias/session_ref matching and avoid mutating selection on malformed/not-found input.
3. Add the smallest focused UI assertions for encoded IDs, direct init/reload/hashchange behavior, pagination/out-of-scope handling, malformed/not-found status, escaping, and unchanged ordinary hashes. Reuse `tests/dashboard_plain_language_renderer.mjs` unless a tiny dedicated harness is materially simpler.
## Plan review

Not applicable during read-only setup; implementation remains for a follow-up task/review.
