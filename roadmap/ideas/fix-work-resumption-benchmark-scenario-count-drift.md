---
id: fix-work-resumption-benchmark-scenario-count-drift
title: Fix stale scenario-count assertions in the work-resumption benchmark test
status: queued
priority: medium
commitment: uncommitted
---

## Summary

`tests/test_work_resumption_benchmark.py` (slow-marked) asserts
`scenarios_total == 13` in five places (lines ~253, 256, 270-272), but
`evals/work_resumption/scenarios.json` has since grown (~19 entries). The test
therefore fails whenever it is run, plus downstream semantic assertions appear to
have drifted too. Because the file is `slow`-marked it runs in NO default CI lane,
so the breakage is invisible in normal CI — it only surfaces on an explicit
`-m slow` run.

## Why

Discovered incidentally while running the reuse-guard during vNext work. It is a
pre-existing, unrelated breakage (predates and is independent of vNext — the file
is byte-identical to HEAD). A benchmark test that can never pass is worse than no
test: it hides real regressions behind an assumed-known failure. Left untracked it
will keep being waved past as "the known work_resumption failures."

## In Scope

- Determine whether the scenario growth (13 → ~19) was intentional; if so, update
  the count assertions and the per-lane `lane_aggregates` `scenarios_total`
  expectations to match, plus any downstream semantic expectations that drifted.
- If the growth was NOT intentional (scenarios added without updating the test),
  decide whether to trim or keep — with the owner of those scenarios.
- Get the slow-marked test green again on `-m slow`.

## Out of Scope

- Un-slow-marking the test or adding it to default CI (separate decision).
- Any change to the work-resumption benchmark's scoring or scenarios' content
  beyond reconciling counts/expectations.

## Done When

1. `python -m pytest tests/test_work_resumption_benchmark.py -m slow` passes.
2. The count + lane-aggregate assertions reflect the actual scenario set, and any
   drifted semantic assertions are reconciled (or the scenario set corrected).

## Notes

Evidence: `tests/test_work_resumption_benchmark.py:253,256,270-272` (asserts 13);
`evals/work_resumption/scenarios.json` (grown). Non-blocking for CI today because
`pytestmark = pytest.mark.slow` excludes it from the default lane.
