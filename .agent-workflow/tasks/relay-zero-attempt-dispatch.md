<!-- agent-workflow:start -->
**Outcome:** Determine why a Relay delivery could remain pending with zero attempts and no activation trace while its recipient appeared idle, and correct any Pallium-owned scheduling defect without unsafe native retries.

**Target:** Pallium Relay.

**Scope:** Relay activation scheduling, durable Codex wake reservations, exact delivery trace/status behavior, focused tests, and roadmap alignment if the reliability claim changes.

**Constraints:** Preserve busy-turn safety, reservation idempotence, delivery/session/container identity, TTL, claim/ACK semantics, recipient scope, model and effort; never infer native admission or retry an uncertain native submission.

**Completion criteria:** The zero-attempt/no-trace path has an evidence-backed root cause; if Pallium-owned, the shared path is fixed with caller-surface regression coverage proving no duplicate native submissions, while external ambiguity is recorded precisely if no safe internal fix exists.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Pre-edit redline classification is GRAY because intended production paths are watched runtime/core/storage surfaces. Moderate complexity reflects uncertainty across scheduling, durable reservations, and evidence projection.

**Discovery:** The exact pending delivery matches the session, container, and endpoint of retained uncertain delivery `relay-delivery-5c6de3ac9d1e4a698690f4fc3834da38`. Its version-2 durable reservation remains `uncertain`; the original bounded trace still contains one exact prepared/completed attempt. `schedule_codex_relay_wake` retains the fence but can emit `associated` only from a process-local attempt map, which is empty after restart, leaving the later delivery at attempts=0 with no trace. Existing tests cover in-process association and duplicate-wake prevention, not restart-loaded association.

**Material assumptions:** Bounded trace is diagnostic and may be missing; durable association is emitted only when the retained reservation and new delivery have the exact same endpoint, session, and container and a direct prior attempt event is available. Missing, conflicting, or legacy evidence preserves the current unknown state. Any need to change API, schema/codec, core service/routing, security, or governance returns this task to planning and reclassification.

**Plan:** Add one bounded helper in `app/codex_wake.py` that reads the retained delivery's existing trace and returns only its latest exact attempt consistent with the durable reservation. On same-scope reservation conflict after restart, reuse that attempt ID to emit `associated`; preserve the in-memory fast path and never release, replace, or retry the reservation. Add an HTTP caller-surface regression in `tests/test_codex_wake.py` proving restart-loaded uncertain fencing yields actionable trace for the later pending delivery with one native submission total, plus a missing-evidence regression. Update the Relay roadmap claim. Stop and re-plan if exact trace identity cannot be established without schema or API changes.

**Verification plan:** When a retained uncertain fence survives restart, a later exact-scope delivery shall remain pending with attempts=0, perform no second native submission, and expose the shared uncertain outcome through HTTP trace → focused end-to-end regression. When retained trace evidence is missing or mismatched, no unsupported association shall be emitted → focused unit regression. Existing busy-sweep and trace projection regressions shall remain green → affected test files. Final diff shall pass workflow/redline/import checks and `tests/ -x -q` before review.

**Plan review:** Pending clean-context review after discovery.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

Authoritative request source: `ff5d1534-0191-47f6-b586-95dd3c980476`.

## Implementation

- Work Record initialized before code inspection or edits. Pre-edit redline verdict: GRAY; no required checkpoint and no boundary risk in the intended scope.
- Discovery established a post-restart diagnostic-linkage gap, not a safe-retry opportunity: the exact durable uncertain fence matches the later delivery scope, while only the process-local attempt map was lost.
- Clean-context code-path review: `/root/trace_zero_attempt_path`; independent incident inspection: `/root/inspect_incident_state` (its runtime-DB uncertainty was resolved by the exact durable reservation file plus installed trace surface).

## Evidence

- Pending discovery.

## Result review

- Pending.
