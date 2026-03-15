# Validation

This page summarizes the validation surface for Pallium.

The goal is to show what the repository currently tests, what has recorded
baselines or successful runs in the current package, and what still needs more
proof.

## What Pallium Currently Tests

Today the repository includes validation for:

- structured memory extraction quality
- repeated-question recall
- resumed-work continuity
- query-path behavior and fallback between memory and source evidence
- scoped visibility and privacy leak guards
- integration-readiness scenarios for the current package
- public-corpus evaluation slices drawn from reviewed WildChat and WildBench
  episodes
- tiered-memory usefulness and false-merge safety

## What That Means In Practice

The current product focus has explicit checks around:

- whether Pallium can bring back prior conclusions
- whether it can preserve useful resumed-work state
- whether retrieval can explain itself when results look wrong
- whether scoped memory stays fail-closed across public and private contexts
- whether the current package still behaves reasonably on messier public-corpus
  slices

## What Has Recorded Baselines Or Successful Runs

Repo-local state currently records successful or committed baselines for:

- semantic regression on the structured extraction path
- recurring-question benchmark runs
- resumed-work benchmark runs
- query-path benchmark runs for memory versus source evidence selection
- integration-readiness scenario runs
- public-corpus evaluation workflows

For the detailed recorded outputs and latest maintained notes, see
`docs/context/state.md`.

## What Remains Uncertain

The main remaining uncertainties are:

- how far resumed-work packaging generalizes across broader downstream traffic
- when broader carry-forward memory should beat lower-level evidence
- whether lexical retrieval is already enough or whether vector and hybrid
  retrieval are the next real bottleneck
- how much broader shared-memory behavior should exist beyond the current scoped
  package

## Why This Matters

The validation surface is part of how Pallium is developed:

- repeated-question consistency is tested
- resumed-work continuity is tested
- privacy leakage is explicitly guarded
- retrieval behavior is inspectable, not opaque

## Read Next

- current maturity: [status.md](status.md)
- product problem and value: [problem-and-approach.md](problem-and-approach.md)
- quick local tryout: [getting-started.md](getting-started.md)
