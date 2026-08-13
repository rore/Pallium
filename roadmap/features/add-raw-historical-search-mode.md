---
id: add-raw-historical-search-mode
title: Raw historical search retrieval mode
status: queued
priority: high
commitment: committed
milestone: pallium-vnext-p1
---

## Summary

Add a source-only retrieval target that ranks raw `source_hit`s (prior agent/user
turns) on their own — a dedicated top-K/fusion over source items so memory objects
cannot starve raw candidates in the mixed pool — under existing
container/thread/actor/visibility scoping and
`source_type`/`role`/`artifact_kind`/`work_refs` filters. Reuses the existing
lexical/vector fusion, visibility, filtering, redaction, and trace infrastructure;
it is not a second retrieval stack.

## Why

The vNext thesis makes raw history a first-class retrieval substrate. The substrate
already exists — source turns are lexically + vector indexed, `source_hit` is a real
result kind — and routing **already scores and selects source hits** today
(`_specificity_bonus_source_hit` in
`semantic/agent_conversation_memory_routing_scoring.py`; a reserved
`MIN_SOURCE_HIT_SLOTS` and work-resumption source companions in
`semantic/agent_conversation_memory_routing_selection.py`). The real gap is that raw
turns compete in a *mixed* candidate pool and are then subject to memory-oriented
routing/injection policy, where memory objects can starve them and the payload is
shaped for memory injection rather than raw lookup. There is no source-only
retrieval target that ranks raw turns before top-K/fusion. Corpus evidence shows raw
hybrid search is already strong (~83% top-5), so giving it a clean, uncontaminated
target is high-leverage.

## In Scope

- a source-only retrieval target in `QueryExecutor.query` that runs top-K/fusion
  over `source_hit`s via `CompositeRetrievalProvider` (RRF is already kind-agnostic)
  so raw candidates aren't starved by memory objects, and returns them without the
  memory-only abstention gate
- restrict eligibility to source items at the **candidate level, before top-K/fusion**
  (not as a post-filter on a blended page), so memory objects cannot consume the
  candidate budget; a source-only search returns **up to K eligible source results**
  (legitimately fewer when little relevant history exists) — the requirement is that
  memory hits never occupy source-search slots, not that K is always filled
- **reuse** existing scope (container/thread/actor/visibility), the
  source_type/role/artifact_kind/work_refs filters, redaction, and trace — do not
  build a parallel retrieval stack
- a source-block result/render shape (excerpt + timestamp + thread/actor + stable
  source id + raw rank) distinct from memory injectable blocks
- retrieval trace coverage for the source-only target

## Out of Scope

- the agent-facing tool that invokes this mode (see `add-agent-historical-lookup-tool`)
- source-centric expansion (see `add-source-context-expansion`)
- changing the existing proactive/memory injection path or its abstention policy
- RAW/DERIVED/HYBRID shadow comparison (continuous eval track)

## Done When

1. A caller can request source-only history search and receive relevance-ranked
   prior source turns as first-class results — with stable source ids and raw rank —
   scoped and visibility-enforced, not starved by memory objects.
2. The source-only target does not alter `should_inject`/injectable_blocks for
   existing proactive queries.
3. Retrieval trace explains the source-only ranking.
4. Visibility enforcement on raw results is verified (fail-closed; 0 violations).
5. No parallel retrieval stack: fusion, visibility, filtering, redaction, and trace
   are the existing shared components.

## Notes

Governance note (2026-08-13): raw search must route through the existing redaction read
barrier (`_redact_query_result`) and visibility enforcement — these are the P0
governance mechanics for the search path (`add-raw-history-governance` was re-scoped to
raw-turn forgetting and delegates reuse-verification here; add tests confirming the raw
path is redacted + visibility-enforced). Because this mode reuses the shared retrieval
target (`matches_filters`), the P0 forgotten-source gate already excludes forgotten raw
turns from source-only search — add a regression test asserting a forgotten turn never
appears as a source-only result.

Guarded paths: `core/service.py` (red), `core/query.py` (watch), `retrieval/`,
`api/`. Start the implementation slice with `/agent-workflow`.
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 1).
