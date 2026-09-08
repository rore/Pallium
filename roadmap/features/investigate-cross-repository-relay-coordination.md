---
id: investigate-cross-repository-relay-coordination
title: Define service-global cross-container Relay routing
status: done
priority: high
commitment: committed
milestone: pallium-relay
lane: investigation
---

## Question

What is the smallest safe change that makes Relay a local single-user fabric service-global on the local Pallium service, lets known endpoints and names communicate across containers without the sender knowing the target `container_ref`, requires every regular send to name an exact endpoint or name, and leaves broadcast as a separate future capability without changing Session History/memory visibility?

## Product boundary

Pallium remains transport only. Claude Code, Codex, OpenCode, and other runtimes decide whom to contact and what work to perform. Relay does not assign work, supervise completion, infer task state, synchronize repositories or artifacts, execute workflows, maintain shared project state, select recipients semantically, or create autonomous agent loops.

For the local single-user product, the Pallium service is the Relay trust boundary. A session's `container_ref`, repository/worktree, runtime, and harness-native `session_ref` are location and provenance metadata used to locate or wake it, show and filter where it belongs, preserve diagnostics, and support lifecycle handling. They are not the logical boundary for targeted Relay communication. This change does not alter Session History or derived-memory visibility: their container and visibility rules remain separate from Relay routing.

Naming and communication are independent. An unnamed session can participate fully, including exact-target sends and replies. A name is only a stable human-friendly address for proactive targeting; assigning one grants no membership, authorization, discovery, or additional communication capability. A received delivery already carries sufficient sender identity for `relay_reply_atomic` to route back to the original `sender_runtime` and `sender_session_ref`; the cross-container design must preserve that reply path without requiring either endpoint to have a name.

Naming is non-destructive by default. When an agent is told to call itself `X`, it first requests `X` without takeover. If another endpoint already owns the service-global name, naming fails with an explicit name-in-use conflict and no ownership change. Agent-facing instructions must then require the agent to ask the user whether it should take over the name. Only explicit approval, or an original instruction that already says to take over `X`, authorizes a retry with `replace_existing=true`. This consent rule is an agent instruction rather than a security boundary; the local service is trusted and the API does not attempt to prove that approval occurred.

Regular Relay messaging is targeted only. Every proactive send must identify one exact endpoint or name; omitting the target and supplying only a runtime such as `codex` must be rejected rather than interpreted as fan-out. Broadcast has different audience, authorization, cost, and wake semantics and belongs behind a separately named future API if it is ever implemented.

### Replaced assumptions

This feature replaces the previous **same-`container_ref` default plus explicit coordination-scope membership** model. Do not implement both models. The first design to investigate is one Relay domain per local service, with containers retained as endpoint metadata and exact endpoints, replies, and names routable across containers. Do not add create/join/revoke/dispose coordination scopes unless the investigation identifies a concrete isolation or product requirement that service-global Relay ownership and explicit targeted addressing cannot satisfy. Cross-container routing alone does not imply global discovery or orchestration.

## Investigation scope

- Define a stable Pallium-level Relay endpoint identity. Do not assume a harness-native `session_ref` is globally unique: the current schema identifies sessions by `(container_ref, runtime, session_ref)` and separately assigns `RelaySessionRecord.id` values such as `relay-session-*`. Prefer exposing and routing through that existing record ID if its creation, persistence, close/reactivation, repository/worktree relocation, and migration semantics can satisfy the canonical-identity contract; add another identity layer only if evidence proves it necessary.
- Make `runtime`, native `session_ref`, `container_ref`, repository/worktree, title, state, health, and timestamps attributes of the canonical endpoint. Define which location fields are current versus historical and how an endpoint is located after a worktree move or native-session collision.
- Define exact targeting that uses the canonical endpoint identity and does not require the sender to know the target container. Specify backward compatibility and deterministic ambiguity handling for existing `runtime:session_ref` selectors when the same native ID exists in more than one container.
- Define one unambiguous name namespace per local Relay service. The current uniqueness key `(container_ref, runtime, name)` must be replaced. Investigate retaining syntax such as `codex:@review` for compatibility, but runtime must not create an independent name namespace; a human-facing Pallium name identifies one endpoint across the service's containers. Naming, transfer, removal, close, and reactivation must not change the endpoint's communication authority.
- Define name takeover as one atomic operation using the existing `replace_existing=true` contract: remove the name from its previous endpoint and assign it to the caller, while leaving both endpoints, their exact identities, and all existing or pending messages and deliveries intact. A conflict response may state that the requested name is occupied but must not expose the current owner's endpoint details. Document the normal attempt → conflict → ask user → approved takeover flow in every agent integration.
- Define targeted send, reply, claim/turn, status, ACK, expiry, retry, and idempotency authorization in terms of canonical sender/recipient endpoint identity. Preserve receipt and claim-token guarantees while removing container equality as the targeted-routing gate.
- Define the one-time local operational conversion, with no reusable migration code. Treat the actor-scoped tables as a historical installed-state format: rebuild Relay sessions, messages, deliveries, and name bindings without actor columns or actor-keyed ownership while preserving canonical endpoint IDs, container metadata, message/delivery relationships, claims, leases, replies, and explicitly resolved names. Reuse the existing persist-first delivery, lease, ACK, reply, expiry, recovery, and status engine rather than duplicating it.
- Route wake and recovery from the destination endpoint's current runtime and container metadata, not from the sender's request scope. Preserve wake-first behavior where the runtime adapter supports it and deterministic next-turn fallback where wake is unavailable.
- Specify closed, unreachable, dormant, reactivated, moved, removed-container, and stale-location behavior, including pending deliveries and name ownership across every transition.
- Remove runtime-only selectors from the regular send contract. Define backward-compatible rejection for bare selectors such as `codex`, with no message, delivery, or wake side effects. Do not add a broadcast path to this feature; track any future fan-out through `idea-explicit-relay-broadcast` and a separately named API.
- Keep recipient listing/discovery bounded and intentional. Cross-container exact or name routing must not by itself make every session globally enumerable; document whether the existing container-local list remains the default and whether any service-global lookup is needed for address management.
- Preserve the existing runtime adapters and platform-specific wake behavior across Windows, Linux, and macOS.

## Required validation

Caller-surface E2E must drive the same public HTTP/MCP and hook/plugin paths used by agents and assert state through public status, receive/list, and audit paths. At minimum it covers:

1. Two unnamed sessions for the same local service in different containers exchange exact-target messages in both directions, including a delivery-based reply, without either sender supplying the other endpoint's `container_ref`.
2. Canonical endpoint identity remains unambiguous when two containers expose the same `(runtime, native session_ref)`; legacy exact selectors either resolve deterministically or fail with an explicit ambiguity contract.
3. One name is unique across all runtimes and containers in the local Relay service; conflict, transfer, removal, close, reactivation, stale name, and runtime-prefixed compatibility behavior are observable and deterministic. A normal naming attempt against an occupied name fails without changing either endpoint. An approved `replace_existing=true` retry transfers only the name atomically; direct user instructions to take over may use that flag on the first attempt. Integration instructions tell an agent that encounters a conflict to ask the user before retrying.
4. Exact send, name send, receiptless hook reply, receipt-based MCP reply/ACK, message status, Unicode, empty/max/over-max inputs, bounded backlog continuation, duplicate/idempotent retries, expiry, lease recovery, and service restart all work across containers.
5. Idle wake uses the recipient endpoint's current location where supported; busy deferral, unreachable targets, stale location, removed container, runtime without wake, and normal next-turn fallback retain messages without misrouting or data loss.
6. Closed endpoints cannot send or receive new targeted messages; reactivation preserves or intentionally replaces canonical identity according to the written contract, and pending/claimed deliveries follow explicit lifecycle rules.
7. Relay has no actor partition: all local service endpoints, names, messages, and deliveries share one operational domain.
8. Bare runtime selectors are rejected through every regular HTTP/MCP send surface, create no message or delivery rows, and trigger no wake; exact endpoint and name sends remain the only proactive send forms.
9. Cross-container Relay activity does not change or leak Session History, memory visibility, repository/worktree state, artifacts, or workflow records.
10. Current-format persistence preserves session, name, message, delivery, reply, receipt, expiry, and lifecycle state across restart, including duplicate native IDs and names across containers or runtimes.
11. Full register → optionally name → send → claim/receive → ACK or reply → status → close/unreachable → reactivate journeys pass on supported runtime/OS combinations without a second delivery engine.

The name lifecycle E2E matrix must drive the public naming, send, receive/list, and status surfaces and verify:

- first assignment, same-owner idempotency, rename, removal, close, and reactivation;
- occupied-name conflicts across containers and runtimes leave ownership and both endpoints unchanged;
- explicit takeover is atomic, immediately routes new name sends to the new owner, leaves existing queued or claimed deliveries with their original endpoint, and preserves exact-address communication for both endpoints;
- denied takeover causes no retry or state change, approved takeover retries with `replace_existing=true`, and an initial explicit “take over `X`” instruction may use that flag immediately;
- repeated and concurrent takeover attempts produce one deterministic owner with no duplicate name or half-transferred state, including across service restart;
- stale, dormant, unreachable, and closed owners follow the written lifecycle contract;
- actor strings have no effect on name ownership, discovery, targeting, takeover, or endpoint identity;
- empty, whitespace, Unicode, case-equivalent, maximum-length, and over-limit names follow one documented normalization and validation contract; and
- legacy duplicate names migrate without a silent winner and require an explicit deterministic takeover before the global name becomes usable.

## Out of scope

- Cross-user or remote-network trust, invitations, ACL administration, multi-tenant policy, or network exposure.
- A coordination/group/membership abstraction unless this investigation demonstrates a concrete requirement beyond service-global Relay ownership and targeted addressing.
- Any broadcast or fan-out implementation. A possible separately named capability is deferred to `idea-explicit-relay-broadcast`; regular Relay send must not expose it.
- Global session discovery, semantic recipient selection, or `work_ref`-, repository-name-, task-title-, or message-text-based routing.
- Task assignment, workflow execution, supervisor logic, completion inference, polling coordinators, shared project state, artifact or repository synchronization, and autonomous agent loops.
- Changing Session History or memory visibility semantics merely to support Relay routing.

## Done when

1. A written contract defines the service-global Relay domain, canonical endpoint identity, exact and name addressing, destination-aware storage, caller authorization, discovery boundary, target-only regular-send boundary, wake/fallback behavior, current-format persistence and lifecycle semantics, with every current container-coupled implementation point accounted for.
2. The contract explicitly records that the old same-container plus explicit coordination-scope model was replaced and either removes coordination scopes from the design or cites the concrete unmet isolation requirement that justifies them.
3. The smallest implementation reuses the existing delivery engine and passes every caller-surface journey above, including duplicate native identity, service-global Relay ownership, bare-runtime rejection without side effects, and memory/history separation.
4. Installed dogfood completes unnamed exact-session, name, reply, wake-capable, and fallback cross-container exchanges without manual recipient wake where wake support exists.
5. README and Relay documentation claim service-global cross-container targeting only after the tests and installed witnesses pass, while stating that regular send requires an exact endpoint or name, broadcast is not currently supported, and memory/history scope is unchanged.

## Dependencies and order

Start only after the current Relay correctness bugs RW-012, RW-013, and RW-014 are fixed. Reuse `add-wake-first-relay-delivery`, `add-relay-retention-and-lifecycle-hardening`, and `validate-relay-dependency-workflows`; do not reopen their transport or workflow boundaries.
