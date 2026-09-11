#!/usr/bin/env python3
"""Shared pre-mutation decision for supported local agent runtimes.

Adapters pass their native tool payload on stdin and identify the runtime with
--runtime. Exit 0 allows the tool, exit 2 denies it. Pre-invocation integration
failures report DEGRADED and fail open; evidence and evaluation failures deny.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePath

SEED = (
    "Project rule: invoke the agent-workflow skill before planning or editing. "
    "It first evaluates any configured applicability policy. Only an explicit "
    "whole-change exemption may skip the Work Record; otherwise every engineering "
    "task is recorded. Any implementation plan for a non-exempt task must include, "
    "as its FIRST implementation step, invoking /agent-workflow to create the Work "
    "Record and classify risk before any code edit."
)
_PREFIXES = ("slice/", "feat/", "feature/", "fix/", "bug/", "chore/", "demo/")
_MUTATION_TOOLS = {"write", "edit", "multiedit", "notebookedit", "apply_patch"}
_PATCH_PATH = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File: (.+)$|^\*\*\* Move to: (.+)$",
    re.MULTILINE,
)
_WINDOWS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class EvidenceError(RuntimeError):
    """Required workflow evidence is unavailable or incomplete."""


def _run(args: list[str], cwd: Path, *, input_text: str | None = None, timeout: int = 25):
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=_WINDOWS_NO_WINDOW,
    )


def _degraded(message: str) -> int:
    sys.stderr.write(f"[agent-workflow] DEGRADED: {message}\n")
    return 0


def _deny(message: str) -> int:
    sys.stderr.write(f"[agent-workflow] DENY: {message}\n")
    return 2


def _repo_root(cwd: str | None) -> Path | None:
    start = Path(cwd or os.getcwd()).resolve()
    result = _run(["git", "rev-parse", "--show-toplevel"], start)
    if result.returncode != 0:
        return None
    root = Path(result.stdout.strip()).resolve()
    return root if root.is_dir() else None


def _normalise_path(root: Path, cwd: Path, value: object) -> str | None:
    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    candidate = Path(value)
    try:
        absolute = candidate.resolve() if candidate.is_absolute() else (cwd / candidate).resolve()
        relative = absolute.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    path = relative.as_posix()
    if not path or any(part in {"", ".", ".."} for part in PurePath(path).parts):
        return None
    return path


def _extract_paths(payload: object) -> tuple[bool, list[object]]:
    if not isinstance(payload, dict):
        return False, []
    tool = payload.get("tool_name") or payload.get("tool")
    if not isinstance(tool, str) or tool.lower() not in _MUTATION_TOOLS:
        return False, []
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = payload.get("args")
    if not isinstance(tool_input, dict):
        return True, []

    if tool.lower() == "apply_patch":
        patch = next(
            (
                tool_input[key]
                for key in ("patchText", "patch", "command")
                if isinstance(tool_input.get(key), str)
            ),
            "",
        )
        return True, [
            first or second
            for first, second in _PATCH_PATH.findall(patch)
            if first or second
        ]

    keys = ("notebook_path", "file_path", "filePath", "path")
    return True, [tool_input[key] for key in keys if key in tool_input]


def _git_z(root: Path, args: list[str]) -> list[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            timeout=20,
            check=False,
            creationflags=_WINDOWS_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvidenceError("Git scope collection failed") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip() or "git failed"
        raise EvidenceError(detail)
    raw = result.stdout
    if not raw:
        return []
    if not raw.endswith(b"\0"):
        raise EvidenceError("git returned incomplete NUL-delimited paths")
    try:
        return [item.decode("utf-8") for item in raw[:-1].split(b"\0") if item]
    except UnicodeDecodeError as exc:
        raise EvidenceError("git returned malformed UTF-8 paths") from exc


def _current_branch(root: Path) -> str | None:
    result = _run(["git", "branch", "--show-current"], root)
    branch = result.stdout.strip() if result.returncode == 0 else ""
    return branch or None


def _default_ref(root: Path) -> tuple[str | None, str | None]:
    try:
        result = _run(["git", "ls-remote", "--symref", "origin", "HEAD"], root, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvidenceError("actual default branch is unavailable") from exc
    if result.returncode != 0:
        raise EvidenceError("actual default branch is unavailable")
    match = re.search(r"^ref:\s+refs/heads/(.+)\s+HEAD$", result.stdout, re.MULTILINE)
    if match is None:
        raise EvidenceError("actual default branch is unavailable")
    name = match.group(1)
    oid_match = re.search(r"^([0-9a-f]{40})\s+HEAD$", result.stdout, re.MULTILINE)
    if oid_match is None:
        raise EvidenceError("actual default-branch revision is unavailable")
    oid = oid_match.group(1)
    try:
        found = _run(["git", "rev-parse", "--verify", "--quiet", f"{oid}^{{commit}}"], root)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvidenceError("local default-branch revision is unavailable") from exc
    return name, oid if found.returncode == 0 else None


def _changed_paths(
    root: Path,
    prospective: list[str],
    default_ref: str | None,
) -> list[str]:
    paths: list[str] = []
    if default_ref is None:
        raise EvidenceError("local default-branch revision is unavailable; committed scope is incomplete")
    try:
        merge_base = _run(["git", "merge-base", "HEAD", default_ref], root)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvidenceError("merge-base is unavailable; committed scope is incomplete") from exc
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        raise EvidenceError("merge-base is unavailable; committed scope is incomplete")
    paths.extend(
        _git_z(
                root,
            [
                "diff",
                "--name-only",
                "-z",
                "--no-renames",
                f"{merge_base.stdout.strip()}..HEAD",
                "--",
            ],
        )
    )
    paths.extend(_git_z(root, ["diff", "--name-only", "-z", "--no-renames", "HEAD", "--"]))
    paths.extend(_git_z(root, ["ls-files", "--others", "--exclude-standard", "-z"]))
    paths.extend(prospective)
    return list(dict.fromkeys(path.replace("\\", "/") for path in paths))


def _slug(branch: str) -> str:
    for prefix in _PREFIXES:
        if branch.startswith(prefix):
            branch = branch[len(prefix):]
            break
    return branch.replace("/", "-")


def _load_runtime_config(root: Path) -> str:
    import yaml

    try:
        with (root / "agent-workflow.yaml").open(encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        template = config["workRecord"]["local"]["taskPath"]
        if not isinstance(template, str) or template.count("{slug}") != 1:
            raise ValueError("workRecord.local.taskPath is invalid")
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise EvidenceError(f"agent-workflow.yaml is missing or invalid: {exc}") from exc
    return template.replace("\\", "/")


def _tooling(root: Path) -> tuple[list[str], Path]:
    vendored_checker = root / "scripts" / "agent-workflow-check.py"
    if vendored_checker.is_file():
        checker = [sys.executable, str(vendored_checker)]
    elif (root / "core" / "checker" / "__main__.py").is_file():
        checker = [sys.executable, "-m", "core.checker"]
    else:
        raise FileNotFoundError("scripts/agent-workflow-check.py is missing")

    vendored_reporter = root / "scripts" / "agent-redline-report.py"
    source_reporter = root / "core" / "agent-redline" / "core" / "reporter" / "reporter.py"
    reporter = vendored_reporter if vendored_reporter.is_file() else source_reporter
    if not reporter.is_file():
        raise FileNotFoundError("scripts/agent-redline-report.py is missing")
    return checker, reporter


def _checker_decision(
    root: Path,
    paths: list[str],
    slug: str,
    is_default: bool,
) -> tuple[int, dict]:
    checker, reporter = _tooling(root)
    policy = root / "agent-redline-policy.yaml"
    if not policy.is_file():
        raise EvidenceError("agent-redline-policy.yaml is missing")

    with tempfile.TemporaryDirectory(prefix="agent-workflow-runtime-") as temp:
        temp_dir = Path(temp)
        changed = temp_dir / "changed.z"
        changed.write_bytes(b"".join(path.encode("utf-8") + b"\0" for path in paths))
        verdict_path = temp_dir / "redline-verdict.json"
        report = _run(
            [
                sys.executable,
                str(reporter),
                "--policy",
                str(policy),
                "--changed-files-z",
                str(changed),
                "--json-out",
                str(verdict_path),
            ],
            root,
        )
        if not verdict_path.is_file():
            raise EvidenceError(report.stderr.strip() or "Redline produced no verdict")

        base_command = [
            *checker,
            "--repo-root",
            str(root),
            "--redline-verdict",
            str(verdict_path),
        ]
        applicability_command = [*base_command, "--changed-files-z", str(changed)]
        if is_default:
            applicability_command.append("--check-default-branch-protection")
            return _checked_payload(_run(applicability_command, root))

        applicability_code, applicability = _checked_payload(
            _run(applicability_command, root)
        )
        if applicability_code < 2 and _is_documentation_exemption(applicability):
            return applicability_code, applicability
        return _checked_payload(
            _run(
                [*base_command, "--slug", slug, "--require-implementation-ready"],
                root,
            )
        )


def _checked_payload(checked: subprocess.CompletedProcess[str]) -> tuple[int, dict]:
    try:
        payload = json.loads(checked.stdout)
    except json.JSONDecodeError as exc:
        raise EvidenceError(f"checker returned invalid JSON: {exc}") from exc
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list) or not records or not all(
        isinstance(record, dict) for record in records
    ):
        raise EvidenceError("checker returned an invalid verdict")
    return checked.returncode, payload


def _default_branch(root: Path, branch: str) -> tuple[bool, str | None]:
    default_name, default_ref = _default_ref(root)
    return branch == default_name, default_ref


def _is_documentation_exemption(payload: dict) -> bool:
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != 1:
        return False
    record = records[0]
    if not isinstance(record, dict) or record.get("slug") != "<documentation-only>":
        return False
    predicates = record.get("predicates")
    return isinstance(predicates, list) and any(
        isinstance(item, dict)
        and item.get("name") == "workflow.applicability"
        and item.get("passed") is True
        for item in predicates
    )


def _is_direct_default_exemption(payload: dict) -> bool:
    if not _is_documentation_exemption(payload):
        return False
    predicates = payload["records"][0]["predicates"]
    return any(
        "Direct-default-branch is allowed" in str(item.get("detail", ""))
        for item in predicates
        if isinstance(item, dict)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, choices=("claude", "codex", "opencode"))
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args(argv)
    if args.seed:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": SEED,
            }
        }))
        return 0

    try:
        payload = json.load(sys.stdin)
        supported, raw_paths = _extract_paths(payload)
        if not supported:
            return 0
        cwd = payload.get("cwd") if isinstance(payload, dict) else None
        execution_dir = Path(cwd or os.getcwd()).resolve()
        root = _repo_root(str(execution_dir))
        if root is None:
            return _degraded("repository root unavailable; mutation guard was not evaluated")
        paths = [_normalise_path(root, execution_dir, value) for value in raw_paths]
        if not paths or any(path is None for path in paths):
            return _degraded("supported mutation payload had no complete repository path set")
        prospective = list(dict.fromkeys(path for path in paths if path is not None))

        branch = _current_branch(root)
        if branch is None:
            return _degraded("current branch unavailable; mutation guard was not evaluated")
        is_default, default_ref = _default_branch(root, branch)
        template = _load_runtime_config(root)
        slug = _slug(branch)
        record_path = template.replace("{slug}", slug)
        if not is_default and all(path == record_path for path in prospective):
            return 0

        complete = _changed_paths(root, prospective, default_ref)
        try:
            code, verdict = _checker_decision(root, complete, slug, is_default)
        except EvidenceError:
            raise
        except (
            ImportError,
            OSError,
            KeyError,
            TypeError,
            ValueError,
            RuntimeError,
            subprocess.TimeoutExpired,
        ) as exc:
            raise EvidenceError(f"workflow evaluation failed: {exc}") from exc
        if is_default:
            if code < 2 and _is_direct_default_exemption(verdict):
                return 0
            return _deny(
                "default-branch mutation requires a complete documentation-only exemption, "
                "separate direct-default approval, and a fresh unprotected result"
            )
        if code < 2:
            return 0
        return _deny(
            "create or repair the configured Work Record, complete required review and "
            "approval, then set State to Ready to implement before editing"
        )
    except EvidenceError as exc:
        return _deny(str(exc))
    except (ImportError, OSError, KeyError, TypeError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return _degraded(f"{exc}; final CI remains authoritative")


if __name__ == "__main__":
    sys.exit(main())