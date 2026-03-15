---
id: add-agent-memory-decision-benchmark-program
title: Agent memory-decision benchmark program
status: queued
priority: high
commitment: committed
milestone: Later
---

## Summary

Expand Pallium's benchmark program from retrieval and continuity usefulness into
an explicit downstream-agent memory-decision benchmark.

The new benchmark layer should test whether Pallium can act as an opinionated
memory sidecar for a thin agent runtime:

- decide when memory should help
- decide when memory should stay quiet
- surface the right memory kind for the query family
- package integration-ready injection output directly
- avoid forcing the downstream agent to add local semantic cleanup, reranking,
  or injectability heuristics

This should turn the first live downstream-agent lessons into a repeatable,
repo-local benchmark program rather than relying on anecdotal integration traces.

## Why

The current benchmark stack is already useful, but it still reflects Pallium's
older shape as mostly a retrieval and routing system.

Today we have solid coverage for:

- work-resumption continuity
- routing and layer choice
- public-corpus continuation pressure
- integration-readiness value / no-value / privacy guardrails

The first live downstream-agent integration showed that this is not enough.

The real product boundary is now:

- agent sends runtime facts and raw events
- Pallium returns memory decisions and integration-ready carry-forward output

That run exposed gaps our current suites do not score directly:

- generic summaries can still beat sharper memory even when strong memory exists
- ingest-time low-value promotion and rebuild churn matter as much as query-time
  routing
- "retrievable" is not the same as "good to inject"
- same-thread continuation and no-value behavior are really injection-decision
  problems, not only retrieval problems
- the agent boundary stays thin only if Pallium can make the right
  memory-decision and packaging call without local semantic compensation

So the benchmark program now needs to score Pallium as a memory-decision system,
not only as a retrieval stack.

## In Scope

- add a new benchmark layer that evaluates the canonical thin-agent contract:
  - raw events and runtime facts in
  - `should_inject`, `decision_reason`, and `injectable_blocks` out
- add authored scenarios that explicitly score injection decisions for:
  - new-thread continuation
  - resumed-session continuation
  - same-thread continuation where memory should stay quiet
  - broad recurring recall
  - investigative-conclusion recall
  - resumed-work carry-forward
  - exact evidence follow-up
- expand the current authored continuity scenarios so they label not only:
  - expected intent
  - expected primary layer
  but also:
  - expected injection decision
  - expected decision reason
  - expected injected block types
  - acceptable injected block count
  - forbidden injected memory kinds
- add a benchmark lane for low-value/noise and churn behavior that scores:
  - whether low-value turns create durable memory
  - whether low-value turns schedule thread rebuilds
  - whether short noisy conversations cause summary supersession churn
- add a benchmark lane for sharp-vs-generic competition where:
  - `investigation_outcome`
  - `decision`
  - `task_checkpoint`
  - `thread_summary`
  - `discussion_summary`
  coexist and the benchmark scores whether the right sharp memory wins for the
  query family
- add a benchmark lane for bounded freshness/conflict handling:
  - fresher same-kind lower-level conclusions should rank above older ones
  - same-thread replacements should beat older same-kind memory
  - cross-thread conflicting conclusions should remain visible and debuggable
    without pretending global truth resolution exists
- add replay-style reviewed scenarios derived from live downstream-agent traces,
  but generalized and scrubbed so the repo benchmark remains product-level and
  does not depend on private downstream details
- extend the benchmark failure taxonomy beyond continuity usefulness to include:
  - `injection_decision_failure`
  - `injectability_packaging_failure`
  - `low_value_promotion_failure`
  - `thread_rebuild_churn_failure`
  - `thin_agent_boundary_failure`
- extend the composite confidence suite so it can say whether the dominant
  bottleneck is now:
  - retrieval recall
  - routing
  - packaging
  - injection decision
  - ingest-time noise/churn
- add one thin-agent simulation harness that:
  - ingests only the supported raw artifact shapes
  - sends only mechanical runtime context
  - consumes Pallium's integration-ready output directly
  - does not apply local phrase filters, memory-kind preferences, or semantic
    reranking
- keep the public-corpus layer, but expand reviewed continuation slices so they
  include:
  - no-value same-thread follow-ups
  - paraphrased "what did we conclude" prompts
  - paraphrased "what should we do next" prompts
  - weaker conversational noise around otherwise valid carry-forward queries
- make benchmark reports explicitly answer:
  - did Pallium help?
  - did Pallium stay quiet when it should?
  - what got injected?
  - what should have been injected?
  - did the agent need to compensate semantically?

## Out of Scope

- replaying or storing private downstream traffic in the repo
- benchmarking arbitrary workflow-engine orchestration behavior
- replacing the current routing, continuity, or public-corpus suites entirely
- building a full downstream-agent product simulator with tools, auth, and UI
- making vector retrieval the benchmark focus before memory-decision and
  packaging behavior are trustworthy
- using benchmark growth as justification to move semantic policy back into the
  downstream agent

## Done When

1. Pallium has a committed benchmark layer that evaluates memory decisions and
   injection-ready output, not only retrieval and answer improvement.
2. Authored scenarios explicitly score `should_inject`, `decision_reason`, and
   injected block quality for continuation, investigation, evidence, and
   no-value cases.
3. The benchmark program can catch low-value promotion and thread rebuild churn
   regressions, not only query-time retrieval/routing regressions.
4. Sharp-vs-generic competition scenarios can fail when generic summaries beat
   sharper memory for investigative or resumed-work prompts.
5. Freshness/conflict scenarios can fail when stale same-kind conclusions beat
   fresher ones or when conflicts become invisible in the debug contract.
6. One thin-agent simulation harness proves a downstream agent can stay
   mechanical and still get useful carry-forward behavior from Pallium.
7. The composite developer-work confidence report can identify whether the next
   dominant problem is recall, routing, packaging, injection decision, or
   ingest-time noise/churn.
8. This benchmark program becomes the acceptance gate for future changes to the
   agent integration contract, routing, packaging, and memory-worthiness logic.

## Notes

Implementation defaults:

- treat the current feature [C:\Dev\rore\Pallium\roadmap\features\add-live-thread-memory-quality-hardening.md](C:\Dev\rore\Pallium\roadmap\features\add-live-thread-memory-quality-hardening.md)
  as the contract shape this benchmark is meant to validate, not bypass
- extend the current benchmark vocabulary in
  [C:\Dev\rore\Pallium\docs\designs\010-developer-work-continuity-benchmark-and-open-corpus-tuning.md](C:\Dev\rore\Pallium\docs\designs\010-developer-work-continuity-benchmark-and-open-corpus-tuning.md)
  rather than inventing a disconnected second benchmark philosophy
- prefer reviewed scenario manifests and stable fixture traces over ad hoc live
  anecdotes
- keep private downstream-specific names and details out of benchmark assets
- preserve explicit failure attribution; do not collapse everything into a
  single pass/fail score

Recommended benchmark additions:

- one authored injection-decision suite
- one low-value/churn regression suite
- one sharp-memory competition suite
- one bounded freshness/conflict suite
- one thin-agent simulation harness
- one generalized replay pack from live downstream-agent lessons
