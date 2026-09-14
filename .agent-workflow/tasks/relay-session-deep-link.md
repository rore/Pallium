<!-- agent-workflow:start -->
**Outcome:**
Allow the Relay dashboard to deep-link to and select an exact session by canonical `endpoint_id`.

**Target:**
Pallium Relay dashboard.

**Scope:**
`app/dashboard.py`, `app/dashboard.html`, `docs/dashboard.md`, `tests/test_dashboard.py`, and `tests/dashboard_relay_deep_link_ui.mjs`.

**Constraints:**
Preserve ordinary `#relay`, `#operational`, and optional evaluation behavior. Keep the feature read-only: no Relay send, wake, name, or association mutation. Accept one canonical endpoint ID only; never match aliases, session refs, or substrings. Preserve the current selection on malformed, missing, failed, or stale exact lookups.

**Completion criteria:**
`/dashboard#relay?session=<percent-encoded endpoint_id>` selects the exact session, including one outside the initial/default recent page, across direct load, reload, and browser navigation. Malformed or unknown targets report a clear status without selection or persisted-state mutation.

**Risk:** Routine

**Complexity:** Simple

**Reason:**
All changed dashboard, documentation, test, and Work Record paths are blue-zone. The route change is one optional validated query parameter on an existing read-only operator endpoint; no persistence, security, schema, or package boundary changes occur.

**Approach:**
Add an optional validated exact `endpoint_id` filter to the existing read-only sessions route. Parse only `#relay?session=<one canonical relay-session-[0-9a-f]{32}>`, preserve the hash during initialization, and resolve it with one exact read independent of current/default filters. Apply a result only while generation, scope, and raw hash still match; keep the authoritative row visible and select only an exact ID. Report errors through `textContent` without changing prior selection.

**Verification:**
Run the dedicated JavaScript contract harness, the full dashboard test file, the workflow checker, `git diff --check`, the repository suite once before PR, and independent smart-model review. Coverage includes active/dormant/closed/non-first-page exact lookup, not-found, malformed validation, exact-not-alias/substring, direct/reload/back-forward, stale raw-hash/generation/scope responses, ordinary hashes, preserved selection, safe rendering, GET-only behavior, and storage read-only evidence.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Added the validated exact filter to `GET /dashboard/api/relay/sessions`; existing filters and pagination remain unchanged.
- Added canonical deep-link parsing and exact selection with raw-hash, generation, and scope guards.
- Query-bearing Relay navigation within the Relay view avoids the ordinary refresh/reset path, so invalid and not-found links retain the previous selection.
- Exact authoritative rows are included in the visible session list.
- Documented the external URL contract and added focused HTTP/JavaScript coverage.
- `apply_patch` failed with machine-local Windows error 1327. Per `AGENTS.local.md`, edits used narrowly scoped deterministic PowerShell or Git-native patch fallbacks limited to the named files.

## Evidence

- `node tests/dashboard_relay_deep_link_ui.mjs app/dashboard.html`: passed.
- Focused deep-link pytest nodes: 2 passed.
- `python -m pytest tests/test_dashboard.py -q -n 0`: 47 passed.
- `python -m pytest tests/ -x -q`: 4,948 passed, 34 skipped, 2 xfailed.
- `python scripts/agent-workflow-check.py --repo-root . --slug relay-session-deep-link`: clean.
- `git diff --check`: clean.
- Independent Sol review found and verified fixes for stale same-view fetches, exact-result visibility, GET-only selection, composed API filters, and preserved pagination offsets. Runtime/API/test code approved; only this evidence reconciliation remained.

## Discovery and plan review

The initial discovery proposed paging the current session list. Independent Sol review rejected that plan because the default `recent` filter cannot reach dormant or closed sessions, `switchView` would erase the query-bearing hash, refresh would reset selection on invalid/not-found input, and generation-only guards miss navigation races. The corrected implementation uses one exact read, preserves the raw hash, checks raw hash plus generation and scope, and keeps the selected authoritative row visible. No general dashboard routing or pagination abstraction was added.