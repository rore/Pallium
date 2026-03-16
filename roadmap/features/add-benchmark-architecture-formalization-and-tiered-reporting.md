---
id: add-benchmark-architecture-formalization-and-tiered-reporting
title: Benchmark architecture formalization and tiered reporting
status: queued
priority: high
commitment: committed
milestone: Next
---

## Summary

Operationalize Pallium's benchmark architecture so the eval stack reports and
gates by benchmark lane and dataset tier instead of only by accumulated runner
names.

This feature turns the documented benchmark architecture into repo-enforced
behavior:

- contract and trace lanes remain the acceptance foundation
- usefulness stays narrow and secondary
- realism assets are explicitly organized as iteration, confidence, or replay
- operational metrics become first-class benchmark output

## Why

Pallium now has the right benchmark direction on paper, and major pieces of that
direction are already shipped:

- thin-agent contract scoring
- trace-aware routing and packaging scoring
- low-value and rebuild-churn coverage
- public-corpus realism slices
- composite confidence reporting

That is not the same as having the benchmark architecture fully operationalized.

Today the benchmark program is still organized mostly by runner history rather
than by one explicit evaluation model. That creates a few risks:

- hard gates remain partly implicit
- dataset tiers are not yet first-class benchmark metadata
- replay discipline is not yet part of the benchmark structure
- operational metrics can be under-emphasized beside correctness summaries
- external pressure packs could arrive before the reporting model is ready to
  keep them clearly separate from the product acceptance gate

This feature closes that gap.

## In Scope

- formalize the five benchmark lanes in the eval program and reports:
  - contract
  - trace
  - usefulness
  - realism
  - operational
- make contract and trace the explicit hard-gate lanes in benchmark summaries
  and confidence reporting
- distinguish hard-gate metrics from tuning signals in benchmark outputs and
  docs that drive implementation decisions
- add explicit dataset-tier support across benchmark assets and reporting:
  - iteration
  - confidence
  - replay
- update reviewed scenario manifests and benchmark helpers so benchmark assets
  can be classified by tier where needed
- update aggregate benchmark reporting so results are grouped by lane and by
  dataset tier rather than only by runner name
- make replay a first-class target in the benchmark architecture even if the
  later live miss-capture pipeline still owns the actual replay promotion flow
- add operational reporting for at least:
  - injected block count distribution
  - over-injection or no-value injection rate
  - low-value promotion rate
  - rebuild churn rate
  - stale-memory failure rate
  - latency and provider cost where supported by the runner
  - repeated-run flakiness where practical
- keep usefulness judging narrow and policy-driven:
  - deterministic first
  - constrained rubric or pairwise judging only where deterministic checks are
    insufficient
  - no open-ended answer-quality judging as the benchmark default
- make the developer-work confidence report clearly identify:
  - hard-gate status
  - dominant tuning bottleneck
  - realism or replay pressure signals
  - operational drift signals
- align existing benchmark docs and implementation vocabulary so the eval stack,
  confidence report, and roadmap use the same lane and tier terms

## Out of Scope

- building the external benchmark pressure-pack slices themselves
- implementing the live miss-capture and replay-promotion pipeline itself
- replacing existing authored or public-corpus benchmark assets wholesale
- turning usefulness evaluation into broad LLM-judged answer scoring
- broadening the benchmark program into generic agent-runtime or workflow
  evaluation

## Done When

1. Pallium's benchmark reports and confidence outputs explicitly group and
   explain results by benchmark lane.
2. Contract and trace are clearly enforced as the acceptance-gate lanes.
3. Benchmark assets can be classified as iteration, confidence, or replay and
   that tiering is reflected in reporting.
4. Operational benchmark metrics are surfaced alongside correctness and routing
   results.
5. The benchmark stack can cleanly accommodate external pressure packs without
   confusing them with the product acceptance gate.
6. The benchmark architecture described in the design docs is reflected in the
   actual repo-local eval structure rather than only in prose.

## Notes

Recommended sequencing:

1. ship the benchmark architecture formalization and tiered reporting layer
2. then adopt the targeted external memory benchmark pressure pack
3. then add the live miss-capture and replay-promotion loop so replay assets
   can grow through one disciplined path

Implementation defaults:

- prefer extending the current eval helpers and confidence suite over building a
  second benchmark framework
- preserve the current deterministic benchmark core
- keep usefulness judging narrow and optional until deterministic checks clearly
  stop being sufficient
- treat replay as a first-class reporting tier even before the live replay loop
  is fully automated
- keep benchmark truth repo-local even if external or commercial eval products later inspire UX or workflow ideas


