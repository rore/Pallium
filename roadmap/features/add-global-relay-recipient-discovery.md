---
id: add-global-relay-recipient-discovery
title: Discover Relay recipients across unknown containers through MCP
status: done
priority: high
commitment: committed
milestone: pallium-relay
lane: product-surface
---

## Outcome

Agents can inspect read-only Relay recipient candidates across the trusted
local service without knowing the target container. The new
`pallium_relay_discover_recipients` MCP tool lists recent candidates or filters
by exact runtime and session reference across all containers. It returns
bounded pages, explicit no-match/ambiguous/single-candidate status, canonical
selectors, and recorded lifecycle/health. It never chooses a recipient or
sends a message.

## Boundaries

`pallium_relay_recipients` remains scoped to the sender's container. Global
Relay discovery neither grants Session History/memory access nor proves task
ownership, live reachability, or receipt. Titles are untrusted hints.
Integrations require independent identity verification before a send; ambiguous
or uncertain candidates lead to asking the user/target for its address or
using a task-message fallback. The existing Dashboard listing is reused with
an exact filter and compact projection; a runtime/session-reference index
keeps global exact lookup indexed.

## Validation

HTTP and MCP caller tests cover cross-container duplicate native references,
runtime filtering, lifecycle states, bounded continuation, Unicode, malformed
inputs, local-only access, secret-free output, and no send side effects.
