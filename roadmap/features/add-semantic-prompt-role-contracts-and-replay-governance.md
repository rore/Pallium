---
id: add-semantic-prompt-role-contracts-and-replay-governance
title: Semantic prompt-role contracts and replay-governed prompt lifecycle
status: queued
priority: high
commitment: committed
milestone: Later
lane: semantic-contract-governance
---

## Summary

Define a small canonical set of semantic prompt roles for Pallium's current
product slice and govern them as bounded, versioned contracts instead of
scattered prompt behavior.

The first slice should cover four prompt roles:

- `write_extraction`
- `write_reconciliation`
- `write_enrichment`
- `query_ambiguity_resolution`

Each role should have:

- one narrow responsibility
- a structured output contract
- explicit abstain, unknown, or no-op behavior
- versioned prompt and schema identity
- replay or eval hooks for change review
- traceability of which role and contract version produced a decision

This feature should formalize the contract and plumbing first. It should not,
by itself, implement the full behavioral logic of reconciliation, enrichment,
or query-time escalation.

## Why

The roadmap already says Pallium should use models cautiously:

- bounded semantic classification and extraction only
- structured outputs
- prompt versioning
- replay-backed review
- deterministic policy after classification

But that truth is currently distributed across multiple feature specs, and no
single feature owns:

- prompt-role separation
- role-specific no-op semantics
- the dedicated reconciliation contract
- shared prompt lifecycle rules across extraction, enrichment, and query
  ambiguity work

Research across stronger systems points to the same pattern:

- no giant memory prompt
- separate prompts by job
- schema-first reliability
- explicit no-op or abstain behavior
- versioned prompt lifecycle with replay and eval review

Pallium should encode that as a first-class architectural contract rather than
leave it as repeated guidance inside later features.

## In Scope

- define the canonical semantic prompt-role set for the current product slice:
  - `write_extraction`
  - `write_reconciliation`
  - `write_enrichment`
  - `query_ambiguity_resolution`
- define a bounded contract for each role, including:
  - purpose
  - allowed output schema shape
  - required abstain, unknown, or no-op outcomes
  - version identity for prompt and schema
- make runtime metadata and trace capable of recording:
  - semantic role
  - prompt or schema version
  - model role or provider profile used
- define prompt-governance rules:
  - prompt changes reviewed like code changes
  - replay-backed evaluation before rollout
  - negative examples required where the role supports abstention
  - no scenario-specific term growth as the main bug-fix path
- define the reconciliation contract shape for later consumers, including:
  - `ADD`
  - `UPDATE`
  - `SUPERSEDE`
  - `DELETE`
  - `NONE`
- align existing feature specs so they reference these shared prompt-role
  contracts instead of each feature inventing prompt behavior ad hoc
- add deterministic tests or eval hooks for:
  - schema-valid output
  - schema-invalid fallback
  - abstain, unknown, or `NONE` behavior
  - prompt-versioned replay stability

## Out of Scope

- replacing current `Next` feature ordering
- implementing the full reconciliation engine in this slice
- changing the public HTTP API
- adding a default query-time model call
- broad prompt editing UX or prompt profile management
- turning prompt governance into a separate benchmark platform
- replacing typed storage, lifecycle, or deterministic policy with prompt prose

## Done When

1. Pallium has a documented and repo-owned set of semantic prompt roles instead
   of scattered prompt responsibilities.
2. Each role has a bounded schema contract and explicit no-op semantics.
3. Runtime trace or provenance can identify which prompt-role contract produced
   a model-backed output.
4. Existing roadmap items for the write-time envelope, constraint lane,
   enrichment, and bounded query ambiguity resolution point to these shared
   prompt-role rules instead of redefining them independently.
5. Replay and deterministic regressions can compare prompt or schema versions
   for at least one write-time role and one query-time role.
6. Concrete behavioral ownership stays with the consuming features:
   - envelope owns extraction usage
   - constraint and lifecycle work own reconciliation behavior
   - enrichment owns enrichment usage
   - bounded query policy owns ambiguity-resolution usage

## Notes

Recommended sequencing:

1. keep current stabilization-foundation and stabilization-semantics work first
2. then add this feature so later prompt-bearing features inherit a shared
   contract instead of continuing to define prompt behavior locally
3. use the Pallium-native scenario and replay lane plus semantic regression
   assets to review prompt changes against bounded contracts

Implementation defaults:

- treat prompts as contract carriers, not hidden heuristic layers
- keep schema enforcement stronger than prompt prose
- require explicit abstain or no-op outcomes where the role supports them
- keep query-time prompt use selective and bounded even after prompt-role
  formalization
- prefer one shared governance feature over spreading prompt lifecycle rules
  across multiple later features