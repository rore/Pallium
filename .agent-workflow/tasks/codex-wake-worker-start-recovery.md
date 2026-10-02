<!-- agent-workflow:start -->
**Outcome:** Recover a pending Codex wake when prewrite deferral or worker-start failure is followed by failed durable release.

**Target:** Existing Codex wake scheduler.

**Scope:** Failed worker-start and retained prewrite-deferral schedule cleanup, HTTP lifecycle regressions and canonical roadmap.

**Constraints:** Clear only the matching local generation marker in proven prewrite failure paths. Preserve durable prepared authority checks, accepted and uncertain fences, hook-owned ACK and all existing transport behavior. No live reservation mutation, resend or infrastructure.

**Completion criteria:** Reproduce the failure, recover in the same process with one native attempt and normal claim/ACK, pass required validation and independent review, merge and verify the installed service.

**Requirement baseline:**
{"source":"2026-10-02 user: And continue till we squash all bugs","outcome":"Recover a pending Codex wake when prewrite deferral or worker-start failure is followed by failed durable release.","scope":"Failed worker-start and retained prewrite-deferral schedule cleanup, HTTP lifecycle regressions and canonical roadmap.","constraints":"Clear only the matching local generation marker in proven prewrite failure paths. Preserve durable prepared authority checks, accepted and uncertain fences, hook-owned ACK and all existing transport behavior. No live reservation mutation, resend or infrastructure.","completion_criteria":"Reproduce the failure, recover in the same process with one native attempt and normal claim/ACK, pass required validation and independent review, merge and verify the installed service."}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Gray runtime scheduler path; no durable authority or transport change.

**Discovery:** Independent read-only diagnosis confirmed Thread.start RuntimeError plus failed SQLite release leaves a local marker that suppresses prepared recovery. No worker has started in this branch. Existing cleanup compares generation.

**Material assumptions:** A failed Thread.start has not run the worker. SQLite errors return a failed release; prepared recovery retains its exact prewrite CAS.

**Plan:** Invoke Agent Workflow and classify before code edits. Clear the matching schedule marker after failed start or retained retry-safe prewrite deferral regardless of durable release success; leave the legacy post-spend path unchanged. Reuse HTTP lifecycle tests for same-process recovery, then focused/affected/selector validation, independent review and rollout.

**Verification plan:** Same-process recovery -> HTTP send with worker-start and durable-release failure, resume through existing recovery, exactly one native call and normal turn/ACK/readback. Fence preservation -> existing wake subsystem regressions. Whole change -> selector-required checks and full suite once.

**Plan review:** Agent technical review: /root/service_handoff_security accepted the exact handler-only change on 2026-10-02. No worker can have written; surviving prepared authority still requires reconciliation and prewrite CAS. Matching-generation cleanup preserves newer markers.

**Approvals:** User authorized continued Relay bug fixes on 2026-10-02. No new action authority or ambiguous retry is introduced.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

Canonical roadmap: `roadmap/features/add-wake-first-relay-delivery.md`.

## Implementation

Pre-edit classification: GRAY, no boundary violations or checkpoints. Independent plan review accepted. Implementation underway on feat/codex-wake-worker-start-recovery. Root found the same release-failure dependency after retained retry-safe prewrite deferral. Independent service_handoff_security accepted both prewrite cleanups before the sibling edit; legacy post-spend cleanup stays unchanged. HTTP regressions cover both triggers.

Both cases reproduced failure at same-process recovery before the production
change and passed afterward. The final affected suite passed 324 tests in
90.84 seconds; import boundaries passed. Full selector validation passed
5,955 tests, 34 skipped and 2 expected failures in 298.07 seconds.
Evidence: `build/codex-worker-start-affected.txt`,
`build/codex-worker-start-imports.json`, `build/codex-worker-start-full.txt`.

## Result review

Agent technical review: /root/service_handoff_security, independent non-implementer review on 2026-10-02.

Reviewed revision: app blob cd389e57a05f614400c4143abbb3af17c241a8ea; test blob cbdec10ae4bc8e258ebed22bddfd8b3b535227a9.

Verification adequacy: Accepted both proven prewrite cleanup branches and the
parametrized HTTP lifecycle regression. Tests assert prepared state with zero
native calls, same-generation recovery, one native attempt, repeat-recovery
deduplication, payload claim/ACK and delivered readback. Durable fences and the
legacy post-CAS path are unchanged. Affected and full validation passed.
