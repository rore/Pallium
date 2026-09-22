<!-- agent-workflow:start -->
**Outcome:** Determine why a Relay delivery could remain pending with zero attempts and no activation trace while its recipient appeared idle, and correct any Pallium-owned scheduling defect without unsafe native retries.

**Target:** Pallium Relay.

**Scope:** Relay activation scheduling, durable Codex wake reservations, exact delivery trace/status behavior, focused tests, and roadmap alignment if the reliability claim changes.

**Constraints:** Preserve busy-turn safety, reservation idempotence, delivery/session/container identity, TTL, claim/ACK semantics, recipient scope, model and effort; never infer native admission or retry an uncertain native submission.

**Completion criteria:** The zero-attempt/no-trace path has an evidence-backed root cause; if Pallium-owned, the shared path is fixed with caller-surface regression coverage proving no duplicate native submissions, while external ambiguity is recorded precisely if no safe internal fix exists.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Pre-edit redline classification is GRAY because intended production paths are watched runtime/core/storage surfaces. Moderate complexity reflects uncertainty across scheduling, durable reservations, and evidence projection.

**Discovery:** Pending focused inspection of the exact incident, activation dispatch callers, reservation state machine, and existing regressions.

**Material assumptions:** The installed incident evidence remains available read-only; absence of historical evidence will not be treated as proof of no native admission. Any need to change API, schema/codec, core service/routing, security, or governance returns this task to planning and reclassification.

**Plan:** Pending discovery. No code edit until the exact zero-attempt path is traced and a clean-context reviewer approves the smallest evidence-backed change or blocker conclusion.

**Verification plan:** Exact incident trace/read-only state inspection; focused activation and Relay tests; no-duplicate recovery regression; affected subsystem tests; full `tests/ -x -q` before review if code changes.

**Plan review:** Pending clean-context review after discovery.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

Authoritative request source: `ff5d1534-0191-47f6-b586-95dd3c980476`.

## Implementation

- Work Record initialized before code inspection or edits. Pre-edit redline verdict: GRAY; no required checkpoint and no boundary risk in the intended scope.

## Evidence

- Pending discovery.

## Result review

- Pending.
