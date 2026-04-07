# MCP Agent Awareness — Integration Runtime Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Note:** This plan covers the integrating runtime side of the MCP agent awareness feature. It is a companion to the Pallium-side plan at `docs/plans/2026-04-07-mcp-agent-awareness.md`. Remove this file once the work is complete.

**Goal:** Wire the Pallium MCP server into the integrating runtime so the LLM gains memory awareness — MCP registration, per-message environment variables, agent instructions, and a CLI enable/disable command.

**Architecture:** The runtime already calls Pallium's HTTP API for automatic memory injection. This plan adds a parallel MCP path where the LLM can explicitly query, debug, and ingest via tools. All changes are scoped to Pallium-specific code — no changes to the daemon core, installer, SessionManager, or ClaudeSessionRunner constructor.

**Key design choice — minimal blast radius:** Static config (`PALLIUM_BASE_URL`, `PALLIUM_PROJECT_DIR`) is set on the daemon's process environment at startup, inherited by all subprocesses. Dynamic per-session scope vars are computed in session_runner from `self._session_info` (which already exists). This avoids plumbing new config through SessionManager or modifying constructors.

**Scope:** Local mode only. Container mode (docker exec) env propagation is a follow-up.

**Spec:** Pallium repo `docs/specs/2026-04-07-mcp-agent-awareness-design.md`, Integration Guide section.

**Codebase:** `c:\sap-dev\xlm\pelican`

---

## File Map

| File | Responsibility | Change |
|---|---|---|
| `agent-config/mcp.json` | MCP server declarations | Add `pallium` entry (declaration only, not enabled by default) |
| `cli/daemon.py` | Daemon startup | Set static `PALLIUM_BASE_URL` and `PALLIUM_PROJECT_DIR` on `os.environ` when pallium enabled (~4 lines) |
| `cli/config.py` | Config dataclass | Add `project_dir` field to `PalliumConfig` (~2 lines) |
| `cli/session_runner.py` | Claude subprocess env | Compute and inject dynamic `PALLIUM_*` scope vars from existing `self._session_info` (~12 lines) |
| `agent-config/instructions/pallium-memory.md` | Agent instructions for memory tools | Create |
| `cli/pallium_setup.py` | CLI enable/disable command | Create |
| `cli/cli.py` | CLI command registration | Register `pallium` group (~2 lines) |
| `CLAUDE.local.md` | Conditional instruction import | Created/managed by enable/disable command |

**Not touched:** `agent-config/settings.json`, `cli/session_manager.py`, `ClaudeSessionRunner.__init__`, `installer/`, `agent-config/AGENTS.md`.

---

### Task 1: Add Pallium MCP Entry to mcp.json

The server declaration goes in mcp.json but is **not** added to `enabledMcpjsonServers` in `settings.json`. The `pelican pallium enable` command (Task 4) handles activation. This means pallium has zero impact on anyone who doesn't explicitly enable it.

**Files:**
- Modify: `agent-config/mcp.json`

- [ ] **Step 1: Add pallium MCP server to mcp.json**

In `agent-config/mcp.json`, add a `"pallium"` entry to the `"mcpServers"` object, after the existing entries:

```json
"pallium": {
    "command": "python",
    "args": ["-m", "app.run", "mcp"],
    "cwd": "${PALLIUM_PROJECT_DIR}",
    "env": {
        "PALLIUM_BASE_URL": "${PALLIUM_BASE_URL}",
        "PALLIUM_CONTAINER_REF": "${PALLIUM_CONTAINER_REF}",
        "PALLIUM_THREAD_REF": "${PALLIUM_THREAD_REF}",
        "PALLIUM_ACTOR_REF": "${PALLIUM_ACTOR_REF}",
        "PALLIUM_VISIBILITY": "${PALLIUM_VISIBILITY}"
    }
}
```

- [ ] **Step 2: Verify settings.json is NOT modified**

Confirm that `agent-config/settings.json` `enabledMcpjsonServers` does NOT include `"pallium"`. The server is declared but dormant until `pelican pallium enable` is run.

- [ ] **Step 3: Commit**

```bash
git add agent-config/mcp.json
git commit -m "feat(pallium): declare pallium MCP server in mcp.json (disabled by default)"
```

---

### Task 2: Set Static Env Vars on Daemon Startup

The daemon sets `PALLIUM_BASE_URL` and `PALLIUM_PROJECT_DIR` on its own process environment when pallium is enabled. These are static for the daemon's lifetime and are inherited by all `claude -p` subprocesses via `os.environ.copy()` in session_runner.

**Files:**
- Modify: `cli/daemon.py` (~4 lines in `__init__`)
- Modify: `cli/config.py` (~2 lines)

- [ ] **Step 1: Add project_dir to PalliumConfig**

In `cli/config.py`, add `project_dir` to the `PalliumConfig` dataclass (after `debug_trace`):

```python
project_dir: str = ""  # Path to Pallium project, used for MCP server cwd
```

And in the config loading section (inside the `if "pallium" in processed:` block), add to the `PalliumConfig()` constructor call:

```python
project_dir=pallium_data.get("project_dir", ""),
```

- [ ] **Step 2: Set static env vars in daemon.__init__**

In `cli/daemon.py`, find the section after `self.pallium_client` is created (around line 221, after `self._logger.info("Pallium integration enabled")`). Add:

```python
            # Set static Pallium env vars — inherited by Claude subprocess via os.environ.copy()
            # Dynamic per-session vars (container_ref, thread_ref, etc.) are set in session_runner
            import os
            os.environ["PALLIUM_BASE_URL"] = self.config.pallium.base_url
            if self.config.pallium.project_dir:
                os.environ["PALLIUM_PROJECT_DIR"] = self.config.pallium.project_dir
```

- [ ] **Step 3: Commit**

```bash
git add cli/config.py cli/daemon.py
git commit -m "feat(pallium): set static MCP env vars on daemon startup"
```

---

### Task 3: Inject Dynamic Env Vars Per-Message

The runner computes per-session scope variables from `self._session_info` (which already exists on `ClaudeSessionRunner`) and adds them to the subprocess env. No constructor changes needed.

**Files:**
- Modify: `cli/session_runner.py` (~12 lines)

- [ ] **Step 1: Add dynamic Pallium env var injection**

In `cli/session_runner.py`, after line 194 (`env["PELICAN_SESSION_ID"] = self.pelican_session_id`) and before the `env.pop("CLAUDECODE", None)` line, add:

```python
        # Pallium MCP: dynamic per-session scope vars
        # Static vars (PALLIUM_BASE_URL, PALLIUM_PROJECT_DIR) are inherited from daemon env.
        # Ref-building logic mirrors cli/pallium_client.py:_container_ref, _thread_ref, _visibility
        if env.get("PALLIUM_BASE_URL") and self._session_info:
            s = self._session_info
            is_dm = s.is_dm
            env["PALLIUM_CONTAINER_REF"] = (
                f"slack:dm:{s.slack_channel or s.slack_user}" if is_dm
                else f"slack:channel:{s.slack_channel}"
            )
            if s.slack_channel and s.slack_thread_ts:
                env["PALLIUM_THREAD_REF"] = f"slack:thread:{s.slack_channel}:{s.slack_thread_ts}"
            env["PALLIUM_ACTOR_REF"] = f"slack:user:{s.slack_user}"
            env["PALLIUM_VISIBILITY"] = "private" if is_dm else "public"
```

Note: The guard `env.get("PALLIUM_BASE_URL")` checks whether the daemon set the static vars (i.e., pallium is enabled). No config object needed — the env is the signal. The ref-building formulas are inlined from `pallium_client.py` (`_container_ref`, `_thread_ref`, `_visibility`). If those formulas ever evolve, both sites need to be updated.

- [ ] **Step 2: Commit**

```bash
git add cli/session_runner.py
git commit -m "feat(pallium): inject dynamic MCP scope vars per-message"
```

---

### Task 4: Create Agent Instructions File

**Files:**
- Create: `agent-config/instructions/pallium-memory.md`

- [ ] **Step 1: Create instructions directory**

```bash
mkdir -p agent-config/instructions
```

- [ ] **Step 2: Create the agent instructions file**

Create `agent-config/instructions/pallium-memory.md`:

```markdown
## Memory (Pallium)

You have access to a memory system that remembers decisions, investigation
outcomes, and context from previous conversations. It works in two ways:

**Automatic (most turns):** Relevant memories are injected at the top of the
message as `[Prior learned state from earlier related work]`. Trust this — it's
pre-selected for relevance. You don't need to do anything.

**Explicit tools (when automatic isn't enough):**
- `pallium_query` — Search memory when the injected context is missing
  something specific. Example: user asks about a past decision that wasn't
  auto-injected.
- `pallium_query_debug` — Investigate retrieval. Use when a user asks
  "why don't you remember X?" or when you suspect a memory should exist
  but wasn't injected.
- `pallium_ingest` — Store an artifact for memory processing. Use when the
  user explicitly asks you to remember something, or to record a
  decision/outcome for future reference.

**When NOT to use tools:**
- Don't query on every turn — automatic injection handles ~90% of cases.
- Don't re-query for something already in `[Prior learned state]`.
- Don't ingest routine conversation — the integration layer already ingests
  your outputs automatically.
```

- [ ] **Step 3: Commit**

```bash
git add agent-config/instructions/pallium-memory.md
git commit -m "feat(pallium): add agent instructions for memory tools"
```

---

### Task 5: Enable/Disable CLI Command

A Click command group `pallium` with `enable`, `disable`, and `status` subcommands. The `enable` command manages three things in `settings.local.json`: `enabledMcpjsonServers` (activation), `mcp__pallium` permission (allow tool calls), and the `CLAUDE.local.md` instruction import.

Default state after code merges: **disabled**. Pallium is declared in mcp.json but not in enabledMcpjsonServers until the user runs `pelican pallium enable`.

**Files:**
- Create: `cli/pallium_setup.py`
- Modify: `cli/cli.py`

- [ ] **Step 1: Implement the setup module**

Create `cli/pallium_setup.py`:

```python
"""Pallium MCP enable/disable commands.

Manages Claude Code configuration files to conditionally activate
the Pallium MCP server and agent instructions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click

logger = logging.getLogger(__name__)

INSTRUCTIONS_IMPORT = "@services/pelican/agent-config/instructions/pallium-memory.md"
CLAUDE_LOCAL_MD = "CLAUDE.local.md"
MCP_SERVER_NAME = "pallium"
MCP_PERMISSION = "mcp__pallium"


def _workspace_root() -> Path:
    """Resolve workspace root from LOYALTY_WORKSPACE or cwd."""
    import os
    ws = os.environ.get("LOYALTY_WORKSPACE", "")
    return Path(ws) if ws else Path.cwd()


def _settings_local_path() -> Path:
    return _workspace_root() / ".claude" / "settings.local.json"


def _claude_local_md_path() -> Path:
    return _workspace_root() / CLAUDE_LOCAL_MD


def _read_settings_local() -> dict:
    path = _settings_local_path()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _write_settings_local(data: dict) -> None:
    path = _settings_local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")


def _ensure_in_list(data: dict, key: str, value: str) -> None:
    """Add value to a list in data[key] if not already present."""
    lst = data.get(key, [])
    if value not in lst:
        lst.append(value)
    data[key] = lst


def _remove_from_list(data: dict, key: str, value: str) -> None:
    """Remove value from data[key] list. Remove key if list becomes empty."""
    lst = data.get(key, [])
    if value in lst:
        lst.remove(value)
    if lst:
        data[key] = lst
    else:
        data.pop(key, None)


@click.group()
def pallium():
    """Manage Pallium memory integration."""
    pass


@pallium.command()
def enable():
    """Enable Pallium MCP server and agent instructions."""
    settings = _read_settings_local()

    # 1. Add to enabledMcpjsonServers
    _ensure_in_list(settings, "enabledMcpjsonServers", MCP_SERVER_NAME)

    # 2. Remove from disabledMcpjsonServers if present
    _remove_from_list(settings, "disabledMcpjsonServers", MCP_SERVER_NAME)

    # 3. Add mcp__pallium permission
    permissions = settings.setdefault("permissions", {})
    allow = permissions.get("allow", [])
    if MCP_PERMISSION not in allow:
        allow.append(MCP_PERMISSION)
    permissions["allow"] = allow

    _write_settings_local(settings)
    click.echo(f"MCP server: enabled ({MCP_SERVER_NAME} added to enabledMcpjsonServers)")
    click.echo(f"Permission: enabled ({MCP_PERMISSION} added to permissions.allow)")

    # 4. Add @import to CLAUDE.local.md
    md_path = _claude_local_md_path()
    existing = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    if INSTRUCTIONS_IMPORT not in existing:
        with md_path.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(f"{INSTRUCTIONS_IMPORT}\n")
    click.echo(f"Agent instructions: enabled (added to {CLAUDE_LOCAL_MD})")
    click.echo("\nDone. Restart the daemon for changes to take effect.")


@pallium.command()
def disable():
    """Disable Pallium MCP server and agent instructions."""
    settings = _read_settings_local()

    # 1. Remove from enabledMcpjsonServers
    _remove_from_list(settings, "enabledMcpjsonServers", MCP_SERVER_NAME)

    # 2. Add to disabledMcpjsonServers
    _ensure_in_list(settings, "disabledMcpjsonServers", MCP_SERVER_NAME)

    # 3. Remove mcp__pallium permission
    permissions = settings.get("permissions", {})
    allow = permissions.get("allow", [])
    if MCP_PERMISSION in allow:
        allow.remove(MCP_PERMISSION)
        permissions["allow"] = allow

    _write_settings_local(settings)
    click.echo(f"MCP server: disabled ({MCP_SERVER_NAME} removed, added to disabledMcpjsonServers)")

    # 4. Remove @import from CLAUDE.local.md
    md_path = _claude_local_md_path()
    if md_path.exists():
        lines = md_path.read_text(encoding="utf-8").splitlines(keepends=True)
        filtered = [line for line in lines if INSTRUCTIONS_IMPORT not in line]
        md_path.write_text("".join(filtered), encoding="utf-8")
    click.echo(f"Agent instructions: disabled (removed from {CLAUDE_LOCAL_MD})")
    click.echo("\nDone. Restart the daemon for changes to take effect.")


@pallium.command()
def status():
    """Show Pallium MCP integration status."""
    settings = _read_settings_local()
    enabled_servers = settings.get("enabledMcpjsonServers", [])
    disabled_servers = settings.get("disabledMcpjsonServers", [])
    permissions = settings.get("permissions", {}).get("allow", [])

    mcp_enabled = MCP_SERVER_NAME in enabled_servers and MCP_SERVER_NAME not in disabled_servers
    permission_set = MCP_PERMISSION in permissions

    md_path = _claude_local_md_path()
    instructions_enabled = False
    if md_path.exists():
        instructions_enabled = INSTRUCTIONS_IMPORT in md_path.read_text(encoding="utf-8")

    click.echo(f"MCP server:         {'enabled' if mcp_enabled else 'disabled'}")
    click.echo(f"Tool permission:    {'set' if permission_set else 'not set'}")
    click.echo(f"Agent instructions: {'enabled' if instructions_enabled else 'disabled'}")
```

- [ ] **Step 2: Register the pallium group in cli.py**

In `cli/cli.py`, add near the other `cli.add_command` calls (near the `sso`, `proxy` group registrations):

```python
from cli.pallium_setup import pallium
cli.add_command(pallium)
```

- [ ] **Step 3: Verify the commands work**

Run: `python -m cli pallium status`
Expected: All three items show `disabled` / `not set`.

Run: `python -m cli pallium enable`
Expected: All three items enabled. Check `.claude/settings.local.json` has `enabledMcpjsonServers` with `"pallium"`, `permissions.allow` with `"mcp__pallium"`, and `CLAUDE.local.md` has the import.

Run: `python -m cli pallium disable`
Expected: All three items disabled. Check `disabledMcpjsonServers` has `"pallium"`, permission removed, import removed.

- [ ] **Step 4: Commit**

```bash
git add cli/pallium_setup.py cli/cli.py
git commit -m "feat(pallium): add enable/disable CLI commands for MCP integration"
```

---

### Task 6: Update pelican.json with Project Dir

**Files:**
- Modify: `.claude/pelican.json` (or wherever the active config is)

- [ ] **Step 1: Add project_dir to pallium config**

In the active `pelican.json` configuration, add `project_dir` under the `pallium` section:

```json
{
    "pallium": {
        "enabled": true,
        "base_url": "http://127.0.0.1:8000",
        "query_limit": 3,
        "debug_trace": true,
        "project_dir": "/mnt/c/Dev/rore/Pallium"
    }
}
```

Adjust the path for the deployment environment (WSL path for local dev).

- [ ] **Step 2: Commit**

```bash
git add .claude/pelican.json
git commit -m "feat(pallium): add project_dir to pallium config"
```

---

### Task 7: Verification

- [ ] **Step 1: Enable Pallium MCP**

Run: `python -m cli pallium enable`
Expected: MCP enabled, permission set, instructions enabled.

- [ ] **Step 2: Verify settings.local.json**

Check `.claude/settings.local.json`:
- `enabledMcpjsonServers` contains `"pallium"`
- `disabledMcpjsonServers` does NOT contain `"pallium"`
- `permissions.allow` contains `"mcp__pallium"`

- [ ] **Step 3: Verify CLAUDE.local.md**

Check that `CLAUDE.local.md` contains the `@services/pelican/agent-config/instructions/pallium-memory.md` import line. Verify Claude Code loads it by checking if the instructions appear in context during a test session.

- [ ] **Step 4: Start daemon and send a test message**

Start the daemon with Pallium enabled. Send a message via local-chat. Verify in daemon logs:
- Static env vars were set at startup (PALLIUM_BASE_URL, PALLIUM_PROJECT_DIR)
- No MCP startup errors from Claude Code

- [ ] **Step 5: Verify MCP tools are available in Claude session**

In a Claude session, the three tools (`pallium_query`, `pallium_query_debug`, `pallium_ingest`) should appear. Ask Claude "what memory tools do you have?" — it should list them.

- [ ] **Step 6: Test disable**

Run: `python -m cli pallium disable`
Restart daemon, send message. Verify MCP tools are NOT available.

---

## Known Limitations (v1)

- **Container mode**: `PALLIUM_*` env vars may not propagate through `docker exec`. Container mode support is a follow-up.
- **Cloud deployments**: `entrypoint.sh` generates its own settings. Cloud activation needs `shared_brain.py` integration (follow-up).
- **Ref-building duplication**: The container_ref/thread_ref/visibility formulas in session_runner mirror `pallium_client.py`. If those formulas evolve (e.g., to use `channel_type` for visibility), both sites need updating. Accepted tradeoff for minimal blast radius.
- **`@import` syntax**: Claude Code's `@path` import in CLAUDE.local.md was confirmed in research but has no existing usage in this codebase. Verify during implementation.

---

## Summary

| Task | What | Existing files touched | Lines changed |
|------|------|----------------------|---------------|
| 1 | MCP declaration in mcp.json | `mcp.json` | +12 |
| 2 | Static env vars on daemon startup | `daemon.py`, `config.py` | +6 |
| 3 | Dynamic env vars per-message | `session_runner.py` | +12 |
| 4 | Agent instructions file | (new file) | — |
| 5 | Enable/disable CLI command | `cli.py` + (new file) | +2 |
| 6 | Config update | `pelican.json` | +1 |
| 7 | End-to-end verification | — | — |

**Total lines changed in existing files: ~32**
