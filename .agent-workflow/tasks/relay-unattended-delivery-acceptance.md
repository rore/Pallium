<!-- agent-workflow:start -->
**Outcome:** Fresh unattended Codex delivery evidence distinguishes idle wake from busy completion, and any stall is exposed with an actionable supported next step without claiming universal Relay reliability.

**Target:** Pallium Relay.

**Scope:** This Work Record; the existing Relay roadmap evidence; payload-free live Relay/Codex observations; one fresh idle-recipient probe and its return delivery as the busy-recipient probe; current readiness/trace inspection; and the existing dashboard plain-language guidance plus its focused UI contract test.

**Constraints:** No replay of historical instructions, manual receive alongside hook delivery, service/config/trust mutation for a witness, direct-user preemption, historical cleanup, or other-platform qualification. Any runtime/code/test fix requires return to planning and fresh risk classification before editing.

**Completion criteria:** An idle existing Codex recipient wakes, reads, and replies without a user-entered prompt or retains an exact supported limitation; a busy recipient receives after current work completes; and missing hook trust or a stalled delivery is distinguishable with an actionable next step.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Fresh clean-context pre-edit Redline classified `app/dashboard.html`, its focused renderer test, the Work Record, and the Relay roadmap BLUE. The dashboard path is watched, but there is no boundary, contract, API/schema, runtime-config, import, or checkpoint finding.

**Approach:** Reuse exact installed witnesses and authoritative status/trace/turn evidence, run only the missing fresh idle and busy checks, and record honest outcomes. Reuse the dashboard summary fields already shipped to expose wait age, incomplete evidence, and the safe trace/no-resend next step; add no timeout policy or delivery mechanism.

**Verification:** Exact Relay recipient/status/trace reads; recipient hook-derived reply evidence; Codex turn timing; readiness/trace next-step inspection; `git diff --check`; fresh Redline and agent-workflow gates; smart result review and PR CI.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-15: The initial `@pall-arc` incident is user-prompt-assisted, not unattended-idle evidence. Delivery `relay-delivery-1d33bcba23384811a6ff99c048aba429` remained pending with attempts `0` behind an accepted/queued activation and an in-flight durable reservation until an ordinary user turn began at 10:21 Jerusalem time.
- 2026-09-15: That turn and subsequent task turns drained older deliveries one at a time; the exact delivery became delivered on attempt `1` at 10:33:05. This supports busy-after-current-work behavior for that session but does not prove a fresh idle wake.
- 2026-09-15: The durable reservation cleared after delivery admission before its persisted row could be captured. Legacy-fence causation therefore remains an evidence-backed inference, not a conclusion.
- 2026-09-15: Current recipient readiness reported `attempt_inflight` from `durable_reservation` with `next_natural_turn` fallback, while exact trace reported accepted native activation without payload admission. Neither surface identified the long stall or supplied an actionable supported recovery step.
- 2026-09-15: Fresh idle witness `relay-msg-2ec765dfc8094423a9804017d4c63cb1` targeted the rediscovered idle `dict-dev2` endpoint without any app follow-up. Codex started an autonomous turn, the hook injected exact delivery `relay-delivery-b4d46c3584284425b76d6ad03de2b45c`, and the recipient atomically replied `UNATTENDED-IDLE-OK idle-codex-20260915-1048`.
- 2026-09-15: Reply delivery `relay-delivery-f61a7d9ff7cf419b8c0d99dcf8b6a515` remained queued while this recipient was working, then entered this task at the next turn boundary. Exact trace records native acceptance at 08:00:54 UTC and delivery on attempt `1` at 08:02:29 UTC. This is the bounded busy-after-current-work witness.
- 2026-09-15: The installed summary reports hook execution `verified`, two accepted Codex deliveries awaiting later exact-recipient check-in, an oldest wait of `69225` seconds, and four incomplete traces. The dashboard carries these fields but its visible neutral guidance omits wait age, incomplete evidence, and the safe `pallium_relay_trace` / do-not-resend next step. The planned fix is presentation-only and reuses existing data.
- 2026-09-15: Fresh pre-edit Redline classified the exact presentation-only paths BLUE with no checkpoint. Risk remains Routine; complexity remains Simple.
- 2026-09-15: Implemented the presentation-only guidance in `app/dashboard.html` and extended `tests/dashboard_plain_language_renderer.mjs`. The full focused dashboard file passed: `57 passed in 28.18s`.
- 2026-09-15: Roadmap evidence now records the bounded idle and busy Codex witnesses, the diagnosability fix, and the remaining limits without claiming universal reliability.
- 2026-09-15: Full repository suite passed: `5017 passed, 34 skipped, 2 xfailed in 248.94s`. Final import-boundary report has zero violations; generated Redline verdict is BLUE with only the expected dashboard watch path; agent-workflow exits `0`; `git diff --check` passes.
- 2026-09-15: Astra high-reasoning result review returned APPROVE with no actionable findings after the shipped renderer contract and an additional 45-case state/count matrix. Residual limits are documented: no direct aggregate-to-oldest-delivery link, no browser layout replay, and no automatic stalled-activation repair.
