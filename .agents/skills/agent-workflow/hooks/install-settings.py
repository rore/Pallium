#!/usr/bin/env python3
"""Merge agent-workflow hooks into Claude Code or Codex project settings.

The installer owns only exact agent-workflow command registrations. It preserves
third-party hooks, rejects malformed JSON without writing, and is idempotent.
Claude also receives the supplemental plan gate sidecar; Codex receives portable
Unix and Windows commands and still requires project-hook trust.

Usage:
    python install-settings.py --runtime claude|codex [--settings PATH]
"""
import argparse
import base64
import json
import os
import sys

def _codex_windows_command(action):
    script = (
        "& (Join-Path (git rev-parse --show-toplevel) "
        "'scripts/agent-workflow-runtime.ps1') codex " + action
        + "; exit $LASTEXITCODE"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return (
        "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass "
        "-EncodedCommand " + encoded
    )


# event -> (matcher or None, command, optional Windows command)
_RUNTIME_HOOKS = {
    "claude": [
        ("UserPromptSubmit", None, 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/seed-workflow.sh"', None),
        ("PreToolUse", "ExitPlanMode", 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/check-plan.sh"', None),
        ("PostToolUse", "ExitPlanMode", 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/reinforce-workflow.sh"', None),
        (
            "PreToolUse",
            "Write|Edit|MultiEdit|NotebookEdit|apply_patch",
            'bash "$CLAUDE_PROJECT_DIR/scripts/agent-workflow-runtime.sh" claude guard',
            None,
        ),
    ],
    "codex": [
        (
            "UserPromptSubmit",
            None,
            'bash "$(git rev-parse --show-toplevel)/scripts/agent-workflow-runtime.sh" codex seed',
            _codex_windows_command("seed"),
        ),
        (
            "PreToolUse",
            "Edit|Write|apply_patch",
            'bash "$(git rev-parse --show-toplevel)/scripts/agent-workflow-runtime.sh" codex guard',
            _codex_windows_command("guard"),
        ),
    ],
}


def _existing_command(event_groups, command):
    for group in event_groups:
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks", []) or []:
            if isinstance(hook, dict) and hook.get("command") == command:
                return hook
    return None


def _atomic_write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)  # atomic
    except Exception:
        # Don't leave a stale partial .tmp behind (e.g. if os.replace raises
        # on a cross-device rename or a locked destination on Windows).
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write_guarded_paths_sidecar(settings_path):
    """Resolve hooks.guardedPaths from the repo's agent-workflow.yaml and write
    the gate's sidecar (.claude/hooks/guarded-paths.json).

    Degrades gracefully and NEVER raises: on any problem (no yaml, no pyyaml,
    key absent/empty/malformed) it leaves no sidecar and prints a note — the
    gate then falls back to its built-in ["src/"] default.
    """
    try:
        claude_dir = os.path.dirname(os.path.abspath(settings_path))  # .../.claude
        repo_root = os.path.dirname(claude_dir)                       # parent of .claude
        hooks_dir = os.path.join(claude_dir, "hooks")
        sidecar = os.path.join(hooks_dir, "guarded-paths.json")
        yaml_path = os.path.join(repo_root, "agent-workflow.yaml")

        if not os.path.isfile(yaml_path):
            print("note: no agent-workflow.yaml at %s; gate will default guarded paths to ['src/']." % yaml_path)
            return

        try:
            import yaml  # pyyaml — present at bootstrap/install time
        except Exception:
            print("note: pyyaml unavailable; gate will default guarded paths to ['src/'].")
            return

        try:
            with open(yaml_path, encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh)
        except Exception as exc:
            print("note: could not parse %s (%s); gate will default guarded paths to ['src/']." % (yaml_path, exc))
            return

        hooks_cfg = cfg.get("hooks") if isinstance(cfg, dict) else None
        raw = hooks_cfg.get("guardedPaths") if isinstance(hooks_cfg, dict) else None
        if not isinstance(raw, list):
            print("note: hooks.guardedPaths not set in agent-workflow.yaml; gate will default to ['src/'].")
            return
        paths = [p for p in raw if isinstance(p, str) and p.strip()]
        if not paths:
            print("note: hooks.guardedPaths is empty; gate will default to ['src/'].")
            return

        _atomic_write_json(sidecar, {"guardedPaths": paths})
        print("wrote guarded paths %s to %s." % (paths, sidecar))
    except Exception as exc:
        # Never let sidecar resolution fail the install.
        print("note: could not write guarded-paths sidecar (%s); gate will default to ['src/']." % exc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", choices=("claude", "codex"), default="claude")
    ap.add_argument("--settings")
    args = ap.parse_args()
    path = args.settings or os.path.join(
        f".{args.runtime}",
        "settings.json" if args.runtime == "claude" else "hooks.json",
    )

    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            sys.stderr.write(
                "error: %s exists but is not valid JSON (%s). "
                "Refusing to overwrite — merge the hooks manually.\n" % (path, exc)
            )
            return 1
        if not isinstance(data, dict):
            sys.stderr.write("error: %s is not a JSON object; refusing to modify.\n" % path)
            return 1
    else:
        data = {}

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        sys.stderr.write("error: settings 'hooks' is not an object; refusing to modify.\n")
        return 1

    added = 0
    for event, matcher, command, command_windows in _RUNTIME_HOOKS[args.runtime]:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            sys.stderr.write("error: hooks.%s is not a list; refusing to modify.\n" % event)
            return 1
        existing = _existing_command(groups, command)
        if existing is not None:
            if command_windows and existing.get("commandWindows") != command_windows:
                existing["commandWindows"] = command_windows
                added += 1
            continue
        hook = {"type": "command", "command": command}
        if command_windows:
            hook["commandWindows"] = command_windows
        entry = {"hooks": [hook]}
        if matcher:
            entry["matcher"] = matcher
        groups.append(entry)
        added += 1

    if added == 0:
        print("agent-workflow hooks already installed in %s (no change)." % path)
        if args.runtime == "claude":
            _write_guarded_paths_sidecar(path)
        return 0

    _atomic_write_json(path, data)  # atomic — avoids partial-write/truncation on interrupt
    print("installed %d agent-workflow hook(s) into %s." % (added, path))
    if args.runtime == "claude":
        _write_guarded_paths_sidecar(path)
    elif args.runtime == "codex":
        print("note: Codex project hooks run only after the repository .codex layer is trusted.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        sys.stderr.write("error: %s\n" % exc)
        sys.exit(1)
