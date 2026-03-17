---
id: add-bounded-query-intent-resolution
title: Bounded query policy contract and selective ambiguity resolution
status: queued
priority: high
commitment: committed
milestone: Next
lane: stabilization-foundation
---

## Summary

Define a bounded query-policy contract for `agent_conversation_memory` and add a
selective semantic ambiguity-resolution step for the minority of queries that
remain unresolved after deterministic narrowing.

This feature should not add a default extra model call on every query. The hot
path should stay deterministic and cheap. A bounded model-backed query
classification step may be used only when cheap pre-guards, scope, kind,
subject, and constraint-aware filtering still leave multiple plausible memory
behaviors or candidate sets.

The semantic step, when it is used, should emit a small stable intent or routing
contract plus confidence and reasons through a structured schema rather than
free-form prompt text. Initial query-policy families should stay narrow and
product-shaped, for example:

- `noise`
- `recall_fact`
- `latest_status`
- `resume_work`
- `check_constraints`

## Why

Pallium still needs an explicit query-policy contract, but the latest research
pass changed how this should land.

Stronger memory systems usually do not run a dedicated LLM router before every
memory lookup. They instead:

- narrow by scope and typed structure first
- retrieve directly inside the narrowed set
- escalate to a semantic router or reranker only when the case is still
  ambiguous

That is a better fit for Pallium's local-first, debuggable product slice than a
per-query model tax.

This feature keeps the benefits of a bounded intent contract without forcing an
always-on semantic classifier into the hot path.

## In Scope

- define the bounded query-policy contract that later query-time features plug
  into
- keep the enum or policy families small and explicitly versioned
- define the deterministic hot path for ordinary queries, including:
  - cheap pre-guards for obvious no-value cases
  - hard scope and visibility filtering
  - use of write-time memory kinds when available
  - use of subject/workstream anchors when available
  - use of typed constraint compatibility when available
  - direct retrieval and ranking inside the narrowed set
- allow a bounded semantic query-resolution step only for ambiguous cases after
  deterministic narrowing
- allow the semantic step to use its own dedicated model role or provider
  settings distinct from write-time extraction, while still supporting a shared
  default model configuration
- require the semantic step, when invoked, to emit at least:
  - chosen bounded policy or intent output
  - confidence
  - concise reasons or features used
  - fallback behavior when confidence is low
- preserve query/debug trace visibility for:
  - whether semantic escalation happened
  - why it happened
  - what bounded decision it returned
- define a stable prompt or schema contract for the semantic step, including:
  - closed structured output
  - versioned prompt text or classifier contract
  - deterministic fallback when classification is low-confidence or invalid
- keep the semantic step aligned with the later shared
  `query_ambiguity_resolution` prompt-role contract instead of treating this
  feature as the long-term owner of query-time prompt governance
- define query-time operational rules, including at least:
  - no model call for obvious no-value cases when a deterministic guard can fail
    closed safely
  - a strict timeout budget for the semantic step
  - schema-invalid and provider-failure fallback behavior
  - conservative low-confidence fallback behavior
  - optional caching or reuse for repeated normalized ambiguity cases where safe
- add focused deterministic tests for:
  - hot-path ordinary recall that should not trigger semantic escalation
  - ambiguous cases that should trigger bounded semantic resolution
  - paraphrase and low-value query classes
  - low-confidence and failure fallback behavior
- add verification that measures:
  - semantic escalation rate
  - added latency and cost when escalation occurs
  - how often deterministic short-circuits avoided a model call

## Out of Scope

- a broad open-ended LLM router
- a mandatory extra model call on every query
- replacing all routing heuristics in one step
- topic/workstream filtering as a standalone feature
- first-class constraint storage semantics
- public API expansion for external intent override

## Done When

1. Pallium has a bounded, explicit query-policy contract that can be reviewed
   independently of phrase tables.
2. Ordinary in-scope recall can stay on the deterministic hot path without a
   mandatory extra model call.
3. Greeting/noise, recall-fact, latest-status, resumed-work, and
   constraint-check prompts can be differentiated without adding scenario
   wording directly into routing tables as the main mechanism.
4. Query/debug trace clearly shows whether semantic escalation happened, why it
   happened, and what bounded decision it returned.
5. Focused regressions cover paraphrase variants, typo variants, low-value/noise
   cases, ambiguous-case escalation, and low-confidence fallback behavior.
6. The semantic-step contract is prompt-versioned and bounded enough that prompt
   changes can be reviewed and replay-tested instead of silently changing query
   semantics.
7. Query-time semantic escalation has explicit timeout, failure, and
   low-confidence behavior, and its latency/cost impact is measured rather than
   assumed acceptable.

## Query Pipeline Contract

This feature owns the first explicit version of the staged query pipeline for
`agent_conversation_memory`.

The intended query flow after this feature family lands is:

1. cheap pre-guards
   - empty or obviously low-value queries may fail closed before any model call
2. hard scope and visibility filtering
3. kind-aware filtering from the write-time memory envelope when available
4. subject or workstream filtering when anchor data exists
5. constraint compatibility filtering when a typed constraint lane exists
6. direct retrieval and ranking inside the narrowed candidate set
7. bounded semantic ambiguity resolution only if the deterministic path still
   leaves multiple plausible memory behaviors or candidate sets
8. final packaging, suppression, and `should_inject` decision
9. query/debug trace emission for the full path

The semantic step is an escalation path, not the default inner loop.

The key rule is:

- models may classify or extract into bounded typed outputs
- Pallium-owned deterministic policy must decide the default hot path and the
  final filtering, compatibility, ranking boundaries, and packaging behavior

This query pipeline contract should be treated as durable feature truth and used
as the reference point for later design and implementation work.

## Notes

Recommended stream placement:

- this is a foundation feature, but it should land after or alongside the
  write-time envelope so deterministic narrowing exists first
- it can run in parallel with broader Pallium-native scenario/replay expansion
  as long as the replay lane treats the query-policy contract as canonical once
  it lands

Implementation defaults:

- prefer a constrained schema output or other bounded classifier contract over
  free-form model routing
- prefer a small cheap dedicated query-resolution model role over reusing a
  larger extraction model by default, while allowing both roles to share one
  model in simpler deployments
- do not require a model call for ordinary in-scope queries if deterministic
  narrowing already gives a plausible bounded candidate set
- keep the resolver package-owned in `agent_conversation_memory`
- preserve debuggability over sophistication
- do not treat prompt growth as the primary way to fix new incidents; new bugs
  should first be categorized as hot-path filter gaps, subject gaps,
  compatibility gaps, freshness gaps, or bounded ambiguity-resolution failures
- this feature owns the concrete query-policy behavior, but the later shared
  prompt-role feature should own the durable query-time prompt contract and its
  replay-governed lifecycle
