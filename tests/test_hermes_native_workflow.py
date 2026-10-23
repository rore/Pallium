"""Safety contracts for the manually approved disposable Windows runner."""
from pathlib import Path
import tomllib

import yaml


def test_native_qualification_stays_manual_bounded_and_candidate_scoped():
    workflow = yaml.safe_load((Path(__file__).resolve().parents[1] /
                              ".github/workflows/hermes-native-qualification.yml").read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"workflow_dispatch"}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["pallium_revision"]["required"] is True
    assert inputs["scope_mode"] == {
        "description": "Select fixed compatibility scope or automatic CWD scope",
        "required": True,
        "type": "choice",
        "options": ["fixed", "cwd"],
        "default": "fixed",
    }
    assert inputs["case_selection"] == {
        "description": "Select all native UI journeys or the CWD TUI pair",
        "required": True,
        "type": "choice",
        "options": ["all", "tui"],
        "default": "all",
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    job = workflow["jobs"]["native"]
    assert job["runs-on"] == "windows-latest" and job["timeout-minutes"] == 60
    assert job["permissions"] == {"contents": "read"}
    assert not any("runner." in str(value) for value in job["env"].values())
    assert job["env"]["HERMES_E2E_SCOPE_MODE"] == "${{ inputs.scope_mode }}"
    assert job["env"]["HERMES_NATIVE_CASE_SELECTION"] == "${{ inputs.case_selection }}"
    assert len(job["steps"][0]["env"]) == 4
    assert all("${{ runner.temp }}" in value for value in job["steps"][0]["env"].values())
    assert job["strategy"]["max-parallel"] == 1 and job["strategy"]["fail-fast"] is True
    expected_matrix = "${{ fromJSON(inputs.scope_mode == 'cwd' && '[{\"release\":\"v0.22.4\",\"revision\":\"4d04303818b61bf3aa09278af48356315515965b\"}]' || '[{\"release\":\"v0.22.0\",\"revision\":\"e06df9c2eae6901f4c88f464e0ae6e753c0428b8\"},{\"release\":\"v0.22.2\",\"revision\":\"d923a5eb487a17c0a68801bba9ef0f56c81040a8\"}]') }}"
    assert job["strategy"]["matrix"]["include"] == expected_matrix
    checkout = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ inputs.pallium_revision }}"
    assert checkout["with"]["persist-credentials"] is False
    scripts = [step["run"] for step in job["steps"] if "run" in step]
    assert all(script.lstrip().startswith("$ErrorActionPreference = 'Stop'") for script in scripts)
    assert not any("${{ inputs." in script or "secrets." in script for script in scripts)
    assert "'^[a-f0-9]{40}$'" in scripts[0] and "'github-hosted'" in scripts[0]
    assert "@('fixed', 'cwd') -cnotcontains $env:HERMES_E2E_SCOPE_MODE" in scripts[0]
    assert "@('all', 'tui') -cnotcontains $env:HERMES_NATIVE_CASE_SELECTION" in scripts[0]
    assert "$env:HERMES_NATIVE_CASE_SELECTION -ceq 'tui' -and $env:HERMES_E2E_SCOPE_MODE -cne 'cwd'" in scripts[0]
    assert '"$name=$value"' in scripts[0] and "$env:GITHUB_ENV" in scripts[0]
    native = next(step["run"] for step in job["steps"] if step["name"] == "Run native caller-surface E2E against local stubs")
    assert "$env:PALLIUM_TUI_REPO_REVISION -ne $env:PALLIUM_EXPECTED_REVISION" in native
    assert "--basetemp $testBase --junitxml $junitPath" in native
    for surface in ("tui", "desktop"):
        for mode in ("off", "on"):
            assert f"test_released_hermes_actual_ui_journey[{surface}-memory-{mode}]" in native
    assert "SelectSingleNode('skipped|failure|error')" in native
    assert "provenance.json" in native
    assert "scope_mode=$env:HERMES_E2E_SCOPE_MODE" in native
    assert "case_selection=$env:HERMES_NATIVE_CASE_SELECTION; required_ui_ids=$requiredUiIds" in native
    command = "& $env:PALLIUM_E2E_PYTHON -m pytest -m slow -n 0 --basetemp $testBase --junitxml $junitPath"
    tui_targets = ("'tests/test_hermes_tui_native_e2e.py::test_released_hermes_actual_ui_journey[tui-memory-off]' "
                   "'tests/test_hermes_tui_native_e2e.py::test_released_hermes_actual_ui_journey[tui-memory-on]'")
    assert command + " " + tui_targets in native
    assert command + " tests/test_hermes_tui_native_e2e.py" in native
    assert native.count(command) == 2 and native.count("::test_released_hermes_actual_ui_journey") == 2
    assert "if ($LASTEXITCODE) { throw 'Hermes native qualification failed' }" in native
    assert "$actualUiCases.Count -ne 2" in native
    assert ".StartsWith('test_released_hermes_actual_ui_journey[', [StringComparison]::Ordinal)" in native
    assert "$requiredUiIds -cnotcontains $actual.name" in native
    assert "foreach ($name in $requiredUiIds)" in native
    assert "Invoke-Expression" not in native and "eval" not in native
    assert not any(step.get("if") for step in job["steps"][:-1])
    upload = job["steps"][-1]
    assert upload["if"] == "always()" and upload["with"]["retention-days"] == 7
    assert "h4-tests" in upload["with"]["path"]
    project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(requirement.lower().startswith("pyyaml") for requirement in project["project"]["optional-dependencies"]["dev"])
