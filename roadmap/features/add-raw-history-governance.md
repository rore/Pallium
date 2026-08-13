---
id: add-raw-history-governance
title: Raw-turn user-requested forgetting (raw-history governance, re-scoped)
status: in-progress
priority: high
commitment: committed
milestone: pallium-vnext-p0
---

## Summary

User-requested **forgetting of raw source turns**: a user can mark specific raw
turns (or a bounded raw-turn scope) as forgotten, after which retrieval (query
`source_hit`s) and source-context expansion no longer surface them. Soft and
auditable (not the existing TTL hard-delete), and distinct from `pallium_forget`
(which acts on memory objects only).

> **Re-scoped 2026-08-13.** The original broad governance ticket was a straddle:
> investigation found redaction already runs at ingest + read barriers, per-neighbor
> visibility is already the expansion pattern, bounded windows already belong to the
> P1 expansion item, "access audit for raw reads" is the *same* exposed-source-ids
> recording deferred from the telemetry item, and shared-raw revocation depends on the
> unbuilt P3 grant contract. Those pieces are folded into P1 or deferred to P3 (see
> "Moved out" below). This ticket keeps the one standalone-buildable, testable-now P0
> piece: raw-turn forgetting.

## Why

vNext makes raw turns a directly retrievable/expandable asset. Today `source_items`
have **no** soft-delete/forgotten field, `pallium_forget` touches memory objects only,
and retrieval never filters source items by any forgotten state — so a user has no way
to remove a raw turn from what search/expansion can surface (short of the automated TTL
hard-delete). That is a real privacy gap and a prerequisite for exposing the
lookup/expansion tools.

## In Scope

- a soft-delete/`forgotten` marker on `source_items` (auditable: who/when/why) +
  inline migration; mirrors the memory-object soft-delete shape
- fail-closed exclusion of forgotten source items in retrieval (lexical + vector) and
  in `source_item_matches_filters` (parallel to the memory `lifecycle == "active"` gate)
- a user-facing raw-turn forget entrypoint (service + API + MCP tool), scoped by
  `source_item_id` and by a bounded scope (e.g. thread/container), named distinctly
  from `pallium_forget`

## Out of Scope / Moved out

- **redaction on search + expansion** — already provided by existing barriers
  (`_redact_query_result`, expand redaction); the P1 search/expansion items reuse them
- **per-neighbor visibility + bounded expansion window/token cap** — already owned by
  `add-source-context-expansion` (P1)
- **access audit for raw reads** — the exposed-source-ids-per-lookup recording deferred
  from `add-historical-lookup-funnel-telemetry`; build ONCE in the P1 slice (it serves
  both the reuse funnel and the read audit)
- **revocation of previously shared raw work** — deferred to **P3**: no sharing/grant
  substrate exists; depends on `idea-visibility-vocab-reconciliation` (the grant
  contract). Tracked as `idea-shared-raw-revocation`.
- structured-memory lifecycle (`add-bounded-memory-lifecycle-hardening`); cold-archive
  storage (non-goal)

## Done When

1. A user can forget a raw turn by `source_item_id` and by a bounded scope; subsequent
   `/query` returns no `source_hit` for it and expansion omits it (0 leaks, fail-closed).
2. Forgetting is idempotent, auditable (row persists with a forgotten marker — not a
   hard delete), and distinct from `pallium_forget` (memory forget ↔ source forget do
   not affect each other).
3. Exclusion holds on both lexical and vector retrieval paths.

## Notes

P0 governance piece; the P1-attached mechanics land with the P1 vertical slice.
Guarded paths: `core/service.py` (red), `core/filters.py`, `storage/`, `api/`,
`app/mcp/`. Start with `/agent-workflow`. Work Record:
`.agent-workflow/tasks/add-raw-history-governance.md`.
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (P0 contract).
