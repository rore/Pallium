import re
from pathlib import Path


WORKFLOW = (Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml").read_text()


def _job(name: str, next_name: str | None = None) -> str:
    block = WORKFLOW.split(f"  {name}:\n", 1)[1]
    return block if next_name is None else block.split(f"  {next_name}:\n", 1)[0]


def test_ci_cancels_only_the_same_event_and_ref() -> None:
    assert "group: ci-${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}" in WORKFLOW
    assert "cancel-in-progress: true" in WORKFLOW


def test_docs_only_pushes_are_ignored_but_pull_requests_are_not() -> None:
    push = WORKFLOW.split("  pull_request:\n", 1)[0]
    ignored = tuple(
        line.strip()[2:].strip('"')
        for line in push.split("    paths-ignore:\n", 1)[1].splitlines()
        if line.startswith("      - ")
    )
    assert ignored == ("docs/*.md", "docs/**/*.md", "roadmap/*.md", "roadmap/**/*.md")
    pull_request = WORKFLOW.split("  pull_request:\n", 1)[1].split("  schedule:\n", 1)[0]
    assert "paths-ignore:" not in pull_request


def test_required_linux_lane_cannot_skip_mcp_tests() -> None:
    linux = _job("test", "windows-smoke")
    assert 'pip install -e ".[dev,vector,mcp]"' in linux
    assert 'python -c "import mcp; import app.mcp.server"' in linux
    assert "--durations=20" in linux


def test_all_test_commands_report_slowest_tests() -> None:
    commands = WORKFLOW.split("python -m pytest")[1:]
    assert len(commands) == 5
    assert all("--durations=20" in command.split("\n\n", 1)[0] for command in commands)


def test_nightly_slow_smoke_is_bounded_and_hermetic() -> None:
    nightly = _job("nightly-slow-smoke")
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