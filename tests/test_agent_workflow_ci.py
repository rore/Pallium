from __future__ import annotations

from pathlib import Path
import subprocess


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
        'git diff --name-only "${BASE_SHA}...${HEAD_SHA}" > changed-files.txt'
    ) == 2

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / "common.txt").write_text("common", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "common")
    merge_base = _git(repo, "rev-parse", "HEAD")

    _git(repo, "switch", "-c", "feature")
    (repo / "head-only.txt").write_text("head", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "head")
    head = _git(repo, "rev-parse", "HEAD")

    _git(repo, "switch", "main")
    (repo / "base-only.txt").write_text("base", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    current_base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "merge", "--no-ff", head, "-m", "synthetic merge")
    synthetic_merge = _git(repo, "rev-parse", "HEAD")

    assert _git(repo, "diff", "--name-only", f"{current_base}...{head}").splitlines() == [
        "head-only.txt"
    ]
    assert set(_git(repo, "diff", "--name-only", merge_base, synthetic_merge).splitlines()) == {
        "base-only.txt",
        "head-only.txt",
    }
