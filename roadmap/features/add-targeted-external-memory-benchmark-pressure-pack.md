---
id: add-targeted-external-memory-benchmark-pressure-pack
title: Targeted external memory benchmark pressure pack
status: queued
priority: high
commitment: committed
milestone: Later
lane: external-pressure
---

## Summary

Adopt a small, curated set of external memory benchmarks as pressure tests for
Pallium's core memory engine.

This is not a competitor-comparison feature and not a leaderboard project. The
goal is to use mature public benchmark families to expose memory weaknesses that
our internal downstream-agent and developer-work suites do not naturally cover
well enough yet.

The external pressure pack should focus on the highest-value blind spots first:

- cross-session updates, temporal change, and stale-memory handling
- long noisy conversational recall and multi-hop retrieval under distraction
- incremental multi-turn memory behavior closer to real agent operation

The result should be a bounded external benchmark layer that helps Pallium get
better at memory, not just look benchmark-aware.

## Why

Pallium's internal benchmark program is now deliberately centered on the real
product boundary:

- thin-agent integration
- injection decisions
- low-value suppression
- rebuild churn
- resumed developer work
- evidence-backed continuity

That is correct and should remain the source of truth for downstream-agent
quality.

It still leaves a gap.

Internal suites are shaped by Pallium's current product assumptions, so they are
less likely to expose some generic memory-engine failures until they show up in
real use:

- stale facts beating newer updates
- weak handling of temporal change across sessions
- repeated similar mentions causing wrong recall under long noisy histories
- multi-hop conversational memory failures
- incremental memory degradation over many turns
- overconfident recall where abstention or downgrade would be safer

A targeted external pressure pack can help here because it gives Pallium a
second kind of signal:

- not whether Pallium solved the downstream-agent product problem
- but whether Pallium's core memory machinery is robust against public memory
  stressors we did not invent ourselves

This should improve Pallium by surfacing failure families that our internal
benchmarks may under-sample, then turning those failures into Pallium-native
regressions and tuning work.

Within Pallium's benchmark architecture, this feature belongs to the realism
and pressure side of the stack. It is explicitly not part of the thin-agent
contract hard gate.

## In Scope

- add one bounded external benchmark pressure-pack layer after the internal
  agent memory-decision benchmark program lands
- keep external pressure-pack reporting separate from the contract and trace
  hard gates so generic memory pressure does not get confused with product
  acceptance
- use external benchmarks only to improve Pallium's core memory engine, not to
  position Pallium against other products or publish unstable leaderboard claims
- prioritize adoption in this order:
  1. LongMemEval
  2. LoCoMo
  3. MemoryAgentBench
  4. optional later consideration of PersonaMem or ConvoMem only if
     personalization or preference memory becomes a real Pallium goal
- make LongMemEval the first external benchmark slice because it pressures the
  highest-value generic memory gaps for Pallium:
  - cross-session memory
  - temporal reasoning
  - knowledge updates
  - stale-memory handling
  - change over time and freshness behavior
  - safer handling when prior memory is outdated or contradicted
- add one curated LongMemEval adoption path rather than a broad raw harness
- the LongMemEval slice should produce Pallium-relevant reporting for at least:
  - update versus stale-memory failures
  - temporal ordering failures
  - cross-session carry-forward failures
  - abstention or unsupported-memory failures where applicable
- make LoCoMo the second adoption slice because it pressures:
  - long conversational recall
  - multi-hop memory use
  - noisy-history robustness
  - confusion among repeated similar mentions
  - recall under broad and adversarial conversational drift
- add one curated LoCoMo slice rather than treating every category equally from
  day one
- prioritize LoCoMo categories most relevant to Pallium tuning, such as:
  - temporal reasoning
  - multi-hop retrieval
  - adversarial or confusing recall
  - long-history factual carry-forward
- treat MemoryAgentBench as a later but still committed exploratory slice
- the MemoryAgentBench work should focus on what is useful to Pallium:
  - incremental multi-turn memory behavior
  - memory updating over interaction history
  - conflict handling or selective forgetting pressure
  - long-range context use in agent-like turn sequences
- do not block the feature on exhaustive MemoryAgentBench support if the public
  assets or harness are still too unstable; a bounded reviewed subset is enough
- build one shared mapping layer from external benchmark outcomes into
  Pallium's own failure taxonomy, including at least:
  - retrieval recall failure
  - stale-memory failure
  - wrong-memory selection failure
  - update or conflict handling failure
  - temporal reasoning failure
  - unsupported-memory overreach
- require every adopted external benchmark slice to answer:
  - what core Pallium weakness did this expose?
  - did it reveal a failure family our internal suites were under-testing?
  - can the failure be promoted into a Pallium-native replay or authored
    regression?
- add one promotion path that turns valuable external benchmark misses into
  Pallium-owned replay cases or benchmark scenarios where they become part of
  the repo's long-lived regression set
- add cost and runtime guidance for adopted external packs so they remain
  practical to run as tuning tools instead of becoming aspirational benchmark
  baggage

## Out of Scope

- building a broad competitor-comparison dashboard
- adopting every popular memory benchmark just because it exists
- prioritizing personalization or preference-memory benchmarks before Pallium
  actually needs them
- replacing Pallium's internal developer-work, integration-contract, or
  injection-decision benchmarks with public benchmark numbers
- using external benchmarks to justify moving semantic policy back into the
  downstream agent
- chasing raw leaderboard scores without stable configs, reviewed methodology,
  and clear failure attribution
- making vector retrieval or embedding-provider expansion the main benchmark
  target before memory-quality and memory-decision behavior are trustworthy

## Done When

1. Pallium has a committed external benchmark pressure-pack layer that is
   explicitly for improving the core memory engine, not for competitor
   comparison.
2. A curated LongMemEval slice is running and can surface update, temporal, and
   stale-memory failures in Pallium terms.
3. A curated LoCoMo slice is running and can surface long noisy recall and
   multi-hop conversational memory failures in Pallium terms.
4. A bounded MemoryAgentBench-oriented slice or equivalent agentic public-memory
   subset is running for incremental multi-turn memory pressure.
5. External benchmark results map into Pallium's own failure taxonomy instead of
   living as disconnected benchmark numbers.
6. Valuable public-benchmark failures can be promoted into Pallium-native replay
   or authored regression cases.
7. Reports and roadmap language make it explicit that internal contract and
   trace benchmarks remain the product acceptance gate, while external packs are
   a complementary pressure layer.

## Notes

Recommended sequencing:

1. finish the live thread memory-quality and thin-agent contract slice
2. land the agent memory-decision benchmark program
3. formalize the benchmark architecture and acceptance-gate vocabulary
4. then adopt this targeted external benchmark pressure pack
5. after that, add the live miss-capture and replay-promotion loop so real and
   public failures can feed the same regression vocabulary

Prioritization rationale:

- LongMemEval is first because Pallium's most valuable generic blind spot is
  freshness, update handling, and cross-session change over time
- LoCoMo is second because long noisy conversational recall is a likely real
  weakness, but less immediately valuable than update correctness for
  downstream-agent continuity
- MemoryAgentBench is third because it is conceptually closer to real agents,
  but still newer and best adopted in a bounded way after the more established
  slices are in place
- PersonaMem and ConvoMem are intentionally deferred unless Pallium broadens
  into preference or personalization memory

Implementation defaults:

- prefer reviewed, curated subsets over giant benchmark ingestion on day one
- keep benchmark configs explicit and stable; do not hide unstable prompt or
  model conditions behind a single score
- use external benchmarks to discover missing Pallium failure families, not only
  to produce one more report
- every adopted slice should have a clear path from public-benchmark miss to
  Pallium-specific regression or tuning work
- treat the main output as pressure on Pallium's realism and replay layers, not
  as a replacement for contract or trace hard-gate reporting


