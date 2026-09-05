![Pallium Banner](assets/logo/pallium_header.png)

# Pallium

Pallium is a local service for Claude Code, Codex, and OpenCode. It lets
existing coding-agent sessions send messages to each other and search work from
earlier sessions.

Pallium is a personal open-source project under active development. It is useful
in its current form, but setup and behavior still have rough edges.

## What it does

### Relay

Relay sends a plain-text message to another existing agent session. Pallium
stores the message before delivery, addresses it to a runtime, exact session, or
alias, and keeps it pending if the recipient cannot receive it immediately.

> Use Pallium Relay to send Codex: "The legacy endpoint is still used by mobile.
> Do not remove it."

Relay can start a new turn in some supported existing sessions. It does not
create agents, assign tasks, or supervise work.

[Read the Relay guide](docs/agent-relay.md).

### Session History

Session History records selected user and agent turns, with scope, redaction, and forgetting controls. A later session can
search that history, inspect a concise match, and open a bounded part of the
surrounding conversation.

Historical content is evidence about earlier work, not proof of current live
state. A previous session saying that a pull request was approved does not mean
it is approved now.

[Read the Session History guide](docs/session-history.md).

## Current status

Relay supports durable messages, exact-session and alias addressing, replies,
status, and next-turn delivery for Claude Code, Codex, and OpenCode.

Wake support is narrower:

- Claude Code wake is qualified on Windows.
- Codex exact-session wake is proven on Windows, with more lifecycle and
  sustained-use checks still open.
- OpenCode currently uses next-turn delivery.
- Unqualified runtime and operating-system combinations use next-turn delivery.

Session History currently supports broad historical search, bounded source
expansion, access telemetry, forgetting, safeguards for outdated guidance, and
structural work references supplied by supported integrations. A separate exact
work-scoped search and operation without semantic packages are planned work.

See the current [roadmap](roadmap/board.md) and
[wake status](roadmap/features/add-wake-first-relay-delivery.md) for moving
details. There is no scheduled or delayed Relay feature.

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev,vector,mcp]"
cp pallium.example.toml pallium.local.toml
cp .env.example .env.local
pallium service install
pallium setup claude-code       # or: pallium setup codex
```

The OpenCode integration currently uses a local plugin. See its
[setup guide](integrations/opencode/README.md).

The current installation still includes semantic-package configuration and an
LLM provider. Making Relay and baseline Session History run without semantic
packages is queued work; the documentation does not assume it has shipped.

Continue with [Getting Started](docs/getting-started.md) to try Relay and Session
History in real coding-tool sessions.

## How the pieces fit

```text
Claude Code, Codex, OpenCode
             |
             v
          Pallium
          |     |
       Relay   Session History
                  |
                  +-- optional derived memory
```

Relay and Session History share the local service, session identity, storage,
scope, and integration hooks. They do not depend on each other for routing or
delivery.

## Optional derived memory

Pallium also contains an experimental derived-memory system. It can turn stored
conversation evidence into compact decisions, findings, facts, constraints, and
work checkpoints, then retrieve or inject them later.

This subsystem remains available, but it is not the definition of Pallium:

- [How Pallium Works](docs/how-it-works.md)
- [Configuration](docs/configuration.md)
- [Derived-memory integration](docs/agent-integration.md)
- [Derived-memory benchmarks](docs/benchmarks.md)

## Scope

Pallium works around coding agents that already exist. It is not an agent
runtime, task manager, workflow engine, or autonomous agent team.

Session History keeps bounded, governed agent and user turns for later search.
It is not intended to store every tool event, mirror external systems, or act as
a complete machine audit log.

Pallium is currently a local, single-user system. Its scope fields are not a
cross-user authorization model.

## Documentation

- [Documentation index](docs/README.md)
- [Getting Started](docs/getting-started.md)
- [Relay](docs/agent-relay.md)
- [Session History](docs/session-history.md)
- [Claude Code integration](docs/claude-code-integration.md)
- [Codex integration](docs/codex-integration.md)
- [OpenCode integration](integrations/opencode/README.md)
- [HTTP API](docs/http-api.md)
- [Privacy and visibility](docs/privacy-and-visibility.md)
- [Dashboard](docs/dashboard.md)
