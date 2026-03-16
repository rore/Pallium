---
id: add-direct-memory-conversation-debug-harness
title: Direct memory conversation debug harness
status: queued
priority: high
commitment: committed
milestone: Next
---

## Summary

Add a Pallium-native exploratory conversation harness so engineers can do the
same kind of iterative, chat-like memory testing they currently do through
Pelican, but directly against Pallium.

The goal is to make interactive memory debugging and exploratory validation a
first-class local workflow:

- simulate multi-turn conversations directly against Pallium
- control container, thread, session, and runtime context explicitly
- inspect routing, selected layer, suppression, and injectable blocks turn by
  turn
- debug memory behavior without Claude, tool runtime, or downstream hooks in
  the middle

## Why

Pytest and benchmark scenarios are necessary but not sufficient.

There is still a missing workflow between:

- formal regression tests
- full downstream end-to-end runs

Right now Pelican is partly filling that gap, but it is the wrong tool for
first-pass memory debugging because it adds too many unrelated variables.

Pallium needs its own direct exploratory surface for questions like:

- what happens if I ask this in a fresh thread?
- what changes after this artifact is ingested?
- why did routing pick `source_evidence` here?
- why did this constraint not carry forward strongly enough?
- what changed between the first query and later replay after contamination?

This feature creates that missing middle layer.

## In Scope

- add a local Pallium-native conversation harness for iterative memory testing
- support turn-by-turn ingest and query flow in one bounded tool surface
- let the harness set or vary at least:
  - `container_ref`
  - `thread_ref`
  - `session_ref`
  - `visibility_context`
  - `runtime_context.turn_kind`
  - `runtime_context.session_has_sufficient_local_context`
- show or export at least:
  - returned results
  - `should_inject`
  - `decision_reason`
  - `injectable_blocks`
  - selected routing layer
  - query family / intent
  - suppression or exclusion reasons
- support replaying a sequence of turns so engineers can inspect how memory
  changes after additional artifacts are ingested
- make the harness usable for anonymized scenario exploration and bug triage
  without requiring Pelican or another downstream agent
- keep the harness aligned with the real `/items`, `/query`, and `/query/debug`
  contract instead of inventing a parallel simulation API

## Out of Scope

- replacing the benchmark suite
- replacing the downstream integration checks
- building a production chat product on top of Pallium
- adding model-side answer synthesis or generic assistant behavior into the
  harness
- moving semantic policy into a new debugging-only codepath

## Done When

1. Engineers can run a local multi-turn exploratory session directly against
   Pallium without Pelican in the middle.
2. The harness makes thread/session/runtime-context transitions easy to vary and
   inspect.
3. Routing, suppression, and injection behavior are visible turn by turn without
   requiring raw DB inspection for every question.
4. A live miss can be reproduced quickly in the harness as an interactive debug
   session before or alongside formal regression promotion.
5. The harness uses the real Pallium ingest/query surfaces rather than a debug-
   only parallel contract.

## Notes

Recommended sequencing:

1. benchmark architecture formalization
2. Pallium-native scenario expansion
3. this direct exploratory harness
4. then the live miss-capture and replay-promotion loop

Implementation defaults:

- start with the smallest useful local workflow, likely CLI or lightweight local
  workbench, before investing in a richer UI
- keep the harness deterministic and inspection-heavy rather than answer-
  generation-heavy
- prefer direct reuse of existing query-debug trace and scenario helper logic
  wherever practical
