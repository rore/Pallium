# Local service delivery and summary reliability

<!-- agent-workflow:start -->
**Outcome:** Explain and fix the causes of accumulating waiting deliveries and repeated queue-summary timeouts without disrupting the user's installed environment.

**Target:** The replacement-budget, prerequisite-admission, bounded claim-timing and busy-recovery caller-surface tests.

**Scope:** Bounded diagnosis from existing source/logs and safe read-only evidence; distinguish summary query cost from shared service/storage contention and delivery lifecycle failures. Implement the smallest supported root-cause correction with observable caller-surface coverage. Coordinate with the existing Codex reconnect patch owner and reuse its evidence without overlapping or duplicating that qualification. Preserve the separate Hermes parity checkpoint.

**Constraints:** Keep installed services, applications, integrations, profiles, credentials, databases, configuration, PATH and the primary dirty checkout untouched. No restart, rollout, queue deletion, expiry/ACK manipulation, timeout relaxation, paid inference or protected-test weakening. Any necessary installed update requires a concrete impact/backup/rollback proposal and separate approval. Keep private settings and raw payloads out of docs, PRs and tracked evidence. Use isolated generated data and test homes. Avoid polling loops, marker chats, duplicate tests and competing host load. Preserve existing delivery identity, privacy, idempotency and custody contracts.

**Completion criteria:** Evidence separates or connects the two reported symptoms with explicit causal limits. A supported root cause is corrected and covered through actual HTTP/MCP/hook surfaces, including relevant empty, boundary, failure, concurrency and lifecycle cases. Existing reconnect qualification is reused truthfully. Focused/subsystem/full-lane and workflow evidence is retained; a clean independent reviewer accepts code and evidence. Coherent work is pushed and canonical owner state reconciled. No unapproved live activation is claimed.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Explain and fix the causes of accumulating waiting deliveries and repeated queue-summary timeouts without disrupting the user's installed environment.","scope":"Bounded diagnosis from existing source/logs and safe read-only evidence; distinguish summary query cost from shared service/storage contention and delivery lifecycle failures. Implement the smallest supported root-cause correction with observable caller-surface coverage. Coordinate with the existing Codex reconnect patch owner and reuse its evidence without overlapping or duplicating that qualification. Preserve the separate Hermes parity checkpoint.","constraints":"Keep installed services, applications, integrations, profiles, credentials, databases, configuration, PATH and the primary dirty checkout untouched. No restart, rollout, queue deletion, expiry/ACK manipulation, timeout relaxation, paid inference or protected-test weakening. Any necessary installed update requires a concrete impact/backup/rollback proposal and separate approval. Keep private settings and raw payloads out of docs, PRs and tracked evidence. Use isolated generated data and test homes. Avoid polling loops, marker chats, duplicate tests and competing host load. Preserve existing delivery identity, privacy, idempotency and custody contracts.","completion_criteria":"Evidence separates or connects the two reported symptoms with explicit causal limits. A supported root cause is corrected and covered through actual HTTP/MCP/hook surfaces, including relevant empty, boundary, failure, concurrency and lifecycle cases. Existing reconnect qualification is reused truthfully. Focused/subsystem/full-lane and workflow evidence is retained; a clean independent reviewer accepts code and evidence. Coherent work is pushed and canonical owner state reconciled. No unapproved live activation is claimed."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":["https://github.com/rore/Pallium/pull/395"]}

**Risk:** High

**Complexity:** Moderate

**Reason:** The task retains its accepted persistence scope and High classification. The current correction changes ordinary test setup, fault injection, timing observation and failure context while preserving caller success, stop, no-replay and durable-state requirements.

**Discovery:** The published diagnostic correction passed normal CI but its full manual run failed. The replacement-budget fixture did not reliably consume its native window, prerequisite registrations need isolated setup, and the bounded claim interval must measure the complete call rather than its HTTP subspan. Busy recovery remains unresolved.

**Material assumptions:** Semantic setup scopes preserve native storage and restore original clocks/providers before each subject. The replacement-budget fault consumes the unchanged real window. Timing observation delegates once without changing return or exception behavior. Bounded failure context does not repair busy recovery.

**Plan:** Retain the published diagnostic JSON and causal ACK ordering correction. Preserve the accepted Linux prerequisite fixtures. Make the replacement-budget fault consume its unchanged real deadline, with one completed injection and no interruption; preserve the original join, stop and no-replay predicates. Isolate only the initial Claude registration clock and assert immediate restoration, including failure. Measure the complete claim call with one unchanged delegate and retain the original 1800..2400 ms interval and HTTP subspan controls. Add bounded failure-only context to the unchanged busy-recovery success assertion. Preserve every original status, expiry, emission, ACK, cleanup and durable-state requirement. Prepare only the exact reviewed source and mandatory current-plan/evidence update; publication and meaningful changed-composition qualification remain separately selected.

**Verification plan:**
- Source identity -> verify all four accepted Windows test postimages, unchanged Linux fixtures, dependencies, full index inventory and exact six-code-file delta from the published parent.
- Replacement budget -> require one completed fault at or beyond the identical recorded native deadline with no interruption, followed by the original worker-stop and no-replay predicates.
- Setup and timing -> verify bounded prerequisite admission/restoration and the unchanged full-call timeout interval, delegate count and original caller controls.
- Busy recovery -> retain result-is-not-None and elapsed-under-two-seconds plus original native-writer, same-wire, claim, emission, ACK and durable-state assertions; diagnostic source acceptance does not clear its functional hold.
- Whole qualification -> after separately admitted publication, execute the changed composition in existing full normal CI; retain first failures and raw results before correction or rerun. Full Windows/native and independent result acceptance remain separate gates.

**Plan review:** Agent technical review: Independent review accepted the unchanged Linux fixture corrections and the four new Windows test changes at their exact source revisions, including direct finish-at-or-after-deadline arithmetic and the unchanged busy-recovery success predicate. This is source acceptance only. Final public-record/composition review and changed-composition runtime/result verification remain pending.

**Approvals:** Approved by user 2026-11-05: "Approve the exact isolated plan".

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Verification status

The binding slice merged in [PR #395](https://github.com/rore/Pallium/pull/395). The published diagnostic/ordering correction passed [normal CI](https://github.com/rore/Pallium/actions/runs/42579966719). Its [full manual qualification](https://github.com/rore/Pallium/actions/runs/42581487113) failed: Linux 3.12 had two failures, Windows 3.12 three, and Windows 3.13 failed the original replacement-budget worker-stop predicate. Linux 3.13 and Windows smoke passed. All first failures remain retained; normal green does not replace full qualification. Earlier phase-fixture [normal](https://github.com/rore/Pallium/actions/runs/42469331723) and [manual](https://github.com/rore/Pallium/actions/runs/42469428642) failures also remain failed evidence.

Independent source review accepted the Linux prerequisite corrections and four Windows test changes. Their composed runtime behavior remains unexecuted. The complete retained 16-entry failure snapshot is not an entire worker lifecycle or physical-cause proof. Busy recovery remains on functional hold; its new context changes reporting only. Source acceptance establishes no product repair, current-platform pass or installed recovery. Changed-composition full CI, full Windows/native evidence and independent result review remain open.
