from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys

import pytest

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


@pytest.mark.parametrize(
    ("paths", "zones", "checkpoints", "labels", "exit_code"),
    [
        ([".github/workflows/ci.yml"], {"red": [".github/workflows/ci.yml"], "blue": [], "gray": [], "watch": []}, [("architecture-review", False)], "", 1),
        (["scripts/test-plan.py"], {"red": ["scripts/test-plan.py"], "blue": [], "gray": [], "watch": []}, [("architecture-review", False)], "", 1),
        (["scripts/agent-workflow-check.py"], {"red": ["scripts/agent-workflow-check.py"], "blue": [], "gray": [], "watch": []}, [("architecture-review", False)], "", 1),
        (["app/mcp/server.py"], {"red": ["app/mcp/server.py"], "blue": [], "gray": [], "watch": ["app/mcp/server.py"]}, [("api-review", False)], "", 1),
        (["core/relay.py"], {"red": ["core/relay.py"], "blue": [], "gray": [], "watch": ["core/relay.py"]}, [("architecture-review", False)], "", 1),
        (["storage/sqlite_relay.py"], {"red": ["storage/sqlite_relay.py"], "blue": [], "gray": [], "watch": ["storage/sqlite_relay.py"]}, [("persistence-review", False)], "", 1),
        (["scripts/agent-workflow-checker.py"], {"red": [], "blue": ["scripts/agent-workflow-checker.py"], "gray": [], "watch": []}, [], "", 0),
        (["app/mcp/other.py"], {"red": [], "blue": [], "gray": ["app/mcp/other.py"], "watch": ["app/mcp/other.py"]}, [], "", 1),
        ([".agents/skills/example/SKILL.md"], {"red": [], "blue": [], "gray": [".agents/skills/example/SKILL.md"], "watch": [".agents/skills/example/SKILL.md"]}, [], "", 1),
        ([".claude/skills/example/SKILL.md"], {"red": [], "blue": [], "gray": [".claude/skills/example/SKILL.md"], "watch": [".claude/skills/example/SKILL.md"]}, [], "", 1),
        (["tests/behavior_contracts/caller.md"], {"red": ["tests/behavior_contracts/caller.md"], "blue": [], "gray": [], "watch": []}, [], "", 0),
        (["scripts/helper.py"], {"red": [], "blue": ["scripts/helper.py"], "gray": [], "watch": []}, [], "", 0),
        (["build/generated.py"], {"red": [], "blue": [], "gray": [], "watch": []}, [], "", 0),
        (["misc/例え.md"], {"red": [], "blue": [], "gray": ["misc/例え.md"], "watch": []}, [], "", 1),
        ([], {"red": [], "blue": [], "gray": [], "watch": []}, [], "", 0),
        (
            [".github/workflows/ci.yml", "app/mcp/server.py", "storage/sqlite_relay.py"],
            {"red": [".github/workflows/ci.yml", "app/mcp/server.py", "storage/sqlite_relay.py"], "blue": [], "gray": [], "watch": ["app/mcp/server.py", "storage/sqlite_relay.py"]},
            [("architecture-review", True), ("persistence-review", True), ("api-review", True)],
            "architecture-reviewed,api-reviewed,persistence-reviewed",
            1,
        ),
        (
            [".github/workflows/ci.yml", "app/mcp/server.py", "storage/sqlite_relay.py"],
            {"red": [".github/workflows/ci.yml", "app/mcp/server.py", "storage/sqlite_relay.py"], "blue": [], "gray": [], "watch": ["app/mcp/server.py", "storage/sqlite_relay.py"]},
            [("architecture-review", True), ("persistence-review", False), ("api-review", False)],
            "architecture-reviewed",
            1,
        ),
    ],
)
def test_redline_report_cli_calibration_matrix(
    tmp_path: Path,
    paths: list[str],
    zones: dict[str, list[str]],
    checkpoints: list[tuple[str, bool]],
    labels: str,
    exit_code: int,
) -> None:
    changed = tmp_path / "changed-files.z"
    changed.write_bytes("\0".join(paths).encode("utf-8") + (b"\0" if paths else b""))
    # Routing-only evidence must not depend on ignored local import-linter output.
    boundary = tmp_path / "boundary.json"
    boundary.write_text('{"violations": []}', encoding="utf-8")
    output = tmp_path / "verdict.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/agent-redline-report.py"),
            "--policy", str(ROOT / "agent-redline-policy.yaml"),
            "--changed-files-z", str(changed),
            "--boundary-report", str(boundary),
            "--boundary-format", "json-violations",
            "--json-out", str(output),
            "--pr-labels", labels,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert output.exists(), f"Reporter exited {result.returncode}: {result.stdout} {result.stderr}"
    verdict = json.loads(output.read_text(encoding="utf-8"))
    assert result.returncode == verdict["exitCode"] == exit_code, result.stderr
    assert verdict["zones"] == zones
    assert sorted((item["id"], item["satisfied"]) for item in verdict["checkpoints"]) == sorted(checkpoints)
