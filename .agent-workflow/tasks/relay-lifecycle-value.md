<!-- agent-workflow:start -->
**Outcome:**
Relay tells a sender that a known recipient is explicitly closed instead of making the terminal lifecycle state look like a typo, and rejects the send or delivery-derived reply before persisting new message state.

**Target:**
Shared SQLite Relay recipient admission for new sends and replies.

**Scope:**
`storage/sqlite_relay.py`; focused public-surface coverage in `tests/test_agent_relay_e2e.py` and the adjacent rollback expectation in `tests/test_relay_mcp_lifecycle.py`; `docs/agent-relay.md`; `roadmap/features/add-relay-retention-and-lifecycle-hardening.md`; this Work Record.

**Constraints:**
Preserve dormant-session routing, unreachable-recipient behavior, alias removal on close, delivery durability, scope isolation, and existing status semantics. Limit the public contract change to closed-recipient error semantics; do not change API routes, schemas, selector rules, service-global scope, core, visibility, actor routing, imports, retention workers, cleanup windows, telemetry, or dependencies. Do not touch unrelated `scripts/validate_relay_cutover_copies.py`.

**Completion criteria:**
(1) A new HTTP Relay send to a known closed recipient through its canonical endpoint or unique legacy exact-session selector returns 409 with stable detail `recipient session is closed`, creates no message or delivery, and the rejected caller-supplied message ID remains 404 through public status. (2) A delivery-derived HTTP reply whose original sender closed after delivery returns the same 409, creates no reply message or delivery, and the deterministic rejected reply ID remains 404 through public status. (3) A released closed alias remains not found, dormant exact sessions remain routable, unreachable exact/alias sends retain their current 409, and retrying a rejected closed target has no side effects. (4) Docs and roadmap identify this user-visible terminal error as the valuable first lifecycle slice and defer retention cleanup until operational evidence justifies concrete windows.

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
`storage/sqlite_relay.py` is gray and on the storage watch list. The change intentionally narrows the public HTTP error semantic from generic 404 to stable 409 for a known closed recipient, while reusing existing exception mapping, changing no API/schema file, and crossing no configured boundary.

**Discovery:**
Current main already routes dormant sessions, rejects unreachable exact and alias targets with stable 409 before persistence, preserves pending delivery state, and reactivates closed sessions on a later turn. `_relay_target` resolves a known closed target and then converts every non-active state except unreachable into generic not-found; `relay_reply_atomic` does the same when the original sender is closed. Existing public E2E proves dormant routing, unreachable behavior, row-count stability, alias release, and close/reactivation. The 2026-09-08 live Relay owner recommended preserving idle routing while making proven terminal outcomes deterministic, and confirmed the earlier actor-scoped alias 404 was correct rather than a Pallium defect. Clean-context classification: `storage/sqlite_relay.py` gray+watch; tests/docs/roadmap/record blue; Elevated/Simple; no architecture, API, persistence, security, or boundary checkpoint.

**Material assumptions:**
An explicitly closed session is safe and useful to distinguish from an unknown selector after the caller presents its known canonical endpoint or unambiguous exact runtime/session selector. Disproof would be an existing privacy or scoping contract that intentionally hides closed state; then retain 404 and close this slice as documentation-only. Closed aliases stay undiscoverable because close removes the binding. Current session states remain `active`, `unreachable`, and `closed`; if another non-active state exists, preserve its current generic handling and do not broaden this change.

**Plan:**
(1) In the two existing pre-persistence recipient checks, add the same closed-state conflict immediately after the existing unreachable check; keep generic non-active handling, routes, schemas, service-global scope, and every selector rule unchanged. (2) Extend the nearest public Relay E2E to cover canonical and unique legacy exact sends, repeat rejection, released alias behavior, and an atomic reply to a newly closed original sender. Assert rejected caller-supplied send IDs and the deterministic reply ID remain 404 through public status; keep row counts as supplementary evidence and reuse existing dormant/unreachable assertions. (3) Update Relay docs and the lifecycle roadmap to record this first value slice and explicitly defer cleanup/retention windows. (4) Run the exact focused E2E, affected Relay suites, workflow/redline and whitespace checks, one full suite before PR, then clean-context result review. Stop and re-plan before any API route/schema, core, visibility, actor-routing, new state, or cleanup work.

**Verification plan:**
When a sender targets a known closed canonical endpoint or unambiguous exact session, Relay shall return stable 409 and persist nothing → public HTTP E2E verifies each rejected caller-supplied message ID remains 404 through status; row counts supplement repeated-attempt evidence.
When a recipient replies after the original sender closes, Relay shall return the same stable 409 and create no reply state → public claim/reply E2E derives the deterministic reply ID and verifies status remains 404; row counts supplement the assertion.
When a closed alias, dormant target, or unreachable target is addressed, existing semantics shall remain unchanged → neighboring public E2E assertions for alias 404, dormant delivery, and unreachable 409.
When lifecycle docs change, they shall state the proven value boundary and defer unevidenced retention work → diff review against the live diagnosis and current roadmap.
Before PR review, the branch shall pass focused and affected Relay tests, workflow/redline, whitespace, and one full suite → pytest commands, `python scripts/agent-workflow-check.py --repo-root . --slug relay-lifecycle-value`, `git diff --check`, and `python -m pytest tests/ -x -q`.

**Plan review:**
2026-09-08 clean-context review by /root/review_relay_lifecycle_plan: APPROVE after requiring explicit narrow public error-semantic disclosure and public status-read proof that rejected send and reply IDs are not persisted.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-08: Created the expanded Work Record before code after clean-context classification returned Elevated/Simple with storage watch visibility and no checkpoint.
- 2026-09-08: Clean-context Elevated plan review approved the closed-recipient 409 boundary after adding public status non-persistence assertions and explicitly freezing routes, schemas, selectors, and service-global scope.
- 2026-09-08: Added two closed-state conflict guards beside the existing unreachable checks in send recipient resolution and atomic reply recipient resolution. No abstraction, import, route, schema, selector, scope, persisted state, or cleanup machinery was added.
- 2026-09-08: Extended the existing public lifecycle E2E for canonical and unambiguous exact closed sends, repeat rejection, released alias, public status absence, atomic reply after the original sender closes, preserved claim state, and supplementary row stability. Updated the adjacent rollback test from the old 404 to the new 409/detail contract.
- 2026-09-08: Marked the lifecycle roadmap active, documented the stable terminal error, and explicitly deferred retention windows and cleanup until observed storage or diagnostic pain justifies them.

## Evidence

- Exact public E2E: `.venv\Scripts\python.exe -m pytest tests\test_agent_relay_e2e.py::test_unreachable_and_closed_destinations_reject_without_new_state -q -n 0` → 1 passed.
- The initial affected run exposed one expected stale 404 assertion in `test_atomic_reply_failure_rolls_back_delivery_claim`; after aligning it, the exact node passed and the affected HTTP/MCP/lifecycle/SQLite set passed 118 tests.
- Full repository gate: `.venv\Scripts\python.exe -m pytest tests\ -x -q` → 4656 passed, 32 skipped, 2 xfailed, four pre-existing Pydantic forward-reference warnings in 237.50 seconds.
- `.venv\Scripts\python.exe scripts\agent-workflow-check.py --repo-root . --slug relay-lifecycle-value` → clean, with gray storage watch visibility, no boundary violation, and no checkpoint. `git diff --check` → clean.
- Untracked `scripts/validate_relay_cutover_copies.py` is unrelated concurrent work and remains excluded.

## Result review

2026-09-08 clean-context review by /root/review_relay_lifecycle_result: APPROVE after correcting the docs to say `unambiguous exact runtime/session`, preserving the established ambiguity behavior for legacy selectors.
