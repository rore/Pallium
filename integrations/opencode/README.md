# Pallium — OpenCode integration

Persistent, cross-session memory for [OpenCode](https://opencode.ai) via the local
Pallium daemon. This is the OpenCode peer of `integrations/claude-code` and
`integrations/codex`: it adapts OpenCode's plugin lifecycle to Pallium's REST
API so memory **auto-injection** and **auto-ingestion** work the same way they
do in Claude Code.

OpenCode does **not** run Claude Code's `settings.json` hooks and has no
Claude-style JSONL transcript, so this integration ships as an **OpenCode
plugin** (JS module) that reads structured messages through the injected SDK
`client` and talks to the daemon over HTTP.

## What it does

| Pallium behaviour | Claude hook | OpenCode adapter |
|---|---|---|
| Orientation query + inject | SessionStart | `event` → `session.created` → `POST /query` (`trigger_origin: session_start_orientation`) → injected via `experimental.chat.system.transform` |
| Ingest user msg + inject memories | UserPromptSubmit | `chat.message` → `POST /item-and-query` (`query_trigger_origin: user_prompt_submit`) → blocks injected via `experimental.chat.system.transform` |
| Deliver Agent Relay | UserPromptSubmit | `chat.message` claims → `experimental.chat.messages.transform` appends an attributed lower-authority reminder → acknowledge |
| Ingest assistant turn | Stop | `event` → `session.idle` → read last assistant message via `client.session.messages` → `POST /items` |
| Failure/retry triggers | PostToolUse | `tool.execute.after` — **off** unless `PALLIUM_POSTTOOL_TRIGGERS=1` |
| Ingest before compaction | PreCompact | `experimental.session.compacting` → `POST /items` (best-effort) |

Every hook is **fail-safe**: it swallows all errors and never breaks the user's
turn, matching the Python hooks' `try/except` + exit-0 behaviour. HTTP calls use
a short (~6s) timeout. Injection formatting (header/footer, `[+expand]`, and the
per-trigger char budgets of 1200 / 2400 / 1200) reuses the same
`format_injection` semantics as the Python integrations, and conforms to
`docs/specs/2026-06-27-injection-policy-abstention.md` (grounded structural
orientation query; no gate bypass except the opt-in deterministic triggers).

## Files

```
integrations/opencode/
├─ package.json                         # npm-publishable ("@pallium/opencode")
├─ opencode.json                        # example wiring (local plugin path)
├─ AGENTS.md                            # Pallium guidance block (OpenCode reads AGENTS.md)
├─ README.md
├─ skills/
│  └─ pallium-memory/SKILL.md           # auto-discovered skill
├─ .opencode/
│  ├─ command/pallium-memory.md         # /pallium-memory slash command
│  └─ plugins/
│     ├─ pallium.mjs                    # the plugin (hook entrypoints)
│     └─ pallium-common.mjs             # JS reimpl of common.py helpers
└─ tests/
   ├─ common.test.mjs                   # parity: container / redaction / dedup / budget / turn extraction
   └─ plugin.test.mjs                   # hook smoke: item-and-query→inject, idle→items, opt-in triggers
```

`pallium-common.mjs` is the OpenCode-runtime copy of the shared helpers. Pallium's
established pattern is that **each host integration carries its own self-contained
`common`** (claude-code and codex each ship a full Python copy, sharing only the
usage-audit matcher). Since OpenCode plugins run as JS in the OpenCode server
process, this is the JS copy — one source of truth per runtime, asserted against
the Python contract by the parity suite.

## Install

### 1. Run the Pallium daemon

The plugin talks to `http://localhost:${PALLIUM_PORT:-19836}`. Start Pallium and
confirm it is healthy:

```bash
python -m app.run all --port 19836
curl http://localhost:19836/status
```

### 2. Add the plugin to your OpenCode config

**From npm** (once published) — in `opencode.json` / `opencode.jsonc`:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["@pallium/opencode"]
}
```

**From a local checkout** — point at the plugin file:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["./integrations/opencode/.opencode/plugins/pallium.mjs"]
}
```

The **`"plugin"` array entry is the recommended, verified method** (it is how
OpenCode loads plugins in practice). A relative path is resolved against the
config file's directory, so for a *global* install add the entry to
`~/.config/opencode/opencode.json` with a path to the plugin file.

> Note: OpenCode also documents auto-loading any file dropped into a
> `.opencode/plugins/` (project) or `~/.config/opencode/plugins/` (global)
> directory. That directory auto-load has been observed **not** to pick the
> plugin up on some setups — prefer the explicit `"plugin"` array entry above.
> If you point the entry at the in-repo file, the plugin imports its sibling
> `pallium-common.mjs` relative to its own location, so keep the two files
> together.

The plugin's `config` hook registers the `pallium-memory` skill directory and the
`/pallium-memory` slash command automatically.

### 3. Add the memory guidance to AGENTS.md

OpenCode reads `AGENTS.md`. Append the block from this directory's `AGENTS.md`
(the `<!-- pallium:start -->…<!-- pallium:end -->` region) to your project or
global `AGENTS.md` so the agent knows how to do deliberate memory work with the
Pallium MCP tools. The skill in `skills/pallium-memory/SKILL.md` carries the same
guidance for on-demand use.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `PALLIUM_PORT` | `19836` | Port of the local Pallium daemon. No port or secret is ever hardcoded. |
| `PALLIUM_POSTTOOL_TRIGGERS` | *(unset)* | Set to `1` to enable opt-in `tool.execute.after` failure/retry triggers. Off by default (matches the Python hooks) because an enabled trigger injects regardless of the server-side injection policy. |

Per-session state (dedup window + container pinning) is stored under
`~/.pallium/hooks/state/`, the **same** directory and file format as the Python
integrations, so a mixed-agent box shares one store.

## Tests

```bash
cd integrations/opencode
node --test tests/*.test.mjs
```

The suite has parity with the codex/claude-code Python suites: git-remote and
path container derivation, redaction behavioural parity (identical inputs →
identical outputs), the 5-minute dedup window, session pinning, injection budget
trimming, and turn extraction / work-trace metadata over OpenCode's message-part
shape. `plugin.test.mjs` drives each hook against the structural OpenCode hook
shapes with a mocked daemon + SDK client (no live OpenCode or Pallium required),
including the fail-safe (daemon-unreachable) path.

## Known gaps / later phases

- **Phase 5b usage-audit populator** (`GET/POST /memory-usage-audit`,
  `GET /memory/<id>/expand`) is implemented in the Python Stop hooks but deferred
  here; it is best-effort telemetry, not load-bearing for injection or ingestion.
- **Compaction ingests but does not query.** `experimental.session.compacting`
  captures the latest assistant turn via `/items` (so pre-compaction work isn't
  lost) but does not issue a `pre_compact`-tagged `/query`; there is no
  pre-compaction memory *injection*, unlike Claude Code's `pre_compact.py`.
- **Synchronous git.** Container/actor/orientation derivation uses synchronous
  `git` calls (bounded at 3s each). The Python peers are short-lived subprocesses
  where this is free; this plugin runs in the long-lived OpenCode server process,
  so a hung `git` can briefly block the event loop. Acceptable for the local
  single-user daemon; the upgrade path is async `execFile` if it ever regresses.
- **Orientation only on new sessions.** Session-start orientation fires on the
  `session.created` event, so a *resumed* session (e.g. after an OpenCode
  restart) gets per-message injection and ingest but no session-start
  orientation query. The Python hooks orient on startup *and* resume; this is a
  minor best-effort parity gap (orientation usually abstains anyway).
- A `pallium setup opencode` CLI (mirroring `setup_codex.py` /
  `setup_claude_code.py`) could automate steps 2–3 and write the working
  `"plugin"` + MCP config deterministically; the npm `"plugin"` entry is the
  idiomatic OpenCode install and is documented above.
