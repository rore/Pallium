---
id: add-direct-memory-conversation-debug-harness
title: Direct thin-agent simulation harness
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Add a Pallium-native thin-agent simulation tool so engineers can run a real
chat-like memory loop against Pallium without the full downstream integration.

The goal is to make exploratory local validation a first-class workflow that
still exercises a realistic memory boundary:

- simulate a thin downstream agent loop directly against Pallium
- control container, thread, session, and runtime context explicitly
- inspect routing, selected layer, suppression, and injectable blocks turn
  by turn
- use one fixed generic agent prompt plus a real model call when configured
- fall back to manual assistant entry when the operator wants forced control
  or no model is available

## Why

Pytest and benchmark scenarios are necessary but not sufficient.

There is still a missing workflow between:

- formal regression tests
- full downstream end-to-end runs

Right now a downstream agent is partly filling that gap, but it is the wrong
tool for first-pass memory debugging because it adds too many unrelated
variables.

Pallium needs its own direct exploratory surface for questions like:

- what would a thin agent actually see and inject before answering here?
- what happens if I ask this in a fresh thread or resumed session?
- what changes after this answer or artifact is ingested?
- why did routing pick `source_evidence` here?
- why did this constraint not carry forward strongly enough?
- what changed between the first query and later replay after contamination?

This feature creates that missing middle layer.

## In Scope

- add a terminal-first local tool at `python -m app.agent_simulation`
- make `chat` the default mode and primary operator workflow
- add `manual` mode for direct `/items`, `/query`, and `/query/debug` work
- add `replay` mode for rerunning saved local sessions deterministically
- support one bounded turn loop in `chat` mode:
  - operator enters a user message
  - harness ingests that message through the real `/items` contract
  - harness calls `/query/debug` before the assistant turn
  - harness renders the carry-forward decision in a compact human-readable way
  - harness calls a real configured model using one fixed thin-agent prompt
  - harness shows the draft assistant answer
  - operator can accept, edit, or discard the draft
  - accepted assistant turns are ingested through the real `/items` contract
  - operator can optionally add one explicit artifact after the assistant turn
- let the harness set or vary at least:
  - `container_ref`
  - `thread_ref`
  - `session_ref`
  - `visibility_context`
  - `runtime_context.turn_kind`
  - `runtime_context.session_has_sufficient_local_context`
- show at least:
  - returned results
  - `should_inject`
  - `decision_reason`
  - `injectable_blocks`
  - selected routing layer
  - query family / intent
  - suppression or exclusion reasons
  - visibility or fail-closed reasons when present
- persist exploratory sessions locally in a simple editable file format
- support explicit save/load/export so engineers can:
  - continue an exploratory session later
  - replay a session after a code change
  - promote a useful local session into a replay-shaped asset later
- keep the harness aligned with the real `/items`, `/query`, and `/query/debug`
  contract instead of inventing a parallel simulation API
- keep the thin agent generic:
  - one fixed small prompt
  - no downstream-specific wording
  - no tool runtime
  - no hidden local heuristics for memory selection
- build the model call on the existing provider abstraction and config surface
  rather than adding a second model integration path

## Operator Workflow

Primary `chat` loop:

1. start or load a local session
2. set scope defaults or accept generated defaults
3. enter a user message
4. inspect Pallium's pre-answer query/debug decision
5. inspect the draft assistant answer from the thin generic model
6. accept, edit, or discard that answer
7. optionally add an explicit artifact:
   - `tool_use_summary`
   - `todo_snapshot`
8. continue in the same thread, fork a new thread, or switch runtime context

Required interactive commands in v1:

- `/scope` to set or show scope defaults
- `/turn` to set `runtime_context.turn_kind`
- `/local-context` to set
  `runtime_context.session_has_sufficient_local_context`
- `/artifact` to add an explicit artifact after a turn
- `/fork` to create a new thread while preserving container and visibility
- `/debug on|off` to control trace verbosity
- `/save` to persist the local session
- `/replay` to rerun a saved session
- `/mode` to switch between `chat` and `manual`
- `/show scope` to print the current request defaults

## Persistence And Export

- save sessions locally under `.local/harness-sessions/`
- use a plain JSON session format in v1
- record at least:
  - session metadata and scope defaults
  - every user, assistant, and explicit artifact turn
  - every `/query` or `/query/debug` request and response snapshot
  - whether the assistant turn came from a real model or manual fallback
  - whether the operator accepted, edited, or discarded the draft
- support explicit export to a replay-friendly bundle format
- do not write repo regression fixtures automatically in v1
- keep local exploratory assets generic and anonymizable by design

## Out of Scope

- replacing the benchmark suite
- replacing the downstream integration checks
- building a production chat product on top of Pallium
- adding tool execution, tool planning, or autonomous multi-step agent behavior
- adding prompt editing or multiple prompt profiles in v1
- auto-extracting structured artifacts from arbitrary assistant prose in v1
- moving semantic policy into a new debugging-only codepath

## Done When

1. Engineers can run `python -m app.agent_simulation` and use `chat` mode as a
   realistic thin-agent loop against a running local Pallium instance.
2. A user turn in `chat` mode automatically performs ingest, pre-answer
   `/query/debug`, draft assistant generation, and optional post-answer ingest
   without the operator assembling raw HTTP by hand.
3. Routing, suppression, visibility, and injection behavior are visible turn by
   turn without requiring raw DB inspection for every question.
4. The operator can force edge cases through `manual` mode and can rerun saved
   sessions through `replay` mode.
5. Sessions can be saved locally and exported cleanly for later replay or bug
   triage promotion.
6. The harness uses the real Pallium ingest/query surfaces and the existing
   provider/config path rather than a debug-only parallel contract.
7. The tool is covered by focused tests for command flow, session persistence,
   model fallback, and end-to-end loop alignment with Pallium's real API.

## Notes

Recommended sequencing:

1. benchmark architecture formalization
2. Pallium-native scenario expansion
3. this direct exploratory harness
4. then the live miss-capture and replay-promotion loop

Implementation defaults:

- start with the smallest useful terminal workflow before investing in any UI
- keep the tool inspection-heavy and thin-agent-oriented rather than
  feature-rich
- use one fixed generic thin-agent prompt in v1
- default the model call to the configured provider/model already used by the
  current package when available, with explicit CLI override if needed
- if no model is configured or the model call fails, fall back to manual
  assistant entry for that turn rather than silently fabricating an answer
- prefer direct reuse of existing provider config, query-debug trace, and sample
  workflow logic wherever practical

## Verification

Worker verification should include:

- focused CLI and session-state tests
- focused tests for model success and manual fallback behavior
- one end-to-end harness test against a test Pallium app or stubbed HTTP layer
  that proves `chat` mode stays aligned with the real `/items` and
  `/query/debug` contract
- documentation updates for local usage in `docs/getting-started.md`
