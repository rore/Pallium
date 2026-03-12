---
id: add-selected-agent-work-artifact-semantic-support
title: Add selected agent work-artifact semantic support
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Extend the current `agent_conversation_memory` evidence model beyond user messages and final assistant outputs so a bounded set of assistant-originated work artifacts can contribute to learned-state and work-continuity memory.

## Why

The current slice is strong for remembered answers and prior conclusions, but it loses too much of the useful state that appears during real work before a final answer exists.

For interruption and resumption, the valuable signals are often partial findings, blockers, failed attempts, and next-step state. Pallium should preserve those selectively, not by ingesting every raw runtime event, but by accepting a small bounded set of work artifacts that represent what the agent already learned.

## In Scope

- support a bounded set of assistant-originated work artifacts beyond final `assistant_output`
- keep the artifact model generic and open-source friendly rather than binding it to one downstream runtime
- allow selected artifacts to contribute to semantic promotion, thread aggregation, and later task-state memory
- preserve provenance and evidence links so artifact-derived memory stays inspectable
- update evaluation coverage so work-artifact-backed continuity can be measured explicitly
- prefer compact checkpoint-like artifacts over raw tool logs, raw notifications, or exhaustive runtime state

## Out of Scope

- ingesting every tool call, MCP event, or runtime notification
- turning Pallium into a task runner or workflow engine
- replacing transcript persistence or live tool retrieval
- a broad artifact ontology covering every possible downstream runtime event
- public API expansion beyond what the current event contract actually needs

## Done When

1. `agent_conversation_memory` can meaningfully use at least one bounded selected work-artifact shape beyond final assistant outputs.
2. Those artifacts can contribute to semantic promotion and retrieval without weakening evidence traceability.
3. Work-resumption evaluation cases improve because partial findings, blockers, or next-step state are no longer lost.
4. The solution stays bounded and avoids raw runtime-log ingestion.

## Notes

This slice is about preserving selected learned state from work, not about mirroring a downstream agent runtime inside Pallium.

Implemented as bounded support for selected assistant-originated `tool_use_summary` and `todo_snapshot` artifacts so explicit progress, blocker, and next-step state can participate in thread aggregation, semantic promotion, and work-resumption retrieval without ingesting raw runtime logs. A later `task_checkpoint` slice still owns compact task-state packaging beyond those source artifacts.
