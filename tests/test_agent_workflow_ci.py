from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


def test_changed_file_jobs_use_pr_head_and_merge_base(tmp_path: Path) -> None:
    workflow = (ROOT / ".github/workflows/agent-workflow.yml").read_text(encoding="utf-8")
    assert "HEAD_SHA: ${{ github.sha }}" not in workflow
    assert workflow.count("HEAD_SHA: ${{ github.event.pull_request.head.sha }}") == 3
    assert workflow.count(
        'MERGE_BASE=$(git merge-base "${BASE_SHA}" "${HEAD_SHA}")'
    ) == 2
    assert workflow.count(
        'git diff --name-only -z --no-renames "${MERGE_BASE}" "${HEAD_SHA}" > changed-files.z'
    ) == 2

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / "common.txt").write_text("common", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "common")
    event_base = _git(repo, "rev-parse", "HEAD")

    _git(repo, "switch", "-c", "feature")
    (repo / "head-only.txt").write_text("head", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "head")
    head = _git(repo, "rev-parse", "HEAD")

    _git(repo, "switch", "main")
    (repo / "base-only.txt").write_text("base", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    _git(repo, "merge", "--no-ff", head, "-m", "synthetic merge")
    synthetic_merge = _git(repo, "rev-parse", "HEAD")

    merge_base = _git(repo, "merge-base", event_base, head)
    assert merge_base == event_base
    assert _git(
        repo, "diff", "--name-only", "--no-renames", merge_base, head,
    ).splitlines() == ["head-only.txt"]
    assert set(_git(repo, "diff", "--name-only", event_base, synthetic_merge).splitlines()) == {
        "base-only.txt",
        "head-only.txt",
    }


def test_work_record_checker_accepts_valid_and_rejects_invalid(tmp_path: Path) -> None:
    checker_paths = [
        "scripts/agent-workflow-check.py",
        ".agents/skills/agent-workflow/scripts/agent-workflow-check.py",
        ".claude/skills/agent-workflow/scripts/agent-workflow-check.py",
    ]
    for relative in checker_paths:
        checker = ROOT / relative
        assert checker.is_file(), f"missing allowlisted checker: {relative}"
        repo = tmp_path / relative.split("/")[0].replace(".", "")
        repo.mkdir()
        (repo / "agent-workflow.yaml").write_text(
            (ROOT / "agent-workflow.yaml").read_text(encoding="utf-8"), encoding="utf-8",
        )
        records = repo / ".agent-workflow/tasks"
        records.mkdir(parents=True)
        record = records / "contract.md"
        record.write_text(
            """<!-- agent-workflow:start -->
**Outcome:** A caller contract is checked.
**Target:** Pallium.
**Scope:** One temporary record.
**Constraints:** —
**Completion criteria:** The checker accepts valid input and rejects invalid input.
**Requirement baseline:** {"source":"test","outcome":"A caller contract is checked.","scope":"One temporary record.","constraints":"—","completion_criteria":"The checker accepts valid input and rejects invalid input."}
**Risk:** Routine
**Complexity:** Simple
**Reason:** —
**Approach:** Run the checker CLI.
**Verification:** Checker CLI accepts valid input and rejects invalid input.
**State:** Ready to implement
<!-- agent-workflow:end -->
""",
            encoding="utf-8",
        )
        verdict = tmp_path / "redline-verdict.json"
        verdict.write_text("{}", encoding="utf-8")

        def check() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(checker), "--repo-root", str(repo), "--slug", "contract", "--redline-verdict", str(verdict)],
                cwd=ROOT, capture_output=True, text=True,
            )

        valid = check()
        assert valid.returncode == 0, f"{relative}: valid Work Record rejected: {valid.stdout} {valid.stderr}"
        record.write_text(record.read_text(encoding="utf-8").replace("**State:** Ready to implement", "**State:** invalid"), encoding="utf-8")
        invalid = check()
        assert invalid.returncode != 0, f"{relative}: invalid Work Record accepted"