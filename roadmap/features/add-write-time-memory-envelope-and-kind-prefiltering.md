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

A typed envelope is the smallest stable structure that lets Pallium narrow the
candidate set deterministically before ranking.

This is a generic capability and fits Pallium's core direction better than more
scenario-specific heuristics.

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
6. The envelope remains small, generic, and easy to evolve without forcing a
   graph platform.

## Notes

Recommended sequencing:

1. bounded query intent resolution first or in parallel if the contracts are
   coordinated
2. then this envelope slice
3. then build first-class constraint handling and subject/workstream filtering
   on top of it

Implementation defaults:

- keep the envelope additive over current memory payloads
- do not move package-specific meaning into the generic core beyond the minimal
  reusable envelope fields
- prefer deterministic prefiltering before ranking, not after-the-fact cleanup
- use model extraction only to populate typed fields; selection and suppression
  behavior should remain deterministic once the fields exist
- improve prompts through smaller typed extraction tasks, versioning, and
  replay-backed review rather than by growing one broad summarization prompt

