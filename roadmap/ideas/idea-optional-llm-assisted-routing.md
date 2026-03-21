---
id: idea-optional-llm-assisted-routing
title: Optional LLM-assisted routing
status: done
priority: medium
commitment: uncommitted
milestone: Idea
resolved_by: add-bounded-query-intent-resolution (query_ambiguity_resolution)
---

## Summary

Explore an optional LLM-assisted routing layer for `agent_conversation_memory`
that can improve intent and layer selection on messy real interactions without
replacing the current deterministic routed retrieval path.

## Why

The current routed policy is explicit, cheap, and inspectable, but it remains
the most brittle part of the stack because it depends heavily on deterministic
query cues.

An optional LLM-assisted layer may improve:

- paraphrase handling
- mixed-intent questions
- awkward resumed-work phrasing
- candidate-aware layer selection

But it should only be adopted if it improves the benchmark stack without
weakening explainability, privacy, or no-value guard behavior.

## In Scope

- optional LLM-assisted intent or layer suggestions inside the package-owned
  routing path
- evaluation of deterministic routing versus deterministic plus LLM-assisted
  routing on the same benchmark stack
- preserving `/query/debug` explainability for the assisted path
- keeping the current deterministic routing path as the baseline and fallback

## Out of Scope

- replacing routing with an LLM-only black box
- making every query depend on an LLM before the benchmark proves the value
- moving routing policy into generic retrieval or storage
- weakening privacy enforcement or fail-closed behavior

## Done When

1. The idea is concrete enough to become a committed feature if the benchmark
   stack shows clear gains.
2. The evaluation plan is explicit: fewer routing failures without increasing
   no-value overreach, wrong-memory failures, stale-memory failures, or privacy
   regressions.
3. The design preserves a deterministic baseline and an inspectable debug path.

## Notes

Recommended shape if this is explored later:

- lexical retrieval still builds the candidate set
- deterministic routing still produces a baseline layer choice
- optional LLM assistance sees the query plus a compact candidate summary
- package policy decides whether to trust, combine, or ignore the LLM hint

This should remain an idea until the current routing-hardening and
open-corpus-expansion queue makes the deterministic baseline as strong as it
can reasonably be.
