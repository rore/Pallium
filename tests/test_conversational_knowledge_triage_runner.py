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

    assert summary["scenarios_total"] == 6
    assert summary["passed"] == 6
    assert len(results) == 6
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


def test_conversational_knowledge_triage_runner_reports_phase_2c_rejections(tmp_path: Path) -> None:
    run_dir = run_eval(
        scenario_file=Path("evals/conversational_knowledge/structural_triage_scenarios.json"),
        output_root=tmp_path / "output",
        run_name="conversational-knowledge-triage-phase-2c",
    )

    results = _read_jsonl(run_dir / "results.jsonl")
    review_question = next(item for item in results if item["scenario_id"] == "review-question-rejected")
    vague_status = next(item for item in results if item["scenario_id"] == "subject-prefixed-vague-status-rejected")

    assert review_question["actual_subjects"] == ["batch digest"]
    assert review_question["actual_statements"] == ["Batch digest runs every 30 minutes."]
    assert vague_status["actual_subjects"] == ["export worker"]
    assert vague_status["actual_statements"] == ["Export worker uses a 1 GiB memory limit."]