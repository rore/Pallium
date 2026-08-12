#!/usr/bin/env python3
"""Install the agent-workflow Claude Code hooks into a repo's .claude/settings.json.

Create-or-merge, idempotent, and non-destructive: it adds three hook
registrations (seed / gate / reinforce) that point at ``.claude/hooks/`` via
``$CLAUDE_PROJECT_DIR``, WITHOUT removing or altering any hook the repo already
has. Run again → no-op.

It also resolves the plan-mode gate's guarded paths: it reads
``hooks.guardedPaths`` from the repo's ``agent-workflow.yaml`` (repo root =
parent of the ``.claude`` dir that holds settings.json) and writes them to a
stdlib-JSON sidecar ``.claude/hooks/guarded-paths.json`` that the dependency-free
gate hook reads at runtime. This step degrades gracefully: if the yaml is
absent, the key is missing, or pyyaml is unavailable, no sidecar is written and
the gate falls back to its historical ``["src/"]`` default (a warning is printed,
exit stays 0).

Safety:
- If an existing settings.json is present but unparseable, ABORT (exit 1) and
  touch nothing — never clobber a file we can't read.
- Idempotency keys on the exact command string, so re-runs don't duplicate.

Usage:
    python install-settings.py [--settings PATH]
    (default PATH: .claude/settings.json under the current directory)
"""
import argparse
import json
import os
import sys

# event -> (matcher or None, command)
_HOOKS = [
    ("UserPromptSubmit", None,          'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/seed-workflow.sh"'),
    ("PreToolUse",       "ExitPlanMode", 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/check-plan.sh"'),
    ("PostToolUse",      "ExitPlanMode", 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/reinforce-workflow.sh"'),
]


def _command_present(event_groups, command):
    for group in event_groups:
        if not isinstance(group, dict):
            continue
        for h in group.get("hooks", []) or []:
            if isinstance(h, dict) and h.get("command") == command:
                return True
    return False


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
    ap.add_argument("--settings", default=os.path.join(".claude", "settings.json"))
    args = ap.parse_args()
    path = args.settings

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
    for event, matcher, command in _HOOKS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            sys.stderr.write("error: hooks.%s is not a list; refusing to modify.\n" % event)
            return 1
        if _command_present(groups, command):
            continue  # idempotent
        entry = {"hooks": [{"type": "command", "command": command}]}
        if matcher:
            entry = {"matcher": matcher, "hooks": [{"type": "command", "command": command}]}
        groups.append(entry)
        added += 1

    if added == 0:
        print("agent-workflow hooks already installed in %s (no change)." % path)
        _write_guarded_paths_sidecar(path)
        return 0

    _atomic_write_json(path, data)  # atomic — avoids partial-write/truncation on interrupt
    print("installed %d agent-workflow hook(s) into %s." % (added, path))
    _write_guarded_paths_sidecar(path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        sys.stderr.write("error: %s\n" % exc)
        sys.exit(1)
