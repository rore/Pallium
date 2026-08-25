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
- `pallium_relay_reply` replies to one received delivery without supplying either endpoint.
- `pallium_relay_status` reports per-recipient delivery state.

Selectors are `codex` for every currently recent Codex session, `codex:<session_ref>` for one immutable session, or `codex:@review` for a Pallium alias. Runtime-wide sends require explicit user intent and snapshot at send time; sessions opened later do not receive them.

The current identity comes from injected Pallium scope: copy `agent_ref` to the current/sender runtime field and `thread_ref` to the current/sender session field. Recipient discovery is only for finding targets, never for inferring the current session. Bundled integrations register it automatically at normal turns.

## Session names and lifecycle

Harness titles are discovery metadata, not routing identities. An alias such as `review` is unique within a container and runtime. If a new session replaces the old review session, transfer it deliberately with `replace_existing=true`. Already queued deliveries remain pinned to the old immutable session; future sends resolve to the new one.

Claude Code and Codex follow a deliberate change into a recognized Git repository at the next model-bound turn. The hook best-effort closes the old project registration and releases its project-local alias before registering the session in the new project; transient non-Git cwd excursions keep the existing project pin. OpenCode plugin instances remain bound to their injected project directory/worktree.

Recent sessions are shown by default. A session becomes dormant after 24 hours without a turn but remains exactly addressable. A close event marks it closed and releases its alias. A later turn reactivates the same session ID. R1 retains session records; automatic purge waits for evidence that accumulation causes real operational pain.

## Delivery contract

Messages contain at most 1,500 Unicode code points and expire after 24 hours by default (allowed range: 60 seconds to 7 days). A turn claims at most three complete messages within a 2,400-character Relay budget. The integration acknowledges only after adding the attributed block to model context. Interrupted claims become eligible again after a lease; stable IDs make acknowledgement idempotent.

A received block includes its `delivery_id`. `pallium_relay_reply` accepts that ID and reply text; Pallium derives the current sender, the original message sender as recipient, and the `in_reply_to` parent from the delivered record. Repeating the same reply is idempotent; changing its text conflicts. Replies do not create a live or autonomous conversation. Delivery means the runtime received the context, not that the model read or acted on it.

Relay is local single-user coordination. `actor_ref` is claimed scope, not authenticated cross-user authorization. The generic secret redactor runs before persistence.

## Not in R1

R1 does not infer a shared `work_ref`, route to a future worker, spawn agents, assign work, wake sessions, create groups, or maintain continuous conversations. Those remain evidence-driven R2/R3 questions.
