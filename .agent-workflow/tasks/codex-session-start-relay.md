<!-- agent-workflow:start -->
**Outcome:** The retained authenticated Codex MCP owner action wakes an unloaded target; its SessionStart hook injects and ACKs a pending Relay delivery.

**Target:** Codex SessionStart hook and focused caller tests.

**Scope:** Preserve the tested two-second SessionStart Relay turn, format, emit, and ACK branch for the retained authenticated MCP connection path. Restore only this task's focused hook tests.

**Constraints:** No deep link, queue-adapter change, live retry, prompt/settings/cwd override, or new connection mechanism. Preserve clear behavior, exact runtime-owned scope, bounded deadline, emit-before-ACK, and fail-closed errors. Root owns installation/live qualification.

**Completion criteria:** Recovered source matches the prior reviewed Git blob and focused caller tests pass. Retained MCP wake delivery remains separately subject to root's live proof.

**Requirement baseline:** {"source":"root-delegated user override 2026-10-01","outcome":"SessionStart injects pending Relay delivery","scope":"Codex SessionStart and focused caller tests","constraints":"reuse existing hook primitives; no live action or publication","completion_criteria":"caller-visible delivery before orientation and safe ACK lifecycle"}

**Behavior changes:** [{"target": "task-context.outcome", "classification": "equivalent", "before": "SessionStart injects pending Relay delivery", "after": "The retained authenticated Codex MCP owner action wakes an unloaded target; its SessionStart hook injects and ACKs a pending Relay delivery.", "reason": "Expand the original hook-recovery shorthand without changing the delegated recovery obligation or granting a live action."}, {"target": "task-context.scope", "classification": "equivalent", "before": "Codex SessionStart and focused caller tests", "after": "Preserve the tested two-second SessionStart Relay turn, format, emit, and ACK branch for the retained authenticated MCP connection path. Restore only this task's focused hook tests.", "reason": "Expand the original hook-recovery shorthand without changing the delegated recovery obligation or granting a live action."}, {"target": "task-context.constraints", "classification": "equivalent", "before": "reuse existing hook primitives; no live action or publication", "after": "No deep link, queue-adapter change, live retry, prompt/settings/cwd override, or new connection mechanism. Preserve clear behavior, exact runtime-owned scope, bounded deadline, emit-before-ACK, and fail-closed errors. Root owns installation/live qualification.", "reason": "Expand the original hook-recovery shorthand without changing the delegated recovery obligation or granting a live action."}, {"target": "task-context.completion_criteria", "classification": "equivalent", "before": "caller-visible delivery before orientation and safe ACK lifecycle", "after": "Recovered source matches the prior reviewed Git blob and focused caller tests pass. Retained MCP wake delivery remains separately subject to root's live proof.", "reason": "Expand the original hook-recovery shorthand without changing the delegated recovery obligation or granting a live action."}]

**Risk:** High

**Complexity:** Simple

**Reason:** The recovered hook is now reviewed as part of the whole retained-wake product change, whose MCP API and native custody changes set the High risk floor. This supersedes the original hook-only Elevated classification.

**Discovery:** At 10:41, the service-owned retained-MCP action activated an unloaded target but did not prove payload delivery. At 11:15, a manual app-owner wake with the tested two-second SessionStart branch proved payload and ACK. A separate abandoned deep-link/queue path caused a prompt-empty conflict. These witnesses do not yet establish service-owned retained-MCP activation plus payload/ACK in one end-to-end run. My interrupted rollback inadvertently restored the hook source/tests to HEAD; both have now been recovered from the prior reviewed diff.

**Material assumptions:** The retained authenticated source and exact recipient remain within the existing finite owner-action custody. If that custody is unavailable, no new action is attempted.

**Plan:** Restore the previously tested SessionStart source and focused tests; verify content identity and run the focused lane once. Stop. Root owns subsequent retained-connection action and installation.

**Verification plan:** Preserved hook behavior -> Git blob identity, twelve recovered SessionStart caller cases, and focused diff review for unrelated adapter changes.

**Plan review:** Agent technical review: /root/retained_product_review, 2026-10-01. Independently reviewed the unchanged recovered hook, all twelve caller cases, and the 12:25 retained wake witness during product integration review. This is current review evidence, not a claim of earlier independent plan review.

**Approvals:** Approved by user 2026-10-01: "ok, you can drive this" for product integration of the proven retained wake and payload hook. User subsequently approved the exact state-based transport choice with "ok" after the architect recommendation. User requested quick local iterations without PR or full-suite wait. No new live action or publication is authorized by this recovery record.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

The proven two-second SessionStart source and twelve focused tests were restored after my accidental `git restore`. No deep-link or queue-adapter code was written. Root's separate retained MCP owner-action path is the only intended activation path.

## Evidence

Restored hook source hashes to Git blob `5dad101d2dfd4cba829c89671c1ece67c2281d60`, the same reviewed content as before the accidental revert. Raw working-file SHA-256 differs from root's earlier `836c1b...` due to mixed line endings; Git-normalized source content matches. Recovered focused cases: 12 passed, 90 deselected in 0.29s. `git diff --check` passed. No full suite by user process waiver.

## Result review

Recovery complete for root review. Service-owned retained-MCP unloaded activation and manual app-owner payload/ACK are separate witnesses; their combination remains unproven. No new live action by this worker.

Agent technical review: /root/retained_product_review, 2026-10-01.

Reviewed revision: hook Git blob 5dad101d2dfd4cba829c89671c1ece67c2281d60 and unchanged recovered twelve caller cases.

Verification adequacy: focused cases and the subsequent 12:25 service-owned witness cover this bounded hook recovery. Shared validation, bounded deadline, emit-before-ACK, clear behavior and error paths are preserved; no new hook finding. General automatic lifecycle remains separate work.

## Subsequent root evidence — 2026-10-01

The recovery-stage statements above are historical. The later service-owned retained MCP witness at 12:25 UTC established unloaded target payload emission and ACK in one run, independently accepted by /root/service_handoff_security. Exact evidence: build/codex-retained-session-start-witness-20261001-1225.json. This does not establish the new automatic lifecycle, busy-turn behavior, or general restart reliability. Current integration continues under codex-retained-wake-product; no PR or full suite in this local iteration under the direct user instruction.
