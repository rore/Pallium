---
id: investigate-cross-repository-relay-coordination
title: Investigate explicit cross-repository Relay coordination
status: queued
priority: high
commitment: committed
milestone: pallium-relay
lane: investigation
---

## Question

What is the smallest safe opt-in coordination scope that lets an architect and workers in separate repositories exchange targeted Relay messages without weakening each repository's default isolation?

## Product boundary

Pallium remains transport only. Each repository keeps its own instructions, Agent Workflow record, minimap, artifacts, and implementation state. Relay does not assign work, supervise completion, synchronize files, or create autonomous agent loops.

The current same-`container_ref` contract remains the default. Cross-repository delivery requires an explicit user-created coordination scope with explicit membership. Never infer membership or routing from `work_ref`, semantic similarity, repository names, task titles, or message text.

## Investigation scope

- Define creation, membership, inspection, revocation, and disposal for one local single-user coordination scope while retaining every member session's exact repository container.
- Define recipient discovery and runtime/exact-session/alias addressing inside that scope without making members globally discoverable.
- Preserve integration-owned runtime/session identity and choose the minimum claimed authorization appropriate to the trusted local single-user service; do not invent cross-user security here.
- Reuse persist-first delivery, bounded batches, replies, wake-first admission, crash recovery, and deterministic next-turn fallback.
- Specify lifecycle behavior for session close/reactivation, alias transfer, repository removal, membership revocation, service restart, and expired deliveries.
- Keep Windows, Linux, and macOS transport differences behind the existing runtime adapters.

## Required validation

Caller-surface E2E must drive the same public HTTP/MCP and hook/plugin paths used by agents and cover:

1. An architect in repository A discovers and addresses an explicitly joined worker in repository B.
2. Exact and alias sends, receiptless hook reply, Unicode, bounded backlog continuation, idle wake, busy deferral, crash/restart recovery, and passive next-turn fallback.
3. Non-member, revoked, wrong-actor, wrong-coordination-scope, stale alias, closed session, missing repository, duplicate, expiry, and over-limit refusal.
4. Independent delivery state for multiple members and no visibility or routing leakage into either repository's memory/history scope.
5. Full create scope → join repositories/sessions → exchange/reply → revoke/leave → dispose journeys on supported runtime/OS combinations.

## Out of scope

- Cross-user or remote trust, invitations, ACL administration, or network exposure.
- Shared repository state, artifact synchronization, task assignment, completion inference, polling supervisors, or workflow orchestration.
- Semantic or `work_ref`-based recipient selection.
- Changing the default same-container Relay boundary.

## Done when

1. A written contract names the explicit scope and membership authority, proves default repository isolation, and records revocation/lifecycle semantics.
2. The smallest implementation passes every caller-surface journey above without duplicating the existing Relay delivery engine.
3. Installed dogfood completes one architect-led and one peer-to-peer cross-repository exchange without a manual recipient wake.
4. README examples claim cross-repository coordination only after those tests and installed witnesses pass.

## Dependencies and order

Start only after the current same-container correctness bugs RW-012, RW-013, and RW-014 are fixed. Reuse `add-wake-first-relay-delivery`, `add-relay-retention-and-lifecycle-hardening`, and `validate-relay-dependency-workflows`; do not reopen their transport or workflow boundaries.
