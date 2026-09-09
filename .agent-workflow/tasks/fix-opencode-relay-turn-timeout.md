<!-- agent-workflow:start -->
<!-- A `**Label:**` at the start of a line inside this block is parsed as a field
     header; an unexpected one (unknown or duplicate) fails the record. Keep bold
     sub-headings out of a field's prose value (put such structure below the block,
     or use plain text). -->
**Outcome:** OpenCode reliably receives persisted Relay messages during normal Windows CI load instead of silently injecting scope-only context after a premature client timeout.

**Target:** Pallium OpenCode integration.

**Scope:** `integrations/opencode/.opencode/plugins/pallium.mjs`, `tests/test_stable_actor_identity_e2e.py`, and this Work Record.

**Constraints:** Keep Relay HTTP/storage contracts, claim-before-injection, acknowledgement-after-injection, fail-safe hook behavior, and other integrations unchanged.

**Completion criteria:** The real-service OpenCode Relay lifecycle test passes repeatedly and reports delivery state when payload injection fails; focused OpenCode tests and the repository workflow check pass.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** The OpenCode runtime adapter is gray-zone; tests and Work Record are blue. No API, schema, security, runtime-config, checkpoint, or dependency-boundary change is planned.

**Discovery:** CI run 34276917061 failed identically in Windows Python 3.12 and 3.13: Relay scope was injected but the persisted payload was absent. The same failure occurred in run 34251320954. The OpenCode adapter gives `/relay/turn` only 750 ms and converts timeout/failure to an empty response; a late server claim can then remain leased without reaching the model. OpenCode is a long-lived async plugin and already exposes `HTTP_TIMEOUT_MS = 6000`, unlike process hooks constrained by a host deadline.

**Material assumptions:** The 750 ms client deadline is the failing boundary. If using the existing 6 s HTTP deadline still produces scope-only injection or the status does not show a pending/claimed delivery, stop and investigate loopback resolution or server transaction behavior rather than adding retries, because retrying an ambiguously claimed delivery is unsafe.

**Plan:** In `pallium.mjs`, reuse `pallium.HTTP_TIMEOUT_MS` for `/relay/turn`; do not change ACK/close deadlines or add retry machinery. In the real-service E2E test, attach the fetched delivery status to the payload assertion so any recurrence identifies pending/claimed/delivered state. Run the exact E2E repeatedly, the OpenCode Node suite, affected Relay tests, redline/workflow checks, then the full suite before review. Stop and return to planning if the longer deadline does not eliminate the failure or requires server/API changes.

**Verification plan:** When a persisted Relay message is fetched during a real OpenCode user turn, the model-bound text shall contain it and the delivery shall be delivered → repeat `test_opencode_public_relay_lifecycle_uses_configured_actor_against_real_service`. When OpenCode hook behavior changes only in deadline tolerance, existing injection, ACK, fail-safe, and lifecycle contracts shall remain intact → OpenCode Node suite and affected Relay hook tests. When the branch is ready for review, governance and regression checks shall pass → redline/workflow checks and full pytest suite.

**Plan review:** Pending clean-context review.

**Approvals:** Not required at this risk level.

**Exceptions:** —

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Discovery and pre-edit redline classification complete; implementation waits for clean-context plan review.

## Evidence

- GitHub Actions runs 34276917061 and 34251320954; source inspection of the OpenCode `/relay/turn` call and shared request deadlines.

## Plan review

Pending.

## Result review

Pending.
