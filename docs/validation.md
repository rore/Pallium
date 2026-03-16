# Validation

This page summarizes the validation surface for Pallium.

The validation model is now organized by explicit benchmark lanes and dataset
tiers instead of only by historical runner names.

## Benchmark Lanes

Pallium's benchmark program uses five lanes:

- `contract`: thin-agent memory contract correctness, including query contract,
  packaging contract, and boundary discipline
- `trace`: routing, retrieval, and decision-trace correctness for the memory
  path that was chosen
- `usefulness`: narrow deterministic checks for whether memory should help in
  the current product slice
- `realism`: reviewed pressure from messier follow-ups and public-corpus slices
  that should influence tuning without replacing the hard gate
- `operational`: low-value promotion, rebuild churn, over-injection, and other
  drift signals the repo can measure defensibly today

`contract` and `trace` are the hard-gate acceptance lanes.

`usefulness`, `realism`, and `operational` are tuning or pressure lanes. They
matter for prioritization and tuning, but they do not replace the acceptance
gate for the thin-agent memory contract and decision trace.

## Dataset Tiers

Benchmark assets are also classified into three dataset tiers:

- `iteration`: fast, local tuning slices used during development
- `confidence`: reviewed assets that make up the current repo-local confidence
  gate
- `replay`: support for replay-driven benchmark assets, reported explicitly even
  before the live miss-capture pipeline exists

Replay is first-class in the reporting model now, even though replay coverage is
still sparse and the live promotion pipeline is a later feature.

## Current Benchmark Mapping

The current benchmark suites map into the architecture as follows:

- `memory_routing`: lane focus `trace`, tier `confidence`, contributes to hard
  gate coverage for both `contract` and `trace`
- `work_resumption`: lane focus `realism`, tier `confidence`, contributes to
  `contract`, `trace`, `usefulness`, `realism`, and `operational`
- reviewed `public_corpus` slices: lane focus `realism`, tier `confidence`,
  contribute to `contract`, `trace`, `usefulness`, `realism`, and `operational`
- `low_value_churn`: lane focus `operational`, tier `confidence`, contributes to
  `trace` and `operational`
- `recurring_question`: lane focus `usefulness`, tier `iteration`, contributes
  to `usefulness` and `realism`

This keeps the deterministic core centered on the current product claim:
conversation continuity, resumed work, scoped recall, and thin-agent memory
behavior.

## Confidence Gate

The developer-work confidence report now rolls up by lane and tier first.

The current confidence gate is defined by:

- hard-gate coverage for `contract` and `trace` must be present before the gate can go green
- hard-gate status for `contract`
- hard-gate status for `trace`
- reviewed `confidence`-tier coverage from `memory_routing`,
  `work_resumption`, reviewed public-corpus slices, and `low_value_churn`

The same report also separates:

- realism pressure from acceptance failures
- replay-tier pressure from current hard-gate status
- operational drift from correctness failures
- dominant tuning bottlenecks from dominant failing benchmark lanes

## Operational Metrics Surfaced Today

Current reporting surfaces operational signals only where the repo already has
defensible data:

- injected block count distribution
- no-value overreach rate
- stale-memory failure rate
- wrong-memory selection failure rate
- low-value promotion failure rate
- thread rebuild churn failure rate

The repo does not yet treat latency, provider cost, or broad flakiness as
formal benchmark metrics by default.

## What Remains Uncertain

The main remaining uncertainties are:

- how broad replay coverage should become once live miss-capture promotion
  exists
- how far resumed-work packaging generalizes across broader downstream traffic
- where realism pressure should trigger new authored scenarios versus better
  deterministic checks
- whether lexical retrieval remains sufficient or whether retrieval itself
  becomes the next hard bottleneck

## Why This Matters

The validation surface is part of how Pallium is developed:

- acceptance stays anchored to the thin-agent memory contract and trace
- realism pressure can inform tuning without redefining the product target
- replay has a reserved place in the architecture before the pipeline is built
- operational drift is visible instead of being buried under correctness totals

## Read Next

- current maturity: [status.md](status.md)
- product problem and value: [problem-and-approach.md](problem-and-approach.md)
- quick local tryout: [getting-started.md](getting-started.md)