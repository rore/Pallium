# Local service delivery and summary reliability

<!-- agent-workflow:start -->
**Outcome:** Explain and fix the causes of accumulating waiting deliveries and repeated queue-summary timeouts without disrupting the user's installed environment.

**Target:** The replacement-budget diagnostic and shared-wake ACK ordering tests.

**Scope:** Bounded diagnosis from existing source/logs and safe read-only evidence; distinguish summary query cost from shared service/storage contention and delivery lifecycle failures. Implement the smallest supported root-cause correction with observable caller-surface coverage. Coordinate with the existing Codex reconnect patch owner and reuse its evidence without overlapping or duplicating that qualification. Preserve the separate Hermes parity checkpoint.

**Constraints:** Keep installed services, applications, integrations, profiles, credentials, databases, configuration, PATH and the primary dirty checkout untouched. No restart, rollout, queue deletion, expiry/ACK manipulation, timeout relaxation, paid inference or protected-test weakening. Any necessary installed update requires a concrete impact/backup/rollback proposal and separate approval. Keep private settings and raw payloads out of docs, PRs and tracked evidence. Use isolated generated data and test homes. Avoid polling loops, marker chats, duplicate tests and competing host load. Preserve existing delivery identity, privacy, idempotency and custody contracts.

**Completion criteria:** Evidence separates or connects the two reported symptoms with explicit causal limits. A supported root cause is corrected and covered through actual HTTP/MCP/hook surfaces, including relevant empty, boundary, failure, concurrency and lifecycle cases. Existing reconnect qualification is reused truthfully. Focused/subsystem/full-lane and workflow evidence is retained; a clean independent reviewer accepts code and evidence. Coherent work is pushed and canonical owner state reconciled. No unapproved live activation is claimed.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Explain and fix the causes of accumulating waiting deliveries and repeated queue-summary timeouts without disrupting the user's installed environment.","scope":"Bounded diagnosis from existing source/logs and safe read-only evidence; distinguish summary query cost from shared service/storage contention and delivery lifecycle failures. Implement the smallest supported root-cause correction with observable caller-surface coverage. Coordinate with the existing Codex reconnect patch owner and reuse its evidence without overlapping or duplicating that qualification. Preserve the separate Hermes parity checkpoint.","constraints":"Keep installed services, applications, integrations, profiles, credentials, databases, configuration, PATH and the primary dirty checkout untouched. No restart, rollout, queue deletion, expiry/ACK manipulation, timeout relaxation, paid inference or protected-test weakening. Any necessary installed update requires a concrete impact/backup/rollback proposal and separate approval. Keep private settings and raw payloads out of docs, PRs and tracked evidence. Use isolated generated data and test homes. Avoid polling loops, marker chats, duplicate tests and competing host load. Preserve existing delivery identity, privacy, idempotency and custody contracts.","completion_criteria":"Evidence separates or connects the two reported symptoms with explicit causal limits. A supported root cause is corrected and covered through actual HTTP/MCP/hook surfaces, including relevant empty, boundary, failure, concurrency and lifecycle cases. Existing reconnect qualification is reused truthfully. Focused/subsystem/full-lane and workflow evidence is retained; a clean independent reviewer accepts code and evidence. Coherent work is pushed and canonical owner state reconciled. No unapproved live activation is claimed."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":["https://github.com/rore/Pallium/pull/395"]}

**Risk:** High

**Complexity:** Moderate

**Reason:** The task retains its accepted persistence scope and High classification. This correction changes two ordinary test assertions only.

**Discovery:** Pytest abbreviated a bounded diagnostic dictionary; coarse clock ticks can be equal after causal ACK ordering is already established.

**Material assumptions:** Diagnostic serialization changes reporting only. Causal ACK-before-release assertions remain the ordering oracle.

**Plan:** Serialize the bounded failure-only observation dictionary with the existing JSON import. Permit equal monotonic ticks in the final consistency check. Preserve the worker-stop predicate, join, sample, phase observations, cleanup and causal ACK/count/durable-state assertions.

**Verification plan:**
- Existing binding behavior → reuse the accepted merged binding evidence without implying installed acceptance.
- Diagnostic and ordering cases → run the corrected composition in ordinary full CI and existing full Windows 3.12/3.13 jobs, retaining raw outcomes and any complete failure-only JSON.
- Full qualification → retain every first failure and inspect serial, remaining, Linux, Windows smoke, governance and aggregate outcomes separately.

**Plan review:** Agent technical review: Independent source review accepted the phase observations and both test-line corrections. Runtime verification remains separate from the accepted binding result.

**Approvals:** Approved by user 2026-11-05: "Approve the exact isolated plan".

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Verification status

The binding slice merged in [PR #395](https://github.com/rore/Pallium/pull/395). The phase fixture [ordinary CI](https://github.com/rore/Pallium/actions/runs/42469331723) and [manual full run](https://github.com/rore/Pallium/actions/runs/42469428642) failed. Both manual full Windows lanes failed; the worker-stop case failed on Windows 3.12 and passed on 3.13 with another failure. The two-line correction is unexecuted. Source acceptance does not establish a product repair, worker cause or installed performance.
