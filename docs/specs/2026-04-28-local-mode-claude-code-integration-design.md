# Local Mode — Claude Code Integration Design

**Date:** 2026-04-28
**Status:** Draft

---

## Problem

Pallium was built as a memory sidecar for AI agents, currently integrated through agent runtimes that manage scope and injection externally. But the most immediate, high-frequency use case is local development: a developer using Claude Code (or other coding tools) across many sessions on the same project, losing context between sessions, rediscovering the same things, and fighting context compaction in long sessions.

Claude Code's built-in memory (flat `.md` files in `.claude/`) doesn't scale: no semantic retrieval, no typed extraction, no consolidation, no evidence provenance, no contradiction detection. It loads everything into context or nothing.

## Goals

1. Run Pallium as an always-on local service that auto-starts with the OS.
2. Integrate with Claude Code via hooks (automatic injection/extraction) and existing MCP tools (explicit queries).
3. Preserve Pallium's existing architecture — no new storage engine, no new extraction logic, no embedded mode.
4. Use a single Pallium instance and database for all workspaces, with logical isolation via container_ref.
5. Enable future extension to other tools (Codex, etc.) sharing the same memory.
6. Ship setup automation: one command to register with Claude Code, one script to install the service.

## Non-Goals

- Embedded mode (MCP process IS the memory engine) — Pallium requires multiple processes.
- Per-repo database isolation — scoping is logical (container_ref), not physical.
- New MCP tools — existing 6 tools are sufficient.
- Session handoff mechanism — existing memory types (task_checkpoint, decision, investigation_outcome) already carry continuity.
- Team/shared memory — this is single-user, local, private.
- Changes to Pallium's core service, retrieval, extraction, or storage layers.

---

## Architecture

### Deployment Model

Pallium runs as a **local sidecar service** — independent of any specific tool's lifecycle.

```
┌─────────────┐     ┌─────────────┐     ┌──────────┐
│ Claude Code │     │   Codex     │     │  Other   │
│  (hooks +   │     │  (future)   │     │  tools   │
│    MCP)     │     │             │     │          │
└──────┬──────┘     └──────┬──────┘     └────┬─────┘
       │                   │                  │
       └───────────────────┼──────────────────┘
                           │ HTTP
                    ┌──────▼──────┐
                    │   Pallium   │
                    │  (sidecar)  │
                    │             │
                    │ server      │
                    │ processor   │
                    │ cleaner     │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ ~/.pallium/ │
                    │  data/      │
                    │  (SQLite +  │
                    │   vector)   │
                    └─────────────┘
```

### Data Location

Single stable location: `~/.pallium/data/`
- One SQLite database
- One vector index
- All repos/workspaces isolated by container_ref values within the same store
- Default port: `19836` (configurable via `~/.pallium/config.toml` or `--port` flag)
- Service install scripts accept `--port` to override if default is taken

### Scoping Model

| Pallium Concept | Local Mode Mapping | Derived From |
|-----------------|-------------------|--------------|
| Container | Workspace/repo | `cwd` → git remote URL or repo root path |
| Thread | Claude Code session | `session_id` from hook payload |
| Actor | Local user | Git user name or fixed `local` |
| Visibility | `private` | Always — enables all memory types (interest, constraint) and actor_ref propagation |

**Why `private`:** Pallium's extraction guards suppress `interest` and `constraint_memory` types in `container`/`public` visibility, and set `actor_ref=null`. Local mode needs personal memory types and actor attribution, so `private` is required.

**Trade-off:** `private` + `container_ref` means memories are strictly isolated per repo. A preference stated in repo A won't surface when querying from repo B. This is accepted for the initial version — cross-container sharing for personal knowledge types is a future iteration.

**Container derivation logic** (shared shell function in `~/.pallium/hooks/lib/common.sh`):
1. If `cwd` is a git repo with a remote → normalize git remote URL (strip `.git`, lowercase) → `"git:github.com/user/repo"`
2. If git repo but no remote → root commit hash → `"repo:<hash-prefix>"`
3. If not a git repo → hash of `cwd` → `"path:<hash-prefix>"`

All integrations (Claude Code, Codex, etc.) source the same shared function, ensuring consistent container_ref derivation.

**Concurrent sessions:** Multiple Claude Code sessions on the same repo share the container (same container_ref) but have distinct threads (different session_id). This is intentional — container-level memories (decisions, facts) are visible across concurrent sessions. Thread-level isolation prevents session A's in-progress state from interfering with session B. SQLite WAL mode supports concurrent reads safely.

---

## Service Lifecycle

### Supervisor Entry Point

Pallium already has a default `all` mode that starts the full stack:

```
python -m app.run
```

This is equivalent to `python -m app.run all` and starts the supervisor with: HTTP server + background processor(s) + cleaner(s). If any process dies, the supervisor restarts it. Accepts `--port` (default 8000, override for local mode to 19836), `--processors`, `--cleaners`.

For local mode, the service install scripts run:
```
python -m app.run all --port 19836
```

### Service Installation

Two scripts in the repo, idempotent (re-running updates rather than duplicates):

**`scripts/install-service.ps1`** (Windows — Task Scheduler):
- Creates scheduled task "Pallium" with trigger "At logon"
- Runs hidden (no console window)
- Restart on failure (configurable retry interval)
- Detects Python/venv path automatically
- Accepts `--port` to override default (if 19836 is taken)
- Matching `scripts/uninstall-service.ps1`

**`scripts/install-service.sh`** (Linux — systemd user service):
- Creates `~/.config/systemd/user/pallium.service`
- Enabled with `systemctl --user enable --now pallium`
- Auto-starts on login, restarts on failure (RestartSec=5)
- Detects Python/venv path automatically
- Accepts `--port` to override default
- Matching `scripts/uninstall-service.sh`

---

## Claude Code Integration

### Setup Command

```
pallium setup claude-code
```

Run once per machine. Does:
1. Registers Pallium MCP server in `~/.claude/settings.json` (streamable-http transport, URL: `http://localhost:19836/mcp`)
2. Installs 4 hook scripts to a stable location (`~/.pallium/hooks/claude-code/`)
3. Registers hooks in `~/.claude/settings.json` (global, applies to all projects)
4. Appends Pallium agent instructions to `~/.claude/CLAUDE.md` (global, teaches Claude when/how to use memory)
5. Hook scripts auto-detect workspace (container_ref) from `cwd` at runtime
6. Verifies Pallium service is running and embedding model is downloaded

Matching teardown: `pallium setup claude-code --uninstall`

### Agent Instructions (`~/.claude/CLAUDE.md` block)

The setup command appends this block to `~/.claude/CLAUDE.md`. It teaches Claude about the two-tier memory model — what's automatic vs what requires explicit tool use.

```markdown
## Memory (Pallium)

You have access to Pallium, a memory system that remembers decisions, outcomes,
constraints, and context across sessions.

**Automatic (every turn):** Relevant memories are injected into context via hooks.
Trust this — it handles ~90% of cases. Don't duplicate it with manual queries.

**When to use explicit tools:**
- `pallium_query` — injected context is empty or missing something the user asked about
- `pallium_get_evidence` — you need the original conversation behind a memory card
- `pallium_flag_memory` — a memory contradicts what you now know to be true
- `pallium_ingest` — user explicitly asks to remember something (hooks already ingest automatically)

**Do not:**
- Query every turn — automatic injection handles routine retrieval
- Re-query for something already in the injected Pallium block
- Ingest routine conversation — hooks do this automatically
- Flag speculatively — only flag when you have concrete contrary evidence
```

This block is static — it doesn't change per session or per project. It complements the dynamic injection from hooks (which provides actual memory content per turn).

### Hook Architecture

Four hooks, registered globally. Each hook sets these fields on ingest:

| Field | Value | Purpose |
|-------|-------|---------|
| `container_ref` | Derived from `cwd` | Repo isolation |
| `thread_ref` | `session_id` from hook payload | Session grouping |
| `actor_ref` | Git user or `"local"` | Personal memory attribution |
| `agent_ref` | `"claude-code"` (or `"claude-code:subagent"`) | Agent provenance |
| `visibility` | `"private"` | Enables all memory types |
| `role` | `"user"` or `"assistant"` | Extraction routing |

Hook behavior:

| Hook Event | Action | Returns to Claude Code |
|------------|--------|------------------------|
| `SessionStart` | Query Pallium (broad scope, container-level) | Orientation memory block (~300 tokens) |
| `UserPromptSubmit` | Ingest user message (role=user) + query Pallium | Memory blocks + flag instruction (400-800 tokens) |
| `Stop` | Read transcript to get assistant response. Ingest it (role=assistant) | Nothing (fire-and-forget) |
| `PreCompact` | Re-query Pallium (broad container-level query) | Memory blocks + flag instruction (400-800 tokens) |

### Hook Payload Contract (from Claude Code docs)

Hooks receive JSON on stdin with these fields:

| Hook | Key Fields | Notes |
|------|-----------|-------|
| `SessionStart` | `session_id`, `cwd`, `source`, `model`, `transcript_path` | `source` is "startup"\|"resume"\|"clear"\|"compact" |
| `UserPromptSubmit` | `session_id`, `cwd`, `prompt`, `transcript_path` | `prompt` contains the user's message text |
| `Stop` | `session_id`, `cwd`, `stop_reason`, `transcript_path` | Does NOT include assistant response — must read `transcript_path` |
| `PreCompact` | `session_id`, `cwd`, `trigger`, `current_token_count`, `transcript_path` | No user prompt available — use broad container query |

Hooks return **plain text via stdout** (for SessionStart, UserPromptSubmit) which gets injected as conversation context. Exit code 0 = success.

### Hook Implementation

Each hook is a script (bash or node) that:
1. Reads Claude Code hook payload from stdin (JSON)
2. Derives scope: container_ref from `cwd`, thread_ref from `session_id`, actor from git config
3. Makes HTTP call(s) to Pallium (`http://localhost:19836`)
4. Writes output to stdout (for hooks that inject context)
5. Uses Claude Code's native `timeout` property (not an internal timeout wrapper)

**Timeouts (in settings.json registration):**
- `UserPromptSubmit`: 8 seconds (must return before model starts)
- `SessionStart`: 8 seconds
- `PreCompact`: 8 seconds
- `Stop`: 15 seconds (transcript reading + ingest, no injection needed)

**Stop hook specifics:** The Stop hook does not receive the assistant response in its payload. It reads the `transcript_path` file (JSONL format) to extract the last assistant turn. Implementation notes:
- Handle both wrapped (`{message: {role, content}}`) and flat (`{role, content}`) JSONL formats
- For tool_result blocks in content arrays, truncate to 500 chars each
- For large transcripts (>10MB), read only the tail (last 2MB)
- Content-length gate: skip ingestion if the extracted response exceeds 20K chars (avoids flooding extraction with large tool dumps)

**Prompt filtering (UserPromptSubmit):**
- Skip prompts shorter than 20 characters (too short to produce memories)
- Skip prompts starting with `/` (slash commands)
- Deduplication: hash the prompt (SHA-256), skip if same hash seen within 5 minutes in the same session. Store hashes in a lightweight state file at `~/.pallium/hooks/state/`

**Degraded mode (Pallium unreachable):**
- `SessionStart`: prints a one-line warning to stderr ("Pallium not reachable — no memory injection this session"), returns empty stdout (no error text enters context)
- `UserPromptSubmit`: returns empty stdout silently (no injection, no error in context)
- `Stop`: logs failure to stderr, skips ingest (turn is lost but session continues)
- `PreCompact`: returns empty stdout silently
- All hooks exit with code 0 even on failure (non-zero would block Claude Code)

### Memory Injection Format

Each injectable block includes a `memory_object_id`. The hook formats them with this ID visible so Claude can reference it:

```
[Pallium memory — container: <container_ref>]

[<title_1> | ref:<memory_object_id_1>] <text_1>

[<title_2> | ref:<memory_object_id_2>] <text_2>

[If any memory above seems incorrect or outdated, use the pallium_flag_memory
tool with the ref ID and a brief reason. Use pallium_get_evidence if you need
more context on how a memory was derived.]

[End Pallium memory]
```

Token budget enforcement: the hook truncates injectable_blocks to fit within budget (400-800 tokens for UserPromptSubmit/PreCompact, ~300 tokens for SessionStart). Budget is approximated at 4 characters per token. Pallium's query `limit` parameter controls how many results are returned; the hook enforces the final character cap by dropping lowest-scored blocks until the budget fits.

### Flagging Mechanism

Unlike the agent-runtime integration (which uses inline `[pallium-flag:]` tags and strips them before display), Claude Code integration uses the **MCP tool** `pallium_flag_memory` directly. Reasons:

- Claude Code hooks fire AFTER the response is rendered — inline tags can't be stripped
- Claude Code is designed for tool use — calling the MCP tool is natural
- The tool already exists and calls the same `/memory/{id}/flag` endpoint
- No regex scanning needed in the Stop hook

The injection instruction tells Claude to call `pallium_flag_memory(memory_object_id, reason)` when a memory contradicts what it knows or appears outdated.

**`source_ref` parameter:** The MCP tool currently requires `source_ref` (who is flagging). For local mode, this is auto-filled from the `PALLIUM_ACTOR_REF` environment variable (set to the local user identity). The MCP context resolution already supports this pattern — `source_ref` becomes optional in the tool signature with a fallback to env. Claude doesn't need to provide it explicitly.

### Evidence Retrieval

The injection instruction also mentions `pallium_get_evidence` — Claude can use it when an injected memory card seems relevant but lacks detail. Since each memory block includes the `memory_object_id`, Claude can call `pallium_get_evidence(memory_object_id)` to see the original source conversation that the memory was derived from.

### MCP Tools

Existing 6 tools unchanged — no new tools needed:

| Tool | Purpose in Local Mode |
|------|----------------------|
| `pallium_query` | Explicit search ("have we seen this before?") |
| `pallium_ingest` | Manual "remember this" (supplements automatic hook ingest) |
| `pallium_query_debug` | Debug why a memory was/wasn't found |
| `pallium_get_evidence` | Get source conversation behind a memory card (when injected context needs more detail) |
| `pallium_flag_memory` | Flag a bad memory (incorrect, outdated, contradicts current knowledge) |
| `pallium_status` | System health check |

Claude learns about `pallium_get_evidence` and `pallium_flag_memory` from two sources:
1. The MCP tool descriptions (always visible to the agent)
2. The injection instruction block (reminds Claude on every injection)

### Session Continuity

On `SessionStart`, the hook queries the container with a broad orientation query (e.g., `"recent decisions, progress, and open tasks"`). Pallium returns the most recent high-value memories: decisions, task checkpoints, investigation outcomes. This provides orientation without requiring a separate handoff mechanism.

**Empty state:** If Pallium has no memories for this container (new repo, first session), the query returns empty results and the hook returns empty stdout — no injection, no placeholder message. The session proceeds normally without memory context.

**PreCompact query:** Since the PreCompact hook has no user prompt in its payload, it uses the same broad orientation query as SessionStart. The goal is to re-inject key context that may be lost during compaction.

---

## Ingest Flow (Per Turn)

```
1. User types prompt
       ↓
2. UserPromptSubmit hook fires (receives: session_id, cwd, prompt)
       ↓
3. Hook derives scope (container from cwd, thread from session_id)
       ↓
4. Hook calls POST /item-and-query
   (single call: ingests user message + queries for relevant memories)
       ↓
5. Pallium returns injectable_blocks (memories relevant to this prompt)
       ↓
6. Hook formats memory blocks + flag instruction, enforces token budget
       ↓
7. Hook writes to stdout → Claude sees prompt + memory context
       ↓
8. Claude responds (may call pallium_flag_memory tool if a memory seems wrong)
       ↓
9. Stop hook fires (receives: session_id, cwd, transcript_path)
       ↓
10. Hook reads last assistant turn from transcript_path (JSONL)
    Skips if content exceeds size gate (avoid ingesting large tool dumps)
       ↓
11. Hook calls POST /items (assistant response, role=assistant)
       ↓
12. Pallium's processor extracts typed memories asynchronously
    (decisions, facts, investigation outcomes, etc.)
```

---

## What Changes in Pallium

### New Code

| Component | Location | Purpose |
|-----------|----------|---------|
| Service install scripts | `scripts/install-service.{ps1,sh}` | OS service registration |
| Service uninstall scripts | `scripts/uninstall-service.{ps1,sh}` | OS service removal |
| Claude Code setup command | `app/cli/setup_claude_code.py` | Register hooks + MCP in Claude Code settings |
| Hook scripts (4) | `integrations/claude-code/hooks/` | UserPromptSubmit, Stop, PreCompact, SessionStart |
| Shared hook library | `integrations/claude-code/hooks/lib/common.sh` | Container derivation, Pallium HTTP calls, error handling |
| `source_ref` auto-fill | `app/mcp/server.py` (modify) | Make `source_ref` optional in `pallium_flag_memory`, default from env |

### Small Changes Needed

- `app/mcp/server.py`: Make `pallium_flag_memory`'s `source_ref` parameter optional with fallback to `PALLIUM_ACTOR_REF` env var
- Port configuration: service install scripts use `--port 19836` (distinct from dev default 8000)

### No Changes Needed

- MCP server (already complete, 6 tools)
- Core service, extraction pipeline, routing
- Storage layer (SQLite + vector index)
- Query/retrieval logic
- Flag/suppression mechanism
- API routes

---

## Future Extensions

- **Cross-container personal memory**: Allow interest/constraint memories to be visible across containers for the same actor (requires visibility model extension)
- **Codex integration**: same Pallium instance, different hook format, same container_ref scoping
- **Session handoff**: if needed, add a `task_checkpoint` extraction on SessionEnd hook
- **Cross-tool memory**: Claude Code and Codex working on the same repo see each other's memories (shared container)
- **Selective ingest tuning**: per-workspace configuration to adjust content-length gate or skip certain turn patterns
- **Token budget tuning**: per-workspace configuration for injection budgets
- **Server-side budget enforcement**: add a `max_chars` parameter to `/query` to move truncation to Pallium
