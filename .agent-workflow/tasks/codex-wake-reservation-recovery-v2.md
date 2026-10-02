<!-- agent-workflow:start -->
**Outcome:** Recover abandoned pre-write Codex wake reservations without repeating a wake that may already have been submitted.

**Target:** Existing Relay wake registry, SQLite reservation transitions and native wake callers.

**Scope:** Resume the blocked reservation portion of `codex-wake-reservation-recovery`; durable prepared provenance and exact pre-write transition, existing scheduler recovery, caller-surface regressions and relevant docs/roadmap. PR #279 connection recovery is already shipped and remains intact.

**Constraints:** Only a new durable prepared generation proves no native attempt. Existing reserved, accepted and uncertain generations remain fenced. An expired prior hook claim may lead to a new prepared generation only through the existing exact claim reconciliation; it does not authorize replay of the old generation. Consume prepared authority atomically before any native write. Preserve endpoint/scope checks, busy deferral, hook-owned ACK, cancellation fences and no ambiguous retries. No live DB reset, resend, manual wake or new infrastructure. Renewed approval does not bypass automatic review.

**Completion criteria:** The abandoned-pre-write regression and expired-prior-claim replacement journey pass through caller surfaces; concurrent/restart recovery permits at most one native attempt; legacy and submitted/uncertain generations never replay; focused and selector-required checks and independent review pass; publish, merge and install through the existing wrapper with health verification. Report remaining legacy fences truthfully.

**Requirement baseline:**
{"source": "2026-10-02 direct user reply: I approve, after status identifying rejected reservation recovery", "outcome": "Recover abandoned pre-write Codex wake reservations without repeating a wake that may already have been submitted.", "scope": "Resume the blocked reservation portion of `codex-wake-reservation-recovery`; durable prepared provenance and exact pre-write transition, existing scheduler recovery, caller-surface regressions and relevant docs/roadmap. PR #279 connection recovery is already shipped and remains intact.", "constraints": "Only a new durable prepared generation proves no native attempt. Existing reserved, accepted and uncertain generations remain fenced. An expired prior hook claim may lead to a new prepared generation only through the existing exact claim reconciliation; it does not authorize replay of the old generation. Consume prepared authority atomically before any native write. Preserve endpoint/scope checks, busy deferral, hook-owned ACK, cancellation fences and no ambiguous retries. No live DB reset, resend, manual wake or new infrastructure. Renewed approval does not bypass automatic review.", "completion_criteria": "The abandoned-pre-write regression and expired-prior-claim replacement journey pass through caller surfaces; concurrent/restart recovery permits at most one native attempt; legacy and submitted/uncertain generations never replay; focused and selector-required checks and independent review pass; publish, merge and install through the existing wrapper with health verification. Report remaining legacy fences truthfully."}

**Risk:** High

**Complexity:** Moderate

**Reason:** Durable action authority crosses the storage persistence boundary; a faulty recovery predicate could duplicate an external wake.

**Discovery:** PR #279 repaired retained connection loss. The independent reserved-generation starvation remains. Prior saved partial patch lacks correct handling of newly prepared replacement generations whose delivery retains an expired claimed state; it must not be applied blindly. Prior rejections and evidence are preserved in build/codex-wake-recovery-rejected-delta.txt and build/codex-wake-reservation-blocked.patch.

**Material assumptions:** New prepared provenance can be consumed through existing exact-row SQLite transactions. Trace or age cannot prove an old generation was unsent. A new prepared generation after expired-claim reconciliation is distinct from its prior attempted generation.

**Plan:** Invoke Agent Workflow and classify risk before editing production code. Refresh independent review of the minimal prepared-generation/CAS design. Record and submit the exact renewed user-authorized change to normal approval review. Implement only if accepted; stop on a new rejection. Reuse existing scheduler, locks and transactions; correct all native write callers together. Add focused caller-surface red-green tests, required validation, independent result review, PR/CI/merge and installed wrapper health checks.

**Verification plan:** Caller-visible recovery and denial criteria -> Existing HTTP/MCP/hook journeys exercise fresh unsent abandonment, service restart, competing registries and expired prior claim replacement. Denials cover legacy reserved, accepted/uncertain, active claims, stale generation, wrong endpoint/scope and database error. Native writes must follow one successful exact prepared-to-uncertain transition. Run focused -n 0, affected subsystem, selector-required full once and independent review. Do not mutate live reservations to demonstrate success.

**Plan review:** Agent technical review: /root/service_handoff_security, refreshed 2026-10-02 prepared-generation plan review. Refreshed independent review by /root/service_handoff_security accepted the future-row prepared provenance and exact-generation CAS plan. Both reconciliation and pre-write CAS must validate effective pending state, exact endpoint and active wake target inside the existing SQLite immediate transaction. A newly prepared replacement after an expired prior claim is eligible; an active claim and old reserved/accepted/uncertain generations are not. Both native callers consume prepared authority before writing. Accepted settlement may retain same-generation claim-correlation bookkeeping without granting another write. Concurrent recovery and crash-boundary caller regressions are required. This technical acceptance does not bypass normal automatic approval review.

**Approvals:** Approved by user 2026-10-02: "I approve". Direct reply to the status stating that automatic review rejected reservation recovery despite earlier exact approval, citing duplicate-wake risk. This renews authorization for the reservation-recovery fix while preserving the explicit no-replay constraints. Earlier exact approval was "Approve this exact recovery case" in reply to call_K7Z3hfdy04YAGF5ZeH7Z09V3, limited to a new durable prepared replacement after an expired prior hook claim. No fabricated source item ID is supplied.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

Canonical roadmap: `roadmap/features/add-wake-first-relay-delivery.md`. Existing completed connection repair and historical rejection evidence remain in the prior Work Record. New branch resumes only the unfinished reservation defect under renewed human approval; no production change has yet been applied.

Persistence review: exact current prepared row transitions atomically to uncertain before native action. Old rows are never relabelled. At most one native attempt is promised per generation, not per delivery across the existing expired-claim retry lifecycle.

## Implementation

The HTTP restart regression reproduced the blocked reservation and passed after
prepared recovery was implemented. Both native paths now require the pre-write
transition. Root and independent review identified and corrected the legacy
launch lock boundary and the persistent generic replacement authority path.
The latter retains reserved state; only validated reconciliation creates a
prepared retry generation. Focused/affected and full validation have passed;
no deployment or live reservation mutation has occurred.

## Verification

Caller restart starvation reproduced before the fix and passed afterward.
The final affected run passed 207 tests in test_codex_wake.py and
test_codex_wake_sqlite.py, plus 115 in test_codex_retained_wake.py. Coverage
includes HTTP claim/ACK, expired-claim replacement, competing SQLite registries,
active-claim denial, ambiguous fences, and pre-write exception recovery. Import
boundaries and git diff --check passed. The selector requires the full non-slow
suite. The first run stopped at a legacy fixture that bypassed the new CAS (2,350 passed). Related fixtures were corrected without weakening assertions; 19 lifecycle, 150 related tests and four corrected nodes passed. The complete retry passed 5,953 tests, 34 skipped and 2 expected failures in 297.16 seconds; output build/codex-reservation-v2-full-final.txt.

## Result review

Agent technical review: /root/service_handoff_security, independent result
review on 2026-10-02.

Reviewed revision: working-tree Git blobs bridge d8d60bf9,
app wake 75bbbb61, core a0cfdc53, SQLite 7732551a; tests
719f77ed/f62f4f56/21a540a0.

Verification adequacy: the 322 affected tests cover
the changed caller contracts and the reviewed assertions were not weakened.
Both authority-boundary findings and the pre-CAS scheduler-cleanup finding were
fixed. Final test-only review accepted codex_wake 1ce224a9, lifecycle 3a9264be, trace 140e2f34, contract f03a715d and health b10c770c after explicit CAS/settlement setup corrections. Full-suite completion is green. Existing legacy reservations
remain fenced; this is not a new live Desktop receipt witness.
