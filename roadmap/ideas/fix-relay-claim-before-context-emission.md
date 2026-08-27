---
id: fix-relay-claim-before-context-emission
title: Make Relay delivery failure-safe, visible when truncated, and retryable under SQLite contention
status: in-progress
priority: high
commitment: committed
milestone: pallium-relay
---

## Summary

Live Relay use exposed three connected delivery failures: a claimed message could be hidden while memory work or terminal encoding failed (RF-005), a truncated turn gave no backlog signal (RF-006), and SQLite lock contention became an opaque HTTP 500 (RF-007).

## In Scope

- Emit Relay independently of memory retrieval in Claude Code, Codex, and OpenCode; ACK only model-visible blocks.
- Return `has_more` and `remaining_count`, reserve the integration backlog notice, and leave omitted deliveries unacknowledged.
- Retry only immediate-transaction acquisition within hook deadlines; return sanitized retryable `503 relay_busy` on exhaustion without duplicating send/reply/delivery work.
- Cover Unicode output, lease recovery, bounds, contention, idempotency, and public HTTP/MCP/hook surfaces.

## Done When

1. A Relay delivery reaches model context even when memory retrieval fails or stalls.
2. Every truncated response signals the remaining eligible backlog and a later turn drains it.
3. A transient lock either clears before the bounded deadline or returns `503` with `relay_busy`, `retryable: true`, and `Retry-After: 1`.