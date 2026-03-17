---
id: add-write-time-memory-envelope-and-kind-prefiltering
title: Write-time memory envelope and kind prefiltering
status: queued
priority: high
commitment: committed
milestone: Next
lane: stabilization-foundation
---

## Summary

Introduce a typed write-time memory envelope so retrieval can prefilter by
memory kind and deterministic metadata before semantic ranking.

The goal is to move Pallium away from retrieval-time guesswork over free text
and toward bounded memory objects with inspectable meaning.

The first envelope slice should stay small and local-first. It should add
stable metadata for at least:

- memory kind
- scope tuple
- provenance
- temporal validity or freshness metadata
- confidence or reliability hints where already available

The first memory kinds should be generic and product-shaped, for example:

- `constraint`
- `finding`
- `episode`
- `next_step`
- `summary`

## Why

Current routing is still too dependent on textual inference because most of the
important distinctions are not available as first-class metadata.

That creates repeated failure classes:

- a summary and a next step compete as if they are only text
- a hard constraint competes as if it is just another sentence
- broad recall has to infer whether it wants a finding, summary, or status
  snapshot from wording and surface overlap

Research across other memory systems points to the same conclusion: the main
way to reduce query-time complexity is to structure memory at write time so the
hot path can stay mostly deterministic. That makes this envelope slice the first
stabilization step, not a follow-on optimization.

## In Scope

- add a first-class write-time envelope for derived memory objects
- include at least:
  - `kind`
  - `scope`
  - `provenance`
  - `temporal` metadata
  - existing identifiers needed for replay/debug traceability
- define a small initial kind set appropriate for
  `agent_conversation_memory`
- allow write-time envelope fields to be produced by bounded semantic
  extraction, but require structured outputs rather than free-form prose
- allow write-time extraction to use its own dedicated model role or provider
  settings distinct from query-time ambiguity resolution, while still
  supporting a shared default model configuration
- make query-time policy able to restrict allowed kinds before semantic
  ranking or final packaging
- preserve evidence-backed links and current compact carry-forward behavior
- expose the envelope metadata in debug trace and relevant tests
- add deterministic tests showing kind-aware filtering changes candidate
  selection in useful ways
- version the extraction prompt or contract for fields that depend on model
  classification
- require explicit unknown or abstain behavior when the extractor cannot assign
  a field confidently rather than fabricating a precise type
- keep the extraction role aligned with the shared prompt-role contract owned by
  `add-semantic-prompt-role-contracts-and-replay-governance` once that later
  feature lands
- define write-time operational rules for extraction quality and cost,
  including at least:
  - per-role prompt versioning
  - schema-invalid fallback behavior
  - explicit unknown handling
  - traceability of which model role and contract version produced the envelope
- make the envelope sufficient for the deterministic query hot path to narrow by
  kind before any optional semantic ambiguity resolution is considered

## Out of Scope

- a full graph model
- broad ontology work
- new cross-container reuse behavior
- external public contract changes for direct envelope authoring
- replacing the current retrieval backend

## Done When

1. Derived memory objects carry a stable typed envelope at write time.
2. Query-time retrieval or packaging can restrict allowed memory kinds before
   final semantic selection.
3. Debug trace can explain candidate inclusion and exclusion partly in terms of
   kind and envelope metadata, not only lexical/support scores.
4. Regressions cover at least one case where kind-aware filtering prevents a
   previously plausible but wrong candidate from being selected.
5. Extraction fields that rely on model classification use a bounded schema,
   support abstention, and are prompt-versioned for replay review.
6. Write-time extraction roles can be configured separately from query-time
   ambiguity resolution without changing the generic query contract.
7. The envelope materially reduces how often query-time semantic escalation is
   needed for ordinary recall.
8. The envelope remains small, generic, and easy to evolve without forcing a
   graph platform.

## Notes

Recommended sequencing:

1. land this envelope slice before or alongside selective query ambiguity
   resolution
2. then build first-class constraint handling and subject/workstream filtering
   on top of it
3. use Pallium-native scenario coverage to prove the deterministic hot path got
   stronger rather than only adding another semantic layer

Implementation defaults:

- keep the envelope additive over current memory payloads
- do not move package-specific meaning into the generic core beyond the minimal
  reusable envelope fields
- prefer deterministic prefiltering before ranking, not after-the-fact cleanup
- prefer a stronger write-time extraction role than the query-time ambiguity
  role when separate model roles are configured, because write-time extraction
  can trade more latency for better typed output quality
- use model extraction only to populate typed fields; selection and suppression
  behavior should remain deterministic once the fields exist
- improve prompts through smaller typed extraction tasks, versioning, and
  replay-backed review rather than by growing one broad summarization prompt
- treat this feature as the first concrete consumer of the later shared
  `write_extraction` prompt-role contract, not as the long-term owner of prompt
  governance rules
