---
id: add-qpp-injection-justification
title: Add QPP-based injection justification
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Replace the binary retrieval relevance floor with a QPP (Query Performance
Prediction) justification score that evaluates whether retrieval produced a
trustworthy result set before injecting memory into the agent context.

## Why

Pallium injected memories into off-topic queries ("how's the weather?") because
retrieval always returns something and the injection decision had no way to
evaluate result set quality. Previous fixes (lexical floor, per-candidate gate,
content overlap) all broke legitimate recall queries where memory text has
generic wording ("what should I do next?" shares no words with "batch 417
blocked by stale handles").

QPP is an established IR technique: estimate retrieval quality from the score
distribution and result structure, without relevance labels or conversation
history. This fits Pallium's stateless API constraint perfectly.

## In Scope

- Justification score computed from four signal groups:
  - Score shape (top score strength, dispersion, top-1/top-2 gap, flatness)
  - Memory type richness (task_checkpoint, decision, investigation_outcome)
  - Support grade strength (weak/supported/strong distribution)
  - Recency factor (freshness relative to container cadence)
- Dual formula calibration (justify_inject vs justify_suppress)
- Calibration runner against 44 labeled scenarios from benchmark + exploratory QA
- Wired into `_build_injectable_blocks` in routing selection
- Replaces binary relevance floor and lexical-only bypass

## Out of Scope

- Multi-channel agreement signals (lexical-vector rank correlation) — deferred,
  not needed at current scale
- Container cadence normalization — deferred, simple absolute recency sufficient
- Intent classification or agent-side cooperation

## Done When

1. Off-topic queries ("how's the weather?", "under the weather") suppress injection
2. Legitimate recall queries ("what should I do next?") still inject when
   structure justifies (active checkpoint, recent work memories)
3. Calibrated against labeled scenario set with documented thresholds
4. Full regression suite passes with no regressions
5. Design doc: `docs/designs/off-topic-injection-qpp-design.md`
