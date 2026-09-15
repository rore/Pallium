<!-- agent-workflow:start -->
**Outcome:** Fresh unattended Codex delivery evidence distinguishes idle wake from busy completion, and any stall is exposed with an actionable supported next step without claiming universal Relay reliability.

**Target:** Pallium Relay.

**Scope:** This Work Record; the existing Relay roadmap evidence; payload-free live Relay/Codex observations; at most one fresh idle-recipient probe and one busy-recipient probe; and current readiness/trace inspection.

**Constraints:** No replay of historical instructions, manual receive alongside hook delivery, service/config/trust mutation for a witness, direct-user preemption, historical cleanup, or other-platform qualification. Any runtime/code/test fix requires return to planning and fresh risk classification before editing.

**Completion criteria:** An idle existing Codex recipient wakes, reads, and replies without a user-entered prompt or retains an exact supported limitation; a busy recipient receives after current work completes; and missing hook trust or a stalled delivery is distinguishable with an actionable next step.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Clean-context pre-edit Redline classified the Work Record and Relay roadmap paths BLUE with no boundary, contract, watch, runtime-config, or checkpoint finding.

**Approach:** Reuse exact installed witnesses and authoritative status/trace/turn evidence, run only the missing fresh idle and busy checks, and record honest outcomes. Replan and reclassify before any product-code change.

**Verification:** Exact Relay recipient/status/trace reads; recipient hook-derived reply evidence; Codex turn timing; readiness/trace next-step inspection; `git diff --check`; fresh Redline and agent-workflow gates; smart result review and PR CI.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-09-15: The initial `@pall-arc` incident is user-prompt-assisted, not unattended-idle evidence. Delivery `relay-delivery-1d33bcba23384811a6ff99c048aba429` remained pending with attempts `0` behind an accepted/queued activation and an in-flight durable reservation until an ordinary user turn began at 10:21 Jerusalem time.
- 2026-09-15: That turn and subsequent task turns drained older deliveries one at a time; the exact delivery became delivered on attempt `1` at 10:33:05. This supports busy-after-current-work behavior for that session but does not prove a fresh idle wake.
- 2026-09-15: The durable reservation cleared after delivery admission before its persisted row could be captured. Legacy-fence causation therefore remains an evidence-backed inference, not a conclusion.
- 2026-09-15: Current recipient readiness reported `attempt_inflight` from `durable_reservation` with `next_natural_turn` fallback, while exact trace reported accepted native activation without payload admission. Neither surface identified the long stall or supplied an actionable supported recovery step.