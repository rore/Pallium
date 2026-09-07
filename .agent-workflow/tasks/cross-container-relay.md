<!-- agent-workflow:start -->
**Outcome:** Relay users can target one known endpoint or actor-global name across containers, with safe name takeover and no regular-send broadcast.

**Target:** Pallium Relay.

**Scope:** Relay endpoint/message/delivery persistence and migration; selector, naming, claim/reply/ACK/status, and wake routing; HTTP/MCP response contracts and agent instructions; focused caller-surface E2E, migration, wake, and regression tests; Relay docs after installed witnesses pass.

**Constraints:** Keep actor_ref as the trust boundary; keep container_ref as location/provenance; reuse RelaySessionRecord.id and the existing delivery engine; keep recipient listing container-local; preserve receipts, leases, idempotency, pending deliveries, and memory/history isolation; never silently resolve legacy ambiguity or alias collisions; reject bare-runtime sends without rows or wake; no broadcast API, coordination scopes, global discovery, or unrelated refactor.

**Completion criteria:** Exact endpoint IDs and actor-global names route one message across containers; name conflicts require explicit replace_existing takeover and transfer only the name; claims, replies, ACK/status, wake/recovery, lifecycle, migration, legacy ambiguity, actor isolation, validation boundaries, concurrency, and restart behavior pass through public HTTP/MCP/hook surfaces; existing Relay regressions pass; installed supported-runtime dogfood succeeds before public docs claim the feature.

**Risk:** High

**Complexity:** Large

**Reason:** Redline reports SCHEMA_CHANGE + API_CHANGE on persistence and public Relay contracts. High because endpoint identity, actor isolation, alias ownership, and queued delivery routing change; Large because persistence, HTTP/MCP, wake adapters, integrations, migration, and independent E2E outcomes are involved.

**Discovery:** Current code keys sessions and all send/claim/reply/status/ACK/wake paths through container_ref plus runtime/native session. RelaySessionRecord.id already provides a durable canonical ID but is not exposed. Messages lack sender endpoint ID; deliveries lack recipient endpoint ID/location. Bare runtime selectors broadcast. Alias uniqueness and resolution are container/runtime scoped. The split Relay DB migration copies ORM rows once and needs additive source/target column handling. Claude architecture review found endpoint-ID-first ordering mandatory to avoid reply failures, ambiguous legacy 500s, and inbox adoption. Redline requires persistence-review and api-review; no forbidden import is planned. Roadmap prerequisites RW-012–014 are fixed.

**Material assumptions:**
- RelaySessionRecord.id can be exposed as the canonical exact address without a second identity layer. Disproved by a lifecycle or integration path that cannot retain it; if disproved, return to planning before schema edits.
- actor_ref is the sole local trust boundary. Endpoint IDs select and bind destinations; they do not authenticate a caller. Same-actor callers holding object IDs retain the existing trusted capability to inspect status and, with the existing receipt/claim rules, ACK or reply. Disproved by a requirement for per-endpoint caller authorization; then stop because runtime-owned authentication is a separate design.
- A small Relay alias registry keyed by (actor_ref, normalized alias) can durably represent either one owner endpoint or an unresolved legacy collision while RelaySessionRecord.alias remains a compatibility view. Disproved if split migration or lifecycle tests cannot keep both representations atomic; then return to planning for a table rebuild.
- A session appearing at a new container/runtime/native location without a runtime-owned relocation credential is a new endpoint; v1 does not infer relocation or accept model-supplied endpoint identity as proof. Disproved by an existing integration contract requiring identity-preserving moves; then expand and re-review the plan.
- Endpoint backfill runs once under the schema/migration lock. Rows that cannot be matched uniquely remain permanently unresolved: status/ACK rules may preserve already-observable state, but they cannot be claimed, woken, rebound, or used to create a reply. Disproved if a supported legacy lifecycle requires safe delivery of such a row; then stop and choose a stable historical endpoint representation.
**Plan:**
1. Add sender_endpoint_id to Relay messages; add recipient_endpoint_id and recipient_container_ref provenance to deliveries; add a Relay alias registry keyed by actor plus normalized alias with either one endpoint owner or an unresolved-collision state. Expose RelaySessionRecord.id as endpoint_id. Keep endpoint columns nullable only for unresolved legacy rows; all new writes populate them.
2. Add an idempotent relay_endpoint_identity_v1 migration. For same-DB startup: create/upgrade columns and registry, then backfill and mark once under the Relay/schema lock. For split startup: upgrade any legacy source columns before ORM reads, initialize target, copy/verify without overwriting an already-authoritative target, then run and mark endpoint/name migration on the target. Recovery from target-marker-before-source-marker uses subset verification and never recopies over target state.
3. Define canonical selectors as relay-session-<32 lowercase hex> and @<normalized alias>. Retain runtime:session_ref as a legacy exact form that fails if more than one actor endpoint matches before lifecycle filtering. Retain runtime:@alias only when the prefix matches the global owner's runtime; otherwise return an explicit use-@alias conflict. Reject bare runtimes during validation before storage or wake.
4. Resolve self for turn/name/close/send from the current actor plus local container/runtime/native tuple; a new tuple mints a new endpoint. Resolve proactive destinations actor-wide by canonical endpoint or alias. Re-key new send, claim/turn, reply, pending lookup, idempotency, expiry, and recovery to persisted endpoint IDs. Status and ACK/reply object access remain actor-trusted; claimed ACK/reply still requires the receipt/token. Unresolved legacy rows are never dynamically rebound.
5. Make name assignment use the alias registry in the existing immediate transaction. Normal conflicts change nothing. replace_existing atomically assigns one owner, clears legacy aliases from all previous sessions, and preserves their exact IDs and deliveries. Close/rename releases only an assigned name; unresolved collision markers persist until explicit takeover. Closed endpoints cannot create replies.
6. Normalize immediate send/reply and recovered wake input to the recipient endpoint's current runtime/native session/container before calling existing Claude/Codex adapters. Keep historical delivery provenance separate, retain freshness/unreachable guards, and fall back without loss when the endpoint/location is missing.
7. Update HTTP/MCP response models, recipient rendering, tool descriptions, and Claude Code/Codex/OpenCode instructions for endpoint IDs, global names, conflict → ask user → approved takeover, direct takeover instructions, same-actor trust, and no broadcast.
8. Extend caller-surface E2E around cross-container exact/alias journeys and zero-side-effect failures, then cover literal old-DDL same/split/crash migration, orphan rows, duplicate identities/names, takeover races/lifecycle, reply chains, paging budgets, immediate/recovered wake, restart, validation, actor isolation, and memory/history non-effects. Update README/Relay docs only after installed witnesses pass.
Key conventions: no new delivery engine, auth system, or dependency; API remains thin over core; storage does not import app/capabilities; endpoint/name migration precedes removal of container routing gates. Target files: storage/sqlite_schema.py, storage/sqlite.py, storage/sqlite_relay.py, core/relay.py, api/schemas.py, api/routes.py only if destination callback data requires it, app/dependencies.py and existing wake adapters only where normalization requires it, app/mcp/client.py/server.py/context.py as needed, relevant integration instruction sources, focused Relay tests, and post-witness docs. Stop on a forbidden import, unverifiable migration, actor-isolation regression, alias-registry divergence, or need for endpoint-level authentication/relocation.
**Verification plan:**
- When two same-actor endpoints occupy different containers, canonical ID and global-name sends shall produce one delivery and support receive → ACK/reply → status, including reply chains longer than two → focused HTTP and MCP E2E.
- When a bare runtime, ambiguous legacy selector, runtime-mismatched prefixed alias, occupied name without takeover, forged cross-actor object ID, or closed sender/replier is used, no prohibited message/delivery/name/wake state shall change → negative public-surface E2E plus read-path assertions.
- When any same-actor endpoint holds a message/delivery ID, actor-wide status and existing receipt/token-gated ACK/reply behavior shall match the documented trust boundary without accepting a model-supplied self ID → explicit same-actor capability E2E.
- When takeover is approved, denied, repeated, or concurrent, the registry shall retain exactly one owner or a durable unresolved collision; new sends follow the owner while prior queued/claimed deliveries remain bound to endpoint IDs across close/rename/restart → naming concurrency/lifecycle E2E.
- When a literal old database starts in same-DB, fresh split, already-split, interrupted-marker, mixed-column, divergent-target, duplicate, or repeat-restart state, columns/registry shall migrate exactly once without overwrite or rebind; unmatched rows remain inspectable but undeliverable → file-backed migration E2E.
- When canonical-ID or alias delivery is first persisted or later recovered, wake shall receive the recipient's native selector and current location; missing/unreachable locations shall retain fallback work without misrouting → immediate and recovery wake adapter E2E.
- When empty/max/over-max, ASCII normalization, Unicode rejection, expiry, lease, retry, duplicate message ID, close/reactivate, paging budget, and service restart boundaries occur, the observable contract shall hold → focused boundary matrix in existing Relay E2E modules.
- When cross-container Relay runs, Session History/memory visibility and repository/worktree state shall not change → existing public isolation assertions.
- When the final diff is ready, import boundaries, redline/workflow predicates, targeted Relay suites, full test suite, and installed cross-runtime dogfood shall pass → repository scripts, pytest, service wrapper health checks, and installed witnesses.
**Plan review:** Clean-context architecture re-review approves the revised plan; all five blockers are resolved. See ### Re-review under ## Plan review.

**Approvals:** Approved by user 2026-09-07T16:23:31+03:00: "yes, approve this and you should take this through pr, seeing everything is green, commenting and resolveing pr comments"

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Checkpoint: persistence-review + api-review

What is changing: Migrate Relay from container-scoped resolution to actor-scoped canonical endpoint addressing and expose exact/alias-only targeting through HTTP and MCP.

Why: Known endpoints must communicate across containers without weakening actor isolation or introducing broadcast.

Affected contract / model / boundary: Relay session/message/delivery identity, alias uniqueness, selector compatibility, receipt/ACK/reply/status authorization, and destination wake location.

Compatibility / migration risk: High — existing rows may contain duplicate native identities and aliases legal under the old scope; queued and claimed deliveries must retain exactly-once behavior.

Verification plan: Public HTTP, MCP, and hook E2E across containers; migration/restart tests; duplicate native-ID and alias-transfer races; actor isolation; bare-runtime rejection without side effects; destination-aware wake/fallback; existing delivery-engine regressions.

## Implementation

- Established isolated branch `feat/cross-container-relay` from `origin/main` at `88ed0e64`.
- Discovery and pre-edit redline classification completed; production implementation is now in progress.
- Intended production files are limited to the schema/migration/store/service/API/MCP/wake/instruction surfaces named in Plan; tests and post-witness docs may change within Scope.
- Implemented the reviewed architecture: actor-trusted canonical endpoint IDs, permanent orphan non-binding, sequenced split migration, durable actor-global names, and recipient-location wake normalization.
- Added literal legacy-DDL migration coverage for same-DB backfill, alias uniqueness/conflicts, permanent orphan NULLs, fresh split sequencing, and target-marker recovery.
- Removed bare-runtime broadcast from regular send, exposed endpoint/location provenance in HTTP/MCP results, and updated takeover guidance across integrations.
- Added caller-level cross-container HTTP E2E; existing Relay regression expectations are being migrated to the exact-endpoint contract.

## Evidence

- Pre-edit inventory: current Relay code and tests plus roadmap feature.
- Redline: MIXED SCHEMA_CHANGE + API_CHANGE; persistence-review and api-review; no boundary violation.
- Focused result: uv run --with pytest python -m pytest -o addopts="" tests/test_sqlite_relay_isolation.py -k "literal_legacy or split_recovery" -q -> 5 passed.

- Focused persistence/isolation suite: 15 passed.
- Direct cross-container send, claim, ACK, status, reply, actor-denial, and no-broadcast smoke: passed.
- Expanded persistence/lifecycle/wake contract suite: 46 passed with one intentional stale wrong-container expectation delegated for update.

## Plan review

Clean-context review of the Work Record, roadmap contract, repository policies, Relay core/store/schema, split migration, HTTP/MCP entry points, wake dispatch/adapters, and focused lifecycle/migration tests. No implementation changed or tests run. Verdict: revise before implementation. Reusing RelaySessionRecord.id and the existing delivery engine is sound.

1. **[P1, blocking] Separate caller binding from target addressing.** Reply/ACK/status requests and the MCP client carry scope plus object IDs, not caller endpoint identity. relay_reply_atomic infers its sender from the delivery; delivered-state replies need no receipt. Removing container equality permits any same-actor caller holding a delivery ID to reply as its recipient. Specify whether this intentionally remains a trusted-actor capability or requires caller endpoint matching; do not claim endpoint authorization while only checking actor. If matching is required, thread runtime-owned caller identity through HTTP/MCP/client paths; a model-supplied endpoint ID is not proof of self. Turn/name/close/send should resolve self from the existing local identity plus actor, while canonical IDs select destinations. Define status audience and claim-token/receipt exposure. Test another same-actor endpoint, cross-actor IDs, forged self IDs, and duplicate native identities. Do not add a new authentication system by implication.

2. **[P1, blocking] Prevent orphan inbox adoption.** A live same-container fallback or repeated NULL-column backfill can attach an orphan delivery to a newly registered endpoint at the old location. Bind only from the original actor/container/runtime/native tuple with one matching endpoint; preserve non-NULL IDs. Record migration completion or an explicit unresolved state so restart cannot rebind historical rows. Choose whether unresolved rows remain inspectable but undeliverable or receive a stable historical endpoint representation. A dynamic fallback needs evidence that later registration cannot adopt it. Test absent sender/recipient, actor mismatch, deleted/recreated location, restart after registration, and old claimed/delivered reply/ACK.

3. **[P1, blocking] Make split migration ordering explicit.** _initialize_schema(include_relay=False) leaves old source Relay tables intact, but _copy_relay_rows and _verify_relay_ids SELECT every mapped column. Source columns must exist before those ORM reads. Target initialization precedes copy, so target-only backfill runs too early for a fresh split. Specify consistent source/target locking, source-column upgrade, copy/verification, authoritative-target endpoint/name migration, and durable marker ordering. Define recovery when the target committed before the source marker, including comparison of derived columns; resumed split must not overwrite mutable target state from frozen source rows. Use literal old-DDL fixtures, not the current ORM constructor. Cover same-DB, fresh split, already-split, interrupted markers, mixed column presence, divergent target state, conflicting rows, and repeat restart without rebind/recopy.

4. **[P1, blocking] Preserve legacy name conflicts across lifecycle changes.** BEGIN IMMEDIATE safely serializes cooperating naming calls; the narrower UNIQUE constraint does not enforce actor-global ownership. Naming/close and bulk split import are relevant writers. Keeping legacy duplicate aliases only on session rows loses collision history: close/rename/removal can leave one owner and silently make the name usable without explicit takeover. Define and persist the unresolved-collision rule. Compare session-only enforcement with a small name table keyed by (actor_ref, normalized_alias), pointing to an endpoint or marking an unresolved conflict; retain legacy aliases as migration evidence until resolution. Prefer database-enforced ownership if it removes repeated collision bookkeeping. If retaining session-only enforcement, document every writer/import and prove the durable rule with multi-connection takeover/close/conflict races and restart. Takeover must roll back fully on failure and never move old deliveries. Concurrent calls promise one serialized winner, not a scheduler-independent winner.

5. **[P1, blocking] Adapt immediate wake to canonical selectors.** Both schedule_codex_relay_wake and schedule_claude_relay_wake validate result.recipient as a native-session or alias selector; relay-session-* fails that validation even after correcting destination scope. The smallest change is constructing existing adapter input in dispatch_relay_wake from the persisted recipient endpoint's runtime/native session/current location. Reuse it for initial send, reply, recovery, and ACK backlog rearm; destination-health callbacks retain the freshness guard. Distinguish historical delivery provenance from current wake location and specify missing/removed-location fallback. Exact-ID immediate-wake E2E is required; recovery-only success misses this failure.

6. **[P2, required before approval] Write concrete compatibility/lifecycle outcomes.** Detect legacy ambiguity across all actor-matching endpoints before state eligibility, so closing a duplicate cannot silently select another. Define prefixed-alias runtime mismatch, canonical-ID grammar, ASCII/lowercase alias normalization, and stable HTTP/MCP errors. Specify same-location reactivation preserving ID, alias release, queued/claimed retention, and reply while closed (relay_reply_atomic currently lacks normal send's closed-sender guard). Idempotent sends must retain their persisted recipient after takeover and never wake a replacement owner. Add public cases for these decisions, reply chains longer than two, paging/budget growth from identity fields, memory/history non-effects, and installed supported-runtime witnesses. Deliberately update old broadcast/wrong-container expectations. Include api/routes.py and any needed MCP client/context or wake files in the target inventory.

Required next step: revise Plan, Material assumptions, and Verification plan, then obtain clean-context re-review and the required High-risk human approval. This review does not approve implementation or alter State/Approvals.

### Re-review

Approved: the revised plan resolves all five blocking findings. It explicitly preserves actor-level caller trust, makes unresolved historical bindings permanent, sequences source-column/split-target migration with crash recovery, gives aliases durable database-keyed ownership/collision state, and normalizes destination identity for immediate and recovered wake. The expanded verification plan covers these contracts and the required compatibility/lifecycle cases. This is architecture-plan approval only; implementation evidence and the separate High-risk human approval remain required. State and Approvals are unchanged.

## Result review

Implemented and reviewed. Persistence/security review found and verified fixes for permanent orphan adoption during same-DB-to-split migration, mutable target alias removal on restart, and alias resurrection during interrupted split recovery. API/wake review found and verified fixes for duplicate native Claude session IDs across containers plus scoped wake-intent upgrade, corruption, persistence-failure, repeated-recovery, and restart safety. Both smart-model re-reviews report no remaining concrete findings. Independent Claude architect review of PR #133 at `fbd4b374` likewise found no blockers; its alias-authority observation is clarified in the schema, while migration-only orphan observability is deliberately deferred because permanent orphan behavior is already explicit and covered.

Verification:
- Focused cross-container, migration, FastMCP, Claude wake, and Codex wake matrix: 241 passed, 2 skipped.
- Complete Claude wake regression matrix after final intent-precedence hardening: 140 passed, 2 skipped.
- Full repository suite on the prior rebased main after all review fixes: 4598 passed, 32 skipped, 2 expected failures.
- After rebasing onto `origin/main` at `80cf4312`: complete dev+vector suite 4478 passed, 48 skipped, 2 expected failures; affected all-extras Relay/FastMCP/hook/capacity suite 125 passed.
- Diff hygiene and Python syntax compilation: clean.
- Import-linter report: zero violations.

Installed dogfood remains a pre-merge roadmap gate. Repository operations forbid repointing the long-lived installation at this temporary worktree; run the installed witness from a stable checkout before merging/publication. The roadmap item therefore remains queued.
