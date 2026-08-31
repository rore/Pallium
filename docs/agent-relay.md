# Agent Relay

Agent Relay is Pallium's explicit communication track, parallel to semantic memory. It persists a bounded message from one supported agent session and injects it at the recipient's next model-bound turn. Routing is deterministic; it never uses search, embeddings, ranking, or an LLM.

R1 supports Claude Code, Codex, and OpenCode in one local Pallium container.

## How to use it

Tell an agent plainly what to send and where:

> Use Pallium Relay to send Codex: "The legacy endpoint is still used by mobile. Do not remove it." List recipients first if the target is ambiguous.

The agent uses five MCP tools:

- `pallium_relay_recipients` lists recent sessions and optional aliases.
- `pallium_relay_name` sets or transfers an alias.
- `pallium_relay_send` sends a new message to a runtime, exact session, or alias.
- `pallium_relay_reply` replies to one received delivery without supplying either endpoint; if the MCP configuration has no Relay scope, also copy the exact injected `container_ref` and `actor_ref`.
- `pallium_relay_status` reports per-recipient delivery state.

Selectors are `codex` for every currently recent Codex session, `codex:<session_ref>` for one immutable session, or `codex:@review` for a Pallium alias. Runtime-wide sends require explicit user intent and snapshot at send time; sessions opened later do not receive them.

The current identity comes from injected Pallium scope: copy `agent_ref` to the current/sender runtime field and `thread_ref` to the current/sender session field. Recipient discovery is only for finding targets, never for inferring the current session. Bundled integrations register it automatically at normal turns.

## Session names and lifecycle

Harness titles are discovery metadata, not routing identities. An alias such as `review` is unique within a container and runtime. If a new session replaces the old review session, transfer it deliberately with `replace_existing=true`. Already queued deliveries remain pinned to the old immutable session; future sends resolve to the new one.

Claude Code and Codex follow a deliberate change into a recognized Git repository at the next model-bound turn. The hook best-effort closes the old project registration and releases its project-local alias before registering the session in the new project; transient non-Git cwd excursions keep the existing project pin. OpenCode plugin instances remain bound to their injected project directory/worktree and pin both container and actor identity across resumed turns; deleting the session releases that pin.

Recent sessions are shown by default. A session becomes dormant after 24 hours without a turn but remains exactly addressable. A close event marks it closed and releases its alias. A later turn reactivates the same session ID. R1 retains session records; automatic purge waits for evidence that accumulation causes real operational pain.

## Delivery contract

Messages contain at most 1,500 Unicode code points and expire after 24 hours by default (allowed range: 60 seconds to 7 days). A turn claims at most three complete messages within a 2,400-character Relay budget. If renderable eligible messages remain, its response sets `has_more: true` and a non-negative `remaining_count`; integrations reserve room for a compact backlog notice and acknowledge only blocks actually added to model context. Relay emission is independent of memory retrieval. OpenCode claims on `chat.message`, injects the lower-authority envelope through its model-bound message transform, and acknowledges only after that mutation; this avoids its resumed-session system-transform loss mode. Interrupted claims become eligible again after a lease; stable IDs make acknowledgement idempotent. Transient SQLite write contention retries during bounded transaction acquisition; exhaustion is the retryable HTTP 503 code `relay_busy` with `Retry-After: 1`, never a database error.

A received block includes its `delivery_id`. `pallium_relay_reply` accepts that ID and reply text; if the MCP configuration does not carry both Relay scope values, copy the exact injected `container_ref` and `actor_ref` to reply (and to recovery-path receive/ACK). They are paired scope selectors, not runtime/session identity, cannot override configured scope, and do not replace receipt validation. Pallium derives the current sender, the original message sender as recipient, and the `in_reply_to` parent from the delivered record. Repeating the same reply is idempotent; changing its text conflicts. Replies do not create a live or autonomous conversation. Delivery means the runtime received the context, not that the model read or acted on it.

Relay is local single-user coordination. `actor_ref` is claimed scope, not authenticated cross-user authorization. The generic secret redactor runs before persistence.

## Not in R1

R1 does not infer a shared `work_ref`, route to a future worker, spawn agents, assign work, wake sessions, create groups, or maintain continuous conversations. Those remain evidence-driven R2/R3 questions.
