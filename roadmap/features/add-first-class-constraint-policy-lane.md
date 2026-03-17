---
id: add-first-class-constraint-policy-lane
title: First-class constraint and policy compatibility lane
status: queued
priority: high
commitment: committed
milestone: Next
lane: stabilization-semantics
---

## Summary

Turn hard constraints and operational prohibitions into a dedicated typed memory
lane with explicit compatibility checks, instead of treating them as generic
sentences inside summaries and checkpoints.

This feature should introduce a small first-class constraint representation and
make both query-time packaging and write-time reconciliation respect it.

The goal is to stop contradictory next-step or auth/retry guidance from
surviving merely because token overlap or phrasing happened to miss the
conflict.

## Why

This is currently the highest-pain stability gap.

The existing heuristic path keeps creating variants of the same bug class:

- a hard constraint is remembered textually but not enforced semantically
- contradictory next steps survive because the conflict check is token-based
- newer lower-quality structured memory can still poison later recall

Stronger systems usually separate durable instruction or policy memory from
ordinary episodic state. Pallium needs a small version of that split now.

This is still generic Pallium work because the lane models memory behavior
classes such as prohibited action, preferred source, and compatibility, not any
one tool or downstream integration.

It also reduces the need for query-time semantic adjudication by making one of
Pallium's highest-value policy classes deterministic in the hot path.

## In Scope

- add a dedicated typed representation for hard constraints or policies
- model at least:
  - subject or target surface
  - action class
  - polarity or prohibition or preference
  - provenance
  - temporal validity or supersession metadata
- allow typed constraint fields to be extracted with bounded semantic
  classification, but do not rely on free-form prompt prose as the enforcement
  mechanism
- use the later shared `write_reconciliation` prompt-role contract for typed
  update or supersession decisions once prompt-role formalization lands, rather
  than defining a one-off reconciliation prompt inside this feature
- make query-time selection filter or demote incompatible candidates using the
  typed constraint lane
- make write-time reconciliation of `task_checkpoint`, `thread_summary`, and
  `discussion_summary` use the typed compatibility check
- preserve compatible newer state next to a hard constraint when it does not
  violate the policy
- expose active-constraint selection and compatibility decisions in query/debug
  trace and memory provenance
- add deterministic regressions for:
  - prohibition vs contradictory next step
  - preferred-source vs wrong-source guidance
  - local same-thread constraint correction affecting query-time packaging
  - no active structured memory preserving both the hard constraint and a
    contradictory action

## Out of Scope

- global contradiction resolution across all memory types
- a broad policy engine for every future semantic package
- cross-container policy inheritance
- a full action ontology beyond the minimum needed for current compatibility
  classes

## Done When

1. Hard constraints are represented as a dedicated typed lane rather than only
   free-text memory content.
2. Query-time packaging excludes or demotes incompatible state using typed
   compatibility checks.
3. Write-time reconciliation prevents active structured memory from preserving
   both the hard constraint and contradictory next-step guidance.
4. Constraint recall queries preferentially surface the typed constraint lane.
5. Debug trace can explain which constraint was active and why a candidate was
   deemed compatible or incompatible.
6. Constraint extraction and compatibility stay generic and typed rather than
   regressing into scenario-specific token lists as the main policy mechanism.
7. Ordinary constraint-aware queries can stay on the deterministic hot path
   rather than needing semantic escalation just to understand prohibitions or
   preferences.

## Notes

Recommended sequencing:

- depends on the write-time memory envelope
- can run in parallel with subject/workstream filtering once the envelope and
  kind contracts exist
- should be validated by the Pallium-native scenario/replay lane as it lands

Implementation defaults:

- keep the first compatibility model intentionally small and explicit
- prefer fail-closed behavior when a typed hard constraint clearly conflicts
- avoid reintroducing phrase-chasing as the primary conflict mechanism
- use prompt improvements to sharpen typed extraction boundaries and abstention,
  not to encode product-specific constraint wording into longer prompts
- keep this feature focused on typed compatibility semantics; shared
  prompt-contract ownership should live in
  `add-semantic-prompt-role-contracts-and-replay-governance`
