---
id: add-bounded-query-intent-resolution
title: Bounded query intent resolution before retrieval routing
status: queued
priority: high
commitment: committed
milestone: Next
lane: stabilization-foundation
---

## Summary

Add a bounded, explainable query-intent resolver in front of retrieval routing so
Pallium stops relying mainly on phrase lists and candidate-shape accidents to
choose memory behavior.

The resolver should be model-backed, but tightly bounded. It should emit a
small stable intent enum plus confidence and reasons through a structured
contract rather than free-form prompt text. Initial intent families should stay
narrow and product-shaped, for example:

- `noise`
- `recall_fact`
- `latest_status`
- `resume_work`
- `check_constraints`

Routing, suppression, and allowed memory-kind policy should attach to that enum
instead of spreading across ad hoc lexical cue tables.

## Why

Pallium's current instability is no longer mainly a missing-tests problem.
Real failures still cluster around:

- greeting and low-value chatter entering recall packaging
- paraphrase-sensitive recall wording
- same-thread corrections being misrouted
- evidence-oriented layers winning when the question is asking for compact
  carry-forward

These are signs that query understanding is too coupled to brittle lexical
heuristics.

A bounded intent step is the smallest architectural move that reduces
phrase-chasing without making Pallium opaque.

It also preserves Pallium's generic scope because the intent enum describes
memory behavior classes, not downstream-specific scenarios or tool names.

## In Scope

- add a bounded query-intent resolver before retrieval-family and packaging
  selection
- implement the resolver as a constrained semantic classification step, not as
  another large phrase table and not as an open-ended free-form router
- keep the enum small and explicitly versioned
- emit at least:
  - chosen intent
  - confidence
  - concise reasons or features used
  - fallback behavior when confidence is low
- make routing policy attach to intent rather than directly to large cue tables
- use intent to drive at least:
  - low-value/noise fail-closed behavior
  - allowed memory kinds for recall packaging
  - broad recall vs latest-status vs resumed-work behavior
  - constraint-check behavior
- preserve query/debug trace visibility for the resolver output
- keep lexical heuristics only as cheap edge guards or fallback evidence, not
  the primary routing architecture
- define a stable prompt or schema contract for the resolver, including:
  - closed enum output
  - versioned prompt text or classifier contract
  - deterministic fallback when classification is low-confidence or invalid
- add focused deterministic tests for paraphrase and low-value query classes
- add resolver-specific regressions that prove behavior is not tied to one
  scenario wording only

## Out of Scope

- a broad open-ended LLM router
- replacing all routing heuristics in one step
- topic/workstream filtering
- first-class constraint storage semantics
- public API expansion for external intent override

## Done When

1. Query routing is driven by a small explicit intent enum rather than only by
   phrase tables and candidate-shape accidents.
2. Greeting/noise, recall-fact, latest-status, resumed-work, and
   constraint-check prompts can be differentiated without adding scenario
   wording directly into routing tables as the main mechanism.
3. Query/debug trace clearly shows the chosen intent, confidence, and reasons.
4. Focused regressions cover paraphrase variants, typo variants, low-value/noise
   cases, and low-confidence fallback behavior.
5. Existing routing behavior can be reviewed in terms of intent mistakes rather
   than only family or cue drift.
6. The resolver contract is prompt-versioned and bounded enough that prompt
   changes can be reviewed and replay-tested instead of silently changing
   routing semantics.

## Notes

Recommended stream placement:

- this is the first architecture stabilization step
- it can run in parallel with broader Pallium-native scenario/replay expansion
  as long as the replay lane treats the intent contract as canonical once it
  lands

Implementation defaults:

- prefer a constrained schema output or other bounded classifier contract over
  free-form model routing
- use the model only to classify into a Pallium-owned closed enum; all later
  filtering and packaging policy should remain deterministic
- keep the resolver package-owned in `agent_conversation_memory`
- preserve debuggability over sophistication
- do not treat prompt growth as the primary way to fix new incidents; new bugs
  should first be categorized as intent, kind, subject, compatibility, or
  freshness failures

