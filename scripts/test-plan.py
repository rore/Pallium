#!/usr/bin/env python3
"""Choose conservative local/CI validation from complete Git path evidence."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SELECTOR_PATHS = {
    "scripts/test-plan.py", ".github/workflows/ci.yml",
    "tests/test_test_plan.py", "tests/test_ci_workflow.py",
    "tests/test_agent_workflow_ci.py", "agent-workflow.yaml",
    "pyproject.toml", "pytest.ini", "tox.ini",
}
GOVERNANCE_FILES = {
    "AGENTS.md", "scripts/agent-workflow-check.py",
    ".agents/skills/agent-workflow/scripts/agent-workflow-check.py",
    ".claude/skills/agent-workflow/scripts/agent-workflow-check.py",
}
DOC_TESTS = [
    "python -m pytest --noconftest -q -n 0 tests/test_test_plan.py tests/test_ci_workflow.py",
]
GOVERNANCE_TESTS = [
    "python -m pytest --noconftest -q -n 0 tests/test_test_plan.py tests/test_ci_workflow.py tests/test_agent_workflow_ci.py",
]
FULL_TESTS = ["python -m pytest tests/ -x -q"]


def _is_governance(path: str) -> bool:
    if path in GOVERNANCE_FILES:
        return True
    if path.startswith(".agent-workflow/tasks/") and path.endswith(".md") and path.count("/") == 2:
        return True
    for tree in (".agents/skills/agent-workflow/", ".claude/skills/agent-workflow/"):
        if path.startswith(tree) and (path.endswith((".md", ".md.template")) or path.endswith("manifest.txt")):
            return True
    return False


def _is_docs(path: str) -> bool:
    return path == "README.md" or (path.startswith(("docs/", "roadmap/")) and path.endswith(".md"))


def classify(paths: list[str] | None) -> tuple[str, str]:
    if not paths:
        return "full", "missing or empty change evidence"
    if any(
        not path or path.startswith("/") or "\\" in path or str(PurePosixPath(path)) != path
        for path in paths
    ):
        return "full", "invalid path evidence"
    if any(
        path in SELECTOR_PATHS or path.startswith(("tests/", ".github/workflows/"))
        for path in paths
    ):
        return "full", "selection policy, CI, test files, or behavior contracts changed"
    if all(_is_docs(path) or _is_governance(path) for path in paths):
        if any(_is_governance(path) for path in paths):
            return "governance", "supported Agent Workflow files and documentation only"
        return "docs", "recognized Markdown documentation only"
    return "full", "application, mixed, runtime, or unrecognized paths changed"


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def _paths(data: bytes) -> list[str]:
    return [os.fsdecode(item) for item in data.split(b"\0") if item]


def changed_paths(base: str, head: str | None = None, exact: bool = False, repo_root: Path = ROOT) -> list[str]:
    """Return complete no-rename Git paths; local mode includes all working changes."""
    if head:
        target = head
        start = base if exact else _git(repo_root, "merge-base", base, head).decode().strip()
        paths = _paths(_git(repo_root, "diff", "--name-only", "-z", "--no-renames", start, target))
    else:
        target = "HEAD"
        start = _git(repo_root, "merge-base", base, target).decode().strip()
        paths = _paths(_git(repo_root, "diff", "--name-only", "-z", "--no-renames", start, target))
        paths += _paths(_git(repo_root, "diff", "--name-only", "-z", "--no-renames"))
        paths += _paths(_git(repo_root, "diff", "--cached", "--name-only", "-z", "--no-renames"))
        paths += _paths(_git(repo_root, "ls-files", "--others", "--exclude-standard", "-z"))
    return list(dict.fromkeys(paths))


def _commands(lane: str) -> list[str]:
    return {"docs": DOC_TESTS, "governance": GOVERNANCE_TESTS, "full": FULL_TESTS}[lane]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="trusted base ref (default: origin/main)")
    parser.add_argument("--head", help="CI head ref; omitted locally to include dirty and untracked paths")
    parser.add_argument("--exact", action="store_true", help="compare base directly to head, for pushes")
    parser.add_argument("--repo-root", type=Path, default=ROOT, help="Git checkout to inspect")
    parser.add_argument("--github-output", type=Path, help="write lane and selector_error to GITHUB_OUTPUT")
    args = parser.parse_args(argv)
    try:
        paths = changed_paths(args.base, args.head, args.exact, args.repo_root.resolve())
        lane, reason = classify(paths)
        error = False
    except (OSError, UnicodeError, subprocess.SubprocessError, ValueError) as exc:
        paths, lane, reason, error = [], "full", f"Git evidence unavailable: {exc}", True
    result = {"lane": lane, "reason": reason, "paths": paths, "commands": _commands(lane)}
    print(json.dumps(result, ensure_ascii=True))
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"lane={lane}\nselector_error={str(error).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())