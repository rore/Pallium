# How Pallium Works

Read the [README](../README.md) first for the short product description.

## Product shape

```text
Pallium
|-- Relay: send context to another session
+-- Session History: find context from an earlier session
    +-- derived memory (experimental)
```

Relay and Session History share one local service, session registration, scope,
storage, and integration hooks. They solve different problems and can be used
independently.

## Relay

Relay routes an explicitly addressed message to another existing session.
Pallium stores the message before attempting delivery. Wake and next-turn
delivery behavior depend on the recipient integration.

Relay does not use history search, embeddings, ranking, or an LLM. See
[Relay](agent-relay.md).

## Session History

Session History stores selected user and agent messages. Search returns concise
matches from earlier sessions; expansion opens a limited set of nearby messages
for context.

Visibility and redaction are checked before content is returned. Earlier
session content is historical evidence, not proof of current live state. See
[Session History](session-history.md).

## Shared foundation

The current integrations register each agent session with the local service.
Pallium uses trusted session and scope identity to:

- address Relay messages;
- scope history and memory to the configured container and visibility;
- record where historical messages came from;
- apply visibility rules before search or expansion.

Claude Code, Codex, OpenCode, and Hermes Desktop/TUI are the current integrations.
They remain independent tools and own their execution, user interaction, and
workflow.

The [Hermes integration](hermes-integration.md) bundles a native plugin, skill
and profile-scoped MCP bridge for Relay, private Session History and opt-in
memory tools. Its guide covers capture, wake and reconnection limits.

## Current default

Relay and Session History do not require an LLM or derived memory. Derived
memory is disabled by default. Enabling it requires a configured provider and
model.

See [Configuration](configuration.md) for the optional setup.

## Go deeper

- [Relay](agent-relay.md)
- [Session History](session-history.md)
- [Derived memory](derived-memory.md)
- [HTTP API](http-api.md)
- [Privacy and visibility](privacy-and-visibility.md)
- [Architecture](context/architecture.md)
