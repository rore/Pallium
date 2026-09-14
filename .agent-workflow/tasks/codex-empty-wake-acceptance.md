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

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-09-15: Applicability requires the normal workflow because Work Records are never exempt. Clean-context pre-edit Redline classified the bounded documentation/Work Record scope BLUE/Routine with no checkpoint. Plan self-review found no runtime change and no justified roadmap board transition.
