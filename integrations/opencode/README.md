# Pallium — OpenCode integration

This plugin connects OpenCode sessions to the local Pallium service. It records
selected turns for Session History, delivers Relay messages on normal turns, and
supports optional derived-memory processing.

## What you get

### Relay

- send messages to another connected Pallium session through the MCP tools;
- receive attributed messages on the next normal OpenCode turn;
- reply to the sender and inspect delivery status.

OpenCode does not have active Relay wake today. Messages remain stored until the
recipient's next normal turn.

> List Pallium Relay recipients, then send `codex:@review`: "The API response
> still needs the legacy field."

### Session History

- record OpenCode user and assistant messages;
- search earlier sessions with `pallium_search_history`;
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

From a local checkout:

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

A relative plugin path is resolved from the configuration file. For a global
install, put the entry in `~/.config/opencode/opencode.json` and use a path that
reaches the checked-out plugin file.

The explicit `"plugin"` array is the verified loading method. Directory
auto-loading has failed on some setups. Keep `pallium.mjs` and
`pallium-common.mjs` together because the plugin imports its sibling by relative
path.

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

## How the hooks map

| Pallium behavior | Claude hook | OpenCode adapter |
|---|---|---|
| Register and orient a session | SessionStart | `event` → `session.created` → optional orientation query |
| Record a user message | UserPromptSubmit | `chat.message` → `POST /item-and-query` |
| Deliver incoming Relay | UserPromptSubmit | `chat.message` claims deliveries → `experimental.chat.messages.transform` appends an attributed reminder → acknowledge |
| Record an assistant turn | Stop | `event` → `session.idle` → read the last assistant message → `POST /items` |
| Optional failure/retry memory | PostToolUse | `tool.execute.after`, off unless `PALLIUM_POSTTOOL_TRIGGERS=1` |
| Preserve before compaction | PreCompact | `experimental.session.compacting` → `POST /items`, best effort |

Every hook is fail-safe: it catches errors and never breaks the user's turn.
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
|   +-- pallium-memory/SKILL.md
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

- Active OpenCode wake is not implemented; Relay uses durable next-turn
  delivery.
- The usage-audit populator available in Python Stop hooks is not implemented.
- Compaction records the latest assistant turn but does not run a pre-compaction
  query.
- Session orientation runs on `session.created`, not on every resumed session.
- Git discovery is synchronous and bounded; a hung Git call can briefly block
  the OpenCode event loop.
- There is no `pallium setup opencode` command. Plugin, MCP, and guidance setup
  remain manual.
