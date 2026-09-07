---
id: optimize-developer-test-loop
title: Optimize the developer test loop
status: in_progress
priority: high
commitment: committed
milestone: engineering-health
lane: test-infrastructure
---

## Summary

Make agent development feedback fast by standardizing focused pytest runs and removing one duplicated count-harness execution, while fixing cancellation-safe operation draining exposed by the scheduler-sensitive Relay isolation test.

## In Scope

- define the edit → subsystem → full validation ladder for agents
- use serial pytest for exact node/file development runs and native last-failed reruns
- perform the deterministic vNext count measurement once while preserving both checks
- keep Relay and diagnostic operations counted until the actual worker completes across active, queued, cancelled, and failed paths
- tolerate scheduler jitter in the Relay capacity-isolation guard while preserving the isolation proof

## Out of Scope

- CI worker-count changes
- dependencies, pytest configuration, or new markers
- public contracts or unrelated product behavior
- the separately queued slow-suite contract repair

## Done When

1. Repository instructions make focused tests the normal development loop and reserve the full suite for pre-review validation.
2. Cancellation and failure cannot let the shutdown barrier finish before the actual worker, and queued work drains without counter leaks.
3. The Relay isolation tests pass repeated focused/default-worker runs without weakening blocked-capacity proofs.
4. The vNext count gate runs one measurement and retains normal plus seeded-regression coverage.
5. The full default suite and governance checks pass.