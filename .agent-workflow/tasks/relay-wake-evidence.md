# Diagnose missing Codex Relay wake delivery

<!-- agent-workflow:start -->
**Outcome:**
A reproducible Codex Relay wake failure leaves durable, payload-free evidence of the exact delivery's hook progress while the delivery remains governed by existing scoped Relay behavior.

**Target:**
Codex UserPromptSubmit Relay wake evidence and ACK reporting.

**Scope:**
`app/codex_readiness.py`, `integrations/codex/hooks/common.py`, `integrations/codex/hooks/user_prompt_submit.py`, focused tests in `tests/test_agent_relay_hooks.py` and `tests/test_codex_wake.py`, and this Work Record.

**Constraints:**
Keep the wake prompt unchanged. Do not infer or persist scope, weaken Relay authorization, attribute hook evidence to a native activation attempt, call live receive/resend, wake real sessions, restart services, or claim historical root cause from missing evidence.

**Completion criteria:**
1. A canonical delivery wake records bounded durable `hook_started`, actual `payload_emitted`, strict `delivery_acked`, or fixed-reason `hook_failed` evidence without payload or scope.
2. Missing/invalid scope, unavailable/malformed/empty Relay results, emit failure, ACK failure, marker failure, stale hook definition, Unicode payload, and successful delivery preserve existing safe behavior and truthful evidence.
3. Frozen pre-change hooks remain compatible with the unchanged prompt; missing evidence remains unknown and never proves absence or trust failure.
4. Scope moves continue through the existing current-scope `relay_turn` path with no historical scope exposed by diagnostics.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Redline classifies the runtime and hook files as gray/watch. Elevated judgment is retained because the hook sits on a delivery and scope boundary; complexity is Moderate across durable evidence, hook output, and ACK validation.

**Discovery:**
The activation trace already persists exact-delivery `prepared/associated/completed` facts, while Codex readiness records only the last matching hook execution. The original hook window was pruned, so historical cause is indeterminate. Native `codex queue --help` exposes no correlation field beyond message text; the unchanged prompt carries the exact delivery ID but cannot distinguish native retries. Therefore hook evidence must remain delivery-only and advisory. The Codex ACK helper currently discards the response, while the Claude helper already returns confirmed acknowledgments.

**Material assumptions:**
- Delivery-only hook evidence is sufficient to diagnose the next reproduction without claiming a native attempt; disproved if operators require attempt-level ordering, which would need a separate native correlation contract.
- The existing readiness marker is the appropriate durable local evidence boundary; disproved if its bounded atomic writes cannot preserve validated events, in which case stop rather than add a second telemetry system.
- ACK response fields are authoritative only when delivery ID and delivered state match; any other response remains `ack_failed`.

**Plan:**
1. Extend the existing locked Codex readiness marker with a bounded, validated, payload-free delivery evidence list and expose only those safe fields through its existing public read.
2. Reuse the Claude ACK result pattern in Codex, with stricter matching of delivery ID, delivered state, and boolean `already_delivered`.
3. Record hook stages only after the corresponding observable action: start after exact wake recognition, emitted after output succeeds, acknowledged after strict ACK proof, otherwise one fixed failure reason. Marker failures remain best-effort unknown and never alter Relay flow.
4. Add focused caller-surface tests for success, invalid/missing scope, unavailable/malformed/empty response, emit/ACK failure, stale definition, Unicode, bounds, frozen prompt compatibility, and scope-move non-disclosure.

**Verification plan:**
- When an exact wake succeeds, the system shall record started → emitted → acknowledged for that delivery and no payload/scope → focused hook/readiness test.
- When any hook boundary fails, the system shall record only the last proven stage plus a bounded failure reason and retain existing Relay state → parameterized caller-surface tests.
- When marker identity or persistence is unavailable, the system shall continue delivery behavior with no evidence and no inferred cause → readiness failure tests.
- When the session scope moved or the hook is frozen, the system shall expose no historical scope and keep the unchanged wake contract → existing scope-move/frozen prompt regression plus focused assertions.

**Plan review:**
Clean-context review `/root/missing_wake_evidence_fix/wake_evidence_security_review`: APPROVE after removing native-attempt association and trace draining; strict ACK validation and unknown-on-marker-failure resolve the blocking findings.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Discovery and clean-context review complete. No production code changed before approval.

## Evidence

- Native queue help has no hook correlation field beyond the message text.
- Existing exact prompt remains the only delivery identifier visible to frozen and current hooks.
- Clean-context review approved delivery-only advisory evidence and rejected attempt attribution.

