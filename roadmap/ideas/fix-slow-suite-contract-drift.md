---
id: fix-slow-suite-contract-drift
title: Repair stale contracts in the complete slow test suite
status: queued
priority: medium
commitment: uncommitted
---

## Summary

Bring the complete `-m slow` suite back to green before expanding scheduled coverage beyond the bounded hermetic smoke lane.

## Evidence

A neutral local audit on 2026-09-07 produced 32 failed, 135 passed, 1 skipped, 1 xfailed, and 1 xpassed. Failures cluster in stale semantic and eval expectations, including the separately identified work-resumption scenario-count drift.

## In Scope

- classify the 32 failures by obsolete expectation, product regression, or fixture drift
- repair the smallest shared causes without weakening assertions
- keep candidate-recovery, injection-precision, and downstream-task-effect measurements distinct
- make `python -m pytest tests/ -m slow` green under the intended optional dependencies

## Done When

1. The complete slow suite passes with expected skips and xfails documented.
2. Repaired expectations remain semantically meaningful rather than accepting current output blindly.
3. Scheduled coverage can be expanded based on measured runtime and isolation.
