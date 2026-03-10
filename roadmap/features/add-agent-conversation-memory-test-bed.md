---
id: add-agent-conversation-memory-test-bed
title: Add a realistic agent conversation memory test bed
status: queued
priority: high
commitment: committed
milestone: Next
---

## Summary

Add a realistic test bed that simulates how an interactive downstream agent would actually use Pallium from agent-mediated conversation events and assistant artifacts, so the project can prove concrete value before broader memory expansion.

## Why

Synthetic message samples were useful for the walking skeleton, but they are no longer enough to prove value. Pallium now needs a believable downstream-agent test bed that reflects the actual data shape and usage loop we currently understand: user asks, thread-local context, final assistant output, later recurring question, and evidence-backed recall.

This test bed should make it possible to show when Pallium helps, when it does not help, and why.

## In Scope

- define fixtures that represent the concrete data items currently expected from an interactive downstream agent:
  - inbound user message event
  - hydrated thread reply items
  - final assistant output artifact
  - later recurring-question query case
- model realistic refs and ids such as channel/container, thread, session, actor, message timestamps, and source links
- include at least one positive-value scenario where prior agent-mediated conversation memory helps across threads or later sessions
- include at least one low-value or no-value scenario where same-thread context is already available and Pallium should add little
- keep the test bed generic and avoid naming one internal downstream agent in the committed files
- make the test bed useful for both:
  - manual demo runs
  - repeatable automated evaluation

## Out of Scope

- replaying a full external Slack or chat workspace
- full production telemetry capture
- exact cloning of every downstream-agent runtime behavior
- broad benchmark infrastructure for every future semantic package
- forcing higher-level consolidation into the first realistic test bed

## Done When

1. The repo contains a committed test bed with realistic agent-mediated event fixtures and expected-value scenarios.
2. At least one scenario shows clear value from recalling prior agent conversations across threads or sessions.
3. At least one scenario shows a non-value case so the project does not over-claim benefit where thread-local context is already sufficient.
4. The test bed can be used to judge whether a downstream answer is better with Pallium memory than with only lower-level retrieval and current-thread context.
5. The realistic test bed is explicitly usable as input to the recurring-question value benchmark.

## Notes

Current known downstream-agent shape:

- primary inbound item:
  - a user message routed to the agent, with channel/container, actor, thread, session, and timestamp refs
- primary assistant item:
  - the final assistant output artifact, with session and thread correlation
- realistic constraint:
  - the agent already hydrates some current-thread context, so Pallium should not be judged mainly on re-supplying the same thread
- realistic value targets:
  - cross-thread continuity
  - recurring-question recall
  - assistant consistency
  - evidence-backed carry-forward of prior decisions and summaries

Suggested first scenario set:

1. Prior decision in one thread, related question in a later thread in the same container.
2. Same-thread continuation where Pallium should add little or nothing.
3. Prior assistant answer reused to answer a repeated question with less noise.

Sources: `roadmap/scope.md`, `roadmap/features/add-recurring-question-value-benchmark.md`, `docs/context/architecture.md`, downstream-agent analysis (internal only)
