# Documentation

Pallium connects existing agent sessions and keeps earlier session work
searchable. Current integrations are listed separately below. Start with the two
main capabilities, then use the integration and reference guides as needed.

## Start

| Document | What it covers |
|---|---|
| [Getting Started](getting-started.md) | Install the service, connect a coding tool, try Relay, and search Session History |

## Core capabilities

| Document | What it covers |
|---|---|
| [Relay](agent-relay.md) | Send messages between connected agent sessions |
| [Session History](session-history.md) | Search earlier sessions and open the surrounding conversation |

## Coding-tool integrations

| Document | What it covers |
|---|---|
| [Claude Code](claude-code-integration.md) | Hooks, MCP tools, Relay delivery, and history capture for Claude Code |
| [Codex](codex-integration.md) | Hooks, MCP tools, Relay delivery, and history capture for Codex |
| [OpenCode](../integrations/opencode/README.md) | Local OpenCode plugin setup and current limitations |

## Reference and optional features

| Document | What it covers |
|---|---|
| [How Pallium Works](how-it-works.md) | Product architecture and capability boundaries |
| [Derived Memory](derived-memory.md) | The optional derived-memory subsystem, retrieval, lifecycle, and limitations |
| [HTTP API](http-api.md) | Session History, Relay, derived-memory, and operational endpoints |
| [Configuration](configuration.md) | Local service, storage, providers, packages, and tuning |
| [Privacy and Visibility](privacy-and-visibility.md) | Scope rules across history, Relay, and derived memory |
| [Dashboard](dashboard.md) | Service health, Relay activity, search activity, and memory inspection |
| [Agent Integration](agent-integration.md) | Building a custom integration; mostly advanced derived-memory behavior |
| [Slack derived-memory example](integration-example.md) | A custom Slack integration using the derived-memory API |
| [Derived-memory benchmarks](benchmarks.md) | Evaluation of the optional derived-memory subsystem |

## Contributor context

| Document | What it covers |
|---|---|
| [Vision](context/vision.md) | Stable product identity and principles |
| [Architecture](context/architecture.md) | Current top-level system shape |
| [Decisions](context/decisions.md) | Accepted decisions and open architectural questions |
| [State](context/state.md) | Short implementation and handoff snapshot |
| [Lessons](context/lessons.md) | Durable implementation and evaluation rules |
| [Session History vNext strategy](context/strategy-vnext.md) | Direction and validation plan for historical work |
| [Designs](designs/) | Proposals, tradeoffs, and historical design records |

Current planning and feature status live in [`roadmap/`](../roadmap/).
