from __future__ import annotations

import json
import re
from pathlib import Path

from app.config import AppConfig
from evals.work_resumption_benchmark import run_work_resumption_benchmark
from providers.llm.base import LLMJsonResponse
from tests.stub_providers import TieredMemorySemanticProvider


SCENARIOS = Path("evals/work_resumption/scenarios.json")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _benchmark_config() -> AppConfig:
    return AppConfig(
        default_use_case="agent_conversation_memory",
        llm_provider="openai_compatible",
        llm_model="fake-answer-model",
        llm_base_url="http://fake-provider.local",
        llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
    )


class StubWorkResumptionAnswerProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        scenario_id = _extract_line(user_prompt, "Scenario ID:")
        branch = _extract_line(user_prompt, "Branch:")
        payload = _payload_for(scenario_id=scenario_id, branch=branch)
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def _extract_line(text: str, prefix: str) -> str:
    match = re.search(rf"^{re.escape(prefix)}\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _payload_for(*, scenario_id: str, branch: str) -> dict[str, object]:
    baseline = branch == "baseline"

    if scenario_id == "resume-investigation-after-pause":
        if baseline:
            return {
                "answer": "Resume the delayed catalog sync investigation first.",
                "task_orientation": "Delayed catalog sync investigation",
                "reused_findings": [],
                "blocker_state": "",
                "preserved_progress": "",
                "next_step": "",
                "evidence_used": [],
            }
        return {
            "answer": "Resume the delayed catalog sync investigation from the duplicate-hold conclusion: arrival-time ordering reused stale hold state, so we switched to item event time.",
            "task_orientation": "Delayed catalog sync investigation and duplicate holds",
            "reused_findings": [
                "arrival-time ordering reused stale hold state",
                "item event time",
            ],
            "blocker_state": "",
            "preserved_progress": "",
            "next_step": "",
            "evidence_used": ["investigation_outcome", "decision"],
        }

    if scenario_id == "debugging-continued-from-partial-findings":
        if baseline:
            return {
                "answer": "Resume duplicate-hold debugging on the delayed sync workers.",
                "task_orientation": "Duplicate-hold debugging",
                "reused_findings": [],
                "blocker_state": "",
                "preserved_progress": "",
                "next_step": "",
                "evidence_used": [],
            }
        return {
            "answer": "Stay oriented on duplicate-hold debugging for delayed sync workers. The prior finding was that the reservation cache is warm and cache invalidation is the likely path.",
            "task_orientation": "Duplicate-hold debugging on delayed sync workers",
            "reused_findings": [
                "reservation cache is warm",
                "cache invalidation",
            ],
            "blocker_state": "",
            "preserved_progress": "Local replay confirmed the bug.",
            "next_step": "",
            "evidence_used": ["investigation_outcome", "assistant_artifact"],
        }

    if scenario_id == "resume-after-auth-tool-failure":
        if baseline:
            return {
                "answer": "The retry is queued again.",
                "task_orientation": "",
                "reused_findings": [],
                "blocker_state": "",
                "preserved_progress": "",
                "next_step": "",
                "evidence_used": [],
            }
        return {
            "answer": "Refresh the catalog service token before the next catalog sync retry because the last run hit a 401 and the service token expired.",
            "task_orientation": "Catalog sync retry",
            "reused_findings": [],
            "blocker_state": "401 because the service token expired",
            "preserved_progress": "Refreshed 312 reservation records.",
            "next_step": "Refresh the catalog service token, then retry the sync.",
            "evidence_used": ["assistant_artifact source evidence"],
        }

    if scenario_id == "resume-implementation-ticket-after-interruption":
        if baseline:
            return {
                "answer": "Resume ticket LIB-241.",
                "task_orientation": "Ticket LIB-241",
                "reused_findings": [],
                "blocker_state": "",
                "preserved_progress": "",
                "next_step": "",
                "evidence_used": [],
            }
        return {
            "answer": "Resume ticket LIB-241 with the reservation ordering fix still behind the use_item_event_time flag.",
            "task_orientation": "Ticket LIB-241 and the use_item_event_time flag",
            "reused_findings": [
                "reservation ordering fix",
            ],
            "blocker_state": "",
            "preserved_progress": "Schema change and backfill done.",
            "next_step": "",
            "evidence_used": ["decision", "assistant_artifact"],
        }

    return {
        "answer": "Refresh the catalog service token first, then rerun the sync.",
        "task_orientation": "Catalog sync",
        "reused_findings": [],
        "blocker_state": "Refresh auth first",
        "preserved_progress": "",
        "next_step": "Refresh the catalog service token, then rerun the sync.",
        "evidence_used": [],
    }


def test_work_resumption_benchmark_outputs_summary_results_and_report(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_work_resumption_benchmark(
        scenario_file=SCENARIOS,
        output_root=tmp_path / "output",
        config=_benchmark_config(),
        run_name="work-resumption-smoke",
        answer_provider=StubWorkResumptionAnswerProvider(),
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = _read_jsonl(run_dir / "results.jsonl")
    report = (run_dir / "report.md").read_text(encoding="utf-8")

    assert summary["scenarios_total"] == 5
    assert summary["value_scenarios"] == 4
    assert summary["non_value_scenarios"] == 1
    assert len(results) == 5
    assert "## Gap Signals" in report
    assert summary["biggest_gap"] == "compact_task_state_memory"


def test_work_resumption_benchmark_captures_memory_help_and_gap_signal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_work_resumption_benchmark(
        scenario_file=SCENARIOS,
        output_root=tmp_path / "output",
        config=_benchmark_config(),
        run_name="work-resumption-gaps",
        answer_provider=StubWorkResumptionAnswerProvider(),
    )
    results = {item["scenario_id"]: item for item in _read_jsonl(run_dir / "results.jsonl")}

    resumed = results["resume-investigation-after-pause"]
    assert resumed["winner"] == "memory_backed"
    assert resumed["expected_memory_types_found"] is True
    assert resumed["top_layer"] == "lower_level_memory"

    debugging = results["debugging-continued-from-partial-findings"]
    assert debugging["winner"] == "memory_backed"
    assert "compact_task_state_memory" in debugging["gap_signals"]
    assert "next_step_guidance" in debugging["missing_dimensions_after_memory"]

    auth_retry = results["resume-after-auth-tool-failure"]
    assert auth_retry["top_layer"] == "source_evidence"
    assert "selected_work_artifact_support" in auth_retry["gap_signals"]

    implementation = results["resume-implementation-ticket-after-interruption"]
    assert "thread_summary" in implementation["returned_memory_types"]


def test_work_resumption_benchmark_keeps_no_value_continuation_guard(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_work_resumption_benchmark(
        scenario_file=SCENARIOS,
        output_root=tmp_path / "output",
        config=_benchmark_config(),
        run_name="work-resumption-guard",
        answer_provider=StubWorkResumptionAnswerProvider(),
    )
    results = {item["scenario_id"]: item for item in _read_jsonl(run_dir / "results.jsonl")}
    no_value = results["same-thread-no-value-continuation"]

    assert no_value["winner"] == "baseline"
    assert no_value["non_value_guard_success"] is True
    assert no_value["rubric"]["memory_backed"]["overreach"] is False
