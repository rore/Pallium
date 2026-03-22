---
id: add-language-agnostic-query-signals-and-typed-constraint-state
title: Language-agnostic query signals and typed constraint state
status: queued
priority: high
commitment: committed
milestone: Next
lane: stabilization-foundation
---

## Summary

Add a package-owned `QuerySignalEnvelope` for residual query routing and
ambiguity handling in `agent_conversation_memory`.

After structural lane narrowing lands, Pallium should stop relying on
English-specific query-shape and phrase tables as the default residual control
plane. Structural context and typed state should remain primary. When the
structural path does not resolve the case, Pallium should derive bounded query
signals from typed evidence first and selective semantic resolution second,
while keeping legacy English cue logic only as a measurable compatibility
fallback.

This feature also moves constraint lookup and compatibility toward typed stored
constraint state rather than English snippet recovery.

## Why

Structural lane narrowing will remove phrase-derived intent from the hot path
for clear cases, but it does not make Pallium language agnostic by itself.
The residual path remains English-first today:

- query-family and query-shape inference still depend on English tokens,
  phrases, and prefix rules
- policy classification for `noise`, `latest_status`, `resume_work`, and
  `check_constraints` still depends on English wording
- active constraint recovery still prefers English snippet extraction such as
  `do not`, `avoid`, and `cannot use`

That is acceptable only as temporary compatibility behavior. It should not
remain the primary read-time control plane if Pallium is supposed to answer
bounded recall and resumed-work questions outside English.

The goal of this feature is not full multilingual parity across the whole
system. The goal is a smaller and more defensible step: remove the specific
English dependency from the residual query router and typed constraint lookup so
Pallium becomes language-agnostic enough for the current product slice.

## In Scope

- add a package-owned `QuerySignalEnvelope` for residual routing and ambiguity
  handling
- define a bounded signal set for the current product slice, including at
  least:
  - `low_value`
  - `history_lookup`
  - `latest_status_request`
  - `resume_state`
  - `constraint_lookup`
  - `evidence_request`
- derive the signal envelope using this precedence:
  - structural context first
  - typed candidate evidence and runtime context second
  - bounded semantic query resolution only for unresolved residual cases
- change residual policy-family selection and ambiguity handling to consume the
  signal envelope instead of directly consuming English cue tables and
  query-shape tags
- keep structural lane narrowing authoritative for clear single-lane cases; do
  not reopen excluded lanes through signal inference
- prefer typed or stored constraint state over English snippet extraction when
  building local constraint context or resolving constraint-focused recall
- keep legacy English cue tables and English constraint snippet extraction only
  as compatibility fallback, with explicit trace visibility when they are used
- extend query/debug trace with at least:
  - `query_signal_source = structural | semantic | legacy_english_fallback`
  - `query_signal_confidence`
  - `legacy_english_fallback_used`
  - bounded signal contents or selected signal summary
- add focused deterministic tests and replay or benchmark coverage for:
  - non-English paraphrase variants in the residual path
  - typed constraint lookup without English query wording
  - evidence request without English cue phrases
  - low-confidence semantic fallback and abstention behavior
  - English compatibility fallback behavior

## Out of Scope

- an always-on model router
- generic multilingual abstractions in `core/`
- a full multilingual rewrite of write-time extraction or promotion
- historical backfill or retyping of all stored memory
- retrieval-substrate changes such as vector or hybrid retrieval work
- public API expansion beyond bounded trace additions needed to explain signal
  derivation

## Done When

1. Residual query routing no longer depends primarily on English cue tables or
   English query-shape tags.
2. Non-English paraphrase cases in the current product slice can reach the
   correct bounded policy or lane without requiring English wording matches.
3. Structural lane narrowing remains authoritative for clear single-lane cases,
   and residual query signals do not reopen excluded lanes.
4. Constraint lookup and constraint compatibility prefer typed stored state over
   English snippet recovery.
5. Legacy English heuristics remain available only as measurable compatibility
   fallback, not as the default read-time control plane.
6. Query/debug trace shows how the residual signal was produced, whether
   semantic help was used, and whether legacy English fallback was needed.
7. Existing English regressions remain stable while non-English residual cases
   improve without introducing an always-on query-time model call.

## Notes

Implementation defaults:

- keep this feature package-owned in `agent_conversation_memory`
- prefer one explicit `QuerySignalEnvelope` helper and one explicit residual
  routing seam over scattering new multilingual logic across existing cue-table
  call sites
- isolate current English lexical logic behind a single legacy fallback helper
  so the new signal path remains reviewable and measurable
- if semantic help is needed, use the existing bounded
  `query_ambiguity_resolution` contract selectively rather than creating a new
  always-on router
- treat this feature as read-time control-plane cleanup, not as a promise of
  full multilingual understanding across the whole write path

Recommended sequencing relative to other roadmap work:

1. land structural query lane narrowing before intent tie-break
2. land language-agnostic query signals and typed constraint state
3. move the live miss-capture and replay-promotion loop back up once misses are
   more likely to reflect residual ambiguity and operational drift than known
   English-specific router behavior
4. keep later vector and hybrid retrieval work bounded by the less-English
   residual path so semantic retrieval does not become an unconstrained fallback
