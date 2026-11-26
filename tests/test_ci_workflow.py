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


def test_opencode_settlement_qualification_keeps_exact_regression_and_bounded_native_selection() -> None:
    import yaml

    root = Path(__file__).parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/opencode-native-qualification.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["qualify"]
    assert job["runs-on"] == "windows-latest" and job["timeout-minutes"] == 15
    assert "continue-on-error" not in job
    assert "github.run_attempt == 1" in job["if"]
    assert "github.event.label.name == 'qualify-opencode-2.3.0'" in job["if"]
    assert "github.event.pull_request.head.repo.full_name == github.repository" in job["if"]
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert workflow["permissions"] == {"contents": "read"}
    assert job["env"]["BASELINE"] == "93f497bf0eed29659630c277626d821d24964524"
    steps = {step["id"]: step for step in job["steps"] if "id" in step}
    assert job["env"]["OPENCODE_ARCHIVE_SHA256"] == "2e14eee53f4abad803d55fdc472c1b12dc3802d687ae204f81e7908bd2ab1895"
    assert "releases/download/v2.3.0/opencode-windows-x64.zip" in steps["setup"]["run"]
    assert "Length -ne 124586665" in steps["setup"]["run"]
    assert "opencode v2.3.0" in steps["setup"]["run"] and "PALLIUM_OPENCODE_BINARY_VERSION=2.3.0" in steps["setup"]["run"]
    assert list(steps) == ["setup", "baseline", "focused", "package", "native", "backend"]
    for phase in steps.values():
        assert "if" not in phase and "continue-on-error" not in phase
    assert steps["package"]["timeout-minutes"] == 2
    focused = "coalesced native wake settles from exact outcome-bearing idle: succeeded"
    root_focused = "fresh supersession settles exact frozen generation: succeeded"
    admission_focused = "known admitted wake reentry preserves admission and uncertainty"
    git_focused = "Git discovery yields to unrelated caller work while child waits"
    for phase in ("baseline", "focused"):
        assert f"--test-name-pattern='^({focused}|{root_focused}|{admission_focused}|{git_focused})$'" in steps[phase]["run"]
        assert "startup empty discovery" not in steps[phase]["run"]
    assert "coalesced exact wake must settle activation without replay" in steps["baseline"]["run"]
    assert "fresh promoted ordinary work must release the missing admitted anchor" in steps["baseline"]["run"]
    assert "known admitted wake must not rewrite admission" in steps["baseline"]["run"]
    assert "Git discovery must yield to unrelated caller work" in steps["baseline"]["run"]
    assert "$exit -ne 1 -or $selected.Count -ne 4 -or $failed.Count -ne 4" in steps["baseline"]["run"]
    assert "$case.Count -ne 1" in steps["baseline"]["run"] and "[regex]::Escape($expected[$name])" in steps["baseline"]["run"]
    assert "$selected.Count -ne 4" in steps["focused"]["run"] and "$case.Count -ne 1" in steps["focused"]["run"]
    for name in (focused, root_focused, admission_focused, git_focused):
        assert name in steps["baseline"]["run"] and name in steps["focused"]["run"]
    preflight = steps["package"]["run"]
    for name in ("test_opencode_qualification_executes_embedded_failure_locator", "test_opencode_recovery_payload_oracle_rejects_extra_presentation"):
        assert f"tests/test_ci_workflow.py::{name}" in preflight and f"'{name}'" in preflight
    assert preflight.index("python -m pytest") < preflight.index("npm --prefix integrations/opencode")
    assert "--noconftest -q -n 0" in preflight
    assert "$checks.Count -ne 2" in preflight and "$check.Count -ne 1" in preflight
    assert "//testcase[skipped or failure or error]" in preflight
    assert '$env:NEW_CASES + "`n" + $env:ASYNC_CASES' in preflight
    sources = re.search(r"foreach \(\$path in @\(([^)]+)\)\)", steps["setup"]["run"])[1]
    assert set(re.findall(r"'([^']+)'", sources)) == {
        "integrations/opencode/.opencode/plugins/pallium-v2.mjs",
        "integrations/opencode/.opencode/plugins/pallium-common.mjs",
        "integrations/opencode/tests/v2-plugin.test.mjs",
        "tests/test_opencode_native_wake_e2e.py", "tests/test_opencode_relay_wake_e2e.py",
        "tests/test_ci_workflow.py", ".github/workflows/opencode-native-qualification.yml",
        "integrations/opencode/.opencode/plugins/pallium.mjs",
        "integrations/opencode/tests/common.test.mjs", "integrations/opencode/tests/plugin.test.mjs",
        "tests/test_stable_actor_identity_e2e.py",
    }
    backend = steps["backend"]["run"]
    command, = [line.strip() for line in backend.splitlines() if line.strip().startswith("python ")]
    assert shlex.split(command) == ["python", "-u", "-m", "pytest",
        "tests/test_opencode_relay_wake_e2e.py::test_activation_settlement_preserves_original_authority_before_backlog",
        "tests/test_opencode_relay_wake_e2e.py::test_stale_or_wrong_binding_is_rejected", "-vv", "-n", "0",
        "--junitxml=$env:QUALIFICATION_ROOT/raw/backend.xml", "*>", "$env:QUALIFICATION_ROOT/raw/backend.log"]
    assert "tests/test_ci_workflow.py" not in backend
    assert "$cases.Count -ne 25" in backend and "$states.Count -ne 4" in backend
    assert "$env:HTTP_CASES" in backend and "$selected.Count -ne 1" in backend
    assert "//testcase[skipped or failure or error]" in backend
    assert steps["backend"]["timeout-minutes"] == 1
    assert "-gt 660) { throw 'Insufficient HTTP/cleanup reserve' }" in backend
    native = steps["native"]["run"]
    assert "-gt 540) { throw 'Insufficient native/HTTP/cleanup reserve' }" in native
    assert "test_released_native_coalesced_settlement_and_automatic_backlog -m slow -q -n 0" in native
    assert "--tb=short" in native
    assert "$cases.Count -ne 1 -or $cases[0].skipped" in native
    assert "PALLIUM_OPENCODE_COALESCED_SUMMARY" in native and ".Count -ne 13" in native
    assert "$summary.fresh_supersession_reload_recovery -cne $true" in native
    assert steps["native"]["timeout-minutes"] == 2
    drain = next(step for step in job["steps"] if step.get("name") == "Verify owned drain and produce public-safe evidence")
    assert drain["if"] == "always()" and drain["timeout-minutes"] == 1
    evidence = drain["run"]
    assert "'expected_host_version': '2.3.0'" in evidence
    for key in ("ordered_coalesced_outcome", "lost_terminal_reply_reconciled", "automatic_backlog_over_two",
                "terminal_reload_safe", "missing_proof_compaction_hold", "missing_proof_reload_hold", "fresh_supersession_reload_recovery"):
        assert key in evidence
    assert "if expected and line.startswith(node):" in evidence
    assert "('PASSED', 'FAILED', 'ERROR', 'SKIPPED') else 'started'" in evidence
    assert "progress.append({'case': sanitize(expected), 'state': state})" in evidence
    assert "item['progress'] = progress[-25:]" in evidence
    assert "inventory_key = 'new_cases' if name == 'package' else 'required_cases'" in evidence
    assert "os.environ['NEW_CASES' if name == 'package' else 'HTTP_CASES']" in evidence
    assert "item['async_cases']" in evidence and "os.environ['ASYNC_CASES']" in evidence
    uploads = [step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@")]
    assert len(uploads) == 1 and uploads[0]["with"]["path"].endswith("/public/summary.json")
    assert uploads[0]["if"] == "always()" and uploads[0]["timeout-minutes"] == 1


def test_opencode_qualification_executes_embedded_failure_locator(monkeypatch) -> None:
    import ast
    import yaml

    workflow = yaml.safe_load((Path(__file__).parents[1] / ".github/workflows/opencode-native-qualification.yml").read_text(encoding="utf-8"))
    evidence = next(step["run"] for step in workflow["jobs"]["qualify"]["steps"]
                    if step.get("name") == "Verify owned drain and produce public-safe evidence")
    code = evidence.split("@'\n", 1)[1].split("\n'@", 1)[0]
    functions = [node for node in ast.parse(code).body if isinstance(node, ast.FunctionDef)
                 and node.name in ("sanitize", "failure_locator", "failure_details")]
    assert len(functions) == 3
    namespace = {"re": re, "os": os}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<embedded-evidence>", "exec"), namespace)
    details, locate = namespace["failure_details"], namespace["failure_locator"]
    checkout = "C:/qualification/checkout"
    monkeypatch.setenv("GITHUB_WORKSPACE", checkout)
    native = "tests/test_opencode_native_wake_e2e.py"
    http = "tests/test_opencode_relay_wake_e2e.py"
    noise = [f'    assert provider_status_{i} == "source noise"' for i in range(30)]
    late = [f"{native}:190: in test_wrapper", f"{native}:610: in helper", f"{native}:610: AssertionError"]
    result = details("\n".join(noise + late))
    locator = result["locator"]
    assert len(result["lines"]) == 24 and result["truncated"] is True
    assert locator == {"state": "captured", "frames": [
        {"file": native, "line": 190, "kind": "frame"},
        {"file": native, "line": 610, "kind": "frame"},
        {"file": native, "line": 610, "kind": "footer"}],
        "order": "observed_tail", "frames_truncated": False, "frames_omitted_prefix": 0,
        "exception_state": "captured", "exception_classes": ["AssertionError"]}
    windows = f"{checkout}/{native}:610: AssertionError".replace("/", "\\")
    assert locate(windows, checkout.replace("/", "\\"))["frames"] == [locator["frames"][-1]]
    assert locate(f"/qualification/checkout/{native}:610: AssertionError", "/qualification/checkout")["frames"] == [locator["frames"][-1]]
    wrapper = locate(late[0], checkout)
    assert wrapper["frames"] == [locator["frames"][0]] and wrapper["exception_state"] == "missing"
    assert locate(f"{http}:216: ValueError", checkout)["exception_classes"] == ["ValueError"]
    for forged in (f"C:/outside/{native}:610: AssertionError",
                   f"{checkout}-other/{native}:610: AssertionError",
                   f"{checkout}/../{native}:610: AssertionError",
                   f"tests/../{native}:610: AssertionError",
                   f"{native}:0: AssertionError", f"{native}:9999999999: AssertionError",
                   f"{native}:NaN: AssertionError", f"{native}:610: CustomError",
                   f"{native}:610: in helper arbitrary suffix",
                   f"{native}:610: AssertionError: runtime value",
                   f'    "{native}:610: AssertionError"', f">   {native}:610: in helper",
                   f'print("{native}:610: AssertionError")', f"    {native}:610: in helper",
                   f"/outside/{native}:610: AssertionError",
                   "tests/test_ci_workflow.py:1: AssertionError"):
        rejected = locate(forged, checkout)
        assert rejected["state"] == "unparseable" and rejected["frames"] == []
        assert rejected["exception_classes"] == []
    for missing in ("", "no traceback retained"):
        absent = locate(missing, checkout)
        assert absent["state"] == absent["exception_state"] == "missing" and absent["frames"] == []
    unknown = locate("E   CustomError: private message", checkout)
    assert unknown["exception_state"] == "unparseable" and unknown["exception_classes"] == []
    private = '\n'.join((
        '{"payload": "provider-private-body", "apiKey": "credential-value"}',
        '    local = "C:/private/profile/secret.txt"',
        f'E   RuntimeError: provider-private-body credential-value C:/private/profile/secret.txt {native}:4: in forged'))
    safe = details("\n".join(noise + late + [private]))["locator"]
    assert safe["frames"] == locator["frames"] and safe["exception_classes"] == ["AssertionError", "RuntimeError"]
    for forbidden in ("provider-private-body", "credential-value", "C:/", "private/profile", "local =", "apiKey", "payload"):
        assert forbidden not in json.dumps(safe)
    bounded = locate("\n".join(f"{native}:{i}: in helper" for i in range(1, 13)), checkout)
    assert bounded["order"] == "observed_tail" and bounded["frames_truncated"] is True
    assert bounded["frames_omitted_prefix"] == 4 and [frame["line"] for frame in bounded["frames"]] == list(range(5, 13))
    assert bounded["exception_state"] == "missing" and bounded["exception_classes"] == []
    exact = locate("\n".join(f"{native}:{i}: in helper" for i in range(1, 9)), checkout)
    assert len(exact["frames"]) == 8 and exact["frames_truncated"] is False and exact["frames_omitted_prefix"] == 0
    classes = ["AssertionError", "RuntimeError", "TimeoutError", "ValueError", "TypeError", "OSError", "Failed"]
    classes_only = locate("\n".join(f"E   {name}: private-value" for name in classes * 3), checkout)
    assert classes_only["state"] == "missing" and classes_only["frames"] == []
    assert classes_only["exception_state"] == "captured" and classes_only["exception_classes"] == classes
    assert "private-value" not in json.dumps(classes_only)
    assert len(json.dumps(locate("\n".join(late * 10 + [private]), checkout))) < 2048


def test_opencode_recovery_payload_oracle_rejects_extra_presentation() -> None:
    import ast

    source = (Path(__file__).parents[1] / "tests/test_opencode_native_wake_e2e.py").read_text(encoding="utf-8")
    functions = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef)
                 and node.name == "assert_no_original_presentation"]
    assert len(functions) == 1
    namespace = {"json": json, "original_payload": "original-payload-界", "root_payload_count": 1}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<native-payload-oracle>", "exec"), namespace)
    check = namespace["assert_no_original_presentation"]
    requests = [{"messages": [{"role": "user", "content": namespace["original_payload"]}]}]
    counters = {"acks": 1, "admissions": 1, "prompts": 1, "attempts": 1}
    before = counters.copy()
    check(requests)
    replay = {"messages": [{"role": "user", "content": namespace["original_payload"]}], "fixture_input_id": "msg_fresh_recovery_ordinary"}
    with pytest.raises(AssertionError, match="original payload re-presented"):
        check([*requests, replay])
    assert counters == before
    check(requests)  # Copied evidence did not dispatch or mutate the real list.
    assert source.index("root_payload_count =") < source.index('api("POST", prefix + "/prompt", {"id": "msg_fresh_recovery_ordinary"')
    assert source.count("assert_no_original_presentation(requests)") == 2


def test_opencode_primary_observer_actual_identity_and_lifecycle(tmp_path) -> None:
    """Run the fixture's real embedded observer without importing the app or host."""
    source = (Path(__file__).parents[1] / "tests/test_opencode_native_wake_e2e.py").read_text(encoding="utf-8")
    observer = source.split("// FIRST_PRIMARY_OBSERVER_START\n", 1)[1].split("// FIRST_PRIMARY_OBSERVER_END", 1)[0]
    node = shutil.which("node")
    assert node, "Node is required for the actual fixture observer controls"
    checks = r"""
import assert from 'node:assert/strict';
const session='ses_fixture', input='msg_original', delivery='relay-delivery-'+'a'.repeat(32);
const args=()=>({sessionID:session,id:input,metadata:{delivery_id:delivery,generation:1}});
const event=(id=input,sid=session)=>({sessionID:sid,messages:[{id,role:'user'}]});
const request=(kind='primary',sid=session)=>({kind,sessionID:sid,request:new Request('http://fixture.invalid/v1',{
 method:'POST',headers:{'x-existing':'kept'},body:'unchanged body'})});
const header=e=>JSON.parse(e.request.headers.get('x-pallium-fixture'));
const oracleTags=[];
const ready=()=>{const b=primaryBoundary('fixture-instance');b.prompt(args());const t=b.enter(event());b.complete(t,true);return b;};
{
 const b=ready(), e=request(), original=e.request;
 for(const name of ['clone','text','json','arrayBuffer'])Object.defineProperty(e.request,name,{value(){throw Error('observer read body');}});
 Object.defineProperty(e.request,'body',{get(){throw Error('observer accessed body');}});
 b.observe(e);
 const tag=header(e);assert.equal(tag.error,null);assert.equal(tag.completed,true);
 assert.equal(tag.input,input);assert.deepEqual(tag.expected,{session,input,delivery,generation:1});
 assert.equal(e.request,original);assert.equal(e.request.headers.get('x-existing'),'kept');assert.equal(e.request.bodyUsed,false);
 assert.equal(await Request.prototype.text.call(e.request),'unchanged body');
 const later=request();b.observe(later);assert.equal(header(later).prefix,false);
}
for(const kind of ['title','compaction','generate']){
 const b=ready(), aux=request(kind);b.observe(aux);
 assert.equal(header(aux).kind,kind);assert.equal(header(aux).prefix,undefined);
 const primary=request();b.observe(primary);assert.equal(header(primary).error,null);
}
for(const fault of ['no-prompt','wrong-session','wrong-input','wrong-delivery','fraction','incomplete','throw','overlap','stale','second-prompt','duplicate-completion']){
 const b=primaryBoundary('fixture-instance');
 if(fault!=='no-prompt'){const a=args();if(fault==='wrong-delivery')a.metadata.delivery_id='bad';
  if(fault==='fraction')a.metadata.generation=.5;b.prompt(a);}
 const first=b.enter(event(fault==='wrong-input'?'msg_other':input,fault==='wrong-session'?'ses_other':session));
 if(fault==='overlap'||fault==='stale'){
  const next=b.enter(event());b.complete(next,true);b.complete(first,true);
 }else if(fault!=='incomplete')b.complete(first,fault!=='throw');
 if(fault==='duplicate-completion')b.complete(first,true);
 if(fault==='second-prompt')b.prompt(args());
 const e=request();b.observe(e);assert.ok(header(e).error,fault);
 const next=b.enter(event());b.complete(next,true);const later=request();b.observe(later);
 assert.equal(header(later).prefix,false,`${fault}: later good cannot republish first pairing`);
}
// Ordinary early return and an ACK-negative resolved callback are not success filters.
for(const callback of [()=>undefined,()=>({success:false,error:'ack_failed'})]){
 const b=primaryBoundary('fixture-instance');b.prompt(args());const t=b.enter(event());
 await callback();b.complete(t,true);const e=request();b.observe(e);
 assert.equal(header(e).completed,true);assert.equal(header(e).error,null);
 oracleTags.push(header(e));
}
{
 const b=ready(), bad=request('primary','ses_other');b.observe(bad);assert.ok(header(bad).error);
 const good=request();b.observe(good);assert.equal(header(good).prefix,false);
}
for(const fault of ['none','registration','setup','production-cleanup','observer-dispose','both-cleanups','foreign-fetch']){
 const b=ready();let disposed=0,restored=0,cleaned=0,registered=0,callback;
 const savedFetch=globalThis.fetch,originalFetch=()=>1,observedFetch=()=>2,foreignFetch=()=>3,bootstrap=false,coalesced=true;
 globalThis.fetch=fault==='foreign-fetch'?foreignFetch:observedFetch;
 /* ACTUAL_OWNED_FETCH_RESTORE */
 const restoreAndCount=()=>{restored++;restore();};
 const native={session:{hook:async(name,fn)=>{
  assert.equal(name,'http.request');registered++;callback=fn;
  if(fault==='registration')throw Error(fault);
  return {dispose:async()=>{disposed++;if(['observer-dispose','both-cleanups'].includes(fault))throw Error(fault);}};
 }}};
 const setup=async()=>{if(fault==='setup')throw Error(fault);return async()=>{
  cleaned++;const late=request();callback(late);assert.equal(late.request.headers.has('x-pallium-fixture'),false);
  if(['production-cleanup','both-cleanups'].includes(fault))throw Error(fault);
 };};
 let cleanup;
 if(['setup','registration'].includes(fault))await assert.rejects(b.attach(native,setup,restoreAndCount));
 else{
  cleanup=await b.attach(native,setup,restoreAndCount);
  const closing=cleanup(); // Invalidates synchronously, before production cleanup can await.
  const late=request();callback(late);assert.equal(late.request.headers.has('x-pallium-fixture'),false);
  if(['none','foreign-fetch'].includes(fault))await closing;else await assert.rejects(closing);
  assert.equal(cleanup(),closing);if(['none','foreign-fetch'].includes(fault))await cleanup();else await assert.rejects(cleanup());
 }
 assert.equal(registered,1);assert.equal(disposed,fault==='registration'?0:1);
 assert.equal(restored,1);assert.equal(cleaned,['registration','setup'].includes(fault)?0:1);
 assert.equal(globalThis.fetch,fault==='foreign-fetch'?foreignFetch:originalFetch);
 globalThis.fetch=savedFetch;
 const late=b.enter(event());b.complete(late,true);const e=request();b.observe(e);
 assert.equal(e.request.headers.has('x-pallium-fixture'),false);
}
{
 const b=primaryBoundary('fixture-instance');b.prompt(args());const t=b.enter(event());
 b.retire();b.complete(t,true);const e=request();b.observe(e);assert.equal(e.request.headers.has('x-pallium-fixture'),false);
}
console.log(JSON.stringify(oracleTags));
"""
    restore = "const restore=" + source.split("  const restore=", 1)[1].split("\n", 1)[0]
    checks = checks.replace("/* ACTUAL_OWNED_FETCH_RESTORE */", restore)
    result = subprocess.run([node, "--input-type=module", "--eval", observer + checks],
                            cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    import ast
    import threading
    from types import SimpleNamespace

    calls = []
    def get_status(path, params):
        calls.append((path, params))
        return SimpleNamespace(status_code=200, text="", json=lambda: {"deliveries": [{"state": "pending"}]})
    namespace = {"json": json, "re": re, "client": SimpleNamespace(get=get_status), "scope": {}}
    functions = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef)
                 and node.name in ("_primary_gate", "_assert_first_primary", "delivered")]
    assert len(functions) == 3
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<actual-public-oracle>", "exec"), namespace)
    tags = json.loads(result.stdout)
    assert len(tags) == 2
    for tag in tags:
        first = {"instance": tag["instance"], "value": None}
        assert namespace["_primary_gate"]({"x-pallium-fixture": json.dumps(tag)}, "ses_fixture",
                                          first, threading.Event(), threading.Lock()) is True
        namespace["_assert_first_primary"](first, "ses_fixture", "relay-delivery-" + "a" * 32,
            [{"sessionID": "ses_fixture", "inputID": "msg_original",
              "metadata": {"delivery_id": "relay-delivery-" + "a" * 32, "generation": 1}}])
        with pytest.raises(AssertionError):
            assert namespace["delivered"]({"message_id": "relay-message-original"})
    assert len(calls) == 2, "early/ACK-negative completion must reach the real public read oracle"


def test_opencode_primary_provider_actual_first_gate_and_public_oracle() -> None:
    """Exercise the functions used by the real HTTP handler and main assertion."""
    import ast
    import io
    import threading
    from types import SimpleNamespace

    source = (Path(__file__).parents[1] / "tests/test_opencode_native_wake_e2e.py").read_text(encoding="utf-8")
    functions = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
                 and node.name in ("_primary_gate", "_assert_first_primary")]
    assert len(functions) == 2
    namespace = {"json": json, "re": re}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<actual-primary-gate>", "exec"), namespace)
    gate, oracle = namespace["_primary_gate"], namespace["_assert_first_primary"]
    delivery = "relay-delivery-" + "a" * 32
    expected = {"session": "ses_fixture", "input": "msg_original", "delivery": delivery, "generation": 1}
    tag = {"version": 1, "instance": "fixture-instance", "kind": "primary", "session": "ses_fixture",
           "prefix": True, "invocation": 1, "input": "msg_original", "expected": expected,
           "completed": True, "error": None}
    prompts = [{"sessionID": "ses_fixture", "inputID": "msg_original",
                "metadata": {"delivery_id": delivery, "generation": 1}}]
    def fresh():
        return {"instance": "fixture-instance", "value": None}, threading.Event(), threading.Lock()
    def headers(value):
        return {"x-pallium-fixture": json.dumps(value)}
    first, entered, lock = fresh()
    for kind in ("title", "compaction", "generate"):
        aux = {key: tag[key] for key in ("version", "instance", "session")}
        aux["kind"] = kind
        assert gate(headers(aux), "ses_fixture", first, entered, lock) is False
        assert not entered.is_set() and first["value"] is None
    assert gate(headers(tag), "ses_fixture", first, entered, lock) is True
    assert entered.is_set()
    oracle(first, "ses_fixture", delivery, prompts)
    saved = json.dumps(first)
    assert gate(headers({**tag, "prefix": False}), "ses_fixture", first, entered, lock) is True
    assert json.dumps(first) == saved
    # Later reload instances retain routing, but cannot create a replacement FIRST result.
    for kind in ("compaction", "primary"):
        later = {key: tag[key] for key in ("version", "session")}
        later.update(instance="reloaded-instance", kind=kind)
        if kind == "primary":
            later["prefix"] = False
        assert gate(headers(later), "ses_fixture", first, entered, lock) is (kind == "primary")
        assert json.dumps(first) == saved
    for field, value in (("session", "ses_other"), ("input", "msg_wrong"), ("instance", "other"),
                         ("invocation", None), ("completed", False), ("prefix", False),
                         ("kind", "unknown"), ("expected", None), ("error", "context-threw")):
        first, entered, lock = fresh()
        assert gate(headers({**tag, field: value}), "ses_fixture", first, entered, lock) is False
        assert entered.is_set()
        with pytest.raises(AssertionError):
            oracle(first, "ses_fixture", delivery, prompts)
        saved = json.dumps(first)
        gate(headers(tag), "ses_fixture", first, entered, lock)
        assert json.dumps(first) == saved, "bad first must not filter to later good"
    for malformed in ({}, {"x-pallium-fixture": "{"}, {"x-pallium-fixture": "[]"}):
        first, entered, lock = fresh()
        assert gate(malformed, "ses_fixture", first, entered, lock) is False
        assert entered.is_set()
        with pytest.raises(AssertionError):
            oracle(first, "ses_fixture", delivery, prompts)
    first, entered, lock = fresh()
    gate(headers(tag), "ses_fixture", first, entered, lock)
    for bad_delivery, bad_prompts in (("other", prompts), (delivery, []),
                                      (delivery, [*prompts, *prompts]),
                                      (delivery, [{**prompts[0], "inputID": "msg_other"}])):
        with pytest.raises(AssertionError):
            oracle(first, "ses_fixture", bad_delivery, bad_prompts)
    # Correlation is independent of delivery success: the same immediate oracle still fails.
    oracle(first, "ses_fixture", delivery, prompts)
    with pytest.raises(AssertionError):
        assert False, "public delivery is not delivered"
    assert source.index("_assert_first_primary(first_primary,") < source.index("assert delivered(original)")
    assert "if coalesced:" in source and 'before_sessions = api("GET", "/api/session")' in source
    # Execute the ACTUAL HTTP handler, including its wait/response routing, without a server.
    provider = next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ClassDef) and node.name == "Provider")
    post = next(node for node in provider.body if isinstance(node, ast.FunctionDef) and node.name == "do_POST")
    exec(compile(ast.Module(body=[post], type_ignores=[]), "<actual-provider>", "exec"), namespace)
    for coalesced, kind in ((True, "title"), (True, "compaction"), (True, "generate"),
                            (True, "primary"), (True, "unknown"), (False, "title")):
        first, entered, lock = fresh()
        waits = []
        def wait(timeout):
            waits.append(timeout)
            assert not coalesced or kind == "primary", "auxiliary/invalid request waited on closed primary gate"
            return True
        namespace.update(coalesced=coalesced, requests=[], primary_requests=[], session="ses_fixture", first_primary=first,
                         entered=entered, primary_lock=lock, release=SimpleNamespace(wait=wait),
                         tool_emitted=threading.Event(), assistant_outputs=[])
        actual_tag = tag if kind == "primary" else {**{key: tag[key] for key in ("version", "instance", "session")}, "kind": kind}
        output = io.BytesIO()
        handler = SimpleNamespace(headers={"Content-Length": "2", **headers(actual_tag)}, rfile=io.BytesIO(b"{}"),
                                  wfile=output, send_response=lambda *_: None, send_header=lambda *_: None,
                                  end_headers=lambda: None)
        namespace["do_POST"](handler)
        assert namespace["requests"] == [{}] and b"NATIVE_ASSISTANT_" in output.getvalue()
        assert namespace["primary_requests"] == ([(tag, {})] if coalesced and kind == "primary" else [])
        assert bool(waits) == (not coalesced or kind == "primary")
        assert entered.is_set() == (not coalesced or kind in ("primary", "unknown"))
        if coalesced and kind == "unknown":
            with pytest.raises(AssertionError):
                oracle(first, "ses_fixture", delivery, prompts)


def test_opencode_session_list_actual_short_page_contract() -> None:
    """Exercise the native fixture's real request and sole-session predicate."""
    import ast
    import base64
    from contextlib import nullcontext
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlsplit
    from urllib.request import Request

    source = (Path(__file__).parents[1] / "tests/test_opencode_native_wake_e2e.py").read_text(encoding="utf-8")
    functions = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef)
                 and node.name in ("_assert_session_list", "api")]
    assert len(functions) == 2
    seen = []
    page = {"data": []}
    def urlopen(request, timeout):
        assert timeout == 45
        seen.append(request)
        return nullcontext(SimpleNamespace(read=lambda: json.dumps(page).encode()))
    namespace = {"base64": base64, "json": json, "Request": Request, "urlopen": urlopen,
                 "url": "http://fixture.invalid", "coalesced": True}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<actual-session-list>", "exec"), namespace)
    api, validate = namespace["api"], namespace["_assert_session_list"]
    for page, expected in (({"data": []}, []),
                           ({"data": [{"id": "ses_fixture"}], "cursor": {"next": "opaque-resume"}}, ["ses_fixture"])):
        actual = api("GET", "/api/session")
        validate(actual, expected)
        assert actual == page
        request = seen[-1]
        parsed = urlsplit(request.full_url)
        assert request.get_method() == "GET" and request.data is None
        assert parsed.path == "/api/session" and parse_qs(parsed.query) == {"limit": ["2"]}
    for page, expected in (
        ({"data": [{"id": "ses_other"}]}, ["ses_fixture"]),
        ({"data": []}, ["ses_fixture"]),
        ({"data": [{"id": "ses_fixture"}]}, []),
        ({"data": [{"id": "ses_fixture"}, {"id": "ses_other"}]}, ["ses_fixture"]),
        ({"data": [{"id": "ses_other"}, {"id": "ses_fixture"}]}, ["ses_fixture"]),
        ({"data": [{"id": "ses_fixture"}] * 2}, ["ses_fixture"]),
        ({"data": [{"id": "ses_fixture"}] * 3}, ["ses_fixture"]),
        (None, []), ([], []), ({}, []), ({"data": None}, []), ({"data": {}}, []),
        ({"data": [None]}, ["ses_fixture"]), ({"data": [{}]}, ["ses_fixture"]),
        ({"data": [{"id": None}]}, ["ses_fixture"]), ({"data": [{"id": 1}]}, ["ses_fixture"]),
    ):
        with pytest.raises(AssertionError):
            validate(api("GET", "/api/session"), expected)
    for coalesced, method, path, expected_query in (
        (True, "GET", "/api/session", "limit=2"),
        (False, "GET", "/api/session", ""),
        (True, "POST", "/api/session", ""),
        (True, "GET", "/api/session/ses_fixture", ""),
    ):
        namespace["coalesced"] = coalesced
        api(method, path)
        parsed = urlsplit(seen[-1].full_url)
        assert parsed.path == path and parsed.query == expected_query


def test_opencode_settlement_qualification_inventories_every_new_case_and_preserved_negative() -> None:
    import yaml

    root = Path(__file__).parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/opencode-native-qualification.yml").read_text(encoding="utf-8"))
    cases = workflow["jobs"]["qualify"]["env"]["NEW_CASES"].splitlines()
    expected = {"missing admitted input and unrelated idle cannot settle or issue a new native ID",
                "coalesced native wake waits for settlement and successor work"}
    expected.update(f"coalesced native wake settles from exact outcome-bearing idle: {outcome}"
                    for outcome in ("succeeded", "failed", "interrupted"))
    expected.update(f"coalesced native wake rejects unproven after-wait evidence: {fault}" for fault in (
        "missing-id", "invalid-id", "same-id", "outcomeless", "unknown-outcome", "nonstring-outcome", "before-input",
        "compacted", "wrong-input", "wrong-text", "wrong-marker", "wrong-generation", "wrong-delivery", "uncertain-first-idle"))
    expected.update(f"coalesced native wake fences changed binding after wait: {change}" for change in (
        "dispose", "location", "endpoint", "scope", "wake-generation", "wake-delivery", "wake-input", "wake-location"))
    expected.update(f"coalesced native wake keeps uncertainty without replay: {failure}" for failure in (
        "wait", "context", "terminal-rejected", "terminal-reply-lost"))
    assert len(expected) == 31, "preserve the complete legacy inventory"
    expected.update(f"fresh supersession settles exact frozen generation: {outcome}" for outcome in ("succeeded", "failed", "interrupted"))
    expected.update(f"fresh supersession retains unpromoted candidate: {phase}" for phase in ("prompt-await", "queued"))
    expected.update(("fresh supersession requires observed producer promotion before admission",
        "fresh supersession keeps native ID and ordinary input boundaries",
        "fresh supersession never retrofits duplicate or historical observations",
        "fresh supersession rejects malformed or lost promoted proof",
        "fresh supersession rechecks raw evidence across final asynchronous fences",
        "fresh supersession fences lifecycle and backend changes during settlement",
        "fresh supersession consumes uncertain terminal without stale follow-up"))
    assert len(expected) == 43, "preserve all original settlement and fresh-witness cases"
    expected.add("known admitted wake reentry preserves admission and uncertainty")
    assert len(expected) == 44, "preserve all accepted OC1 cases"
    expected.add("Git discovery yields to unrelated caller work while child waits")
    assert len(cases) == len(set(cases)) == 45 and set(cases) == expected
    async_cases = workflow["jobs"]["qualify"]["env"]["ASYNC_CASES"].splitlines()
    original_async = [
        "async Git shares callback facts without merging container and repository semantics",
        "async Git enforces byte bounds and ignores stderr rather than truncating identity",
        "async Git distinguishes pre-abort, cancellation, signal and timeout outcomes",
        "async actor resolution checks lifetime and keeps actor and container pins coherent",
        "async Git preserves root validation and first-root container truncation",
        "async orientation preserves command order, token order, Unicode, redaction and eight stems",
        "async identity follows Unicode nested cwd and linked worktree Git configuration",
        "V1 lifetime authority covers every first entry and keeps retired callbacks inert",
        "V1 close response cannot purge an explicit same-ID successor with identical pin values",
        "V1 assistant captures its original lifetime before native history awaits",
        "V1 delayed Git cannot publish after deletion and same-ID activation on any caller",
        "V1 ordinary role, capture and orientation updates do not replace a live Git lifetime",
        "V1 unpinned close discovery cannot target a recreated same-ID session",
        "V2 Git waits retain original lifetime, scalar, pin and native owner on every caller",
        "V2 older Git resolution cannot overwrite concurrent successor scope or capture",
        "V2 actor wait cannot pair a newer actor with an older container",
        "V2 checks the original pin after an owned helper returns success",
        "V2 restore reuses callback-local Git facts in prompt and context",
    ]
    assert async_cases == original_async + [
        "async Git bounds owned stdout after parent exit without losing terminal outcomes",
        "V2 timer-only scope mismatch re-arms discovery without native callbacks",
        "V2 in-flight discovery cannot consume a scope-mismatch re-arm",
        "V2 prompt capture reservations retry only unissued original attempts",
    ]
    assert len(async_cases) == len(set(async_cases)) == 22
    sources = "\n".join((root / "integrations/opencode/tests" / file).read_text(encoding="utf-8")
                        for file in ("common.test.mjs", "plugin.test.mjs", "v2-plugin.test.mjs"))
    for case in async_cases:
        assert f'test("{case}",' in sources
    assert not set(async_cases) & set(cases)
    http_cases = workflow["jobs"]["qualify"]["env"]["HTTP_CASES"].splitlines()
    expected_http = {f"test_activation_settlement_preserves_original_authority_before_backlog[semantic-{state}]"
                     for state in ("delivered", "pending", "claimed", "expired")}
    expected_http.update(f"test_stale_or_wrong_binding_is_rejected[semantic-{operation}-overrides{index}-{status}]"
                         for operation in ("poll", "admitted", "terminal")
                         for index, status in enumerate((404, 404, 404, 409, 409, 409, 404)))
    assert len(http_cases) == len(set(http_cases)) == 25 and set(http_cases) == expected_http

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
