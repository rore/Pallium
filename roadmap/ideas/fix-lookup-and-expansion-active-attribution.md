---
id: fix-lookup-and-expansion-active-attribution
title: Local agent history tools must pass active task identity
status: done
priority: high
commitment: committed
---

## Summary

The server-side attribution contract is already shipped: when historical search and expansion receive an active `thread_ref`, persisted events keep that requester session separate from historical source provenance. The remaining real-install gap is at the Codex and Claude edge: hooks capture turns with the host session ID but do not expose that ID to the agent, so deliberate MCP history calls usually omit it and downstream reuse cannot be joined to the task that followed.

## In Scope

- Inject one compact, bounded `container_ref` + active `thread_ref` scope marker from the existing host hooks, including when automatic retrieval abstains.
- Tell both installed integrations to pass that active thread to search and expansion as telemetry.
- Keep missing host identity absent; never fabricate `"unknown"` or guess a latest task.
- Prove source session A can be searched and expanded from active session B, with persisted events attributed to B and source provenance retained as A.

## Out of Scope

- Authorization, authentication, actor-based denial, or treating telemetry identity as a security boundary.
- Server-global current-session state, latest-session registries, schema changes, retrieval/ranking changes, or historical-anchor fallback.
- Reopening the already-shipped event schema and parent-link contract.

## Done When

1. Codex and Claude caller-surface tests show their exact host session in a bounded scope marker even when no memory block is returned; Unicode is preserved, control characters cannot inject lines, over-budget identity is omitted rather than truncated, and two tasks remain distinct.
2. Missing session identity stays NULL/unattributed in captured turns and emits no fabricated scope.
3. MCP search + expansion E2E reads persisted events showing active session B, source session A, and correct parent linkage; cross-session access remains allowed because this field is telemetry, not authorization.
4. Local integrations are refreshed, the VBS-launched service is restarted and healthy (including `embedding_provider_ok`), and a fresh live lookup matches a captured task thread.

## Evidence

Pre-fix local aggregate: 37 historical lookup events, only 2 with any session identity, and 0 whose active session matched a captured source thread. The explicit-thread funnel E2E passed, isolating the defect to integration context rather than persistence.
