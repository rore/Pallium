"""Setup command for Claude Code integration.

Registers Pallium hooks + MCP server in Claude Code's settings,
and appends agent instructions to global CLAUDE.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _pallium_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains app/run.py)."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "app" / "run.py").exists():
            return current
        current = current.parent
    return Path(__file__).resolve().parent.parent.parent


def _python_executable() -> str:
    return sys.executable


def _hooks_dir() -> Path:
    return _pallium_repo_root() / "integrations" / "claude-code" / "hooks"


def _claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _claude_md_path() -> Path:
    return Path.home() / ".claude" / "CLAUDE.md"


def _read_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _hook_command(script_name: str) -> str:
    python = _python_executable()
    script = _hooks_dir() / script_name
    return f"{python} {script}"


def _register_mcp(settings: dict, port: int) -> dict:
    if "mcpServers" not in settings:
        settings["mcpServers"] = {}
    settings["mcpServers"]["pallium"] = {
        "url": f"http://localhost:{port}/mcp"
    }
    return settings


def _register_hooks(settings: dict) -> dict:
    if "hooks" not in settings:
        settings["hooks"] = {}

    hook_defs = [
        ("SessionStart", "session_start.py", 8),
        ("UserPromptSubmit", "user_prompt_submit.py", 8),
        ("Stop", "stop.py", 15),
        ("PreCompact", "pre_compact.py", 8),
    ]

    for event, script, timeout in hook_defs:
        if event not in settings["hooks"]:
            settings["hooks"][event] = []

        existing = settings["hooks"][event]
        command = _hook_command(script)

        already_registered = any(
            any(command in h.get("command", "") for h in entry.get("hooks", []))
            for entry in existing
            if isinstance(entry, dict)
        )
        if not already_registered:
            existing.append({
                "matcher": "",
                "hooks": [{"type": "command", "command": command, "timeout": timeout}],
            })

    return settings


def _unregister_mcp(settings: dict) -> dict:
    if "mcpServers" in settings:
        settings["mcpServers"].pop("pallium", None)
        if not settings["mcpServers"]:
            del settings["mcpServers"]
    return settings


def _unregister_hooks(settings: dict) -> dict:
    hooks_dir_str = str(_hooks_dir())
    if "hooks" not in settings:
        return settings

    for event in list(settings["hooks"].keys()):
        entries = settings["hooks"][event]
        filtered = [
            entry for entry in entries
            if not any(
                hooks_dir_str in h.get("command", "")
                for h in entry.get("hooks", [])
            )
        ]
        if filtered:
            settings["hooks"][event] = filtered
        else:
            del settings["hooks"][event]

    if not settings["hooks"]:
        del settings["hooks"]
    return settings


def _get_claude_md_block() -> str:
    block_file = _pallium_repo_root() / "integrations" / "claude-code" / "claude_md_block.py"
    ns: dict = {}
    exec(compile(block_file.read_text(encoding="utf-8"), block_file, "exec"), ns)
    return ns["CLAUDE_MD_BLOCK"]


def _append_claude_md_block() -> None:
    CLAUDE_MD_BLOCK = _get_claude_md_block()

    path = _claude_md_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")

    if "<!-- pallium:start -->" in existing:
        return

    separator = "\n\n" if existing.strip() else ""
    path.write_text(existing + separator + CLAUDE_MD_BLOCK, encoding="utf-8")


def _remove_claude_md_block() -> None:
    path = _claude_md_path()
    if not path.exists():
        return

    content = path.read_text(encoding="utf-8")
    start_marker = "<!-- pallium:start -->"
    end_marker = "<!-- pallium:end -->"

    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)
    if start_idx == -1 or end_idx == -1:
        return

    end_idx += len(end_marker)
    before = content[:start_idx].rstrip("\n")
    after = content[end_idx:].lstrip("\n")
    separator = "\n\n" if before and after else ""
    path.write_text(before + separator + after, encoding="utf-8")


def _ensure_state_dir() -> None:
    state_dir = Path.home() / ".pallium" / "hooks" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)


def _verify_service(port: int) -> bool:
    url = f"http://localhost:{port}/status"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def install(port: int = 19836) -> int:
    print(f"Setting up Pallium Claude Code integration (port {port})...")

    settings_path = _claude_settings_path()
    settings = _read_json(settings_path)

    settings = _register_mcp(settings, port)
    settings = _register_hooks(settings)
    _write_json(settings_path, settings)
    print(f"  Registered MCP server and hooks in {settings_path}")

    _append_claude_md_block()
    print(f"  Appended Pallium instructions to {_claude_md_path()}")

    _ensure_state_dir()
    print("  Created hook state directory")

    if _verify_service(port):
        print(f"  Pallium service verified at port {port}")
    else:
        print(f"  WARNING: Pallium service not reachable at port {port}")
        print(f"  Start it with: python -m app.run all --port {port}")

    print("\nDone. Pallium is now integrated with Claude Code.")
    return 0


def uninstall() -> int:
    print("Removing Pallium Claude Code integration...")

    settings_path = _claude_settings_path()
    settings = _read_json(settings_path)

    settings = _unregister_mcp(settings)
    settings = _unregister_hooks(settings)
    _write_json(settings_path, settings)
    print(f"  Removed MCP server and hooks from {settings_path}")

    _remove_claude_md_block()
    print(f"  Removed Pallium instructions from {_claude_md_path()}")

    state_dir = Path.home() / ".pallium" / "hooks" / "state"
    if state_dir.exists():
        import shutil
        shutil.rmtree(state_dir, ignore_errors=True)
        print("  Removed hook state directory")

    print("\nDone. Pallium integration removed.")
    return 0


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Setup Pallium integration")
    parser.add_argument(
        "target",
        choices=["claude-code"],
        help="Integration target",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the integration",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=19836,
        help="Pallium service port (default: 19836)",
    )
    parsed = parser.parse_args(args)

    if parsed.uninstall:
        return uninstall()
    return install(port=parsed.port)
