---
id: add-interest-memory-kind
title: Add interest memory kind
status: in-progress
priority: medium
commitment: committed
milestone: Next
---

## Summary

Add one new memory kind `interest` for `agent_conversation_memory` to capture specific subjects that a user explicitly marks as worth future attention, without requiring a concrete action commitment.

## Why

When a user says "Chroma sounds interesting, I should check it some time", the extraction pipeline produces only a `discussion_summary` with no special weight. In a later thread, asking "what was the db I wanted to check?" returns generic summaries but nothing pointed about the specific interest.

Concrete commitments ("I'll try it this weekend") already work via `task_checkpoint` through the `next_step_text` signal. But vague-but-specific interest falls through to `discussion_summary` where it disappears among other summaries.

The `interest` type fills the gap between `discussion_summary` (too generic) and `task_checkpoint` (requires concrete action).

## In Scope

- one new memory type `interest` — stronger than `discussion_summary`, weaker than `task_checkpoint`
- LLM extraction recognizes specific future-oriented interest as `candidate_type: "interest"` with `interest_text`
- no evidence grounding required — the LLM decides if content is interest
- minimal payload: `interest_text`, `summary`, scope metadata
- routing weights between `discussion_summary` and `task_checkpoint`
- unconditional injection eligibility (same as task_checkpoint, decision)
- envelope kind `"summary"`, confidence `"medium"`
- vector embedding support

## Out of Scope

- interest aging or expiry (can add later)
- interest strength levels or subtypes
- automatic upgrade to `task_checkpoint` when a commitment follows
- supersession logic between `interest` and later decisions (can remain as historical support)

## Done When

1. "Chroma sounds interesting, I should check it some time" produces a `type=interest` memory object with `interest_text` referencing Chroma.
2. Cross-thread queries like "what was the db I wanted to check?" surface the interest memory in injectable blocks.
3. `interest` ranks above `discussion_summary` but below `task_checkpoint` in routing.
4. Existing test suite passes with no regressions.
