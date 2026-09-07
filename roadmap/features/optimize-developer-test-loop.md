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

Make agent development feedback fast by standardizing focused pytest runs, removing one duplicated count-harness execution, and hardening a scheduler-sensitive Relay isolation test without reducing required coverage.

## In Scope

- define the edit → subsystem → full validation ladder for agents
- use serial pytest for exact node/file development runs and native last-failed reruns
- perform the deterministic vNext count measurement once while preserving both checks
- tolerate scheduler jitter in the Relay capacity-isolation guard while preserving the isolation proof

## Out of Scope

- CI worker-count changes
- dependencies, pytest configuration, or new markers
- product behavior or public contracts
- the separately queued slow-suite contract repair

## Done When

1. Repository instructions make focused tests the normal development loop and reserve the full suite for pre-review validation.
2. The Relay isolation test passes repeated focused/default-worker runs without weakening its blocked-capacity proof.
3. The vNext count gate runs one measurement and retains normal plus seeded-regression coverage.
4. The full default suite and governance checks pass.