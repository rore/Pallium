<!-- agent-workflow:start -->
**Outcome:** Relay operators can distinguish ordinary waiting from deliveries stranded on an older endpoint of the same runtime session, and the live legacy Dictation incident is handed through the existing guarded repair workflow without duplicate execution.

**Target:** Pallium Relay.

**Scope:** Add read-only split-session diagnostics to the existing Relay dashboard summary and session/message views, update the dashboard presentation, add caller-facing E2E coverage and focused documentation/roadmap alignment; use the already-shipped guarded endpoint-repair workflow for the live incident without adding another mutation path.

**Constraints:** Do not change Relay admission, claim, ACK, alias, endpoint, schema, or automatic convergence semantics. Do not infer that two endpoints may be merged merely from matching runtime/session identity. Do not mutate live deliveries until every affected delivery has an explicit consumer disposition and the existing repair fence accepts it.

**Completion criteria:** When one runtime/session has multiple endpoints and a non-current endpoint owns claimable deliveries, the dashboard shall report the split identity, stranded delivery count, oldest age, and affected endpoint; healthy single-endpoint and current-endpoint queues remain ordinary waiting. The live 24-delivery incident shall have a reviewed per-delivery handoff or an explicit guarded blocker, never silent deletion or automatic retargeting.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline classifies the intended dashboard/tests/docs paths blue, with app paths watched and no boundary/API/schema checkpoint. Risk is raised because the diagnostic can guide irreversible operator repair decisions; complexity spans aggregate semantics, UI, E2E coverage, and a separate guarded live handoff.

**Discovery:** The exact active Codex session has three canonical Relay endpoints across legacy scopes. Its old Dictation endpoint owns 24 durable pending deliveries with attempts=0 and no claim timestamps, while the same session actively polls a newer Pallium endpoint holding the alias. Existing PR 180 provides guarded offline dispositions and PR 181 provides trace evidence; neither surfaces split identity in Relay health. The dashboard already queries Relay tables directly, so detection can remain read-only in app/dashboard.py without storage/schema changes.

**Material assumptions:** Matching runtime/session plus multiple endpoint rows is diagnostic evidence of a split, not authorization to merge. The most recently seen endpoint is only the display-side current candidate; if a tie or missing timestamp makes that ambiguous, report the identity split and pending counts without recommending a destination. Evidence disproving this is a supported contract for concurrent same-session endpoints; if found, return to planning and narrow the diagnostic.

**Plan:** 1. Use the existing dashboard Relay queries and models to compute bounded split-identity diagnostics, with deterministic current-candidate selection only for display and no routing mutation. Target app/dashboard.py. 2. Expose split counts/ages in the existing summary and per-session dashboard responses, then show an attention state and affected-endpoint badge in app/dashboard.html. 3. Extend existing Relay/dashboard E2E tests for empty/single endpoint, split without backlog, old-endpoint pending, current-endpoint pending, stale claimed lease, expired/suppressed/terminal rows, deterministic ties, and Unicode identity. 4. Update docs/dashboard.md or docs/agent-relay.md and the canonical roadmap item only where status/contract changed. 5. Run focused tests, affected Relay/dashboard files, --lf, one full suite, workflow/redline checks, and smart result review; resolve PR threads and merge only when required CI is green. 6. Sync both clean main checkouts, restart only with scripts/restart-service.ps1, verify /health, /status, /debug/queue/health, and inspect the installed split diagnostic. 7. For the live incident, use the existing PR 180 workflow to produce a complete read-only inventory and obtain consumer dispositions; apply only if the guarded tool and existing High-risk approval conditions permit it.

**Verification plan:** Split identity with claimable work shall be reported without changing Relay state -> dashboard HTTP E2E asserting summary and per-session fields before/after identical reads. Healthy and terminal cases shall not be mislabeled -> E2E matrix for single endpoint, current endpoint, expired, delivered, suppressed, and split-without-work. Ambiguous identity shall not imply a repair destination -> deterministic tie/missing-time response assertion. UI shall replace the generic normal-wait message when stranded work exists -> dashboard rendering contract test. Live incident shall remain safe -> existing repair dry-run/apply fences plus reviewed disposition inventory and post-action dashboard/status evidence.

**Plan review:** Clean-context review completed on 2026-09-14; blocked findings and required corrections are recorded in the Plan review section below.

**Approvals:** Not required at this risk level. User authorized ownership and implementation on 2026-09-14: "so take ownership of this and fix".

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Work Record created before production edits. Read-only incident evidence and clean-context redline classification completed; production code is untouched pending plan review.

## Evidence

- Pre-edit redline: dashboard/tests/docs/roadmap/Work Record are blue; app paths watched; no boundary, API, schema, security, or persistence checkpoint. storage/sqlite_relay.py is intentionally excluded from the planned diff.

## Result review

- Pending.

## Plan review

Verdict: Blocked; revise affected planning fields and repeat review before implementation. Reviewed independently against the workflow Plan and Review checkpoint, repo instructions, dashboard routes/renderers, Relay schema, registration/claim/repair code, dashboard E2E tests, and docs/agent-relay.md. The read-only dashboard approach is the smallest suitable implementation; no storage or routing change is needed.

1. **Narrow the asserted failure.** The material assumption's stop condition is met: RelaySessionRecord is unique on (container_ref, runtime, session_ref); relay_turn registers separate scoped endpoints without transition intent; test_overview_container_ties_are_deterministic creates two through HTTP. Both remain exactly addressable and can poll independently. Replace definitive "stranded"/"non-current" claims with "possible split identity" and "claimable backlog on another endpoint". Matching identity and last_seen_at prove neither abandonment nor consumer equivalence. Update Outcome, Completion criteria, and Material assumptions. The documented project-transition contract preserves one endpoint only for an explicit valid transition; this diagnostic is not convergence or repair.

2. **Define candidate and ambiguity.** Label the candidate "most recently seen endpoint", not authoritative current destination. Specify closed/unreachable/dormant eligibility; a conservative choice is a unique most-recent active/recent sibling, otherwise no candidate. Endpoint ID may stabilize display but cannot break an evidence tie. Evaluate all siblings, including those hidden by container/lifecycle/page filters. Independently polling siblings remain possible regardless of timestamp ordering; alias ownership does not settle this. No diagnostic enables or recommends retargeting.

3. **Define queue semantics.** At one response timestamp, eligibility is message.expires_at > as_of AND (pending OR claimed with non-null lease_expires_at <= as_of). Exclude live/null claimed leases and exact expiry. Count deliveries; derive oldest age from those rows, clamped to zero. Join recipient_endpoint_id, not historical recipient container or runtime/session alone. Preserve pending_now, which already includes live claims. GET must not expire, reclaim, register, or ACK. Repair independently rejects every stored claimed source row, including elapsed leases; diagnostic eligibility is not repair eligibility.

4. **Make bounds concrete.** Use SQL aggregates for complete totals instead of loading all endpoints/deliveries. Bound returned detail lists with total/truncation metadata, evaluating whole sibling groups before limiting results. Reuse one calculation for bounded session/message endpoint pages without per-endpoint queries. Never infer global health from a partial page. Use the configured Relay database. Resolve message-page frozen-until time versus live diagnostic time explicitly.

5. **Close E2E gaps.** Name tests/test_dashboard.py and the existing renderer harness. Add HTTP-observed coverage for 3+ siblings, independent polling, candidate lifecycle states, ties, live/elapsed/null/exact-boundary leases, exact expiry, terminal/suppressed rows, same session_ref across runtimes, moved endpoint with historical container, missing endpoint metadata, Unicode/HTML-sensitive identity, page/filter-hidden siblings, empty/max/over-max bounds, and a separate Relay database. Cover create -> send -> claim -> ACK -> close/reopen through dashboard reads. Repeated GETs must preserve state, attempts, tokens, and timestamps. Missing last_seen_at violates the current non-null schema: specify defensive handling only if intended. Renderer checks must qualify both the dynamic waiting note and static "waiting is normal" subtitle when attention exists.

The live incident remains a separate guarded operational action. Preserve complete per-delivery dispositions, current reservation evidence, and existing approval/preimage fences; this review does not authorize apply. Roadmap/docs alignment must describe diagnostic uncertainty, not proven delivery failure or completed repair.