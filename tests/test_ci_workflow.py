import re
import shlex
import shutil
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

WORKFLOW = (Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _job(name: str, next_name: str | None = None) -> str:
    block = WORKFLOW.split(f"  {name}:\n", 1)[1]
    return block if next_name is None else block.split(f"  {next_name}:\n", 1)[0]


def test_ci_cancels_only_the_same_event_and_ref() -> None:
    assert "group: ci-${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}" in WORKFLOW
    assert "cancel-in-progress: true" in WORKFLOW


def test_subprocess_qualification_workflow_is_manual_only() -> None:
    path = Path(__file__).parents[1] / ".github" / "workflows" / "subprocess-qualification.yml"
    assert path.is_file(), "Dedicated subprocess qualification workflow is missing"

    import yaml

    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    events = workflow.get("on", workflow.get(True))
    assert isinstance(events, dict)
    assert set(events) == {"workflow_dispatch"}


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


@pytest.mark.parametrize("version", ("3.12", "3.13"))
@pytest.mark.parametrize("event", ("pull_request", "push", "schedule", "workflow_dispatch"))
def test_linux_full_suite_preserves_selection_and_reporting(version, event) -> None:
    import yaml

    job = yaml.safe_load(WORKFLOW)["jobs"]["test"]
    assert job["strategy"]["matrix"]["python-version"] == ["3.12", "3.13"]
    command, = [step["run"] for step in job["steps"] if step.get("name") == "Run tests"]
    flag = "${{ github.event_name != 'workflow_dispatch' && '-x' || '' }}"
    command = command.replace(flag, "" if event == "workflow_dispatch" else "-x")
    command = command.replace("${{ matrix.python-version }}", version)
    tokens = shlex.split(command)
    assert tokens[:4] == ["python", "-m", "pytest", "tests/"]
    args = tokens[4:]
    expected = {"-q", "--durations=20",
                f"--junitxml=test-results/linux-{version}-test-all.xml"}
    if event != "workflow_dispatch":
        expected.add("-x")
    assert set(args) == expected and len(args) == len(expected)


def test_windows_smoke_installs_mcp_for_actual_logging_regression() -> None:
    smoke = _job("windows-smoke", "windows-full")
    assert "tests/test_runtime_logging.py" in smoke
    assert 'pip install -e ".[dev,vector,mcp]"' in smoke


def test_only_manual_full_lanes_continue_after_pytest_failures() -> None:
    flag = "${{ github.event_name != 'workflow_dispatch' && '-x' || '' }}"
    for job, next_job, count in (("test", "windows-smoke", 1),
                                 ("windows-smoke", "windows-full", 2),
                                 ("windows-full", "nightly-slow-smoke", 2)):
        block = _job(job, next_job)
        commands = ["python -m pytest" + part.split("\n\n", 1)[0]
                    for part in block.split("python -m pytest")[1:]]
        assert len(commands) == count
        for command in commands:
            assert command.count(flag) == 1
            for event in ("workflow_dispatch", "pull_request", "push", "schedule"):
                tokens = shlex.split(command.replace(flag, "" if event == "workflow_dispatch" else "-x"))
                assert ("-x" in tokens) == (event != "workflow_dispatch")
        if job != "test":
            assert block.count("continue-on-error: ${{ github.event_name == 'workflow_dispatch' }}") == 2
            assert "id: serial" in block and "id: remaining" in block
    assert flag not in _job("nightly-slow-smoke", "result")


def test_manual_windows_final_checks_reject_any_incomplete_selection(record_property) -> None:
    checks = []
    for job, next_job in (("windows-smoke", "windows-full"), ("windows-full", "nightly-slow-smoke")):
        block = _job(job, next_job).split("      - name: Preserve manual selection failures\n", 1)[1]
        assert "if: always() && github.event_name == 'workflow_dispatch'" in block
        assert "SERIAL: ${{ steps.serial.outcome }}" in block
        assert "REMAINING: ${{ steps.remaining.outcome }}" in block
        script = block.split("        run: |\n", 1)[1].split("\n      - ", 1)[0]
        checks.append((job, textwrap.dedent(script)))
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell and os.name != "nt":
        pytest.skip("PowerShell is unavailable for executing the Windows CI outcome checks")
    assert shell, "PowerShell is required to verify Windows CI failure preservation"
    started = time.monotonic()
    # Share the watchdog across real shell starts and reserve time to reap failures.
    deadline = started + 30
    work_deadline = deadline - 2
    # shortcut: own fixed shell roots only; add tree ownership before scripts may spawn children.
    children = []
    record_property("manual_selection_shell", str(Path(shell).resolve()))
    try:
        for job, code in checks:
            for pair, (serial, remaining) in enumerate((("success", "success"), ("failure", "success"),
                                                       ("success", "failure"), ("failure", "failure"),
                                                       ("skipped", "success"), ("success", "skipped"),
                                                       ("", "success"), ("success", "")), 1):
                child = None
                stdout = stderr = ""
                failure = None
                row = {"block": job, "pair": pair, "serial": serial, "remaining": remaining,
                       "completed_before": len(children), "pid": None, "phase": "admission", "kill_requested": False,
                       "streams_complete": False, "cleanup_error": None}
                children.append(row)
                try:
                    allowance = work_deadline - time.monotonic()
                    row["work_remaining_seconds"] = allowance
                    if allowance <= 0:
                        raise subprocess.TimeoutExpired("manual selection check", 28)
                    child = subprocess.Popen([shell, "-NoLogo", "-NoProfile", "-Command", code],
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                             env={**os.environ, "SERIAL": serial, "REMAINING": remaining})
                    row["pid"] = child.pid
                    row["phase"] = "communication"
                    allowance = work_deadline - time.monotonic()
                    if allowance <= 0:
                        raise subprocess.TimeoutExpired("manual selection check", 28)
                    stdout, stderr = child.communicate(timeout=allowance)
                    row["streams_complete"] = True
                    row["phase"] = "return"
                    if time.monotonic() > work_deadline:
                        raise subprocess.TimeoutExpired("manual selection check", 28)
                    assert (child.returncode == 0) == (serial == remaining == "success"), stderr[-2000:]
                except BaseException as exc:
                    failure = exc
                    raise
                finally:
                    if child is not None and not row["streams_complete"]:
                        try:
                            if child.poll() is None:
                                row["kill_requested"] = True
                                child.kill()
                            stdout, stderr = child.communicate(timeout=max(0, deadline - time.monotonic()))
                            row["streams_complete"] = True
                        except BaseException as cleanup_error:
                            row["cleanup_error"] = type(cleanup_error).__name__
                    row.update(returncode=None if child is None else child.poll(),
                               elapsed_seconds=time.monotonic() - started,
                               stdout=stdout[-2000:], stderr=stderr[-2000:],
                               stdout_truncated=len(stdout) > 2000, stderr_truncated=len(stderr) > 2000)
                    row["exited"] = child is not None and row["returncode"] is not None
                    row["cleanup_complete"] = row["exited"] and row["streams_complete"] and row["cleanup_error"] is None
                    row["total_remaining_seconds"] = deadline - time.monotonic()
                    if failure is not None:
                        if isinstance(failure, subprocess.TimeoutExpired):
                            failure.cmd = "manual selection check"
                        failure.add_note(json.dumps(row))
                    else:
                        assert row["returncode"] is not None and row["streams_complete"], json.dumps(row)
        assert len(children) == 16
        assert time.monotonic() <= deadline, "manual selection checks exceeded their shared test watchdog"
    finally:
        record_property("manual_selection_children", json.dumps(children))


def test_windows_stop_verifier_runs_serially_for_pr_and_full_windows_lanes() -> None:
    node = "tests/test_service.py::test_windows_stop_verifier_executes_new_and_legacy_launcher_parsers"
    launcher = "tests/test_service_launcher_lifecycle.py"
    smoke = _job("windows-smoke", "windows-full")
    full = _job("windows-full", "nightly-slow-smoke")
    assert "github.event_name != 'pull_request'" not in smoke
    for block in (smoke, full):
        commands = re.findall(r"(?m)^\s+run: (python -m pytest .+)$", block)
        for path in (node, launcher):
            selected = [command for command in commands if path in command.split()]
            assert len(selected) == 1
            assert "-n 0" in selected[0]
    for path in (node, launcher):
        assert smoke.count(path) == 1
        assert full.count(path) == 2
    assert f"--deselect={node}" in full
    assert f"--ignore={launcher}" in full


def test_all_test_commands_report_slowest_tests() -> None:
    commands = WORKFLOW.split("python -m pytest")[1:]
    assert len(commands) >= 5
    assert all("--durations=20" in command.split("\n\n", 1)[0] for command in commands)


def test_retained_hook_deadline_runs_once_in_each_windows_lane() -> None:
    node = "tests/test_codex_retained_wake.py::test_session_start_lock_budget_claims_emits_and_acks_once"
    smoke = _job("windows-smoke", "windows-full")
    full = _job("windows-full", "nightly-slow-smoke")
    for block in (smoke, full):
        commands = re.findall(r"(?m)^\s+run: (python -m pytest .+)$", block)
        selected = [command for command in commands if node in command.split()]
        assert len(selected) == 1 and "-n 0" in selected[0]
    assert smoke.count(node) == 1
    assert full.count(node) == 2
    assert f"--deselect={node}" in full


def test_windows_full_runs_native_reconnect_serially_with_slow_cases() -> None:
    path = "tests/test_codex_retained_native_reconnect.py"
    full = _job("windows-full", "nightly-slow-smoke")
    commands = re.findall(r"(?m)^\s+run: (python -m pytest .+)$", full)
    serial, = [command for command in commands if path in command.split()]
    assert "-n 0" in serial and '-m "slow or not slow"' in serial
    assert f"--ignore={path}" in full
    assert full.count(path) == 2
    assert path not in _job("windows-smoke", "windows-full")


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


def _subprocess_qualification() -> dict:
    import yaml

    path = Path(__file__).parents[1] / ".github/workflows/subprocess-qualification.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _qualification_program(step_id: str) -> str:
    steps = _subprocess_qualification()["jobs"]["helper"]["steps"]
    step, = [step for step in steps if step.get("id") == step_id]
    return step["run"].split("$program = @'\n", 1)[1].split("\n'@", 1)[0]


def test_subprocess_qualification_fixed_pair_permissions_and_phase_budgets() -> None:
    workflow = _subprocess_qualification()
    events = workflow.get("on", workflow.get(True))
    assert isinstance(events, dict)
    assert set(events["workflow_dispatch"]["inputs"]) == {"candidate_revision"}
    assert events["workflow_dispatch"]["inputs"]["candidate_revision"]["required"] is True
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["group"] == "fixed-subprocess-helper-qualification"
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert set(workflow["jobs"]) == {"helper"}
    job = workflow["jobs"]["helper"]
    assert job["timeout-minutes"] == 15
    assert job["strategy"]["max-parallel"] == 1
    assert job["strategy"]["fail-fast"] is True
    pair = job["strategy"]["matrix"]["include"]
    assert [(x["os"], x["platform"]) for x in pair] == [
        ("ubuntu-24.04", "Linux"), ("windows-2025", "Windows")]
    assert job["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert job["env"]["PYTEST_ADDOPTS"] == job["env"]["PYTEST_PLUGINS"] == ""
    assert [x["timeout-minutes"] for x in job["steps"]] == [1, 1, 1, 2, 5, 1, 2, 1, 1]
    assert sum(x["timeout-minutes"] for x in job["steps"][:5]) == 10
    assert sum(x["timeout-minutes"] for x in job["steps"]) == 15
    assert [x["id"] for x in job["steps"]] == [
        "control", "candidate", "admission", "runtime", "dependencies",
        "collection", "execution", "evidence", "upload"]
    execution, = [x for x in job["steps"] if x["id"] == "execution"]
    evidence, = [x for x in job["steps"] if x["id"] == "evidence"]
    upload = job["steps"][-1]
    assert execution["continue-on-error"] is True
    assert evidence["if"] == "always()"
    assert evidence["env"]["SQ_EXECUTION_OUTCOME"] == "${{ steps.execution.outcome }}"
    assert "steps.evidence.outputs.upload_ready == 'true'" in upload["if"]
    assert upload["with"]["retention-days"] == 7
    assert upload["with"]["if-no-files-found"] == "error"


def test_subprocess_qualification_pins_are_control_owned_complete_and_preinstall() -> None:
    import hashlib

    job = _subprocess_qualification()["jobs"]["helper"]
    manifest = json.loads(job["env"]["SQ_MANIFEST"])
    assert manifest["authority"] == "manager-accepted-r1"
    assert manifest["files"] == {
        "tests/subprocess_helpers.py": "ff7290a8e6e12ad234931f2160a6a771622c49d56315c889c05703333e653c96",
        "tests/test_subprocess_helpers.py": "24ccbc18fa94d893c50054ad41500bdc370f431ce44693be0369ee1ed14f3a7b",
    }
    assert manifest["control_files"] == {
        "tests/__init__.py": "8d59fa56c515a193065022203626052e83ca7ae73f3f13bc9309022af61f5be0"}
    assert hashlib.sha256(manifest["pytest_ini"].encode()).hexdigest() == manifest["pytest_ini_sha256"]
    assert "tmp_path_retention_policy = all" in manifest["pytest_ini"]
    assert "tmp_path_retention_count = 1" in manifest["pytest_ini"]
    assert manifest["python_version"] == "3.13.18"
    assert set(manifest["case_counts"]) >= {
        "test_windows_setup_error_closes_allocated_handles_and_never_runs_target",
        "test_live_job_failure_uses_kill_on_close_in_disposable_runner",
        "test_real_sigint_deferral_and_handler_restoration_in_disposable_runner",
        "test_posix_auto_reaping_is_rejected_before_launch"}
    assert manifest["case_counts"]["test_windows_setup_error_closes_allocated_handles_and_never_runs_target"] == 8
    versions = {w["name"]: w["version"] for w in manifest["wheels"]}
    assert versions == {"pip": "26.3", "pytest": "9.2.0", "pytest-xdist": "3.8.0",
                        "execnet": "2.1.2", "iniconfig": "2.3.1", "packaging": "26.3",
                        "pluggy": "1.7.0", "pygments": "2.21.0", "colorama": "0.4.6"}
    for wheel in manifest["wheels"]:
        assert re.fullmatch("[a-f0-9]{64}", wheel["sha256"])
        assert wheel["filename"].endswith("none-any.whl")
        assert wheel["url"].startswith("https://files.pythonhosted.org/packages/")
        assert wheel["platforms"] == (["Windows"] if wheel["name"] == "colorama" else ["Linux", "Windows"])
    for variant in job["strategy"]["matrix"]["include"]:
        assert re.fullmatch("[a-f0-9]{64}", variant["runtime_sha256"])
        assert "/20261110/cpython-3.13.18%2B20261110-" in variant["runtime_url"]
    uses = [s["uses"] for s in job["steps"] if "uses" in s]
    assert uses == ["actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                    "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9"]
    steps = {s["id"]: s for s in job["steps"]}
    assert "SQ_ROOT" not in job["env"]
    for step_id in ("candidate", "evidence"):
        assert steps[step_id]["env"]["SQ_ROOT"].startswith("${{ runner.temp }}/")
    assert steps["candidate"]["env"]["SQ_ROOT"] == steps["evidence"]["env"]["SQ_ROOT"]
    assert "SQ_ROOT=$root" in steps["candidate"]["run"]
    assert steps["upload"]["with"]["path"] == "${{ steps.evidence.outputs.path }}"
    assert steps["control"]["with"]["ref"] == "${{ github.workflow_sha }}"
    assert steps["control"]["with"]["persist-credentials"] is False
    assert "Get-FileHash" in steps["runtime"]["run"]
    assert steps["runtime"]["run"].index("Get-FileHash") < steps["runtime"]["run"].index("tar -xzf")
    assert "--without-pip" in steps["dependencies"]["run"]
    assert "--require-hashes" in steps["dependencies"]["run"]
    assert "--no-index" in steps["dependencies"]["run"]
    assert "--no-deps" in steps["dependencies"]["run"]
    assert "--no-cache-dir" in steps["dependencies"]["run"]


def test_subprocess_qualification_stages_only_admitted_import_and_config_closure() -> None:
    steps = {s["id"]: s for s in _subprocess_qualification()["jobs"]["helper"]["steps"]}
    candidate = steps["candidate"]["run"]
    assert "^[a-f0-9]{40}$" in candidate and ".Trim()" not in candidate
    assert "refs/tags/subprocess-qualification-control-" in candidate
    assert "SQ_RUN_ATTEMPT -cne '1'" in candidate
    assert candidate.index("^[a-f0-9]{40}$") < candidate.index("git init --bare")
    assert "git init --bare" in candidate and "git checkout" not in candidate
    assert "cat-file blob" in steps["admission"]["run"]
    assert "control_files" in steps["admission"]["run"]
    assert "pytest_ini_sha256" in steps["admission"]["run"]
    for step_id in ("collection", "execution"):
        code = steps[step_id]["run"]
        for fixed in ("tests/test_subprocess_helpers.py", "--noconftest", "--import-mode=importlib",
                      "-o addopts=", "-o xfail_strict=true", "-m slow", "-n 0", "-p xdist.plugin", "-I -B"):
            assert fixed in code
        assert "-c (Join-Path" in code
        assert "pip install -e" not in code
    assert "--collect-only" in steps["collection"]["run"]
    assert "-x -q" in steps["execution"]["run"]
    assert "exit $code" in steps["execution"]["run"]


def _qualification_gate_fixture(tmp_path: Path, platform: str = "Linux") -> tuple[dict, dict, Path]:
    """Synthetic control-plane receipts only; never helper qualification evidence."""
    import hashlib
    import xml.etree.ElementTree as ET

    job = _subprocess_qualification()["jobs"]["helper"]
    manifest = json.loads(job["env"]["SQ_MANIFEST"])
    opposite = ("test_windows_creation_failure_prevents_target_execution" if platform == "Linux"
                else "test_posix_missing_waitid_fails_before_target_execution")
    manifest["case_counts"] = {"test_common": 1, opposite: 1}
    manifest["files"] = {"tests/subprocess_helpers.py": hashlib.sha256(b"helper").hexdigest(),
                         "tests/test_subprocess_helpers.py": hashlib.sha256(b"tests").hexdigest()}
    manifest["control_files"] = {"tests/__init__.py": hashlib.sha256(b"init").hexdigest()}
    root = tmp_path / "evidence hé 東京"
    work = root / "work"
    payload = root / "payload"
    work.mkdir(parents=True)
    for name, content in (("tests/subprocess_helpers.py", b"helper"),
                          ("tests/test_subprocess_helpers.py", b"tests"), ("tests/__init__.py", b"init")):
        path = payload / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (payload / "pytest.ini").write_bytes(manifest["pytest_ini"].encode("utf-8"))
    raw = json.dumps(manifest)
    environ = {**os.environ, "SQ_ROOT": str(root), "SQ_MANIFEST": raw, "SQ_PLATFORM": platform,
               "SQ_CONTROL": "a" * 40, "SQ_CANDIDATE": "b" * 40,
               "SQ_RUNTIME_SHA": "c" * 64, "SQ_EXECUTION_OUTCOME": "success"}
    source = {"control": environ["SQ_CONTROL"], "candidate": environ["SQ_CANDIDATE"],
              "manifest_sha256": hashlib.sha256(raw.encode()).hexdigest(),
              "files": {**manifest["files"], **manifest["control_files"]}}
    (work / "source.json").write_text(json.dumps(source), encoding="utf-8")
    (work / "runtime.json").write_text(json.dumps({"version": manifest["python_version"],
                                                  "artifact_sha256": environ["SQ_RUNTIME_SHA"]}), encoding="utf-8")
    distributions = {w["name"]: w["version"] for w in manifest["wheels"] if platform in w["platforms"]}
    (work / "dependencies.json").write_text(json.dumps({"distributions": distributions}), encoding="utf-8")
    ids = ["tests/test_subprocess_helpers.py::test_common[hé 東京]", "tests/test_subprocess_helpers.py::" + opposite]
    (work / "collection.json").write_text(json.dumps({"nodeids": ids}), encoding="utf-8")
    (work / "exit.json").write_text('{"code":0}', encoding="utf-8")
    (work / "stdout.txt").write_bytes(b"")
    (work / "stderr.txt").write_bytes(b"")
    suite = ET.Element("testsuite")
    for node in ids:
        case = ET.SubElement(suite, "testcase", classname="tests.test_subprocess_helpers", name=node.split("::")[1])
        if node.endswith(opposite):
            ET.SubElement(case, "skipped", type="pytest.skip", message=manifest["allowed_skips"][platform][opposite])
    (work / "results.xml").write_bytes(ET.tostring(suite, encoding="utf-8"))
    modes = ["signal_setup", "signal_cleanup"] + (["native_query", "native_terminate"] if platform == "Windows" else [])
    for mode in modes:
        path = work / "tests" / mode / "case-result.json"
        path.parent.mkdir(parents=True)
        report = {"ok": True, "mode": mode, "handler_restored": True, "leases_released": True,
                  "retained_root_exited": True, "resources_closed": True,
                  "native_failure_observed": mode.startswith("native_")}
        path.write_text(json.dumps(report), encoding="utf-8")
    return environ, manifest, root


@pytest.mark.parametrize("platform", ["Linux", "Windows"])
@pytest.mark.parametrize("stream_size", [0, 65536])
@pytest.mark.parametrize("metadata_size", [0, 1048576])
def test_subprocess_qualification_evidence_accepts_complete_synthetic_boundaries(tmp_path, platform, stream_size, metadata_size):
    environ, _, root = _qualification_gate_fixture(tmp_path, platform)
    for stream in ("stdout.txt", "stderr.txt"):
        (root / "work" / stream).write_bytes(b"x" * stream_size)
    if metadata_size:
        for filename in ("results.xml", "collection.json"):
            path = root / "work" / filename
            path.write_bytes(path.read_bytes().ljust(metadata_size, b" "))
        for path in (root / "work/tests").rglob("case-result.json"):
            path.write_bytes(path.read_bytes().ljust(8192, b" "))
    result = subprocess.run([sys.executable, "-I", "-B", "-c", _qualification_program("evidence")],
                            env=environ, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    summary = json.loads((root / "normalized/summary.json").read_text(encoding="utf-8"))
    assert summary["complete"] is True


@pytest.mark.parametrize("fault", [
    "missing-junit", "empty-junit", "invalid-xml", "duplicate-case", "missing-case", "extra-case",
    "unexpected-skip", "missing-opposite-skip", "xfail", "failure", "error", "class-drift",
    "empty-collection", "duplicate-collection", "inventory-drift", "missing-collection",
    "execution-failure", "execution-cancelled", "execution-skipped", "missing-exit", "nonzero-exit",
    "missing-source", "control-drift", "candidate-drift", "manifest-drift", "source-drift", "config-drift",
    "missing-runtime", "runtime-version", "runtime-digest", "missing-dependencies", "dependency-drift",
    "stdout-over", "stderr-over", "junit-over", "collection-over", "missing-case-report",
    "duplicate-case-report", "case-report-over", "case-not-released", "unexpected-case-key",
])
def test_subprocess_qualification_evidence_rejects_incomplete_or_unapproved_receipts(tmp_path, fault):
    import xml.etree.ElementTree as ET

    environ, _, root = _qualification_gate_fixture(tmp_path)
    work = root / "work"
    if fault in {"missing-junit", "missing-collection", "missing-exit", "missing-source", "missing-runtime", "missing-dependencies"}:
        name = {"junit": "results.xml", "collection": "collection.json", "exit": "exit.json",
                "source": "source.json", "runtime": "runtime.json", "dependencies": "dependencies.json"}[fault[8:]]
        (work / name).unlink()
    elif fault in {"empty-junit", "invalid-xml", "junit-over", "collection-over", "stdout-over", "stderr-over"}:
        name, content = {"empty-junit": ("results.xml", b"<testsuite/>"), "invalid-xml": ("results.xml", b"<bad"),
                         "junit-over": ("results.xml", b"x" * (1048576 + 1)),
                         "collection-over": ("collection.json", b"x" * (1048576 + 1)),
                         "stdout-over": ("stdout.txt", b"x" * (65536 + 1)),
                         "stderr-over": ("stderr.txt", b"x" * (65536 + 1))}[fault]
        (work / name).write_bytes(content)
    elif fault.startswith("execution-"):
        environ["SQ_EXECUTION_OUTCOME"] = fault[10:]
    elif fault == "nonzero-exit":
        (work / "exit.json").write_text('{"code":1}', encoding="utf-8")
    elif fault in {"empty-collection", "duplicate-collection", "inventory-drift"}:
        data = json.loads((work / "collection.json").read_text())
        data["nodeids"] = ([] if fault == "empty-collection" else data["nodeids"] * 2 if fault == "duplicate-collection"
                           else ["tests/test_subprocess_helpers.py::test_other"])
        (work / "collection.json").write_text(json.dumps(data), encoding="utf-8")
    elif fault in {"control-drift", "candidate-drift", "manifest-drift", "runtime-version", "runtime-digest", "dependency-drift"}:
        filename, key = {"control-drift": ("source.json", "control"), "candidate-drift": ("source.json", "candidate"),
                         "manifest-drift": ("source.json", "manifest_sha256"), "runtime-version": ("runtime.json", "version"),
                         "runtime-digest": ("runtime.json", "artifact_sha256"), "dependency-drift": ("dependencies.json", "distributions")}[fault]
        data = json.loads((work / filename).read_text())
        data[key] = {} if key == "distributions" else "drift"
        (work / filename).write_text(json.dumps(data), encoding="utf-8")
    elif fault in {"source-drift", "config-drift"}:
        (root / "payload" / ("pytest.ini" if fault == "config-drift" else "tests/subprocess_helpers.py")).write_bytes(b"drift")
    elif "case-report" in fault or fault in {"case-not-released", "unexpected-case-key"}:
        path = work / "tests/signal_setup/case-result.json"
        if fault == "missing-case-report":
            path.unlink()
        elif fault == "duplicate-case-report":
            other = work / "tests/duplicate/case-result.json"
            other.parent.mkdir()
            other.write_bytes(path.read_bytes())
        elif fault == "case-report-over":
            path.write_bytes(b"x" * 8193)
        else:
            data = json.loads(path.read_text())
            data["leases_released" if fault == "case-not-released" else "unexpected"] = False
            path.write_text(json.dumps(data), encoding="utf-8")
    else:
        tree = ET.parse(work / "results.xml")
        suite = tree.getroot()
        case = suite[0]
        if fault == "duplicate-case":
            suite.append(ET.fromstring(ET.tostring(case)))
        elif fault == "missing-case":
            suite.remove(case)
        elif fault == "extra-case":
            ET.SubElement(suite, "testcase", classname="tests.test_subprocess_helpers", name="test_extra")
        elif fault == "missing-opposite-skip":
            suite[1].remove(suite[1][0])
        elif fault == "class-drift":
            case.set("classname", "other.module")
        else:
            ET.SubElement(case, "skipped" if fault in {"unexpected-skip", "xfail"} else fault,
                          type="pytest.xfail" if fault == "xfail" else "pytest.skip", message="unexpected")
        tree.write(work / "results.xml", encoding="utf-8")
    result = subprocess.run([sys.executable, "-I", "-B", "-c", _qualification_program("evidence")],
                            env=environ, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0, fault
    summary = json.loads((root / "normalized/summary.json").read_text(encoding="utf-8"))
    assert summary["complete"] is False
    assert all(p.stat().st_size <= 1048576 for p in (root / "normalized").iterdir())


@pytest.mark.parametrize(("outcome", "code"), [("failure", 1), ("cancelled", None), ("failure", None)])
def test_subprocess_qualification_retains_partial_failure_receipts(tmp_path, outcome, code):
    import xml.etree.ElementTree as ET

    environ, _, root = _qualification_gate_fixture(tmp_path)
    environ["SQ_EXECUTION_OUTCOME"] = outcome
    work = root / "work"
    if code is None:
        (work / "exit.json").unlink()
        (work / "results.xml").unlink()
    else:
        (work / "exit.json").write_text(json.dumps({"code": code}), encoding="utf-8")
        tree = ET.parse(work / "results.xml")
        suite = tree.getroot()
        suite.remove(suite[1])
        ET.SubElement(suite[0], "failure", message="fixture assertion")
        tree.write(work / "results.xml", encoding="utf-8")
    (work / "stdout.txt").write_bytes(b"fixture stdout")
    (work / "stderr.txt").write_bytes(b"fixture stderr")

    result = subprocess.run([sys.executable, "-I", "-B", "-c", _qualification_program("evidence")],
                            env=environ, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1, result.stderr
    normalized = root / "normalized"
    summary = json.loads((normalized / "summary.json").read_text(encoding="utf-8"))
    assert summary["complete"] is False
    assert (summary["execution_outcome"], summary["exit_code"]) == (outcome, code)
    assert (normalized / "stdout.txt").read_bytes() == b"fixture stdout"
    assert (normalized / "stderr.txt").read_bytes() == b"fixture stderr"
    if code is None:
        assert "missing-or-invalid-exit" in summary["errors"]
        assert not (normalized / "results.xml").exists()
    else:
        assert (normalized / "results.xml").read_bytes() == (work / "results.xml").read_bytes()


def _qualification_powershell(step_id: str, tmp_path: Path, environ: dict) -> subprocess.CompletedProcess:
    shell = shutil.which("pwsh")
    assert shell, "PowerShell 7.4+ is required for hosted workflow-contract coverage"
    step, = [s for s in _subprocess_qualification()["jobs"]["helper"]["steps"] if s["id"] == step_id]
    script = tmp_path / (step_id + ".ps1")
    script.write_text(step["run"], encoding="utf-8")
    return subprocess.run([shell, "-NoLogo", "-NoProfile", "-File", str(script)], env=environ,
                          capture_output=True, text=True, timeout=20)


@pytest.mark.parametrize("candidate", ["", "main", "a" * 39, "a" * 41, "A" * 40,
                                     "a" * 40 + "\n", " " + "a" * 40, "é" * 40, "東京"])
def test_subprocess_qualification_rejects_raw_invalid_refs_before_git_or_writes(tmp_path, candidate):
    root = tmp_path / "new-job"
    environ = {**os.environ, "SQ_CANDIDATE": candidate, "SQ_CONTROL": "a" * 40,
               "SQ_REF": "refs/tags/subprocess-qualification-control-" + "a" * 40,
               "GITHUB_SHA": "a" * 40, "SQ_RUN_ATTEMPT": "1", "GITHUB_EVENT_NAME": "workflow_dispatch",
               "GITHUB_SERVER_URL": "https://github.com", "RUNNER_ENVIRONMENT": "github-hosted",
               "RUNNER_ARCH": "X64", "RUNNER_OS": "Linux", "SQ_PLATFORM": "Linux",
               "ImageOS": "synthetic", "ImageVersion": "synthetic", "RUNNER_TEMP": str(tmp_path),
               "SQ_ROOT": str(root), "GITHUB_REPOSITORY": "example/fixture",
               "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "protocol.https.allow", "GIT_CONFIG_VALUE_0": "never"}
    result = _qualification_powershell("candidate", tmp_path, environ)
    assert result.returncode != 0
    assert "Unmodified lowercase full candidate SHA required" in result.stderr
    assert not root.exists()


@pytest.mark.parametrize("override", [
    {"SQ_REF": "refs/heads/main"}, {"GITHUB_SHA": "b" * 40}, {"SQ_CONTROL": "A" * 40},
    {"SQ_RUN_ATTEMPT": "2"}, {"GITHUB_EVENT_NAME": "pull_request"},
    {"RUNNER_ENVIRONMENT": "self-hosted"}, {"RUNNER_ARCH": "ARM64"}, {"RUNNER_OS": "Windows"},
    {"ImageVersion": ""},
])
def test_subprocess_qualification_rejects_changed_control_rerun_and_host_before_writes(tmp_path, override):
    root = tmp_path / "new-job"
    environ = {**os.environ, "SQ_CANDIDATE": "a" * 40, "SQ_CONTROL": "a" * 40,
               "SQ_REF": "refs/tags/subprocess-qualification-control-" + "a" * 40,
               "GITHUB_SHA": "a" * 40, "SQ_RUN_ATTEMPT": "1", "GITHUB_EVENT_NAME": "workflow_dispatch",
               "GITHUB_SERVER_URL": "https://github.com", "RUNNER_ENVIRONMENT": "github-hosted",
               "RUNNER_ARCH": "X64", "RUNNER_OS": "Linux", "SQ_PLATFORM": "Linux",
               "ImageOS": "synthetic", "ImageVersion": "synthetic", "RUNNER_TEMP": str(tmp_path),
               "SQ_ROOT": str(root), "GITHUB_REPOSITORY": "example/fixture",
               "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "protocol.https.allow", "GIT_CONFIG_VALUE_0": "never",
               **override}
    result = _qualification_powershell("candidate", tmp_path, environ)
    assert result.returncode != 0 and not root.exists()


@pytest.mark.parametrize("fault", [None, "payload-drift", "control-drift", "candidate-authority", "missing-wheel-pin", "second-admission", "tag-object"])
def test_subprocess_qualification_admits_only_control_approved_git_blobs(tmp_path, fault):
    import hashlib

    root = tmp_path / "job hé 東京"
    workspace = tmp_path / "workspace"
    control = workspace / "control"
    control.mkdir(parents=True)
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=control, text=True).strip()
    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("config", "core.autocrlf", "false")
    manifest = json.loads(_subprocess_qualification()["jobs"]["helper"]["env"]["SQ_MANIFEST"])
    for rel, data in (("tests/subprocess_helpers.py", b"helper\n"), ("tests/test_subprocess_helpers.py", b"tests\n"),
                      ("tests/__init__.py", b"init\n")):
        path = control / rel
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        manifest["control_files" if rel.endswith("__init__.py") else "files"][rel] = hashlib.sha256(data).hexdigest()
    git("add", ".")
    git("commit", "-m", "fixture")
    commit = git("rev-parse", "HEAD")
    candidate_ref = commit
    if fault == "tag-object":
        git("tag", "-a", "fixture-tag", "-m", "fixture")
        candidate_ref = git("rev-parse", "refs/tags/fixture-tag")
    (root / "work").mkdir(parents=True)
    candidate = root / "candidate.git"
    git("init", "--bare", str(candidate))
    git("--git-dir=" + str(candidate), "fetch", "--no-tags", str(control), candidate_ref)
    variant = _subprocess_qualification()["jobs"]["helper"]["strategy"]["matrix"]["include"][0]
    if fault == "payload-drift":
        manifest["files"]["tests/subprocess_helpers.py"] = "0" * 64
    elif fault == "candidate-authority":
        manifest["authority"] = "candidate"
    elif fault == "missing-wheel-pin":
        manifest["wheels"][0]["sha256"] = ""
    environ = {**os.environ, "SQ_ROOT": str(root), "SQ_MANIFEST": json.dumps(manifest),
               "GITHUB_WORKSPACE": str(workspace), "SQ_CONTROL": "0" * 40 if fault == "control-drift" else commit,
               "SQ_CANDIDATE": candidate_ref, "SQ_RUNTIME_SHA": variant["runtime_sha256"], "SQ_RUNTIME_URL": variant["runtime_url"]}
    result = _qualification_powershell("admission", tmp_path, environ)
    if fault in {None, "second-admission"}:
        assert result.returncode == 0, result.stderr
        for rel, digest in {**manifest["files"], **manifest["control_files"]}.items():
            assert hashlib.sha256((root / "payload" / rel).read_bytes()).hexdigest() == digest
        if fault == "second-admission":
            assert _qualification_powershell("admission", tmp_path, environ).returncode != 0
    else:
        assert result.returncode != 0, fault
        if fault == "tag-object":
            assert "Candidate must be a commit object" in result.stderr
            assert not (root / "payload").exists()


@pytest.mark.parametrize("target", ["normalized", "work", "payload/tests", "work/results.xml"])
def test_subprocess_qualification_evidence_rejects_symlink_escape_without_overwriting(tmp_path, target):
    environ, _, root = _qualification_gate_fixture(tmp_path)
    path = root / target
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("unchanged", encoding="utf-8")
    if path.exists():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    path.symlink_to(outside, target_is_directory=True)
    result = subprocess.run([sys.executable, "-I", "-B", "-c", _qualification_program("evidence")],
                            env=environ, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert {p.name for p in outside.iterdir()} == {"sentinel"}
    assert sentinel.read_text(encoding="utf-8") == "unchanged"
