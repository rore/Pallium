![Pallium Banner](assets/logo/pallium_header.png)

# Pallium

Pallium is a local service that lets agent sessions across coding tools send
messages to each other and search earlier session history. It currently supports
Claude Code, Codex, and OpenCode.

It connects sessions you already run; it does not create or manage them.

## What it does

### Relay

Relay sends a plain-text message to another existing agent session. Pallium
stores each message before attempting delivery. Where the integration supports
it, Relay can start a recipient turn immediately; otherwise, the message remains
pending for the recipient's next turn. You can send to a specific session or a
named session.

> Use Pallium Relay to send Codex: "The legacy endpoint is still used by mobile.
> Do not remove it."

[Read the Relay guide](docs/agent-relay.md).

### Session History

Session History keeps selected user and agent messages from earlier sessions. A
later session can search them and open nearby messages when it needs more
context.

Scope, redaction, and forgetting rules control what is stored and returned.
Historical content is evidence about earlier work, not proof of current live
state.

[Read the Session History guide](docs/session-history.md).

## Use cases

- **Dependency or decision.** A worker sends a newly discovered constraint or a
  blocked question to the session that needs it. An architect session can use the
  same channel to send decisions or review requests; Pallium delivers the
  messages but does not coordinate the work.
- **Independent review.** A builder sends a commit or diff reference and a review
  request to a session using another supported coding tool; the reviewer returns
  concrete findings through Relay.
- **Returning to earlier work.** A later session searches Session History for a
  previous decision or investigation and opens the surrounding messages before
  continuing.

Pallium is a personal open-source project under active development. It is useful
in its current form, but setup and behavior still have rough edges.

## Current status

Relay works across the current integrations. Every supported path has durable
next-turn delivery; some qualified paths can also start a new turn. See the
[Relay support details](docs/agent-relay.md#delivery-and-wake-behavior).

Session History supports broad topic search, exact work-reference search, and
nearby-message lookup. A simpler setup that does not require configuring an LLM
provider is planned next. See the
[Session History status](docs/session-history.md#available-now) and current
[roadmap](roadmap/board.md).

## Getting started from source

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[vector,mcp]"
cp pallium.example.toml pallium.local.toml
cp .env.example .env.local
pallium service install
pallium setup claude-code       # or: pallium setup codex
```

The OpenCode integration currently uses a local plugin. See its
[setup guide](integrations/opencode/README.md).

Pallium can run Relay without an LLM provider. With the current default
configuration, history ingestion stays paused until provider credentials are
added. A provider-free Session History setup is planned work.

Continue with [Getting Started](docs/getting-started.md) to try Relay and Session
History in real agent sessions.

## How the pieces fit

```text
Pallium
|-- Relay: send context to another session
+-- Session History: find context from an earlier session
    +-- derived memory (experimental)
```

## Optional derived memory

Pallium also contains an experimental derived-memory system. It can turn stored
conversation evidence into compact decisions, findings, facts, constraints, and
work checkpoints, then retrieve or inject them later.

This subsystem remains available, but it is not the definition of Pallium:

- [Derived memory](docs/derived-memory.md)
- [Configuration](docs/configuration.md)
- [Derived-memory integration](docs/agent-integration.md)
- [Derived-memory benchmarks](docs/benchmarks.md)

## Scope

Pallium works around coding agents that already exist. It is not an agent
runtime, task manager, workflow engine, or autonomous agent team.

Session History keeps selected agent and user turns for later search. It is not
intended to store every tool event, mirror external systems, or act as a complete
machine audit log.

Pallium is currently a local, single-user system. Its scope fields are not a
cross-user authorization model.

## Documentation

- [Documentation index](docs/README.md)
- [Getting Started](docs/getting-started.md)
- [Relay](docs/agent-relay.md)
- [Session History](docs/session-history.md)
- [How Pallium Works](docs/how-it-works.md)
- [Derived memory](docs/derived-memory.md)
- [Claude Code integration](docs/claude-code-integration.md)
- [Codex integration](docs/codex-integration.md)
- [OpenCode integration](integrations/opencode/README.md)
- [HTTP API](docs/http-api.md)
- [Privacy and visibility](docs/privacy-and-visibility.md)
- [Dashboard](docs/dashboard.md)
