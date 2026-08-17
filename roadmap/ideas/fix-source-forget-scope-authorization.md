---
id: fix-source-forget-scope-authorization
title: Single-source forgetting must be scope-authorized (IDOR)
status: queued
priority: high
commitment: uncommitted
---

## Summary

The single-item raw-turn forget path mutates a source by primary-key `source_item_id` with **no
ownership check**. Any caller holding an id (from search results, logs, or a shared/public turn) can
soft-delete that turn from any container. The supplied `actor_ref` is written as an audit stamp, never
compared. This is a classic missing-authorization / IDOR on a destructive mutation.

## Why

Verified against the code (external review + independent confirmation):
- `core/service.py:1101-1104` — single-item branch calls `self._storage.forget_source_item(id, reason, actor_ref)` with no container/actor verification.
- `storage/sqlite.py:616-643` — `forget_source_item` does `session.get(SourceItemRecord, id)` (global PK lookup), checks only `forgotten_at` for idempotency, writes `forgotten_by = actor_ref` (**audit only**).
- Contrast: the *scoped* branch (`core/service.py:1110-1116` → `storage/sqlite.py:645-675`) **requires** `container_ref` and filters `WHERE container_ref == ...`. The single-item path has no equivalent gate.
- HTTP (`api/routes.py:943-962`) and MCP (`app/mcp/server.py:409-435`, `app/mcp/client.py:346-368`) add no auth.

Only mitigation today is UUID obscurity — obscurity, not authorization. This is a Phase-0 raw-history
governance requirement (scope.md: "raw-turn forgetting") that shipped without the authorization half.

## In Scope

- Load-and-authorize the source before mutation in the service layer: validate caller actor vs owning
  actor / permitted-admin role, container, and visibility scope, and expected source lifecycle state.
- Define the trusted-local policy explicitly (missing actor identity → rejected, or an explicit
  local-trust allowance) rather than silently allowing.
- Storage must not be the first layer deciding solely by id.

## Out of Scope

- Bulk/scope forget already container-bounded (only close any gaps the audit reveals).
- A general RBAC system — minimal actor/container/visibility gate only.

## Done When

1. Cross-actor / cross-container forget by raw `source_id` is **denied** through both HTTP and MCP, verified by an E2E permission-error test (not only a unit test).
2. Owner-forgets-own (private and public) succeeds; wrong-container-with-correct-id is denied.
3. Observable state: after allowed forget, source is gone from source-only search and cannot be an expansion anchor/neighbor; after denied forget, source stays retrievable by its owner and **no `forgotten_at` is written**; audit distinguishes denied attempts from successful mutations.
4. Lifecycle cases covered: nonexistent, already-forgotten (idempotent), concurrent double-forget, forget during in-flight lookup/expansion.

## Notes

External-review register item 5 (severity High). Touches red `core/service.py` — clean-context plan
review required. Related: `add-raw-history-governance`, `fix-source-expansion-visibility-enforcement`.
