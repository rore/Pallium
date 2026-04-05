# Vision

## What Pallium Is

Pallium is a generic memory engine for agents.

It stores selected source items, derives reusable knowledge from them through
extensible semantic layers, and returns compact evidence-backed memory objects
to downstream consumers.

One important internal use case is team knowledge support for an agent, but the
project itself should remain generic and open-source friendly.

The first concrete semantic package is agent_conversation_memory. That package
is intentionally narrower than Pallium itself and is the first product slice
being used to prove value.

Pallium's differentiated direction is derived knowledge memory for agents:
not only fact storage and not only episodic transcript recall, but compact,
evidence-backed knowledge objects such as decisions, investigation outcomes,
and later higher-level recurring patterns.

The main thing Pallium is trying to preserve is knowledge produced during the
agent's own reasoning work: conclusions, findings, checkpoints, constraints,
and later the evolution of those conclusions over time. That is different from
only re-finding facts that already existed cleanly in source systems.

Real downstream incidents should shape Pallium's priorities, but they should be
translated into reusable memory behaviors rather than turning Pallium into a
collection of scenario-specific fixes. Product decisions should therefore be
framed as generic retrieval policy, routing policy, packaging policy,
memory-worthiness policy, lifecycle policy, compatibility handling, or
benchmark categories rather than as one downstream product's vocabulary.

## North-Star Use Cases

Pallium's roadmap should be driven by the downstream-agent use cases it is meant
to solve, not by generic memory-system feature accumulation.

The north-star use cases are:

- requirement and architecture questions answered from prior decisions,
  reasoning, and evidence rather than transcript rediscovery
- long-running investigation continuity, where prior findings, rejected paths,
  and supporting evidence are carried forward cleanly
- resumed work after interruption, where a later continuation begins with prior
  progress, blockers, and next-step orientation instead of restarting analysis
- repeated-question reuse across later conversations when the same conclusion
  should safely help again
- evidence-backed reuse of findings discovered while exploring external
  systems, without turning Pallium into the system of record for those systems
- long-lived conversation continuity that relies on compact memory and explicit
  injection decisions rather than growing transcript replay
- evaluation of whether downstream agents remember what matters, stay quiet
  when they should, and remain thin rather than accumulating local memory
  heuristics

These use cases should be the standard for deciding what Pallium needs next,
what gaps matter most, and which later capabilities are worth the complexity.
Concrete incidents are useful evidence, but they should not narrow Pallium into
product-specific names, tool terms, or one-off prompt wording.

## Benchmark Direction

Pallium's benchmark program should be treated as part of the product
architecture, not as an afterthought.

The benchmark north star is the thin-agent memory-decision boundary:

- remember what matters
- stay quiet when local context is already sufficient
- return compact, evidence-backed, injection-ready carry-forward
- avoid stale, wrong-scope, privacy-unsafe, or low-value memory
- avoid forcing semantic cleanup back into the downstream agent

The benchmark architecture should therefore keep:

- deterministic contract and trace grading as the foundation
- usefulness judging narrow and secondary
- authored and reviewed realism sets as the product-shaping realism layer
- external benchmark packs as complementary pressure on the core memory engine,
  not as product truth
- live misses promoted into replay assets so real interaction failures become
  permanent regressions

That benchmark program should also preserve Pallium's generic scope:

- live misses should be generalized into Pallium-owned failure classes before
  they become replay assets
- benchmark and replay fixtures should stay anonymized and domain-generic by
  default
- scenario-specific downstream vocabulary should not become the benchmark
  architecture's naming system

## What Pallium Is Not

Pallium is not:

- a system-of-record database
- a connector framework as its core identity
- an agent runtime
- a workflow engine
- a replacement for source retrieval from Jira, GitHub, docs, logs, or chat

## Core Principles

1. Generic core, extensible semantic layer.
   The core stores memory primitives. Semantic layers define meaning.

2. Source of truth stays outside.
   Pallium stores selected copies and derived knowledge, not the authoritative
   record for external systems.

3. Selective ingestion.
   Important source items should be ingested intentionally, not mirrored
   exhaustively.

4. Raw first, semantics second.
   Source items are persisted first. Semantic output is additive and replayable.

5. Evidence-backed memory.
   Durable memory objects must link back to supporting source evidence.

6. Local-first deployment.
   Pallium should run as a simple local stack first and scale only when needed.

7. Provider abstraction.
   Model access must sit behind adapters so model choices can change without
   reshaping the core.

8. Structured retrieval first.
   Prefer filters, relations, and lexical retrieval where possible. Semantic
   retrieval is an enhancement, not the only foundation.

9. Versioned semantics.
   Memory objects and consolidation outputs should be attributable
   to a schema and producer version.

10. Tiered memory is an extension.
    Higher-level consolidation is important, but it should not be required for
    the base system to function.

11. Build iteratively around a walking skeleton.
    Prefer a thin end-to-end system with all major layers present over a large
    upfront design freeze.
