# Custom Agent Integration

Use the [Claude Code](claude-code-integration.md),
[Codex](codex-integration.md), or
[OpenCode](../integrations/opencode/README.md) guide for a supported coding tool.
This document is for building another runtime integration.

A complete integration can expose three separate responsibilities:

1. **Relay:** register exact sessions, deliver attributed messages, and expose
   send, reply, recipient, alias, and status operations.
2. **Session History:** record governed user and agent turns, search earlier
   sessions, and expand a bounded part of the surrounding conversation.
3. **Optional derived memory:** process stored evidence into compact memory and
   decide when that memory should be returned or injected.

The runtime owns the live conversation, tools, and user interaction. Pallium
owns persisted Relay messages, governed history, scope enforcement, and any
configured derived-memory behavior.

The rest of this guide concentrates on the older custom derived-memory API.
Relay and Session History are the normal front door for coding-tool users.

## One derived-memory flow

A realistic current-package loop looks like this:

1. a user asks why a background job keeps missing status updates
2. the runtime calls `POST /item-and-query` — this stores the user message
   as evidence and retrieves prior memory in one call
3. Pallium returns `should_inject=true` with a compact prior decision card
4. the runtime injects that card into the LLM prompt and drafts an answer
5. the runtime stores the assistant reply via `POST /items`
6. later the user asks the same question again, or the work is resumed after an
   interruption — step 2 fires again and Pallium returns the right memory

That is one advanced derived-memory flow. It is not required for Relay or deliberate Session History search.

## When To Ingest

There are two ingest patterns:

- **User messages** — use `POST /item-and-query` to store and query in one
  call. This is the only point where you need memory back.
- **Assistant replies and artifacts** — use `POST /items` to store evidence
  for future recall. No query needed.

Good ingest moments for assistant artifacts:

- an assistant answer contains a conclusion you want to carry forward
- a tool run produced a compact explicit finding worth preserving
- the runtime has an explicit progress update, blocker state, or next-step note

Avoid ingesting:

- every token or partial assistant draft
- raw tool logs
- raw MCP traffic
- ambient messages that never flowed through the agent

The current package is designed for bounded, intentional ingest. The runtime
should perform only mechanical validation here, such as empty-payload rejection
or obvious duplicate suppression. Semantic filtering belongs in Pallium.

## What To Ingest Today

The runtime sends events. Pallium decides what is worth remembering.

If your runtime can provide `artifact_kind` and `role` cheaply (e.g. the
runtime already knows it is forwarding a user message vs. an assistant reply),
include them — they help Pallium route faster. But these are hints, not
classification requirements. The semantic layer extracts meaning from content.

Common shapes that work well today:

- user question or requirement
  - `artifact_kind="message"`, `role="user"`
- final assistant answer or decision
  - `artifact_kind="assistant_output"`, `role="assistant"`
- explicit tool-derived finding or blocker summary
  - `artifact_kind="tool_use_summary"`, `role="assistant"`
- explicit next-step snapshot
  - `artifact_kind="todo_snapshot"`, `role="assistant"`
- user explicitly asks to remember something
  - `artifact_kind="note"`, `role="user"` — bypasses standard extraction,
    preserves content verbatim, extracts only a title for retrieval

The content should be the compact text you want Pallium to reason over. The
current semantic layer is text-oriented; keep the text explicit and bounded.

## Item Request Contract

See [http-api.md — POST /items](http-api.md#post-items) for exact fields and
examples.

Practical guidance:

- make `source_id` stable and unique per upstream event
- use `content_type="text/plain"` unless you are deliberately handling another
  text-compatible format
- keep `source_ref` if you want to point users or tooling back to the origin
- always send `container_ref` for `agent_conversation_memory`

Repeated ingest for the same item should be idempotent when the source identity
is stable.

## Query Patterns

Most integrations should use `POST /item-and-query` for user messages — it
stores the message and queries in one call.

Use standalone `POST /query` when you need to query without ingesting, for
example re-querying during debugging or querying from a different context.

The kinds of questions where Pallium adds value:
- repeated questions
- "why did we choose this?"
- "what did the investigation find?"
- resumed work after an interruption
- cross-thread continuity in the same bounded context

Useful query filters:

- `container_ref`
- `thread_ref`
- `actor_ref` — pass the current user's identity to scope results to their
  personal memories plus shared evidence. When omitted, no actor filtering is
  applied.
- `artifact_kind`
- `work_refs` — external work identifiers (e.g. ticket IDs, PR numbers) for
  cross-thread work continuity
- `role`
- `source_type`

Use `POST /query/debug` when:

- a result seems missing
- a higher-level memory kind is beating lower-level evidence unexpectedly
- you need to inspect visibility exclusions
- you need to see lexical matched tokens and text views

For local exploratory work, the supported way to exercise this integration
boundary is `python -m app.agent_simulation`. Use `chat-lite` when you want a
normal chat loop, or plain `chat` when you want operator-visible accept/edit/discard
and artifact capture. The harness stays on the real HTTP contract, keeps same-thread
local chat context in the app layer, keeps Pallium-approved carry-forward in a separate
prompt section, and shows Pallium's decision path without adding a second memory policy
in the client. When `prompt_toolkit` is available, the harness also adds slash-command
completion and colorized prompts plus role-prefixed output for agent/system/debug lines.

## Query Input Contract

See [http-api.md — POST /query](http-api.md#post-query) for exact fields and
examples.

The runtime should send:

- current user text
- refs and visibility:
  - `container_ref`
  - `visibility`
  - `thread_ref`
  - `work_refs` (optional)

Pallium infers session lifecycle state (new thread, continuation, resumed
session) from its own data. Agents do not need to classify turns.

### Runtime Hints for Work References

Structural integration helpers add raw, ordered work references to this list: `git-branch:<branch>` for the current non-base Git branch, `agent-workflow:<slug>` when the exact `.agent-workflow/tasks/<slug>.md` Work Record resolves safely and contains a complete workflow marker block, then any explicitly supplied list-valued refs. The resolver launches no process and reads only bounded local `.git/HEAD` and exact Work Record metadata. Relative, device, Windows UNC/mapped-network, symlink/junction, detached, base-branch, bare-repository, active Git-path-indirection, missing, malformed, oversized, or changing metadata contributes nothing; explicit refs and normal ingestion continue. On Windows, OpenCode deliberately skips structural filesystem discovery and preserves only explicit refs because Node's standard library cannot reliably identify every Windows reparse type without risking a synchronous cloud-placeholder stall. Python-based Claude Code and Codex reject Windows reparse attributes directly. Integrations do not redact or normalize candidates.

The integrating agent can provide `pallium_work_refs` in item `metadata` to
supplement LLM extraction. When present, these refs are merged with any
work references the semantic layer extracts from content. This is useful
when the runtime already knows the active ticket or PR but the conversation
text does not mention it explicitly.

## Query Result Contract

See [http-api.md — POST /query](http-api.md#post-query) for the full response
shape and field reference.

The key fields for integration:

- `should_inject` — whether to inject memory into the agent's prompt
- `decision_reason` — why (e.g. `"carry_forward_available"`,
  `"no_relevant_memory"`)
- `injectable_blocks` — ready-to-use blocks with title, text, evidence, and
  optional `memory_object_id` for drill-down via `GET /memory/{id}/expand`

The downstream agent should not need to decide:

- whether `task_checkpoint` beats `thread_summary`
- whether a greeting summary should be suppressed
- how many weak candidates to drop locally

For the harness specifically, same-thread local transcript continuity is handled in the
app layer as ordinary chat behavior, while cross-thread carry-forward remains a Pallium
decision. That keeps the integration boundary honest: runtime-owned local chat context on one
side, Pallium-owned memory judgment on the other.

## Suggested Runtime Loop

One practical runtime pattern:

1. on each user message, call `POST /item-and-query` to store the message and
   get relevant memory in one round-trip
2. inject Pallium's returned carry-forward block(s) directly when
   `should_inject=true`
3. ingest final assistant answer with `POST /items` when it contains a
   reusable conclusion
4. ingest a compact tool-use summary only when it adds explicit finding,
   blocker, or next-step value
5. if a result looks wrong, inspect `POST /item-and-query/debug` or
   `POST /query/debug` before changing prompts or retrieval code

The direct harness follows this same loop. In `chat-lite` mode it ingests the
user turn through `/items`, calls `/query/debug` before the assistant turn, and
auto-accepts the assistant reply after the model draft. In `chat` mode it keeps
the same HTTP flow but adds operator prompts for accept/edit/discard and optional
artifact capture. In both modes, only `injectable_blocks` are passed to the model
when Pallium says to inject. Ranked results and debug trace stay operator-visible,
not prompt-visible.

## How To Think About The Current Memory Jobs

The current packages are optimizing for two complementary recall jobs:

**Work continuity** (`agent_conversation_memory`):

- remembering prior conclusions
- remembering investigation findings
- remembering thread orientation
- remembering where interrupted work left off
- carrying forward bounded cross-thread context when useful

**Factual recall** (`conversational_knowledge`):

- remembering concrete facts mentioned in conversations: names, dates,
  preferences, events, relationships
- answering "who/what/when" questions about things discussed earlier
- preserving facts in the original language for multilingual recall

The implementation uses multiple memory kinds internally to serve those jobs,
but the integration loop does not require you to think in those terms first.

## Injection Policy (Opt-In)

Proactive injection precision on real agent traffic is the dominant open
quality knob (see the
[Current status](../README.md#current-status) section and
[docs/specs/2026-06-27-injection-policy-abstention.md](specs/2026-06-27-injection-policy-abstention.md)).
An optional `[injection.policy]` TOML block lets operators demote
specific memory types from proactive injection. Available modes per
type: `proactive` (gate on result `score` ≥ `min_score`), `event`
(only on configured event triggers), `on_demand` (only via explicit
`pallium_query`), `suspended` (do not inject under any path). The
commented template in `pallium.example.toml` demotes `task_checkpoint`
to event, `investigation_outcome` and `thread_summary` to on-demand,
and `fact_summary` to suspended. Types without a policy entry remain
proactive without a score gate (the default).

When a type is demoted, the gate runs in
`semantic/agent_conversation_memory_routing_selection.py` and drops the
candidate from `injectable_blocks` unless the request carries a
`trigger_origin` in the bypass set (session-resumption checkpoints,
post-tool failures, retry-threshold events, explicit user queries). The
integrating runtime supplies `trigger_origin` on the query payload —
Claude Code and Codex hooks already plumb the values shipped with the
spec. The agent path is unchanged when the policy is absent (the
default), and the contract on the agent side is identical:
`should_inject` plus `injectable_blocks`.

## Container Visibility and Actor Scoping

Set `visibility` based on the communication context:

- **DM / 1:1 conversation** — `"private"`. All memory types are created.
  Memories carry `actor_ref` from the source item.
- **Team channel / group chat** — `"container"`. Personal memory types (`constraint_memory`) are suppressed (no memory created for those signals).
  All memories have `actor_ref = null`.
- **Public channel / broadcast** — `"public"`. Same suppression rules as
  `"container"`.
- **Cross-container personal memory** — `"global"`. Use for preferences or
  constraints that should follow the user across all containers. Requires
  `actor_ref` on both ingest and query. The memory is invisible without a
  matching actor identity (fail-closed).

When to pass `actor_ref` in queries:

- Always pass it when querying on behalf of a specific user. This ensures the
  user sees their own personal memories from private containers plus shared
  evidence from any accessible container.
- Always pass it when the user may have `global` memories. Without `actor_ref`
  on the query, global items are invisible.
- Omit it for system-level or admin queries where actor scoping is not needed.
- Omit it when the integration does not track actor identity.

The runtime should send `actor_ref` on ingest (identifying the speaker) and on
query (identifying the querying user). Pallium uses these to set and filter
memory attribution.

## Integration Checklist

- send only agent-mediated, high-value events
- keep stable source identifiers
- preserve upstream refs so evidence remains actionable
- send `container_ref` on every ingest and query
- query before prompt-building when continuity matters
- keep local seam rules mechanical rather than semantic
- use the debug endpoint before changing heuristics blindly

For a concrete code walkthrough, see
[integration-example.md](integration-example.md).

## MCP Tools (Agent-Initiated Memory Access)

In addition to the runtime-driven HTTP integration above, Pallium exposes an
MCP endpoint that gives the LLM direct access to memory tools. This enables
the agent to explicitly search, debug retrieval, and ingest artifacts — useful
when automatic injection isn't enough.

### Architecture

Pallium's MCP server runs in two modes:

**Embedded (production)** — when `mcp[cli]` is installed, the MCP endpoint
is automatically available at `/mcp` on the same HTTP server:

```
http://<pallium-host>:8000/mcp
```

No separate process or port. Install with `pip install "pallium[mcp]"`.

**Standalone (local development)** — runs as a separate process, useful for
local testing with Claude Code:

```bash
python -m app.run mcp
```

This starts an MCP server on port 8001 (configurable via `FASTMCP_PORT`).
Transport defaults to streamable-http; set `PALLIUM_MCP_TRANSPORT=stdio`
for stdio mode.

### Tools

| Tool | Purpose |
|---|---|
| `pallium_query` | Search memory explicitly. Use when auto-injection is missing something. |
| `pallium_query_debug` | Investigate retrieval — scores, stages, filtering. Use when memory seems missing. |
| `pallium_ingest` | Store an artifact for processing. Pass `artifact_kind="note"` when the user explicitly asks to remember something — this preserves content faithfully. Without it, standard type-classification extraction is used. |
| `pallium_expand` | Get the full structured payload and source conversation items behind a memory card. Use when a memory card has `[+expand]` available and the agent needs the original context or complete structured fields. |
| `pallium_flag_memory` | Flag a memory as incorrect or outdated. See [Flagging Wrong Memories](#flagging-wrong-memories) below. |

Explicit memory-write tools (use sparingly — automatic extraction covers
routine cases):

| Tool | Purpose |
|---|---|
| `pallium_remember(text, type, ...)` | Durable fact write. `type` ∈ `{decision, investigation_outcome, constraint_memory, operational_fact, note}`. Use when the user has stated an architectural decision, hard constraint, or investigation conclusion that should survive compaction. |
| `pallium_correct(memory_id, corrected_text, reason)` | Fix a wrong memory in place (extraction was mislabeled or partial). Returns 409 if already superseded — walk the chain via `pallium_expand` and correct the head. For fully obsolete memories use `pallium_supersede`. |
| `pallium_supersede(new_text, supersedes_id, reason?)` | Replace an obsolete memory. Both rows persist; retrieval hides the old. Use when the old was correct at the time but a different fact now applies. Returns 409 on double-supersede. |
| `pallium_forget(memory_id, reason)` | Soft-delete. Retrieval hides it; audit trail preserved. Idempotent. Agent-decisive; use `pallium_flag_memory` when you're one voter among many. |
| `pallium_record_outcome(procedure_id, outcome, ...)` | Record `success` / `failure` / `inconclusive` for an `operational_fact` procedure. Confidence and counter values are audit-only — they do not boost retrieval ranking. |

All tools accept optional scope parameters (`container_ref`, `thread_ref`,
`actor_ref`, `visibility`) for filtering. When omitted, defaults come from
environment variables (`PALLIUM_CONTAINER_REF`, `PALLIUM_THREAD_REF`,
`PALLIUM_ACTOR_REF`, `PALLIUM_VISIBILITY`).

Note: when using the embedded HTTP transport (`/mcp`), the MCP server runs
in the Pallium process, not the agent process. Environment variables set in
the agent's process are not visible to the MCP server. In this mode, the
agent must pass scope parameters explicitly on each tool call. The
integrating runtime should include `container_ref` in the injected memory
header so the agent can read and pass it.

### Registration

For Claude Code (standalone mode):

```bash
claude mcp add pallium -- python -m app.run mcp
```

For a remote Pallium instance (embedded mode), configure your MCP client
to connect via streamable-http to `http://<pallium-host>:8000/mcp`.

### Agent Instructions

The integrating runtime should include instructions that teach the LLM the
two-tier model:

1. **Automatic** — the runtime queries Pallium and injects relevant memory
   before each turn. The LLM trusts this for most cases.
2. **Explicit tools** — when automatic injection is insufficient, the LLM
   uses the MCP tools directly.

Example instruction block:

```markdown
You have access to a memory system. Relevant memories are automatically
injected into your context — each block may include a [ref: <id>]
annotation linking to the original conversation.

When using Pallium tools, pass the container_ref from the memory header.

- pallium_query — search when auto-injection is missing something
- pallium_expand — get the full structured payload and original conversation behind a memory
  card when the summary isn't enough (pass the id from [ref: ...])
- pallium_query_debug — investigate why a memory wasn't found
- pallium_ingest — store something for future recall. Pass artifact_kind="note"
  when the user explicitly asks to remember something.

Don't query on every turn. Don't re-query injected context.
Don't fetch evidence for every memory — only when you need more detail.
```

### Responses

All tools return Pallium's HTTP API responses verbatim as pretty-printed JSON.
No transformation — the API response is the contract.

## Flagging Wrong Memories

Pallium sometimes extracts bad memories — stale transient state, fragments,
context-dropped vagueness. The flagging mechanism lets agents and humans
report these so they stop being injected.

### How It Works

1. The agent (or human) calls `POST /memory/{id}/flag` with a reason and a
   `source_ref` identifying the flag source
2. Pallium records the flag and counts distinct sources within a 30-day window
3. After 2 independent sources flag the same memory, it's suppressed —
   excluded from retrieval permanently

For confirmed-bad memories (e.g. from manual review), pass `immediate: true`
to suppress without waiting for a second independent flag.

### When to Flag

Flag a memory when:

- It states something that is now demonstrably incorrect ("PR is blocked" —
  but it was merged yesterday)
- It's a meaningless fragment ("| Can do |" extracted from a table cell)
- It's too vague to be useful ("user is concerned about safety")
- It contradicts a newer, better-supported memory
- It's a meta-extraction artifact (triage commentary re-ingested as memory)

Do not flag speculatively. The agent should only flag when it has concrete
contrary evidence or can see the memory is clearly broken.

### Integration Patterns

**Agent-initiated flagging (MCP tool):**

The agent calls `pallium_flag_memory` directly when it notices a bad memory
in the injected context. Each injected memory block includes a `memory_object_id`
that the agent passes to the tool. The `source_ref` parameter is optional in
the MCP tool — when omitted, it resolves to the agent's actor identity or
`"local"`.

**Runtime-initiated flagging (HTTP API):**

The integrating runtime calls `POST /memory/{id}/flag` directly. Use a
stable `source_ref` that identifies the flagging session or review pass
(e.g. `"agent-session:<session_id>"` or `"triage-review:2026-04-17"`).
This ensures session-level dedup: a chatty session that flags the same
memory repeatedly counts as one voice.

**Human triage:**

For batch review of bad memories, call the flag endpoint with
`immediate: true`. This is appropriate when a human has confirmed the
memory is garbage — no consensus needed.

### Lifecycle After Flagging

Suppressed memories follow the same retention TTL as superseded memories
(7 days by default). After TTL, they're permanently deleted along with
their evidence and flag records.

Suppression is permanent within the TTL — there is no "unflag" mechanism.
If a memory was incorrectly suppressed, re-ingest the original content to
let Pallium re-extract it.

See [http-api.md — POST /memory/{id}/flag](http-api.md#post-memorymemory_object_idflag)
for the full request/response contract.

## Boundaries

Pallium is not an authorization service or agent runtime. Its current scope model is local and single-user.
The downstream agent should be a thin client that provides runtime facts and
accepts Pallium's memory decisions — not a second memory engine.

Pallium does not yet support:

- cross-container shared memory
- automatic ingestion from arbitrary upstream systems
- authorization on behalf of your app
