---
id: add-raw-history-governance
title: Raw-history governance (retention, redaction, exposure, revocation)
status: queued
priority: high
commitment: committed
milestone: pallium-vnext-p0
---

## Summary

Once raw agent/user turns become a first-class product asset (searchable and
expandable), their lifecycle and exposure stop being incidental storage concerns.
Add the governance layer that search and expansion require: retention/deletion and
user-requested forgetting, redaction on search *and* expansion, access audit,
per-neighbor visibility during expansion, mixed-visibility thread handling, bounded
expansion windows/token limits, and revocation of previously shared raw work.

## Why

vNext promotes raw history from "background evidence behind derived memory" to a
directly retrievable and expandable payload. `add-bounded-memory-lifecycle-hardening`
covers *structured memory* only — it does not protect the raw substrate. Without
governance, raw search/expansion can leak across mixed-visibility threads, surface
content a user asked to forget, return unbounded context, or expose raw work that was
un-shared — none of which the current structured-memory lifecycle addresses. This is
a prerequisite for exposing the lookup/expansion tools, not a follow-up.

## In Scope

- source retention / deletion and user-requested forgetting of raw turns (distinct
  from object-level `pallium_forget`, which acts on memory objects)
- redaction behavior applied consistently on both search results and expansion
- access audit for raw-history reads (who saw which raw turns, when, via which lookup)
- **per-neighbor** visibility checks during source-context expansion (never widen to
  a whole thread; threads can be mixed-visibility)
- bounded expansion windows and token limits
- revocation of previously shared raw work (ties into the Phase-3 sharing/grant
  contract)

## Out of Scope

- structured-memory lifecycle (staleness/supersession/contradiction) —
  `add-bounded-memory-lifecycle-hardening`
- the cross-user sharing/grant contract itself (`idea-visibility-vocab-reconciliation`,
  `idea-cross-user-raw-history-value`) — this item supplies the exposure/redaction/
  revocation *mechanics* those rely on
- cold-archive storage for expired raw evidence (explicit non-goal)

## Done When

1. Raw search and expansion apply redaction and per-neighbor visibility consistently,
   with 0 violations (reported with attempted-disallowed-access counts/types).
2. A user can request forgetting of raw turns within a scope, and subsequent
   search/expansion no longer surfaces them.
3. Expansion is bounded (neighbor + token limits); raw-history reads are auditable;
   previously shared raw work can be revoked.

## Notes

P0 governance prerequisite: the exposure-safety mechanics must land alongside the P1
vertical slice, before the lookup/expansion tools are broadly exposed.
Guarded paths: `core/service.py` (red), `core/visibility.py`, `core/filters.py`,
`api/`, `storage/`. Start with `/agent-workflow`.
Execution context: `docs/designs/015-vnext-historical-work-execution.md`
(P0 contract).
