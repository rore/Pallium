# Pallium — OpenCode integration

This plugin connects OpenCode sessions to the local Pallium service. It records
selected turns for Session History, delivers Relay messages on normal turns, and
supports optional derived-memory processing.

## What you get

### Relay

- send messages to another connected Pallium session through the MCP tools;
- receive attributed messages on the next normal OpenCode turn;
- reply to the sender and inspect delivery status.

The stable V1 plugin is passive: messages remain stored until the recipient's
next normal turn. An opt-in V2 adapter adds native queued wake delivery for
OpenCode 2.0.22; it is a separate plugin entry and does not replace an existing
global V1 loader automatically.

> List Pallium Relay recipients, then send `codex:@review`: "The API response
> still needs the legacy field."

### Session History

- record OpenCode user and assistant messages;
- search earlier sessions broadly with `pallium_search_history`;
- search one known exact work reference with `pallium_search_history_by_work_ref`;
- open nearby messages with `pallium_expand_source`.

> Search Pallium Session History for why we kept the legacy response field.

### Optional derived memory

The plugin can ingest turns, request compact memory, and inject selected results.
Failure and retry triggers remain opt-in. None of this is required for Relay
routing or deliberate Session History search.

## Install

### 1. Run Pallium

The plugin and MCP client use the local Pallium service on port `19836` by
default:

```bash
python -m app.run all --port 19836
curl http://localhost:19836/status
```

### 2. Add the plugin and MCP server

OpenCode needs both pieces:

- the plugin for automatic session registration, history capture, incoming Relay
  delivery, and optional derived-memory behavior;
- the Pallium MCP endpoint for Relay send/reply tools and deliberate Session
  History search.

From npm, once the package is published:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["@pallium/opencode"],
  "mcp": {
    "pallium": {
      "type": "remote",
      "url": "http://localhost:19836/mcp",
      "enabled": true
    }
  }
}
```

The stable V1 local loader uses the explicit plugin file:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["./integrations/opencode/.opencode/plugins/pallium.mjs"],
  "mcp": {
    "pallium": {
      "type": "remote",
      "url": "http://localhost:19836/mcp",
      "enabled": true
    }
  }
}
```

To opt in to V2 from a local checkout, use OpenCode's plural `plugins` directory
loader in a project configuration. This loads the package server entry exported
by `integrations/opencode/server.js`; keep the existing global V1 `plugin` entry
unchanged until you deliberately switch configurations. Do not load both adapters
in one OpenCode configuration.

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": ["./integrations/opencode"],
  "mcp": {
    "pallium": {
      "type": "remote",
      "url": "http://localhost:19836/mcp",
      "enabled": true
    }
  }
}
```

Native Windows V2 lifecycle coverage is qualified on released OpenCode 2.0.22
and 2.0.24; this does not imply compatibility with every V2 release. The isolated Windows E2E uses
`PALLIUM_OPENCODE_V2_BINARY` and a local mock provider. It verifies idle and busy
wakes, tool continuation across a Pallium restart after ACK, pre-claim retry,
OpenCode hard restart, service startup recovery, history capture and deletion.
It also reloads the production plugin while a claimed Relay response body is
withheld, verifies the retired callback sends no ACK or payload to the provider,
and verifies successor delivery after claim-lease recovery.

A relative plugin path is resolved from the configuration file. For a global
install, put the entry in `~/.config/opencode/opencode.json` and use a path that
reaches the checked-out plugin file.

The explicit `"plugin"` file entry is the stable V1 loading method. V2 uses the
plural `"plugins"` directory entry shown above. Keep the plugin files together
because each adapter imports its shared helper by relative path.

The `mcp` block follows OpenCode's
[remote MCP configuration](https://opencode.ai/docs/mcp-servers/). If Pallium
uses another port, change both the service command and MCP URL.

### 3. Add the Pallium guidance

OpenCode reads `AGENTS.md`. Append this directory's
`<!-- pallium:start -->...<!-- pallium:end -->` block to a project or global
`AGENTS.md`. It explains when to use Relay, Session History, and optional
derived memory.

The plugin automatically registers the bundled `pallium-memory` skill and
`/pallium-memory` command. Their compatibility names remain memory-oriented, but
their guidance covers all three Pallium uses.

## V1 and V2 Relay behavior

V1 uses the normal-turn `/relay/turn` path. Relay messages are included on a
natural OpenCode turn. V2 polls its native queue in process and asks OpenCode to
queue a native user input; the context hook adds the Relay content to the model
request. The receipt ACK only confirms attachment to model-bound context. It
does not mean the model completed the requested work.

V2 owns a short server lease and renews it while polling. Disposal retires local
hooks and the event stream, cancels ordinary integration requests, and fences
late native callbacks. Best-effort owner detach uses one 500 ms remote cleanup
window with at most four requests in flight; a later owner can enroll after the
lease expires if detach fails. Repeated disposal shares one result. Cleanup
attempts every hook and reports disposal failures rather than claiming success.
Client cancellation cannot undo a request the service already committed.
V2 assistant capture keeps the existing aggregate after the latest native user.
Every selected assistant must have a valid native message ID and a finite
`time.completed` marker. Empty text (including tool-only turns) and text over
20,000 UTF-16 units are skipped; a later completed tool-plus-text aggregate can
be captured. This is best-effort latest-user capture, without historical backfill.
Overlapping callbacks reserve the same scoped capture identity. Retries and
plugin reload reuse a full SHA-256 source key derived from agent, actor,
container, native session and the final selected assistant ID. Pallium's existing
source uniqueness resolves a committed write whose response was lost. Only a
valid single receipt under current native ownership marks the capture successful;
failed writes remain retryable.
A closed session or
changed container scope invalidates the old binding. If compaction removes a
queued native input before V2 can verify it, V2 does not guess that delivery was
admitted or queue it again. Relay keeps the item available for a later normal
turn after its claim lease expires. V1 remains the passive fallback when V2 is
not configured or its native wake cannot be verified.

## How the hooks map

| Pallium behavior | Claude hook | OpenCode adapter |
|---|---|---|
| Register and orient a session | SessionStart | `event` → `session.created` → optional orientation query |
| Record a user message | UserPromptSubmit | `chat.message` → `POST /item-and-query` |
| Deliver incoming Relay (V1) | UserPromptSubmit | `chat.message` claims deliveries → `experimental.chat.messages.transform` appends an attributed reminder → receipt ACK |
| Deliver incoming Relay (V2) | UserPromptSubmit | native queue poll → queued OpenCode input → model context injection → receipt ACK |
| Record an assistant turn | Stop | `event` → `session.idle` → read the last assistant message → `POST /items` |
| Optional failure/retry memory | PostToolUse | `tool.execute.after`, off unless `PALLIUM_POSTTOOL_TRIGGERS=1` |
| Preserve before compaction | PreCompact | `experimental.session.compacting` → `POST /items`, best effort |

Ordinary hooks fail open. A current, verified internal wake without Relay context
fails visibly before provider dispatch. An unproven or stale marker cannot claim
or register a session; it may leave an empty provider turn rather than abort
ordinary user work.
HTTP calls use a short timeout. Incoming Relay uses the message transform
because resumed sessions can discard system-transform additions.

Injection formatting and trigger behavior follow the same contracts as the
Python integrations. See
[the injection policy specification](../../docs/specs/2026-06-27-injection-policy-abstention.md)
for the optional derived-memory details.

## Files

```text
integrations/opencode/
|-- package.json
|-- opencode.json
|-- AGENTS.md
|-- README.md
|-- skills/
|   +-- pallium-memory/
|       |-- SKILL.md
|       +-- references/field-feedback.md
|-- .opencode/
|   |-- command/pallium-memory.md
|   +-- plugins/
|       |-- pallium.mjs
|       +-- pallium-common.mjs
+-- tests/
    |-- common.test.mjs
    +-- plugin.test.mjs
```

`pallium-common.mjs` is the OpenCode JavaScript copy of the shared integration
helpers. Each runtime keeps a self-contained adapter; parity tests compare their
observable behavior.

## Configuration

| Environment variable | Default | Meaning |
|---|---|---|
| `PALLIUM_PORT` | `19836` | Port used by the plugin's HTTP calls. Keep the MCP URL on the same port. |
| `PALLIUM_POSTTOOL_TRIGGERS` | unset | Set to `1` to enable optional failure/retry derived-memory triggers. |

Per-session deduplication and container-pinning state uses
`~/.pallium/hooks/state/`, the same format as the Python integrations.

## Tests

```bash
cd integrations/opencode
node --test tests/*.test.mjs
```

The suite covers container derivation, redaction parity, deduplication, session
pinning, injection budgets, turn extraction, hook behavior, and fail-safe
operation when Pallium is unavailable.

## Known gaps

- V1 remains passive. V2 automatic wake is qualified against isolated Windows
  OpenCode 2.0.22; other releases/platforms and the global installation remain
  unqualified. Native admission and ACK do not guarantee interrupted task completion.
- Usage-audit population is server-owned after durable assistant ingestion.
- Compaction records the latest assistant turn but does not run a pre-compaction
  query.
- Session orientation runs on `session.created`, not on every resumed session.
- Git discovery is synchronous and bounded; a hung Git call can briefly block
  the OpenCode event loop.
- There is no `pallium setup opencode` command. Plugin, MCP, and guidance setup
  remain manual.
