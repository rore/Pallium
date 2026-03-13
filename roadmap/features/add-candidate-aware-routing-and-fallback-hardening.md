---
id: add-candidate-aware-routing-and-fallback-hardening
title: Add candidate-aware routing and fallback hardening
status: queued
priority: high
commitment: committed
milestone: Next
---

## Summary

Harden `agent_conversation_memory` routing so it no longer depends mainly on text cue matching. Keep the current intent families, but make routing use both query wording and candidate evidence shape, then add explicit fallback behavior when confidence is weak.

## Why

The current routed retrieval layer is useful and inspectable, but the main brittle point is still text-only heuristic intent classification. Pallium can already retrieve plausible candidates, yet it may still choose the wrong memory layer on paraphrases, mixed-intent questions, or awkward resumed-work phrasing.

The next hardening step is not a new public API or an opaque classifier. It is a stronger package-owned policy that uses what retrieval already surfaced and degrades safely when confidence is weak.

## In Scope

- keep the current package-owned routing boundary in `agent_conversation_memory`
- preserve the current intent families unless the benchmark proves a new one is necessary
- incorporate candidate-aware signals into routing such as:
  - visible source evidence strength
  - lower-level memory presence
  - `task_checkpoint` presence
  - higher-level memory mix
  - overlap quality rather than cue text alone
- add explicit fallback behavior for weak or ambiguous routing cases
- prefer lower-level memory or source evidence when confidence is weak
- improve no-value and same-thread suppression where current context is already sufficient
- keep `/query/debug` explainable so routing reasons remain inspectable
- use the developer-work confidence harness and public-corpus packs as the acceptance bar

## Out of Scope

- replacing routing with an LLM call
- adding vector retrieval or fusion in the same slice
- moving routing policy into generic retrieval or storage
- expanding the public `/query` contract
- hiding routing behavior behind opaque scores with no traceability

## Done When

1. Routing uses both query cues and candidate evidence shape rather than text cues alone.
2. Weak-confidence cases bias toward safer layers instead of overcommitting to higher-level memory.
3. No-value and wrong-memory guard cases improve or stay flat on the confidence harness.
4. The benchmark stack shows fewer `routing_layer_choice_failure` cases without increasing no-value overreach or privacy regressions.
5. `/query/debug` still explains the routing path clearly enough to inspect why a layer won.

## Notes

This is the highest-value behavioral hardening slice after `task_checkpoint` and privacy enforcement. It should make Pallium less benchmark-wording-sensitive before any further retrieval sophistication is added.
