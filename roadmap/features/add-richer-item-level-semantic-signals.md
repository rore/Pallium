---
id: add-richer-item-level-semantic-signals
title: Add richer item-level semantic signals in the existing LLM call
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Expand the existing per-item LLM extraction so one call produces typed memory candidates plus internal-only work-state signals that Pallium can reuse during thread summaries and task checkpoints.

## Why

Pallium was still relying too much on string heuristics to recover constraints, blockers, progress, next steps, and key findings from plain `message` and `assistant_output` text. That made realistic agent threads too dependent on caller-perfect artifact shaping and too vulnerable to low-value assistant chatter.

## In Scope

- widen the existing item-level extraction schema rather than adding another per-item LLM call
- extract internal-only semantic signals such as:
  - `is_low_value_meta`
  - `constraint_text`
  - `next_step_text`
  - `blocker_text`
  - `progress_text`
  - `key_finding_text`
- keep `decision` and `investigation_outcome` as the only lower-level typed memory kinds
- persist those internal signals in existing compatible storage so later synthesis can inspect them without schema changes
- make `agent_conversation_memory` prefer stored item-level signals over plain-text heuristics during higher-level synthesis
- tighten the production prompt with field-specific nulling rules and examples, then verify it against a real configured provider
- add an opt-in live semantic smoke suite so real-model behavior can be checked without making normal test runs network-dependent

## Out of Scope

- new public memory kinds
- new HTTP endpoints
- adding a second classifier call per item
- moving semantics into the caller/runtime instead of Pallium
- making arbitrary runtime chatter equally memory-worthy

## Done When

1. One item-level LLM call can produce typed candidates plus internal semantic signals.
2. Those signals are persisted and available to higher-level synthesis without a DB schema migration.
3. `agent_conversation_memory` uses the stored signals ahead of brittle text heuristics when building thread-level state.
4. The production prompt is tightened and a real provider-backed smoke suite passes on representative verdict, constraint, and low-value-meta cases.
5. Existing routing, thread aggregation, privacy, and integration-readiness regressions stay green.

## Notes

The current implementation persists internal signal provenance under `SourceItem.metadata["pallium_semantic_signals"]`, keeps the normal API surface unchanged, and adds an opt-in live suite at `tests/test_semantic_llm_live.py` guarded by `PALLIUM_RUN_LIVE_LLM_TESTS=1`.
