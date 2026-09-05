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
Pallium stores the message before attempting delivery. If a safe wake path is
not available, the message remains pending for the recipient's next normal
turn.

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
Pallium uses the session and repository identity to:

- address Relay messages;
- keep unrelated repositories separate;
- record where historical messages came from;
- apply visibility rules before search or expansion.

Claude Code, Codex, and OpenCode are the current integrations. They remain
independent tools and own their execution, user interaction, and workflow.

## Current installation boundary

Relay does not require an LLM or derived memory. The standard Session History
installation still requires a configured semantic package, model, and provider.
Package-independent baseline Session History is planned.

See [Configuration](configuration.md) for the current setup.

## Go deeper

- [Relay](agent-relay.md)
- [Session History](session-history.md)
- [Derived memory](derived-memory.md)
- [HTTP API](http-api.md)
- [Privacy and visibility](privacy-and-visibility.md)
- [Architecture](context/architecture.md)
