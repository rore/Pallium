# Local service delivery and summary reliability

<!-- agent-workflow:start -->
**Outcome:** Explain and fix the causes of accumulating waiting deliveries and repeated queue-summary timeouts without disrupting the user's installed environment.

**Target:** OpenCode Relay binding lookup in `storage/sqlite_relay.py` and its HTTP coverage in `tests/test_opencode_relay_wake_e2e.py`.

**Scope:** Bounded diagnosis from existing source/logs and safe read-only evidence; distinguish summary query cost from shared service/storage contention and delivery lifecycle failures. Implement the smallest supported root-cause correction with observable caller-surface coverage. Coordinate with the existing Codex reconnect patch owner and reuse its evidence without overlapping or duplicating that qualification. Preserve the separate Hermes parity checkpoint.

**Constraints:** Keep installed services, applications, integrations, profiles, credentials, databases, configuration, PATH and the primary dirty checkout untouched. No restart, rollout, queue deletion, expiry/ACK manipulation, timeout relaxation, paid inference or protected-test weakening. Any necessary installed update requires a concrete impact/backup/rollback proposal and separate approval. Keep private settings and raw payloads out of docs, PRs and tracked evidence. Use isolated generated data and test homes. Avoid polling loops, marker chats, duplicate tests and competing host load. Preserve existing delivery identity, privacy, idempotency and custody contracts.

**Completion criteria:** Evidence separates or connects the two reported symptoms with explicit causal limits. A supported root cause is corrected and covered through actual HTTP/MCP/hook surfaces, including relevant empty, boundary, failure, concurrency and lifecycle cases. Existing reconnect qualification is reused truthfully. Focused/subsystem/full-lane and workflow evidence is retained; a clean independent reviewer accepts code and evidence. Coherent work is pushed and canonical owner state reconciled. No unapproved live activation is claimed.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Explain and fix the causes of accumulating waiting deliveries and repeated queue-summary timeouts without disrupting the user's installed environment.","scope":"Bounded diagnosis from existing source/logs and safe read-only evidence; distinguish summary query cost from shared service/storage contention and delivery lifecycle failures. Implement the smallest supported root-cause correction with observable caller-surface coverage. Coordinate with the existing Codex reconnect patch owner and reuse its evidence without overlapping or duplicating that qualification. Preserve the separate Hermes parity checkpoint.","constraints":"Keep installed services, applications, integrations, profiles, credentials, databases, configuration, PATH and the primary dirty checkout untouched. No restart, rollout, queue deletion, expiry/ACK manipulation, timeout relaxation, paid inference or protected-test weakening. Any necessary installed update requires a concrete impact/backup/rollback proposal and separate approval. Keep private settings and raw payloads out of docs, PRs and tracked evidence. Use isolated generated data and test homes. Avoid polling loops, marker chats, duplicate tests and competing host load. Preserve existing delivery identity, privacy, idempotency and custody contracts.","completion_criteria":"Evidence separates or connects the two reported symptoms with explicit causal limits. A supported root cause is corrected and covered through actual HTTP/MCP/hook surfaces, including relevant empty, boundary, failure, concurrency and lifecycle cases. Existing reconnect qualification is reused truthfully. Focused/subsystem/full-lane and workflow evidence is retained; a clean independent reviewer accepts code and evidence. Coherent work is pushed and canonical owner state reconciled. No unapproved live activation is claimed."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":["https://github.com/rore/Pallium/pull/395"]}

**Risk:** High

**Complexity:** Moderate

**Reason:** The lookup changes a persistence and endpoint ownership path. The correction keeps the existing schema, API, and transaction boundaries.

**Discovery:** The OpenCode binding lookup reads the endpoint, scope generation, and wake registration separately. Polling and exact claim both use this lookup.

**Material assumptions:** The endpoint key and child-row relationships support one joined read. A lower SELECT count establishes query cost for this lookup. Installed response time and recovery need separate evidence.

**Plan:** Use one SQLite SELECT with outer joins for the binding lookup. Preserve ORM row identity, missing-row handling, validation order, both existing transactions, enrollment and lease checks, and claim and receipt behavior. Keep the binding implementation and its regression coverage in the two named files. In `tests/test_relay_shadow_snapshot.py`, apply the counted fixture only to the initial HTTP registration. In `tests/test_codex_wake_lifecycle.py`, apply it only to the two initial direct registrations in each offline upgrade case. Restore native timing before the behavior under test. Return material composition drift to review.

**Verification plan:**
- Verify one SELECT per binding through HTTP enrollment, poll, stale snapshot, exact claim, ACK, and response replay.
- Verify missing and mismatched bindings and preserve the 404 precedence over a stale scope generation.
- Verify the exact proposed tree through ordinary full Linux CI, Windows smoke, and governance. Verify the changed cases in the Linux results and keep full Windows and installed qualification separate.

**Plan review:** Agent technical review: Independent review of the OpenCode binding plan, prerequisite scopes, and exact composition.

**Approvals:** Approved by user 2026-11-05: "Approve the exact isolated plan". This approval covers the original two-file binding plan and its isolated verification. On 2026-11-06 the task owner accepted the completed binding result for merge with ordinary PR CI. Full Windows qualification remains separate for rollout.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Verification status

[Ordinary PR CI](https://github.com/rore/Pallium/actions/runs/42207728386/attempts/2) passed on Linux 3.12 and 3.13, including all 11 binding and fixture cases in each lane. Windows smoke and [governance](https://github.com/rore/Pallium/actions/runs/42207728338) also passed. Full Windows and installed behavior and performance remain unverified. The persistence checkpoint is pending.

## Result review

Agent technical review: Independent result review of the [OpenCode binding change](https://github.com/rore/Pallium/pull/395) on 2026-11-06.
Reviewed revision: `8b81c8833abb69f93eb02f7b5cf6008554d9ad6c` with merge preview `8d5408da67603eefbda36fa6413e78158e389af2`.
Verification adequacy: Accepted for the reviewed binding slice. The Linux results cover the single-query lookup, rejection precedence, exact claim and acknowledgment, and the corrected setup cases. Windows smoke covers the ordinary Windows lane. Full Windows qualification remains a rollout requirement.
