from __future__ import annotations

import json
from pathlib import Path

from evals.conversational_knowledge_triage_runner import run_eval


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_conversational_knowledge_triage_runner_reports_all_structural_scenarios(tmp_path: Path) -> None:
    run_dir = run_eval(
        scenario_file=Path("evals/conversational_knowledge/structural_triage_scenarios.json"),
        output_root=tmp_path / "output",
        run_name="conversational-knowledge-triage-smoke",
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = _read_jsonl(run_dir / "results.jsonl")

    assert summary["scenarios_total"] == 4
    assert summary["passed"] == 4
    assert len(results) == 4
    assert all(item["passed"] is True for item in results)


def test_conversational_knowledge_triage_runner_exposes_same_thread_burst_scope(tmp_path: Path) -> None:
    run_dir = run_eval(
        scenario_file=Path("evals/conversational_knowledge/structural_triage_scenarios.json"),
        output_root=tmp_path / "output",
        run_name="conversational-knowledge-triage-burst",
    )

    results = _read_jsonl(run_dir / "results.jsonl")
    burst = next(item for item in results if item["scenario_id"] == "same-thread-burst-grouping")

    assert burst["actual_group_count"] == 1
    assert burst["actual_grouping_scopes"] == ["same_thread_burst"]