import re
import shutil
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path


WORKFLOW = (Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _job(name: str, next_name: str | None = None) -> str:
    block = WORKFLOW.split(f"  {name}:\n", 1)[1]
    return block if next_name is None else block.split(f"  {next_name}:\n", 1)[0]


def test_ci_cancels_only_the_same_event_and_ref() -> None:
    assert "group: ci-${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}" in WORKFLOW
    assert "cancel-in-progress: true" in WORKFLOW


def test_every_event_reports_selection_and_policy_is_trusted() -> None:
    assert "paths-ignore:" not in WORKFLOW
    assert "  workflow_dispatch:" in WORKFLOW
    selector = _job("select", "focused")
    assert "fetch-depth: 0" in selector
    assert "github.event.pull_request.base.sha || github.event.before" in selector
    assert "github.event.pull_request.head.sha || github.sha" in selector
    assert 'git merge-base "$BASE" "$HEAD"' in selector
    assert 'git show "$trusted:scripts/test-plan.py"' in selector
    assert 'python "$RUNNER_TEMP/trusted-test-plan.py" --repo-root "$GITHUB_WORKSPACE"' in selector
    assert '--base "$trusted" --head "$HEAD" --exact' in selector
    assert '"$EVENT" != schedule && "$EVENT" != workflow_dispatch' in selector
    assert "lane=full" in selector and "selector_error=true" in selector


def test_application_jobs_are_full_only_and_focused_checks_avoid_app_setup() -> None:
    for job, next_job in (("test", "windows-smoke"), ("windows-smoke", "windows-full"), ("windows-full", "nightly-slow-smoke")):
        block = _job(job, next_job)
        assert "needs: select" in block
        assert "needs.select.outputs.lane == 'full'" in block
    assert "github.event_name != 'pull_request'" in _job("windows-full", "nightly-slow-smoke")
    focused = _job("focused", "test")
    assert "--noconftest -q -n 0" in focused
    assert 'pip install -e' not in focused
    assert 'pyyaml jsonschema' in focused
    assert 'tests/test_agent_workflow_ci.py' in focused
    assert '["ubuntu-latest","windows-latest"]' in focused


def test_required_linux_lane_cannot_skip_mcp_tests() -> None:
    linux = _job("test", "windows-smoke")
    assert 'pip install -e ".[dev,vector,mcp]"' in linux
    assert 'python -c "import mcp; import app.mcp.server"' in linux
    assert "--durations=20" in linux


def test_all_test_commands_report_slowest_tests() -> None:
    commands = WORKFLOW.split("python -m pytest")[1:]
    assert len(commands) >= 5
    assert all("--durations=20" in command.split("\n\n", 1)[0] for command in commands)


def test_nightly_slow_smoke_is_bounded_and_hermetic() -> None:
    nightly = _job("nightly-slow-smoke", "result")
    assert "if: github.event_name == 'schedule'" in nightly
    assert "timeout-minutes: 15" in nightly
    for filename in (
        "test_snapshot.py",
        "test_snapshot_concurrent.py",
        "test_snapshot_failure.py",
        "test_storage_sqlite.py",
        "test_thread_summary_accumulation.py",
        "test_relay_load_smoke.py",
    ):
        assert f"tests/{filename}" in nightly
    assert "-m slow -n 0 -q --durations=20" in nightly
    assert "test_linux_service_lifecycle_e2e.py" not in nightly
    assert "test_live_exploratory_runner.py" not in nightly

def test_explicit_ci_test_paths_exist() -> None:
    root = Path(__file__).parents[1]
    for relative in re.findall(r"(?m)^\s+(tests/\S+)$", WORKFLOW):
        assert (root / relative).exists(), relative

def _gate(jobs: dict, event: str) -> subprocess.CompletedProcess:
    block = _job("result")
    assert "if: always()" in block
    assert "needs: [select, focused, test, windows-smoke, windows-full, nightly-slow-smoke]" in block
    code = textwrap.dedent(block.split("python - <<'PY'\n", 1)[1].rsplit("          PY", 1)[0])
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          env={**os.environ, "RESULTS": json.dumps(jobs), "EVENT": event})


def _results(lane: str, event: str) -> dict:
    jobs = {"select": {"result": "success", "outputs": {"lane": lane, "selector_error": "false"}}}
    required = {"focused": lane != "full", "test": lane == "full", "windows-smoke": lane == "full",
                "windows-full": lane == "full" and event != "pull_request", "nightly-slow-smoke": event == "schedule"}
    jobs.update({job: {"result": "success" if run else "skipped"} for job, run in required.items()})
    return jobs


def test_aggregate_gate_accepts_only_complete_successful_required_lanes() -> None:
    for lane, event in (("docs", "pull_request"), ("governance", "push"), ("full", "pull_request"),
                        ("full", "push"), ("full", "schedule"), ("full", "workflow_dispatch")):
        jobs = _results(lane, event)
        result = _gate(jobs, event)
        assert result.returncode == 0, result.stderr
        for job in jobs:
            broken = json.loads(json.dumps(jobs))
            broken[job]["result"] = "failure"
            assert _gate(broken, event).returncode != 0, job
        for job, state in jobs.items():
            if state["result"] == "success":
                broken = json.loads(json.dumps(jobs))
                broken[job]["result"] = "skipped"
                assert _gate(broken, event).returncode != 0, job
    jobs = _results("full", "pull_request")
    jobs["select"]["outputs"]["selector_error"] = "true"
    assert _gate(jobs, "pull_request").returncode != 0
    jobs["select"]["outputs"] = {}
    assert _gate(jobs, "pull_request").returncode != 0
    assert _gate(_results("docs", "schedule"), "schedule").returncode != 0
    assert _gate(_results("docs", "workflow_dispatch"), "workflow_dispatch").returncode != 0


def test_selection_step_uses_trusted_policy_and_full_fallback(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe" if os.name == "nt" else None
    shell = str(bash) if bash and bash.is_file() else shutil.which("bash")
    assert shell, "CI selection requires bash (provided by Git for Windows or the CI image)"
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()
    git("init", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    git("config", "core.autocrlf", "false")
    readme = repo / "README.md"
    readme.write_text("base", encoding="utf-8")
    def commit() -> str:
        git("add", ".")
        git("commit", "-m", "fixture")
        return git("rev-parse", "HEAD")
    base = commit()
    code = textwrap.dedent(_job("select", "focused").split("        run: |\n", 1)[1])
    output = tmp_path / "outputs"
    summary = tmp_path / "summary"
    def select(start: str, head: str, event: str = "pull_request") -> dict:
        output.write_text("", encoding="utf-8")
        summary.write_text("", encoding="utf-8")
        result = subprocess.run([shell, "-c", code], cwd=repo, capture_output=True, text=True, env={
            **os.environ, "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
            "EVENT": event, "BASE": start, "HEAD": head, "GITHUB_WORKSPACE": repo.as_posix(),
            "RUNNER_TEMP": tmp_path.as_posix(), "GITHUB_OUTPUT": output.as_posix(), "GITHUB_STEP_SUMMARY": summary.as_posix(),
        })
        assert result.returncode == 0, result.stderr
        return dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert select(base, base) == {"lane": "full", "selector_error": "false"}
    (repo / "scripts").mkdir()
    selector = repo / "scripts/test-plan.py"
    selector.write_text((root / "scripts/test-plan.py").read_text(encoding="utf-8"), encoding="utf-8")
    base = commit()
    readme.write_text("docs change", encoding="utf-8")
    head = commit()
    assert select(base, head) == {"lane": "docs", "selector_error": "false"}
    selector.write_text('print(\'{"lane":"docs"}\')', encoding="utf-8")
    (repo / "application.py").write_text("changed", encoding="utf-8")
    head = commit()
    assert select(base, head)["lane"] == "full"  # Head cannot exempt its own edits.
    selector.write_text("raise RuntimeError('broken policy')", encoding="utf-8")
    broken_base = commit()
    readme.write_text("another docs change", encoding="utf-8")
    head = commit()
    assert select(broken_base, head) == {"lane": "full", "selector_error": "true"}
    assert select(broken_base, head, "schedule") == {"lane": "full", "selector_error": "false"}
    assert select("missing-base", head)["lane"] == "full"
