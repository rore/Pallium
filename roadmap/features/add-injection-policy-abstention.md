---
id: add-injection-policy-abstention
title: Injection policy abstention — narrow delivery, type-gated proactivity, deterministic on-demand
status: in-progress
priority: high
commitment: committed
milestone: Next
---

## Summary

Replace today's broadly-proactive injection with a per-type policy gated
on the injected-block result `score`. Types whose feedback shows
separable score distributions (`constraint_memory`, `decision`) stay
proactive with thresholds. Types whose scores don't separate
(`investigation_outcome`, `thread_summary`, `fact_summary`) become
on-demand or trigger-driven. `task_checkpoint` switches to an
event-trigger model (session resumption + path/branch match) rather
than score-thresholded proactive.

## Why

Five months of self-rated injection feedback shows base precision
~44%, dominated by topically-similar-but-question-irrelevant misses
("off-topic in the moment"). Multiple shipped mechanism iterations did
not move this number. Score separability analysis shows ~half the
memory types cannot reach 70% precision under any threshold. The
right next move is delivery-policy abstention, not another mechanism.

## Spec

[`docs/specs/2026-06-27-injection-policy-abstention.md`](../../docs/specs/2026-06-27-injection-policy-abstention.md)

## Phases

- [x] Phase 0 — analysis snapshot committed
- [ ] Phase 0.5 — `candidate_scores_json` extended with result `score`
- [ ] Phase 1 — chronological holdout threshold validation
- [ ] Phase 2a — approximate historical decision-simulation replay
- [ ] Phase 2b — exact prospective replay (requires fresh data window)
- [ ] Phase 3a — config schema + selection-path gate for proactive types
- [ ] Phase 4 — deterministic triggers in Claude Code integration
- [ ] Phase 3b — demote weak types (ships with Phase 4)
- [ ] Phase 5 — `memory_usage_audit` table + populator
- [ ] Phase 6 — 4-week measurement window
