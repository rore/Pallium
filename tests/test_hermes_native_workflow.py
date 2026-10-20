"""Safety contracts for the manually approved disposable Windows runner."""
from pathlib import Path

import yaml


def test_native_qualification_stays_manual_bounded_and_candidate_scoped():
    workflow = yaml.safe_load((Path(__file__).resolve().parents[1] /
                              ".github/workflows/hermes-native-qualification.yml").read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["pallium_revision"]["required"] is True
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    job = workflow["jobs"]["native"]
    assert job["runs-on"] == "windows-latest" and job["timeout-minutes"] == 60
    assert job["permissions"] == {"contents": "read"}
    assert job["strategy"]["max-parallel"] == 1 and job["strategy"]["fail-fast"] is True
    assert {row["revision"] for row in job["strategy"]["matrix"]["include"]} == {
        "e06df9c2eae6901f4c88f464e0ae6e753c0428b8", "d923a5eb487a17c0a68801bba9ef0f56c81040a8"}
    assert len(job["strategy"]["matrix"]["include"]) == 2
    checkout = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ inputs.pallium_revision }}"
    assert checkout["with"]["persist-credentials"] is False
    scripts = [step["run"] for step in job["steps"] if "run" in step]
    assert all(script.lstrip().startswith("$ErrorActionPreference = 'Stop'") for script in scripts)
    assert not any("${{ inputs." in script or "secrets." in script for script in scripts)
    assert "'^[a-f0-9]{40}$'" in scripts[0] and "'github-hosted'" in scripts[0]
    native = next(step["run"] for step in job["steps"] if step["name"] == "Run native caller-surface E2E against local stubs")
    assert "$env:PALLIUM_TUI_REPO_REVISION -ne $env:PALLIUM_EXPECTED_REVISION" in native
    assert "--basetemp $testBase --junitxml $junitPath" in native
    for surface in ("tui", "desktop"):
        for mode in ("off", "on"):
            assert f"test_released_hermes_actual_ui_journey[{surface}-memory-{mode}]" in native
    assert "SelectSingleNode('skipped|failure|error')" in native
    assert "provenance.json" in native
    upload = job["steps"][-1]
    assert upload["if"] == "always()" and upload["with"]["retention-days"] == 7
    assert "h4-tests" in upload["with"]["path"]
