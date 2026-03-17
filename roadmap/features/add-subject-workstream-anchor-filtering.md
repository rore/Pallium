---
id: add-subject-workstream-anchor-filtering
title: Subject and workstream anchor filtering before semantic ranking
status: queued
priority: high
commitment: committed
milestone: Next
lane: stabilization-semantics
---

## Summary

Add lightweight subject and workstream anchors so Pallium can deterministically
separate adjacent topics before semantic ranking.

This feature should not turn Pallium into a graph platform. It should add a
small practical anchor layer that lets retrieval require or strongly prefer
subject overlap when the query and candidate memory expose clear anchors.

The first slice should support enough anchor structure to stop common adjacent-
topic contamination in recurring-question recall and latest-status queries.

## Why

Recent failures show that retrieval still mixes nearby workstreams because topic
separation happens too late and is too heuristic.

When two investigations share:

- similar wording
- nearby auth or operational language
- common surrounding scope

semantic ranking alone is not enough to keep the wrong checkpoint or summary out
of the final carry-forward set.

A small anchor layer is the shortest generic fix for this class of bug.

It also reduces the need for query-time semantic adjudication by making topic
separation happen before final ranking rather than after contamination is
already present.

## In Scope

- add lightweight subject/workstream anchors to write-time memory metadata
- allow anchors to represent at least:
  - workstream or task family
  - system/component/service when present
  - operational surface or subsystem when clearly available
- allow anchors to be extracted through bounded semantic classification or
  normalization rather than large hand-maintained keyword maps
- add query-time extraction or normalization of subject anchors from the query
- prefilter or strongly gate candidates by subject overlap before final
  semantic selection when the query exposes a clear anchor
- preserve a narrow exception for compatible constraint carry-forward only when
  it is actually aligned with the same anchored topic
- expose anchor overlap and anchor-based exclusions in query/debug trace
- add deterministic regressions for:
  - one-token topic prompts
  - richer multi-token topic prompts
  - adjacent-topic contamination with overlapping operational language
  - same-thread status recall where only one workstream should survive

## Out of Scope

- a general-purpose graph engine
- broad ontology management
- arbitrary cross-container entity expansion
- semantic package support beyond the current `agent_conversation_memory` slice

## Done When

1. Queries with clear subject/workstream anchors can prefilter or strongly gate
   unrelated candidates before final carry-forward selection.
2. Adjacent-topic contamination regressions pass for both simple and richer
   multi-token prompts.
3. Constraint exceptions do not bypass the topic gate unless the candidate is
   genuinely aligned with the same anchored workstream.
4. Debug trace shows anchor overlap or anchor-based exclusion clearly.
5. Anchor extraction and normalization are bounded, inspectable, and not mainly
   driven by scenario-specific keyword growth.
6. Ordinary in-scope topical queries no longer need semantic escalation just to
   separate nearby workstreams.
7. The anchor model remains lightweight and local-first rather than expanding
   into a broad graph platform.

## Notes

Recommended sequencing:

- depends on the write-time memory envelope
- can run in parallel with the first-class constraint lane once envelope fields
  exist
- should be validated by the Pallium-native scenario/replay lane and later by
  the external pressure pack for noisy recall

Implementation defaults:

- prefer a small normalized anchor vocabulary over free-form entity graphs
- keep anchor extraction inspectable and replay-testable
- use semantic ranking inside anchored candidate sets, not instead of them
- improve prompts through tighter anchor schemas, alias normalization, and
  explicit unknown handling rather than growing product-specific term lists
