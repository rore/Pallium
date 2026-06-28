"""Setup command for Codex integration.

Registers Pallium hooks + MCP server in Codex's config,
and appends agent instructions to global AGENTS.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
    return _pallium_repo_root() / "integrations" / "codex" / "hooks"


def _codex_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def _codex_hooks_path() -> Path:
    return Path.home() / ".codex" / "hooks.json"


def _codex_agents_md_path() -> Path:
    return Path.home() / ".codex" / "AGENTS.md"


def _hook_command(script_name: str) -> str:
    python = _python_executable().replace("\\", "/")
    script = str(_hooks_dir() / script_name).replace("\\", "/")
    return f"{python} {script}"


def _mcp_command() -> str:
    return _python_executable().replace("\\", "/")


def _path_for_env(path: Path) -> str:
    return str(path).replace("\\", "/")


def _mcp_pythonpath_entries() -> list[str]:
    """Paths needed when Codex launches MCP via `python -m app.run mcp`."""
    entries: list[Path] = [_pallium_repo_root()]

    local_site = _pallium_repo_root() / ".local" / "test-env" / "site-packages"
    if local_site.exists():
        entries.append(local_site)

    for parent in Path(sys.executable).resolve().parents:
        candidate = parent / "pallium-venv" / "Lib" / "site-packages"
        if candidate.exists():
            entries.append(candidate)
            win32 = candidate / "win32"
            win32_lib = win32 / "lib"
            if win32.exists():
                entries.append(win32)
            if win32_lib.exists():
                entries.append(win32_lib)
            break

    existing = os.environ.get("PYTHONPATH")
    if existing:
        for part in existing.split(os.pathsep):
            if part:
                entries.append(Path(part))

    out: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        text = _path_for_env(entry)
        key = text.lower() if sys.platform == "win32" else text
        if key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _mcp_path_entries() -> list[str]:
    entries: list[str] = []
    for py_path in _mcp_pythonpath_entries():
        pywin32 = Path(py_path) / "pywin32_system32"
        if pywin32.exists():
            entries.append(_path_for_env(pywin32))
    return entries


def _toml_inline_string(value: str) -> str:
    return json.dumps(value)


def _mcp_env_toml(port: int) -> str:
    values = {
        "PALLIUM_MCP_TRANSPORT": "stdio",
        "PALLIUM_BASE_URL": f"http://localhost:{port}",
        "PYTHONPATH": os.pathsep.join(_mcp_pythonpath_entries()),
    }
    path_value = os.pathsep.join(_mcp_path_entries())
    if path_value:
        values["PATH"] = path_value
    pairs = [
        f"{key} = {_toml_inline_string(value)}"
        for key, value in values.items()
    ]
    return "{ " + ", ".join(pairs) + " }"


# -- TOML helpers (minimal, stdlib-only) --


def _read_toml(path: Path) -> str:
    """Read TOML file as raw text. Returns empty string if not exists."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _write_toml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _ensure_feature_flag(content: str) -> str:
    """Ensure [features] section has codex_hooks = true."""
    if re.search(r'^codex_hooks\s*=', content, re.MULTILINE):
        content = re.sub(
            r"^codex_hooks\s*=\s*\w+",
            "codex_hooks = true",
            content,
            flags=re.MULTILINE,
        )
        return content

    # Need to add it
    if re.search(r'^\[features\]', content, re.MULTILINE):
        # Append under existing [features] section
        content = re.sub(
            r'^(\[features\])',
            r'\1\ncodex_hooks = true',
            content,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        # Add new section
        if content and not content.endswith("\n"):
            content += "\n"
        content += "\n[features]\ncodex_hooks = true\n"
    return content


def _ensure_mcp_server(content: str, port: int = 19836) -> str:
    """Ensure [mcp_servers.pallium] section exists in config.toml with correct port."""
    if "[mcp_servers.pallium]" in content:
        content = _remove_mcp_server(content)

    mcp_block = (
        '\n[mcp_servers.pallium]\n'
        f'command = "{_mcp_command()}"\n'
        'args = ["-m", "app.run", "mcp"]\n'
        f'env = {_mcp_env_toml(port)}\n'
        'startup_timeout_sec = 10\n'
        'tool_timeout_sec = 30\n'
    )

    if content and not content.endswith("\n"):
        content += "\n"
    content += mcp_block
    return content


def _remove_mcp_server(content: str) -> str:
    """Remove [mcp_servers.pallium] section from config.toml."""
    # Match section header + all subsequent lines that don't start a new section
    pattern = r'\n?\[mcp_servers\.pallium\]\n(?:(?!\n?\[)[^\n]*\n?)*'
    content = re.sub(pattern, '', content)
    return content


def _remove_feature_flag(content: str) -> str:
    """Remove codex_hooks line from [features] section."""
    content = re.sub(r'\n?codex_hooks\s*=\s*\w+', '', content)
    # Clean up empty [features] section
    content = re.sub(r'\n?\[features\]\s*\n(?=\[|\Z)', '\n', content)
    content = re.sub(r'\n?\[features\]\s*$', '', content)
    return content


# -- Hooks JSON --


def _read_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8-sig"))
    return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _register_hooks(hooks_data: dict) -> dict:
    """Register Pallium hooks in Codex hooks.json."""
    if "hooks" not in hooks_data:
        hooks_data["hooks"] = {}

    hook_defs = [
        ("SessionStart", "session_start.py", 8, "Loading memory"),
        ("UserPromptSubmit", "user_prompt_submit.py", 8, "Retrieving memory"),
        ("Stop", "stop.py", 15, None),
    ]

    for event, script, timeout, status_msg in hook_defs:
        if event not in hooks_data["hooks"]:
            hooks_data["hooks"][event] = []

        existing = hooks_data["hooks"][event]
        command = _hook_command(script)

        already_registered = any(
            any(command in h.get("command", "") for h in entry.get("hooks", []))
            for entry in existing
            if isinstance(entry, dict)
        )
        if not already_registered:
            hook_entry: dict = {
                "type": "command",
                "command": command,
                "timeout": timeout,
            }
            if status_msg:
                hook_entry["statusMessage"] = status_msg

            entry_wrapper: dict = {
                "hooks": [hook_entry],
            }
            # SessionStart needs a matcher
            if event == "SessionStart":
                entry_wrapper["matcher"] = "startup|resume"

            existing.append(entry_wrapper)

    return hooks_data


def _unregister_hooks(hooks_data: dict) -> dict:
    """Remove Pallium hooks from Codex hooks.json."""
    hooks_dir_normalized = str(_hooks_dir()).replace("\\", "/")
    if "hooks" not in hooks_data:
        return hooks_data

    for event in list(hooks_data["hooks"].keys()):
        entries = hooks_data["hooks"][event]
        filtered = [
            entry for entry in entries
            if not any(
                hooks_dir_normalized in h.get("command", "").replace("\\", "/")
                for h in entry.get("hooks", [])
            )
        ]
        if filtered:
            hooks_data["hooks"][event] = filtered
        else:
            del hooks_data["hooks"][event]

    if not hooks_data["hooks"]:
        del hooks_data["hooks"]
    return hooks_data


# -- AGENTS.md --


def _get_agents_md_block() -> str:
    """Read the AGENTS.md block from the integration directory."""
    block_path = _pallium_repo_root() / "integrations" / "codex" / "AGENTS.md"
    return block_path.read_text(encoding="utf-8")


def _append_agents_md_block() -> None:
    path = _codex_agents_md_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")

    block = _get_agents_md_block()
    if "<!-- pallium:start -->" in existing:
        path.write_text(_replace_agents_md_block(existing, block), encoding="utf-8")
        return

    separator = "\n\n" if existing.strip() else ""
    path.write_text(existing + separator + block, encoding="utf-8")


def _replace_agents_md_block(content: str, block: str) -> str:
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


def _remove_agents_md_block() -> None:
    path = _codex_agents_md_path()
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


# -- State dir + service verification --


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


# -- Main install/uninstall --


def install(port: int = 19836) -> int:
    print(f"Setting up Pallium Codex integration (port {port})...")

    # 1. Feature flag + MCP in config.toml
    config_path = _codex_config_path()
    config_content = _read_toml(config_path)
    config_content = _ensure_feature_flag(config_content)
    config_content = _ensure_mcp_server(config_content, port=port)
    _write_toml(config_path, config_content)
    print(f"  Configured feature flags and MCP server in {config_path}")

    # 2. Register hooks in hooks.json
    hooks_path = _codex_hooks_path()
    hooks_data = _read_json(hooks_path)
    hooks_data = _unregister_hooks(hooks_data)
    hooks_data = _register_hooks(hooks_data)
    _write_json(hooks_path, hooks_data)
    print(f"  Registered hooks in {hooks_path}")

    # 3. Append AGENTS.md block
    _append_agents_md_block()
    print(f"  Appended Pallium instructions to {_codex_agents_md_path()}")

    # 4. Create hook state directory
    _ensure_state_dir()
    print("  Created hook state directory")

    # 5. Verify service
    if _verify_service(port):
        print(f"  Pallium service verified at port {port}")
    else:
        print(f"  WARNING: Pallium service not reachable at port {port}")
        print(f"  Start it with: python -m app.run all --port {port}")

    print("\nDone. Pallium is now integrated with Codex.")
    return 0


def uninstall() -> int:
    print("Removing Pallium Codex integration...")

    # Remove MCP + feature flag from config.toml
    config_path = _codex_config_path()
    if config_path.exists():
        config_content = _read_toml(config_path)
        config_content = _remove_mcp_server(config_content)
        config_content = _remove_feature_flag(config_content)
        _write_toml(config_path, config_content)
        print(f"  Removed MCP server and feature flags from {config_path}")

    # Remove hooks from hooks.json
    hooks_path = _codex_hooks_path()
    if hooks_path.exists():
        hooks_data = _read_json(hooks_path)
        hooks_data = _unregister_hooks(hooks_data)
        _write_json(hooks_path, hooks_data)
        print(f"  Removed hooks from {hooks_path}")

    # Remove AGENTS.md block
    _remove_agents_md_block()
    print(f"  Removed Pallium instructions from {_codex_agents_md_path()}")

    # Clean hook state directory
    state_dir = Path.home() / ".pallium" / "hooks" / "state"
    if state_dir.exists():
        import shutil
        shutil.rmtree(state_dir, ignore_errors=True)
        print("  Removed hook state directory")

    print("\nDone. Pallium integration removed.")
    return 0


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Setup Pallium Codex integration")
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
