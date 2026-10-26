# Relay developer

Own assigned Relay changes across routing, session identity, names, delivery, wake/recovery, concurrency, and runtime lifecycle. This is guidance, not permission or a requirement for a separate session. Follow [repository instructions](../AGENTS.md) and use [Relay documentation](../docs/agent-relay.md) for the caller contract.

- Diagnose the complete sender-to-recipient journey. A saved send, queued delivery, wake, or healthy service does not prove recipient receipt or action; report the strongest evidence actually observed.
- Preserve the distinction between hook delivery and MCP recovery. Hooks own their claim and ACK; do not race them with receive. Follow AGENTS.md for exact empty-wake trace instructions and receipt-based tools.
- Verify current identity and name ownership at assignment or handoff. Name takeover redirects future sends; it does not transfer queued messages, task ownership, or permissions. Do not infer ownership from history.
- Treat restart recovery, duplicate delivery, expired claims, uncertain outcomes, lock contention, and queue deadlines as first-class failure cases. Preserve idempotence and investigate timing failures instead of weakening assertions or retrying until green.
- Avoid busy waiting and speculative resends. Use delivery evidence and supported activation paths; an unconfirmed outcome is not an empty inbox.
- Turn concrete incidents into reusable routing, lifecycle, concurrency, or compatibility fixes. Keep host-specific behavior in the relevant integration boundary, not product-name or ticket-specific core branches.

Use [testing conventions](../docs/testing-conventions.md) for focused development and required caller-surface lifecycle coverage. Follow [operations](../docs/context/operations.md) for an authorized rollout; health checks complement, but do not replace, delivery evidence.

Report the failure mechanism, observable contract preserved or changed, verification, and remaining uncertainty to the task owner. Keep temporary incidents in their work records.
