<!-- agent-workflow:start -->
**Outcome:** Relay recovery acceptance is closed with exact live evidence for the original Codex witness, one real current-session work-association lifecycle, separately qualified Claude evidence, and an honest classification of the remaining historical backlog.

**Target:** Pallium Relay acceptance record.

**Scope:** This Work Record; an acceptance addendum in `.agent-workflow/tasks/codex-empty-wake-diagnostic.md`; and the existing R1.5 acceptance prose in `roadmap/ideas/idea-agent-relay.md`.

**Constraints:** No runtime, API, schema, test, integration, or service change. Use the real `git:github.com/rore/pallium` / `codex-empty-wake-diagnostic` work pair; detach only the explicit association created by this check and preserve unrelated work references. Do not claim send acceptance proves receipt, do not mutate or delete historical backlog, and identify every unverified or host-blocked check.

**Completion criteria:** Live reads prove the original witness was processed and replied to; the current session completes attach -> authoritative readback -> detach -> absence for the real task pair without disturbing its existing association; Claude evidence and the remaining backlog are classified separately; the owning roadmap and original Work Record record the bounded closure and residuals.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Independent pre-edit Redline review classified all intended Work Record and roadmap paths BLUE with no boundary, contract, checkpoint, or runtime-config finding.

**Approach:** Reuse existing payload-free Relay trace, summary, session, and work-reference operations. Record only authoritative live results, then add a short acceptance addendum to existing artifacts; leave `roadmap/board.md` unchanged because the parent Relay track remains in progress and its trace item is already Done.

**Verification:** Exact Relay trace/status reads; `pallium_relay_work_refs`, attach, readback, participants, detach, and final readback; dashboard payload-free backlog grouping; `git diff --check`; fresh Redline and agent-workflow checks; PR CI.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-15: Applicability requires the normal workflow because Work Records are never exempt. Clean-context pre-edit Redline classified the bounded documentation/Work Record scope BLUE/Routine with no checkpoint. Plan self-review found no runtime change and no justified roadmap board transition.
- 2026-09-15: Exact trace proves the original Codex recovery witness is delivered to this session. The session created the requested Relay reply; its recipient delivery is still effective pending after an elapsed claim lease, so receipt is explicitly unverified.
- 2026-09-15: The real task association completed attach, list readback, participant lookup, detach, and final absence. Only the newly created explicit origin was removed; the unrelated `add-relay-delivery-trace` association remained.
- 2026-09-15: Claude evidence was classified independently: one existing ready-endpoint wake is delivered after `peer_frame_written`; one busy endpoint retains a pending natural-turn fallback. No fresh Claude round trip was run.
- 2026-09-15: The payload-free backlog snapshot records 25 pending deliveries: 19 recent/qualified and six dormant, with three unreachable, four older than 24 hours, and nine in diagnosed identity-collision groups. No backlog row was deleted or retargeted.
- 2026-09-15: Updated the original Work Record and existing R1.5 roadmap prose. The broader item remains in progress and `roadmap/board.md` remains unchanged because delivery trace is already Done. `apply_patch` failed once with the documented Windows 1327 sandbox error; the two named document updates used unique-anchor deterministic replacements.

## Evidence

- Original witness: `relay-delivery-eadfab5611454eabb6e7f7a986b07c7d` -> delivered, one attempt, exact intended endpoint. Reply: `relay-reply-fe163cbfec8ec4489ab94ca5dc621a52f05c27c5975ce226bec6c93cfe4c466d` -> outbound delivery pending; no receipt claim.
- Work association: canonical key `work:v1:212dc4ac176a6227a92b1550083e685458382292677b8ad91ce8680d7cfc6c3a`; authoritative attach/list/participant/detach/final-list results passed and preserved canonical key `work:v1:ebf22741389dc0d4420d608f2e4e3fd9957ecee08cd314d2754412a2bd28052f`.
- Claude: `relay-delivery-f7c2088765084310ad090fef9a7e889f` -> delivered on the active ready endpoint; the separate busy endpoint has one pending fallback.
- Installed registry: four entries, each exact-traced as effective pending on an active endpoint; no terminal stale fence.
- Fresh Redline verdict: BLUE, no boundary/API/schema/security/runtime-config finding or checkpoint. Import boundary report passed. Agent Workflow passed every blocking predicate after generating the required fresh verdict.
- Smart clean-context result review `/root/empty_wake_acceptance_review`: APPROVE, no actionable findings. Independent live reads reverified the original witness, pending reply, delivered Claude witness, and final association absence; the later 26-pending total was accepted as normal movement after the explicitly timestamped 25-item snapshot.
