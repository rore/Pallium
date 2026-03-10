---
id: add-agent-conversation-memory-package
title: Add the first agent conversation memory package
status: done
priority: high
commitment: committed
milestone: Next
---

## Summary

Define and implement the first concrete semantic package for Pallium as agent conversation memory: a memory layer over agent-mediated user messages and agent outputs that improves continuity, consistency, and recurring-question handling for a downstream interactive agent.

## Why

The current lower-level contract is now expressive enough to model real agent events, but the project still needs a sharper value definition than generic "agent memory." A concrete agent conversation memory package creates a narrower, testable promise: Pallium should help an interactive agent remember prior agent-mediated conversations and its own prior outputs well enough to produce better future responses.

This is the first value slice that can be judged honestly without pretending Pallium already has broad team-knowledge coverage.

## In Scope

- define the package around agent-mediated conversation evidence, not around full workplace-chat coverage
- treat user-to-agent messages and final agent outputs as the primary evidence units
- keep `notification`, `tool_use_summary`, and `todo_snapshot` as optional later extensions, not MVP requirements
- shape retrieval toward recurring downstream questions such as:
  - what did we already conclude?
  - why did we choose this?
  - have we answered this before?
  - what context from prior agent conversations should we carry into this new thread?
- preserve evidence refs such as thread, session, actor, source, role, and artifact kind
- keep the package generic enough to avoid naming one internal agent as the project's public identity
- document the value hypothesis and the package boundary explicitly in repo-local roadmap state

## Out of Scope

- claiming memory over all team chat or all organizational knowledge
- ingesting arbitrary ambient messages that never entered an agent-mediated conversation
- turning Pallium into the downstream agent runtime
- deep connector-specific semantics baked into the core
- broad multi-artifact package scope in the first step

## Done When

1. The roadmap and repo context define a clear package boundary for agent conversation memory that is generic and publicly usable.
2. The first implementation path treats user messages and final agent outputs as the MVP evidence model.
3. Query shaping and result expectations are documented for recurring-question and cross-thread-continuity use cases.
4. The package's value claim is narrow and testable: improved downstream answers from prior agent-mediated conversations, not full-team knowledge coverage.

## Notes

Completed on 2026-03-10.
The runtime now exposes `agent_conversation_memory` as a first-class use-case entry point while reusing the current LLM-backed typed-memory path.


Current known shape:

- primary MVP item types:
  - `artifact_kind="message"` with `role="user"`
  - `artifact_kind="assistant_output"` with `role="assistant"`
- key refs already supported by Pallium:
  - `container_ref`
  - `thread_ref`
  - `session_ref`
  - `actor_ref`
  - `source_ref`
  - `artifact_kind`
  - `role`
- current expected producer behavior:
  - not all workspace chat
  - only conversations that actually flowed through the downstream agent
  - thread context is partly hydrated by the downstream agent already, so Pallium value should focus especially on cross-thread and later-session reuse

Sources: `roadmap/scope.md`, `docs/context/architecture.md`, `docs/context/state.md`, downstream-agent analysis (internal only)
