"""Setup command for Codex integration.

Registers Pallium hooks + MCP server in Codex's config,
and appends agent instructions to global AGENTS.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
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

def _codex_relay_profile_path() -> Path:
    return Path.home() / ".codex" / "pallium-relay.config.toml"


def _codex_hooks_path() -> Path:
    return Path.home() / ".codex" / "hooks.json"


def _codex_agents_md_path() -> Path:
    return Path.home() / ".codex" / "AGENTS.md"


def _codex_skill_src() -> Path:
    """Source SKILL.md for the pallium-memory skill (in-repo)."""
    return (
        _pallium_repo_root()
        / "integrations"
        / "codex"
        / "skills"
        / "pallium-memory"
        / "SKILL.md"
    )


def _codex_skill_dir() -> Path:
    """User-level skill-discovery directory for the pallium-memory skill.

    ``pallium setup codex`` is the primary install path and does not install
    the Codex plugin (the plugin channel is experimental — see
    docs/codex-integration.md), so the plugin's declared ``skills`` dir is not
    deployed by this path. Copy the skill here so the guidance reference in
    AGENTS.md resolves on a plain ``setup codex`` install.
    """
    return Path.home() / ".codex" / "skills" / "pallium-memory"


def _install_skill() -> None:
    """Stage and atomically activate the complete Pallium-managed skill tree."""
    source_dir = _codex_skill_src().parent
    dest_dir = _codex_skill_dir()
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".pallium-memory-", dir=dest_dir.parent
    ) as temp_dir:
        staged = Path(temp_dir) / "skill"
        previous = Path(temp_dir) / "previous"
        shutil.copytree(source_dir, staged)
        if not (staged / "SKILL.md").is_file():
            raise FileNotFoundError("staged Pallium skill has no SKILL.md")
        if dest_dir.exists():
            dest_dir.rename(previous)
        try:
            staged.rename(dest_dir)
        except BaseException:
            if previous.exists():
                previous.rename(dest_dir)
            raise

def _remove_skill() -> None:
    """Remove the deployed pallium-memory skill directory (if present)."""
    skill_dir = _codex_skill_dir()
    if skill_dir.exists():
        shutil.rmtree(skill_dir, ignore_errors=True)


def _quote_hook_arg(value: str) -> str:
    if sys.platform == "win32":
        if any(c.isspace() or c in "'&|;<>()^`" for c in value):
            return f'"{value}"'
        return value
    return shlex.quote(value)


def _hook_command(script_name: str) -> str:
    python = _python_executable().replace("\\", "/")
    script = str(_hooks_dir() / script_name).replace("\\", "/")
    return f"{_quote_hook_arg(python)} {_quote_hook_arg(script)}"


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
    """Render process-wide MCP settings without pinning one project scope.

    Standard setup serves Codex tasks across projects. Hooks inject each task's
    trusted container scope into its turn for Relay callers to copy; an
    intentional hookless integration may configure PALLIUM_CONTAINER_REF.
    """
    values = {
        "PALLIUM_MCP_TRANSPORT": "stdio",
        "PALLIUM_BASE_URL": f"http://localhost:{port}",
        "PALLIUM_AGENT_REF": "codex",
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


def _features_section(content: str) -> re.Match[str] | None:
    return re.search(r"(?ms)^\[features\]\n.*?(?=^\[|\Z)", content)


def _ensure_feature_flag(content: str) -> str:
    """Migrate Pallium's legacy feature flag within Codex's features section."""
    section = _features_section(content)
    if section is None:
        if content and not content.endswith("\n"):
            content += "\n"
        return content + "\n[features]\nhooks = true\n"
    body = section.group()[len("[features]\n"):]
    body = re.sub(r"^codex_hooks\s*=\s*\w+\s*\n?", "", body, flags=re.MULTILINE)
    if re.search(r"^hooks\s*=", body, re.MULTILINE):
        body = re.sub(r"^hooks\s*=\s*\w+", "hooks = true", body, flags=re.MULTILINE)
    else:
        body = "hooks = true\n" + body
    return content[:section.start()] + "[features]\n" + body + content[section.end():]

def _ensure_mcp_server(content: str, port: int = 19836) -> str:
    """Ensure [mcp_servers.pallium] section exists in config.toml with correct port."""
    if "[mcp_servers.pallium]" in content:
        content = _remove_mcp_server(content)

    mcp_block = (
        '\n[mcp_servers.pallium]\n'
        f'command = "{_mcp_command()}"\n'
        'args = ["-m", "app.run", "mcp"]\n'
        f'env = {_mcp_env_toml(port)}\n'
        'required = true\n'
        'startup_timeout_sec = 10\n'
        'tool_timeout_sec = 30\n'
        'default_tools_approval_mode = "prompt"\n'
        'tools = { pallium_relay_send = { approval_mode = "approve" }, '
        'pallium_relay_reply = { approval_mode = "approve" }, '
        'pallium_relay_ack = { approval_mode = "approve" }, pallium_relay_receive = { approval_mode = "approve" } }\n'
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
    """Remove only Pallium's deprecated flag; modern hooks are shared state."""
    section = _features_section(content)
    if section is None:
        return content
    body = section.group()[len("[features]\n"):]
    body = re.sub(r"^codex_hooks\s*=\s*\w+\s*\n?", "", body, flags=re.MULTILINE)
    replacement = "[features]\n" + body if body.strip() else ""
    return content[:section.start()] + replacement + content[section.end():]

def _install_relay_profile() -> None:
    """Install Pallium's dedicated profile over the existing MCP server."""
    _write_toml(
        _codex_relay_profile_path(),
        "[mcp_servers.pallium]\n"
        "required = true\n"
        'enabled_tools = ["pallium_relay_send", "pallium_relay_reply", "pallium_relay_ack", "pallium_relay_receive"]\n'
        'default_tools_approval_mode = "prompt"\n'
        "\n[mcp_servers.pallium.tools.pallium_relay_send]\n"
        'approval_mode = "approve"\n'
        "\n[mcp_servers.pallium.tools.pallium_relay_reply]\n"
        'approval_mode = "approve"\n'
        "\n[mcp_servers.pallium.tools.pallium_relay_ack]\n"
        'approval_mode = "approve"\n'
        "\n[mcp_servers.pallium.tools.pallium_relay_receive]\n"
        'approval_mode = "approve"\n',
    )


def _remove_relay_profile() -> None:
    _codex_relay_profile_path().unlink(missing_ok=True)

# -- Hooks JSON --


def _read_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8-sig"))
    return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _managed_hook_script(hook: object) -> str | None:
    """Return the Pallium script owned by a direct Python hook command."""
    if not isinstance(hook, dict) or hook.get("type") != "command":
        return None
    command = hook.get("command")
    if not isinstance(command, str) or "\r" in command or "\n" in command:
        return None
    try:
        lexer = shlex.shlex(
            command.replace("\\", "/"),
            posix=True,
            punctuation_chars="&|;<>()^`",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        parts = list(lexer)
    except ValueError:
        return None
    if len(parts) != 2:
        return None

    python, script = parts
    python_name = python.rsplit("/", 1)[-1]
    if "/" in python and not re.match(r"^(?:[A-Za-z]:/|/)", python):
        return None
    if not re.fullmatch(
        r"python(?:w)?(?:\d+(?:\.\d+)*)?(?:\.exe)?",
        python_name,
        flags=re.IGNORECASE,
    ):
        return None
    if not re.match(r"^(?:[A-Za-z]:/|/)", script):
        return None

    normalized_script = script.casefold()
    for script_name in ("session_start.py", "user_prompt_submit.py", "stop.py"):
        suffix = f"/integrations/codex/hooks/{script_name}"
        if normalized_script.endswith(suffix):
            return script_name
    return None


def _without_managed_hooks(entries: list) -> list:
    """Remove Pallium hook objects while preserving peer wrappers and order."""
    cleaned: list = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
            cleaned.append(entry)
            continue
        hooks = entry["hooks"]
        remaining = [hook for hook in hooks if _managed_hook_script(hook) is None]
        if len(remaining) == len(hooks):
            cleaned.append(entry)
        elif remaining:
            updated = dict(entry)
            updated["hooks"] = remaining
            cleaned.append(updated)
    return cleaned


def _register_hooks(hooks_data: dict) -> dict:
    """Reconcile Pallium hooks in Codex hooks.json across checkout paths."""
    hooks_by_event = hooks_data.setdefault("hooks", {})
    hook_defs = [
        ("SessionStart", "session_start.py", 8, "Loading memory", "startup|resume"),
        ("UserPromptSubmit", "user_prompt_submit.py", 8, "Retrieving memory", None),
        ("Stop", "stop.py", 15, None, None),
    ]
    expected_events = {event for event, *_ in hook_defs}

    for event in list(hooks_by_event):
        if event not in expected_events:
            cleaned = _without_managed_hooks(hooks_by_event[event])
            if cleaned:
                hooks_by_event[event] = cleaned
            else:
                del hooks_by_event[event]

    for event, script, timeout, status_msg, matcher in hook_defs:
        desired_hook: dict = {
            "type": "command",
            "command": _hook_command(script),
            "timeout": timeout,
        }
        if status_msg:
            desired_hook["statusMessage"] = status_msg

        current_kept = False
        reconciled: list = []
        for entry in hooks_by_event.get(event, []):
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                reconciled.append(entry)
                continue
            entry_matcher = entry.get("matcher")
            matcher_matches = (
                entry_matcher == matcher
                if matcher is not None
                else "matcher" not in entry
            )
            original_hooks = entry["hooks"]
            remaining: list = []
            for hook in original_hooks:
                managed_script = _managed_hook_script(hook)
                if managed_script is None:
                    remaining.append(hook)
                elif (
                    not current_kept
                    and managed_script == script
                    and hook == desired_hook
                    and matcher_matches
                ):
                    remaining.append(hook)
                    current_kept = True

            if len(remaining) == len(original_hooks):
                reconciled.append(entry)
            elif remaining:
                updated = dict(entry)
                updated["hooks"] = remaining
                reconciled.append(updated)

        if not current_kept:
            wrapper: dict = {"hooks": [desired_hook]}
            if matcher is not None:
                wrapper["matcher"] = matcher
            reconciled.append(wrapper)
        hooks_by_event[event] = reconciled

    return hooks_data


def _unregister_hooks(hooks_data: dict) -> dict:
    """Remove Pallium hooks from Codex hooks.json across checkout paths."""
    if "hooks" not in hooks_data:
        return hooks_data

    for event in list(hooks_data["hooks"]):
        cleaned = _without_managed_hooks(hooks_data["hooks"][event])
        if cleaned:
            hooks_data["hooks"][event] = cleaned
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


# Appended to the base AGENTS.md block for the "strong" guidance-strength arm.
# Authored to avoid the token "MANDATORY" and the banned legacy strings so the
# Codex block invariants still hold on the strong variant.
_STRONG_DIRECTIVE = (
    "\n## Resuming prior work\n\n"
    "When you resume or continue prior work on this task, call\n"
    "`pallium_search_history_by_work_ref` first when a valid structural work ref\n"
    "is known; otherwise call `pallium_search_history` before assuming that earlier context is\n"
    "gone. Pull the raw prior turns (a past discussion, an earlier attempt, the\n"
    "original context of a decision) and read them before acting, rather than\n"
    "starting cold.\n\n"
)


#: Deprecated guidance-strength aliases -> canonical arm. ``tool-only`` was a
#: misnomer: the base block already carries a block-level permit nudge, so the
#: arm is not "tool description only". Kept as a non-breaking alias.
_GUIDANCE_STRENGTH_ALIASES = {"tool-only": "base"}
_GUIDANCE_STRENGTH_CHOICES = ["base", "strong", "tool-only"]


def _normalize_guidance_strength(strength: str) -> str:
    """Map a deprecated guidance-strength alias to its canonical arm.

    Prints a one-line deprecation note when an alias is used so existing
    scripts passing ``tool-only`` keep working (they now install the ``base``
    arm) while surfacing the rename.
    """
    canonical = _GUIDANCE_STRENGTH_ALIASES.get(strength)
    if canonical is not None:
        print(
            f"  NOTE: --guidance-strength '{strength}' is deprecated; "
            f"using '{canonical}' (both arms carry a block-level permit nudge)."
        )
        return canonical
    return strength


def _build_agents_md_block(strength: str = "base") -> str:
    """Return the AGENTS.md block variant for the given guidance strength.

    - ``"base"`` (default): the block as-is. It already carries a block-level
      permit nudge; it is NOT a zero-guidance baseline.
    - ``"strong"``: the base block plus an appended "call it first" resume
      directive. The measured contrast is *permit-nudge* vs *permit-nudge +
      call-first*, not presence-vs-absence of guidance.

    An arm-marker comment recording the chosen arm is embedded inside the
    marker-bounded block so an operator can read which arm was installed.
    """
    if strength not in ("base", "strong"):
        raise ValueError(f"unknown guidance strength: {strength!r}")

    block = _get_agents_md_block()
    arm_marker = f"<!-- pallium:guidance-strength={strength} -->"
    block = block.replace(
        "<!-- pallium:start -->\n",
        f"<!-- pallium:start -->\n{arm_marker}\n",
        1,
    )
    if strength == "strong":
        block = block.replace(
            "<!-- pallium:end -->",
            _STRONG_DIRECTIVE + "<!-- pallium:end -->",
            1,
        )
    return block


def _append_agents_md_block(strength: str = "base") -> None:
    path = _codex_agents_md_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")

    block = _build_agents_md_block(strength)
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


def install(port: int = 19836, guidance_strength: str = "base") -> int:
    print(f"Setting up Pallium Codex integration (port {port})...")

    # 1. Feature flag + MCP in config.toml
    config_path = _codex_config_path()
    config_content = _read_toml(config_path)
    config_content = _ensure_feature_flag(config_content)
    config_content = _ensure_mcp_server(config_content, port=port)
    _write_toml(config_path, config_content)
    _install_relay_profile()
    print(f"  Configured feature flags and MCP server in {config_path}")

    # 2. Register hooks in hooks.json
    hooks_path = _codex_hooks_path()
    hooks_data = _read_json(hooks_path)
    hooks_before = json.dumps(hooks_data, sort_keys=True)
    hooks_data = _register_hooks(hooks_data)
    hooks_changed = json.dumps(hooks_data, sort_keys=True) != hooks_before
    if hooks_changed:
        _write_json(hooks_path, hooks_data)
        print(f"  Registered hooks in {hooks_path}")
    else:
        print(f"  Hooks already current in {hooks_path}")

    # 3. Append AGENTS.md block
    _append_agents_md_block(guidance_strength)
    print(f"  Appended Pallium instructions to {_codex_agents_md_path()}")
    print(f"  Guidance-strength arm: {guidance_strength}")

    # 3b. Deploy the pallium-memory skill referenced by the guidance block
    _install_skill()
    print(f"  Installed pallium-memory skill to {_codex_skill_dir()}")

    # 4. Create hook state directory
    _ensure_state_dir()
    print("  Created hook state directory")

    # 5. Verify service
    if _verify_service(port):
        print(f"  Pallium service verified at port {port}")
    else:
        print(f"  WARNING: Pallium service not reachable at port {port}")
        print(f"  Start it with: python -m app.run all --port {port}")

    print("\nConfiguration installed.")
    print("Restart Codex to load this configuration.")
    if hooks_changed:
        print("Hook configuration changed. Approve the Pallium hook review if prompted.")
        print("Relay wake is ready only after that review.")
    else:
        print("Hook configuration is unchanged; no new hook review should be required.")
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
    _remove_relay_profile()

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

    # Remove the deployed pallium-memory skill
    _remove_skill()
    print(f"  Removed pallium-memory skill from {_codex_skill_dir()}")

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
    parser.add_argument(
        "--guidance-strength",
        choices=_GUIDANCE_STRENGTH_CHOICES,
        default="base",
        help=(
            "Which memory-guidance block variant to install: 'base' "
            "(block-level permit nudge, default) or 'strong' (base plus a "
            "'call it first' resume directive). Both arms carry a permit "
            "nudge — the contrast is call-first, not guidance presence. "
            "'tool-only' is a deprecated alias for 'base'. Records the arm in "
            "setup output and inside the installed block."
        ),
    )
    parsed = parser.parse_args(args)

    if parsed.uninstall:
        return uninstall()
    guidance_strength = _normalize_guidance_strength(parsed.guidance_strength)
    return install(port=parsed.port, guidance_strength=guidance_strength)
