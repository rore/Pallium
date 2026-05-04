# Codex Integration Design

**Date:** 2026-05-03  
**Status:** Draft  
**Scope:** Client-side integration of Pallium with OpenAI Codex CLI

## Overview

Pallium integration for Codex, equivalent to the existing Claude Code integration. Uses Codex's hook system for automatic per-turn memory injection and ingestion, MCP for agent-initiated tools, AGENTS.md for behavioral instructions, and Codex's plugin packaging model for distribution.

No backend changes required — this is a pure client-side packaging exercise against the same Pallium HTTP API.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Codex CLI                                                    │
│                                                              │
│  SessionStart ──→ session_start.py ──→ additionalContext     │
│  UserPromptSubmit ──→ user_prompt_submit.py ──→ inject+ingest│
│  Stop ──→ stop.py ──→ silent ingestion                       │
│                                                              │
│  MCP (stdio) ──→ pallium-mcp ──→ 7 tools                    │
│  AGENTS.md ──→ behavioral contract                           │
│  Skill ──→ explicit memory workflows                         │
└──────────────┬──────────────────────────────────────────────┘
               │ HTTP (localhost:19836)
               ▼
┌──────────────────────────┐
│ Pallium Service (sidecar) │
│ POST /item-and-query      │
│ POST /query               │
│ POST /items               │
└──────────────────────────┘
```

## Directory Structure

```
integrations/codex/
├── .codex-plugin/
│   └── plugin.json              # Plugin manifest
├── hooks/
│   ├── hooks.json               # Hook registration (Codex format)
│   ├── common.py                # Shared utilities (standalone, stdlib-only)
│   ├── session_start.py         # SessionStart → inject orientation memory
│   ├── user_prompt_submit.py    # UserPromptSubmit → ingest + inject
│   └── stop.py                  # Stop → ingest assistant response
├── .mcp.json                    # MCP server configuration
├── AGENTS.md                    # Behavioral instructions for Codex
└── skills/
    └── pallium-memory/
        └── SKILL.md             # Explicit memory workflow skill
```

## Plugin Manifest (experimental — not the primary install path)

The plugin structure is defined for future distribution via Codex's marketplace mechanism. However, plugin-local hooks may not execute reliably in current Codex CLI versions (see openai/codex#16430). **The setup CLI (`pallium setup codex`) is the primary and tested installation method.**

`.codex-plugin/plugin.json`:

```json
{
  "name": "pallium-memory",
  "version": "0.1.0",
  "description": "Persistent cross-session memory for Codex via Pallium",
  "author": "pallium",
  "hooks": "./hooks/hooks.json",
  "mcpServers": "./.mcp.json",
  "skills": "./skills"
}
```

## Hook System

### Registration

`hooks/hooks.json` (plugin-relative paths — resolved from plugin root at runtime):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume",
        "hooks": [{
          "type": "command",
          "command": "python3 hooks/session_start.py",
          "timeout": 8,
          "statusMessage": "Loading memory"
        }]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [{
          "type": "command",
          "command": "python3 hooks/user_prompt_submit.py",
          "timeout": 8,
          "statusMessage": "Retrieving memory"
        }]
      }
    ],
    "Stop": [
      {
        "hooks": [{
          "type": "command",
          "command": "python3 hooks/stop.py",
          "timeout": 15
        }]
      }
    ]
  }
}
```

**Path resolution note:** In plugin context, paths are relative to plugin root. In manual CLI install (`~/.codex/hooks.json`), the setup command writes absolute paths to the installed hook scripts.

### Output Protocol

Hooks communicate via JSON on stdout. For context injection:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "formatted memory text here"
  }
}
```

For silent operations (stop hook): print nothing, exit 0.

### Hook Input Schemas

**SessionStart input:**
- `cwd` (string) — working directory
- `session_id` (string) — session identifier
- `source` (enum: "startup", "resume", "clear") — session trigger
- `model` (string) — model identifier
- `hook_event_name` (string) — "SessionStart"
- `permission_mode` (enum) — approval policy
- `transcript_path` (string|null) — transcript file path

**UserPromptSubmit input:**
- `cwd` (string) — working directory
- `session_id` (string) — session identifier
- `turn_id` (string) — turn-scoped identifier
- `prompt` (string) — user message text
- `model` (string) — model identifier
- `hook_event_name` (string) — "UserPromptSubmit"
- `permission_mode` (enum) — approval policy
- `transcript_path` (string|null) — transcript file path

**Stop input:**
- `cwd` (string) — working directory
- `session_id` (string) — session identifier
- `turn_id` (string) — turn-scoped identifier
- `hook_event_name` (string) — "Stop"
- `model` (string) — model identifier
- `permission_mode` (enum) — approval policy
- `transcript_path` (string|null) — transcript file path

### Hook Behaviors

#### session_start.py

1. Read stdin JSON
2. If `source == "clear"` → exit (no orientation on fresh start)
3. Derive `container_ref` from `cwd`
4. Query Pallium: `POST /query` with "recent decisions, progress, and open tasks", limit 5
5. Format injection with 1200-char budget
6. Emit via `hookSpecificOutput.additionalContext`

#### user_prompt_submit.py

1. Read stdin JSON
2. Guards: skip if prompt < 20 chars, starts with `/`, or dedup hit (5-min window)
3. Strip editor context tags
4. Derive `container_ref`, `actor_ref`
5. Call `POST /item-and-query` — combined ingest + retrieval
6. Format injection with 2400-char budget
7. Emit via `hookSpecificOutput.additionalContext`

#### stop.py

1. Read stdin JSON
2. If no `transcript_path` → exit
3. Read last assistant turn from JSONL transcript
4. Guard: skip if content > 20K chars
5. Ingest via `POST /items` (role=assistant)
6. No output — silent ingestion only
7. Exit 0

### common.py

Standalone module (stdlib-only, no Pallium imports). Provides:

- `read_hook_input()` — parse JSON from stdin
- `emit_context(text, event_name)` — write additionalContext JSON to stdout
- `derive_container_ref(cwd)` — git remote → "git:normalized", fallback to repo hash or path hash
- `derive_actor_ref()` — git config user.name, fallback "local"
- `pallium_request(method, path, payload)` — HTTP client to localhost:19836, 6s timeout
- `format_injection(blocks, container_ref, budget_chars)` — format memory blocks with budget capping
- `read_last_assistant_turn(transcript_path)` — parse JSONL transcript, extract last assistant content
- `check_dedup(prompt, session_id)` — hash-based 5-minute dedup

Constants:
```python
AGENT_REF = "codex"
SOURCE_TYPE = "codex"
PALLIUM_PORT = int(os.environ.get("PALLIUM_PORT", "19836"))
HTTP_TIMEOUT = 6
```

## MCP Configuration

`.mcp.json`:

```json
{
  "mcp_servers": {
    "pallium": {
      "command": "/absolute/path/to/pallium-mcp",
      "args": ["--stdio"],
      "env": {
        "PALLIUM_MCP_TRANSPORT": "stdio",
        "PALLIUM_BASE_URL": "http://localhost:19836"
      },
      "startup_timeout_sec": 10,
      "tool_timeout_sec": 30
    }
  }
}
```

**Note:** `PALLIUM_BASE_URL` is required — without it, the MCP context resolver treats the server as unconfigured and all tools return an error. The tested setup CLI writes an absolute `pallium-mcp` executable path so Codex does not depend on shell `PATH` resolution.

Exposes 7 tools:
- `pallium_query` — manual memory search
- `pallium_query_debug` — retrieval debugging
- `pallium_ingest` — explicit artifact storage
- `pallium_get_evidence` — source conversation behind a card
- `pallium_flag_memory` — mark memory as bad
- `pallium_rate_memory` — relevance feedback
- `pallium_status` — system health

The existing MCP server (`app/mcp/server.py`) requires no changes. Transport and context resolution via environment variables work identically.

## AGENTS.md

Behavioral instructions loaded into Codex's context at session start:

```markdown
# Memory (Pallium)

You have access to Pallium, a memory system that remembers decisions, outcomes,
constraints, and context across sessions.

**Automatic (every turn):** Relevant memories are injected into context via hooks.
Trust this — it handles ~90% of cases. Don't duplicate it with manual queries.

**Feedback (non-blocking):**
When an injected memory is clearly useful or clearly off-topic and the MCP tool is
available, call `pallium_rate_memory` with `container_ref` from the injection
header and the user's message as `query_context`. Do not add latency or fail the
turn solely to rate memory.

**When to use other explicit tools:**
- `pallium_query` — injected context is empty or missing something the user asked about
- `pallium_expand` — you need the original conversation behind a memory card.
  If a `[+expand]` card summary is sufficient, trust the card; fetch evidence only
  when you need the original conversation to answer accurately.
- `pallium_flag_memory` — a memory contradicts what you now know to be true
- `pallium_ingest` — user explicitly asks to remember something (hooks already
  ingest automatically)

**Required parameters for manual tool calls:**
When calling `pallium_query`, `pallium_get_evidence`, or `pallium_ingest`, always pass:
- `container_ref`: use the value from the injection header (e.g. "git:github.com/user/repo")
- `visibility`: "private" for project-scoped memory (default)

Without these parameters, queries will return empty results. The automatic hooks
pass them correctly — you only need to worry about this for explicit tool calls.

**Do not:**
- Query every turn — automatic injection handles routine retrieval
- Re-query for something already in the injected Pallium block
- Ingest routine conversation — hooks do this automatically
- Flag speculatively — only flag when you have concrete contrary evidence
```

## Skill

`skills/pallium-memory/SKILL.md`:

```markdown
---
name: pallium-memory
description: Use when you need to explicitly search, store, or debug Pallium memory beyond what automatic injection provides. Triggers on: "remember this", "why don't you remember", "what do you know about", memory debugging, or when injected context is insufficient.
---

# Pallium Memory Workflow

## When to use this skill
- User asks you to remember something explicitly
- User asks why you don't remember something
- Injected memory context is empty but you expect it shouldn't be
- You need to search for a specific past decision or outcome
- You need to debug retrieval (why was something missed)

## Steps

1. **Identify the need**: Is this a store, search, or debug operation?

2. **For storing** (user says "remember this", "save this"):
   - Call `pallium_ingest` with the content
   - Pass `visibility: "private"` and `container_ref`
   - Confirm to the user what was stored

3. **For searching** (user asks about past context):
   - Call `pallium_query` with a natural-language description
   - Pass `visibility: "private"` and `container_ref`
   - If results have `[+expand]`, call `pallium_expand` for richer context

4. **For debugging** (user says "why don't you remember X"):
   - Call `pallium_query_debug` with the expected query
   - Report: was it found but filtered? Never stored? Low relevance score?
   - Suggest remediation (re-ingest, flag stale memory, etc.)

## Do not
- Use this skill for routine retrieval — hooks handle that automatically
- Ingest every conversation turn — hooks already do this
- Call pallium_query before checking if the answer is already in injected context
```

## Identity Model

| Field | Value | Derivation |
|---|---|---|
| `actor_ref` | git user.name (e.g. "Rotem Hermon") | `git config user.name`, fallback "local" |
| `agent_ref` | `"codex"` | Hardcoded constant |
| `source_type` | `"codex"` | Hardcoded constant |
| `container_ref` | `"git:github.com/user/repo"` | Derived from git remote URL |

**Cross-agent memory sharing:** Both Claude Code and Codex integrations derive `container_ref` identically from the git remote URL and use the same `actor_ref` (git user.name). A user working on the same repo in both tools shares the same memory pool. Memories are attributed to the human + project, not the tool.

The `agent_ref` and `source_type` distinguish provenance for observability but do not affect retrieval filtering.

## Setup CLI

`app/cli/setup_codex.py` — invoked via `pallium setup codex` / `pallium setup codex --uninstall`.

### Install steps

1. Enable hooks feature flag in `~/.codex/config.toml`:
   ```toml
   [features]
   codex_hooks = true
   ```

2. Register MCP server in `~/.codex/config.toml`:
   ```toml
   [mcp_servers.pallium]
   command = "/absolute/path/to/pallium-mcp"
   args = ["--stdio"]
   env = { PALLIUM_MCP_TRANSPORT = "stdio", PALLIUM_BASE_URL = "http://localhost:19836" }
   startup_timeout_sec = 10
   tool_timeout_sec = 30
   ```

3. Register hooks in `~/.codex/hooks.json` (create or merge):
   - SessionStart → `<sys.executable> /abs/path/integrations/codex/hooks/session_start.py`
   - UserPromptSubmit → `<sys.executable> /abs/path/integrations/codex/hooks/user_prompt_submit.py`
   - Stop → `<sys.executable> /abs/path/integrations/codex/hooks/stop.py`
   
   **Note:** Use `sys.executable` (resolved at setup time) for the Python interpreter path, not `python3`. This avoids portability issues on Windows and matches the Claude Code setup pattern.

4. Append AGENTS.md block to `~/.codex/AGENTS.md` (with `<!-- pallium:start/end -->` markers)

5. Create hook state directory: `~/.pallium/hooks/state/`

6. Verify Pallium service at `http://localhost:19836/status`

### Uninstall steps

- Remove `[mcp_servers.pallium]` from config.toml
- Remove Pallium entries from hooks.json
- Remove marked block from AGENTS.md
- Clean hook state directory

### Plugin installation (experimental — validate before recommending)

Plugin-local hooks may not execute in current Codex CLI versions (openai/codex#16430). This path exists for future use once plugin hook execution is confirmed working. For now, register via local marketplace only for MCP/skills (not hooks):

```json
{
  "plugins": [{
    "name": "pallium-memory",
    "source": { "type": "path", "path": "/path/to/pallium/integrations/codex" }
  }]
}
```

## Differences from Claude Code Integration

| Aspect | Claude Code | Codex |
|---|---|---|
| Hook events | SessionStart, UserPromptSubmit, Stop, PreCompact | SessionStart, UserPromptSubmit, Stop |
| PreCompact | Available — re-injects context before compaction | Not available — no equivalent event |
| SessionStart source field | Not available | `source: startup\|resume\|clear` — skip injection on "clear" |
| Hook config format | `.claude/settings.json` hooks section (matcher + nested hooks array) | `.codex/hooks.json` (same structure, standalone file) |
| Instructions file | `~/.claude/CLAUDE.md` (appended block) | `~/.codex/AGENTS.md` (appended block) |
| MCP registration | `claude mcp add` CLI command | `config.toml` `[mcp_servers]` section |
| MCP transport | HTTP (streamable-http on port 8001) | stdio (local process) |
| Plugin packaging | Not natively supported | `.codex-plugin/plugin.json` manifest |
| Skills | Not applicable (Claude Code has different skill model) | `skills/pallium-memory/SKILL.md` |
| `agent_ref` | `"claude-code"` | `"codex"` |
| `source_type` | `"claude-code"` | `"codex"` |
| IDE context stripping | Strips `<ide_selection>` and `<ide_opened_file>` tags | Minimal — no known IDE context tags yet |
| Feature flag | Not required | `[features] codex_hooks = true` must be set |

## Implementation Sequence

1. Create `integrations/codex/` directory structure
2. Write `common.py` (copy from claude-code, change AGENT_REF/SOURCE_TYPE, add `emit_context` helper)
3. Write `session_start.py` (adapt for `source` field check)
4. Write `user_prompt_submit.py` (near-identical to claude-code version)
5. Write `stop.py` (identical logic)
6. Write `hooks.json`, `.mcp.json`, `plugin.json`
7. Write `AGENTS.md` (with public/private visibility instructions)
8. Write `skills/pallium-memory/SKILL.md`
9. Write `app/cli/setup_codex.py` (parallel to setup_claude_code.py)
10. Register `pallium setup codex` in CLI entry point
11. Update `docs/claude-code-integration.md` → generalize or create `docs/codex-integration.md`
12. Test manually against Codex CLI

## Open Questions (deferred)

- **Transcript format**: Codex JSONL transcript structure may differ from Claude Code's. The `read_last_assistant_turn` function handles multiple formats already — may need a third if Codex uses a different schema. Validate during manual testing.
- **Plugin hook execution**: Codex plugin-local hooks may not execute in current CLI versions (openai/codex#16430). The setup CLI is the primary path; plugin packaging is experimental until validated.
- **Plugin marketplace publishing**: "Coming soon" per Codex docs. For now, local path installation only.
- **Global/cross-project memory**: The user wants agents to store global memories (`visibility: "public"`, no `container_ref`) when asked to "remember this everywhere." This requires backend support for cross-container memory that is not yet shipped. Deferred from this spec — add to AGENTS.md instructions once the backend supports it. Track in roadmap.
- **Global memory retrieval in hooks**: Currently hooks query with `visibility: "private"`. Once public memories are supported, hooks should surface both private (container-scoped) and public (global) memories in automatic injection. This applies equally to the Claude Code integration.
