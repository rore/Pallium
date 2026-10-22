# Local service delivery and summary reliability

<!-- agent-workflow:start -->
**Outcome:** Explain and fix the causes of accumulating waiting deliveries and repeated queue-summary timeouts without disrupting the user's installed environment.

**Target:** Relay delivery/activation and dashboard summary read paths, their isolated regressions and operational documentation where behavior changes.

**Scope:** Bounded diagnosis from existing source/logs and safe read-only evidence; distinguish summary query cost from shared service/storage contention and delivery lifecycle failures. Implement the smallest supported root-cause correction with observable caller-surface coverage. Coordinate with the existing Codex reconnect patch owner and reuse its evidence without overlapping or duplicating that qualification. Preserve the separate Hermes parity checkpoint.

**Constraints:** Keep installed services, applications, integrations, profiles, credentials, databases, configuration, PATH and the primary dirty checkout untouched. No restart, rollout, queue deletion, expiry/ACK manipulation, timeout relaxation, paid inference or protected-test weakening. Any necessary installed update requires a concrete impact/backup/rollback proposal and separate approval. Keep private settings and raw payloads out of docs, PRs and tracked evidence. Use isolated generated data and test homes. Avoid polling loops, marker chats, duplicate tests and competing host load. Preserve existing delivery identity, privacy, idempotency and custody contracts.

**Completion criteria:** Evidence separates or connects the two reported symptoms with explicit causal limits. A supported root cause is corrected and covered through actual HTTP/MCP/hook surfaces, including relevant empty, boundary, failure, concurrency and lifecycle cases. Existing reconnect qualification is reused truthfully. Focused/subsystem/full-lane and workflow evidence is retained; a clean independent reviewer accepts code and evidence. Coherent work is pushed and canonical owner state reconciled. No unapproved live activation is claimed.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Explain and fix the causes of accumulating waiting deliveries and repeated queue-summary timeouts without disrupting the user's installed environment.","scope":"Bounded diagnosis from existing source/logs and safe read-only evidence; distinguish summary query cost from shared service/storage contention and delivery lifecycle failures. Implement the smallest supported root-cause correction with observable caller-surface coverage. Coordinate with the existing Codex reconnect patch owner and reuse its evidence without overlapping or duplicating that qualification. Preserve the separate Hermes parity checkpoint.","constraints":"Keep installed services, applications, integrations, profiles, credentials, databases, configuration, PATH and the primary dirty checkout untouched. No restart, rollout, queue deletion, expiry/ACK manipulation, timeout relaxation, paid inference or protected-test weakening. Any necessary installed update requires a concrete impact/backup/rollback proposal and separate approval. Keep private settings and raw payloads out of docs, PRs and tracked evidence. Use isolated generated data and test homes. Avoid polling loops, marker chats, duplicate tests and competing host load. Preserve existing delivery identity, privacy, idempotency and custody contracts.","completion_criteria":"Evidence separates or connects the two reported symptoms with explicit causal limits. A supported root cause is corrected and covered through actual HTTP/MCP/hook surfaces, including relevant empty, boundary, failure, concurrency and lifecycle cases. Existing reconnect qualification is reused truthfully. Focused/subsystem/full-lane and workflow evidence is retained; a clean independent reviewer accepts code and evidence. Coherent work is pushed and canonical owner state reconciled. No unapproved live activation is claimed."}

**Relationships:**
{"schema_version":1,"sources":[],"pull_requests":[]}

**Risk:** High

**Complexity:** Moderate

**Reason:** Shared local availability and delivery custody may involve Relay lifecycle, persistence and runtime boundaries. Dashboard-only reads are gray/watch, tests blue; potential shared Relay/storage changes require architecture/persistence checkpoints before edits.

**Discovery:** The manager reports two bounded ten-second summary timeouts, while an MCP trace still answered; these do not establish a shared cause or general service failure. Source-only inspection finds many aggregate/count queries, unbounded historical trace grouping and all last-day latency rows in the summary endpoint. This is a read-amplification candidate, not measured causation. The existing reconnect owner explicitly does not own summary/waiting diagnosis; its separate bounded client recovery patch has one final full qualification active.

**Material assumptions:** Waiting deliveries and summary latency may be separate symptoms. Historical evidence does not establish current service state. Existing live databases/payloads are not test fixtures; use bounded metadata/log inspection and isolated generated reproductions. No runtime correction is justified until an observable failure and cause are established.

**Plan:** Invoke Agent Workflow, create this baseline and classify risk before code edits. Verify actual checkout, owner/run state and existing operational evidence. Perform bounded read-only discovery, then specify the smallest correction and relevant risk checkpoints for independent technical plan review before implementation. Preserve public contracts and do not import an unqualified reconnect patch. Add caller-surface causal regressions and focused verification, then selected subsystem/full-lane checks without duplicating the active owner run. Obtain independent result review, reconcile owner state and push the concrete result. Present rollout separately only if needed.

**Verification plan:**
- Cause and symptom separation -> bounded source/log evidence and isolated generated workload/reproduction, with explicit unavailable measurements.
- Queue/summary observable behavior -> real HTTP/MCP/hook E2E using isolated stores, asserting exact output/lifecycle and query cost where causally relevant.
- Safety and regression -> focused nodes, affected subsystem, whole-change test selector/full lane, import boundaries and workflow checks; protected contracts unchanged.
- Completion -> independent code/evidence acceptance, pushed revision and owner handoff; no installed activation inferred.

**Plan review:** Pending concrete diagnosis and implementation plan; no product edit authorized by an unreviewed mechanism.

**Approvals:** Manager chat 01a16320-c588-72b0-a098-cb3d137b1e75 relayed the user's explicit assignment on 2026-10-22: "assign someone to own the local service reliability investigation and drive it to a fix. waiting messages and queue timeouts are the priority, keep overhead minimal". The manager assigned this chat sole investigation/fix ownership, with existing reconnect work retained by its owner. The human separately approved cross-chat communication directly here. Repository diagnosis/fix is authorized; live mutation remains separate and absent.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Workflow invoked before product edits. New managed worktree on exact merged main5d167936 and branch feat/local-service-reliability keeps Hermes parity and the primary dirty checkout independent. No application edits or new test executions yet.

## Evidence

Hermes parity checkpoint d63b5223921cbb5345e0e6e3496012b279fc5336 is clean/pushed. Its native artifact staging stopped before runtime launch on verified Windows Git archive CRLF versus Linux LF normalization; canonical blob and LF export match. Retained staging evidence needs a manifest/export correction when that work resumes. No Hermes native experiment is active.

Existing reconnect candidate production cb63998e0fc665700b3de70fdf7885a46b1aa1a4, aligned head58ae2262976ed61604719473801b8cd9704414e7, branch feat/codex-retained-idle-reenrollment, Work Record codex-retained-idle-reenrollment. Owner reports175 focused passes and accepted bounded causal matrix. Its one full qualification started12:40:23UTC with a twenty-minute cap; no duplicate/competing run is authorized here. Owner will deliver actual result. That patch does not explain the live HTTP timeout; no attribution is imported.

## Result review

Pending diagnosis, implementation and verification. No live change or completed reliability correction is claimed.
