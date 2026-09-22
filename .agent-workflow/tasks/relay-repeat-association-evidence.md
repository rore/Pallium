# Relay repeat-association evidence

<!-- agent-workflow:start -->
**Outcome:** Make complete retained uncertain wake evidence actionable when its only trailing fact is a same-attempt association, without enabling another native submission.

**Target:** Pallium Relay Codex wake diagnostic association.

**Scope:** The restart evidence guard in `app/codex_wake.py`, focused guard and caller-surface regressions, and Relay roadmap wording if the shipped claim changes.

**Constraints:** Preserve the retained reservation as the native-write gate. Accept only a complete exact-scope generation-zero trace whose latest activation completion is uncertain and retry-unsafe, with exactly one matching prepare and completion. Any later direct fact must be `associated` for that same attempt. Keep retry, claim, ACK, TTL, workspace, scope, model, and effort behavior unchanged.

**Completion criteria:** A restart recovery sweep associates a later pending delivery when the retained source has prepare -> uncertain completion -> same-attempt association, while attempts stay zero and native submissions stay one. A different-attempt or otherwise ambiguous trailing fact remains queued.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** The change is small but touches watched native-wake evidence logic and changes which historical traces qualify for actionable guidance.

**Discovery:** Installed PR #218 recovery enumerated the historical later delivery every sweep, but its source trace ended with a same-attempt `associated` fact after the one uncertain retry-unsafe completion. `_restart_trace_attempt_id` required the latest direct fact itself to be `completed`, so it rejected the complete retained evidence and left the later delivery generically queued.

**Material assumptions:** `associated` is a diagnostic-only fact recorded under the same attempt identifier and does not represent a new native submission. The unique trace-fact constraint bounds one association fact per attempt and delivery.

**Plan:** Select the latest direct activation fact from `prepared` and `completed` stages. Require it to be the existing exact uncertain retry-unsafe completion with one earlier prepare and one completion. Permit zero trailing direct facts, or exactly one `associated` fact for that same retained delivery and attempt after completion; reject any different attempt, duplicate association, other later stage, or pre-completion association. Add focused guard rejection coverage and extend the restart caller-surface regression to include a pre-existing same-attempt association before process restart. Stop if this requires retry, reservation, schema, or public API changes.

**Verification plan:** Exact trailing same-attempt association qualifies -> focused guard unit test. Different-attempt or other ambiguous trailing evidence remains rejected -> fail-closed parameterized regression. Restart with an already-pending later delivery performs one native submission total, preserves attempts=0, and exposes Needs intervention after recovery -> HTTP caller-surface regression. Existing repeated busy-sweep and affected wake suites remain green -> regression suite.

**Plan review:** Clean-context reviewer `/root/review_repeat_association_plan` approved Elevated/Moderate with no checkpoint after correcting its initial interpretation against the exact live trace. Approval requires zero or one trailing direct `associated` fact for the same retained delivery and attempt, exact prepare/completion cardinality, and fail-closed coverage for wrong attempt, duplicate association, other later stage, and pre-completion association. Read-only analysis `/root/analyze_repeat_association` independently identified the same minimal activation-versus-diagnostic distinction.

**Approvals:** Not required unless reclassification reaches High.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Evidence

- Live installed trace was complete and exact: one prepared event, one uncertain `nonzero_exit` completion with `native_retry_safe=false`, then one same-attempt `associated` event. Recovery logs showed the later zero-attempt delivery was enumerated, but its trace remained absent and explained as Queued.
- `apply_patch` had already failed in this session with Windows process-launch error 1327; this Work Record used the permitted deterministic narrow fallback.
- The interrupted Luna implementation changed only the production guard and left malformed tests; its test-file delta was discarded by exact Git-backed replacement, then the approved regressions were rebuilt deterministically.
- Implemented activation-versus-diagnostic selection in `_restart_trace_attempt_id`: exact prepare/completion requirements remain, with zero or one trailing same-attempt association allowed and every other trailing fact rejected.
- Focused guard and restart caller-surface regressions -> `30 passed in 2.17s`.
- Affected suites -> `117 passed in 29.48s` and `83 passed in 32.72s`.
- Independent result review `/root/review_repeat_association_result` found no correctness issue and confirmed the association-only return path cannot launch, claim, ACK, or retry.
- Full suite -> `5096 passed, 34 skipped, 2 xfailed in 218.47s`.
