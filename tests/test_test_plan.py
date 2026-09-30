from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("test_plan", ROOT / "scripts" / "test-plan.py")
assert SPEC and SPEC.loader
plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plan)


def test_classifier_is_conservative() -> None:
    cases = [
        (None, "full"), ([], "full"),
        (["docs/guide.md"], "docs"), (["roadmap/item.md"], "docs"),
        (["AGENTS.md"], "governance"), ([".agent-workflow/tasks/task.md"], "governance"),
        (["scripts/agent-workflow-check.py"], "governance"),
        ([".agents/skills/agent-workflow/scripts/agent-workflow-check.py"], "governance"),
        ([".claude/skills/agent-workflow/scripts/agent-workflow-check.py"], "governance"),
        ([".agents/skills/agent-workflow/SKILL.md"], "governance"),
        ([".claude/skills/agent-workflow/manifest.txt"], "governance"), ([".agents/skills/agent-workflow/templates/agents-section.md.template"], "governance"),
        (["docs/guide.md", "AGENTS.md"], "governance"),
        (["docs/guide.md", "app/main.py"], "full"),
        ([".agents/skills/agent-workflow/hooks/check-plan.py"], "full"),
        ([".agents/skills/agent-workflow/scripts/agent-workflow-runtime.py"], "full"),
        ([".github/workflows/ci.yml"], "full"),
        (["scripts/test-plan.py"], "full"), (["scripts/agent-redline-report.py"], "full"), (["tests/test_test_plan.py"], "full"),
        (["tests/behavior_contracts/test_api.py"], "full"),
        ([".claude/settings.json"], "full"), (["unknown.md"], "full"),
        (["../escape.md"], "full"), (["docs/./guide.md"], "full"), (["docs\\guide.md"], "full"),
        ([".agent-redline/agent-policy.schema.json"], "full"),
    ]
    assert [(plan.classify(paths)[0]) for paths, _ in cases] == [lane for _, lane in cases]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _run(repo: Path, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "test-plan.py"), "--repo-root", str(repo), *args],
        cwd=repo, check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def test_local_cli_reports_committed_dirty_untracked_delete_rename_and_unicode(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "old.md").write_text("old", encoding="utf-8")
    (tmp_path / "rename.txt").write_text("rename", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("instructions", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")

    (tmp_path / "docs" / "old.md").write_text("updated", encoding="utf-8")
    _git(tmp_path, "add", "docs/old.md")
    _git(tmp_path, "commit", "-m", "docs update")
    committed = _run(tmp_path, "--base", base)
    assert committed["lane"] == "docs"
    assert committed["commands"] == plan.DOC_TESTS

    _git(tmp_path, "mv", "rename.txt", "renamed.txt")
    (tmp_path / "docs" / "old.md").unlink()
    (tmp_path / "docs" / "新規.md").write_text("new", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("changed", encoding="utf-8")
    dirty = _run(tmp_path, "--base", base)
    assert dirty["lane"] == "full"
    assert {"rename.txt", "renamed.txt", "docs/old.md", "docs/新規.md", "AGENTS.md"} <= set(dirty["paths"])
    assert dirty["commands"] == plan.FULL_TESTS

    missing = _run(tmp_path, "--base", "missing-trusted-base")
    assert missing["lane"] == "full"
    assert "Git evidence unavailable" in missing["reason"]


def test_ci_cli_supports_merge_base_and_exact_push(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "common").write_text("common", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "switch", "-c", "feature")
    (tmp_path / "README.md").write_text("docs", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "head")
    head = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "switch", "main")
    (tmp_path / "base-only").write_text("other branch", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base advanced")
    _git(tmp_path, "merge", "--no-ff", head, "-m", "synthetic merge")

    pr = _run(tmp_path, "--base", base, "--head", head)
    push = _run(tmp_path, "--base", base, "--head", head, "--exact")
    assert pr["lane"] == push["lane"] == "docs"
    assert pr["paths"] == push["paths"] == ["README.md"]