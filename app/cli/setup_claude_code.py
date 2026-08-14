"""Setup command for Claude Code integration.

Registers Pallium hooks + MCP server in Claude Code's settings,
and appends agent instructions to global CLAUDE.md.
"""

from __future__ import annotations

import argparse
import json
import subprocess
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


def _claude_skill_src() -> Path:
    """Source SKILL.md for the pallium-memory skill (in-repo)."""
    return (
        _pallium_repo_root()
        / "integrations"
        / "claude-code"
        / "skills"
        / "pallium-memory"
        / "SKILL.md"
    )


def _claude_skill_dir() -> Path:
    """User-level skill-discovery directory for the pallium-memory skill."""
    return Path.home() / ".claude" / "skills" / "pallium-memory"


def _install_skill() -> None:
    """Copy the pallium-memory SKILL.md into Claude's skill-discovery dir.

    Idempotent: overwrites on reinstall so the deployed guidance always
    matches the shipped skill.
    """
    dest_dir = _claude_skill_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "SKILL.md").write_text(
        _claude_skill_src().read_text(encoding="utf-8"), encoding="utf-8"
    )


def _remove_skill() -> None:
    """Remove the deployed pallium-memory skill directory (if present)."""
    skill_dir = _claude_skill_dir()
    if skill_dir.exists():
        import shutil

        shutil.rmtree(skill_dir, ignore_errors=True)


def _read_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _hook_command(script_name: str) -> str:
    python = _python_executable().replace("\\", "/")
    script = str(_hooks_dir() / script_name).replace("\\", "/")
    return f"{python} {script}"


def _register_mcp(port: int) -> None:
    subprocess.run(["claude", "mcp", "remove", "--scope", "user", "pallium"], check=False)
    subprocess.run(
        ["claude", "mcp", "add", "--transport", "http", "--scope", "user", "pallium", f"http://127.0.0.1:{port}/mcp"],
        check=True,
    )


def _unregister_mcp() -> None:
    subprocess.run(["claude", "mcp", "remove", "--scope", "user", "pallium"], check=False)


def _register_hooks(settings: dict) -> dict:
    if "hooks" not in settings:
        settings["hooks"] = {}

    hook_defs = [
        ("SessionStart", "session_start.py", 8),
        ("UserPromptSubmit", "user_prompt_submit.py", 8),
        ("Stop", "stop.py", 15),
        ("PreCompact", "pre_compact.py", 8),
        # Phase 4 (2026-06-27): deterministic on-demand triggers for
        # investigation_outcome (failure + retry-threshold). See
        # docs/specs/2026-06-27-injection-policy-abstention.md.
        ("PostToolUse", "post_tool_use.py", 8),
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


def _unregister_hooks(settings: dict) -> dict:
    hooks_dir_normalized = str(_hooks_dir()).replace("\\", "/")
    if "hooks" not in settings:
        return settings

    for event in list(settings["hooks"].keys()):
        entries = settings["hooks"][event]
        filtered = [
            entry for entry in entries
            if not any(
                hooks_dir_normalized in h.get("command", "").replace("\\", "/")
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


def _get_claude_md_block(strength: str = "tool-only") -> str:
    block_file = _pallium_repo_root() / "integrations" / "claude-code" / "claude_md_block.py"
    ns: dict = {}
    exec(compile(block_file.read_text(encoding="utf-8"), block_file, "exec"), ns)
    return ns["get_claude_md_block"](strength)


def _replace_claude_md_block(content: str, block: str) -> str:
    """Replace the marker-bounded Pallium block in ``content`` with ``block``.

    Appends the block if no existing markers are found. Mirrors the Codex
    replace behaviour so re-installing with a different --guidance-strength
    rewrites the block instead of silently no-op'ing.
    """
    start_marker = "<!-- pallium:start -->"
    end_marker = "<!-- pallium:end -->"

    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)
    if start_idx == -1 or end_idx == -1:
        separator = "\n\n" if content.strip() else ""
        return content + separator + block

    end_idx += len(end_marker)
    before = content[:start_idx].rstrip("\n")
    after = content[end_idx:].lstrip("\n")
    separator_before = "\n\n" if before else ""
    separator_after = "\n\n" if after else ""
    return before + separator_before + block + separator_after + after


def _append_claude_md_block(strength: str = "tool-only") -> None:
    block = _get_claude_md_block(strength)

    path = _claude_md_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")

    if "<!-- pallium:start -->" in existing:
        path.write_text(_replace_claude_md_block(existing, block), encoding="utf-8")
        return

    separator = "\n\n" if existing.strip() else ""
    path.write_text(existing + separator + block, encoding="utf-8")


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
            if resp.status != 200:
                return False
            try:
                status_data = json.loads(resp.read())
                funnel = status_data.get("historical_lookup_funnel")
                if isinstance(funnel, dict):
                    armed = "armed" if funnel.get("armed") else "not armed"
                    print(f"  Historical-lookup reuse funnel: {armed}")
            except Exception:
                pass
            return True
    except Exception:
        return False


def install(port: int = 19836, guidance_strength: str = "tool-only") -> int:
    print(f"Setting up Pallium Claude Code integration (port {port})...")

    _register_mcp(port)
    print(f"  Registered MCP server (user scope)")

    settings_path = _claude_settings_path()
    settings = _read_json(settings_path)
    settings = _register_hooks(settings)
    _write_json(settings_path, settings)
    print(f"  Registered hooks in {settings_path}")

    _append_claude_md_block(guidance_strength)
    print(f"  Appended Pallium instructions to {_claude_md_path()}")
    print(f"  Guidance-strength arm: {guidance_strength}")

    _install_skill()
    print(f"  Installed pallium-memory skill to {_claude_skill_dir()}")

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

    _unregister_mcp()
    print("  Removed MCP server")

    settings_path = _claude_settings_path()
    settings = _read_json(settings_path)
    settings = _unregister_hooks(settings)
    _write_json(settings_path, settings)
    print(f"  Removed hooks from {settings_path}")

    _remove_claude_md_block()
    print(f"  Removed Pallium instructions from {_claude_md_path()}")

    _remove_skill()
    print(f"  Removed pallium-memory skill from {_claude_skill_dir()}")

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
    parser.add_argument(
        "--guidance-strength",
        choices=["tool-only", "strong"],
        default="tool-only",
        help=(
            "Which memory-guidance block variant to install: 'tool-only' "
            "(neutral permit, default) or 'strong' (adds a resume directive). "
            "Records the arm in setup output and inside the installed block."
        ),
    )
    parsed = parser.parse_args(args)

    if parsed.uninstall:
        return uninstall()
    return install(port=parsed.port, guidance_strength=parsed.guidance_strength)
