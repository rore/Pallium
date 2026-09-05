# Vision

## What Pallium is

Pallium is a local service for agent work that crosses coding-tool and session
boundaries.

It has two primary capabilities:

- **Relay** moves a bounded message to another existing coding-agent session.
- **Session History** records governed agent and user turns and makes earlier
  work searchable.

Claude Code, Codex, and OpenCode remain normal, independently operated tools.
Pallium connects their sessions and keeps earlier work available; it does not own
their execution or workflow.

Pallium also contains derived-memory packages. They can turn session evidence
into compact decisions, findings, facts, constraints, and checkpoints. These
packages are optional product direction and must earn their complexity through
measured quality or cost improvements over raw Session History.

## Why it exists

Coding work often spans sessions and tools. Useful context is lost when a chat
ends, and parallel sessions still depend on a person copying findings between
them.

Pallium addresses those two concrete gaps:

1. send relevant context to another session now;
2. find relevant work from an earlier session later.

The project should be judged by whether these actions help real downstream work,
not by how much data it stores or how many memory objects it creates.

## What Pallium is not

Pallium is not:

- an agent runtime or agent creator
- a task assignment or supervision system
- a workflow engine
- an autonomous agent team
- an exhaustive transcript archive or raw tool-log store
- a replacement for live source systems such as GitHub, issue trackers, logs, or
  documentation
- a cross-user sharing system without an explicit authorization contract

Relay may start a new turn in an existing supported session. That is different
from creating or managing an agent.

Session History stores bounded, governed turns needed for later search. That is
different from storing every event forever.

## Stable principles

1. **Local first.** Run as one local service before adding deployment complexity.
2. **Existing agents keep control.** Pallium supplies context; the coding tool
   owns execution, tools, and user interaction.
3. **Explicit identity and scope.** Address Relay recipients directly and enforce
   history visibility before retrieval or expansion.
4. **Persist before processing.** Store source evidence or Relay messages before
   optional processing or delivery.
5. **Historical evidence stays historical.** Earlier session content cannot prove
   current live state.
6. **Provenance remains inspectable.** Derived outputs and historical matches link
   back to source evidence.
7. **Retrieval alone is not use.** Accessibility and reuse state change only after
   verified downstream use.
8. **Derived memory is optional.** Keep it only where experiments show an
   advantage over raw history.
9. **Generic capabilities, concrete language.** Generalize real failures in the
   implementation, but explain the public product through Relay, Session History,
   and the coding tools people use.
10. **Build the smallest useful slice.** Add mechanisms only when current evidence
    justifies them.

## Current validation questions

- Does searching earlier sessions improve work enough to justify its token,
  latency, and contamination cost?
- Does Relay reduce manual copying between sessions without turning into noisy
  coordination?
- Does derived memory improve precision, completeness, cost, or downstream
  results compared with raw history?

The roadmap and experiments answer these questions. This file defines the stable
product boundary, not the current queue.
