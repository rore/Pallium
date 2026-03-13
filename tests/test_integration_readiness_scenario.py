from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig
from evals.integration_readiness_scenario import run_integration_readiness_scenario
from tests.test_work_resumption_benchmark import StubWorkResumptionAnswerProvider
from tests.stub_providers import TieredMemorySemanticProvider

SCENARIOS = Path("evals/integration_readiness/scenarios.json")


def _benchmark_config() -> AppConfig:
    return AppConfig(
        default_use_case="agent_conversation_memory",
        llm_provider="openai_compatible",
        llm_model="fake-answer-model",
        llm_base_url="http://fake-provider.local",
        llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
    )


def test_integration_readiness_scenario_builds_green_milestone_gate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_integration_readiness_scenario(
        scenario_file=SCENARIOS,
        output_root=tmp_path / "output",
        config=_benchmark_config(),
        run_name="integration-readiness",
        answer_provider=StubWorkResumptionAnswerProvider(),
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    report = (run_dir / "report.md").read_text(encoding="utf-8")

    assert summary["scenario_count"] == 3
    assert summary["component_policy_successes"] == 3
    assert summary["gates"]["positive_value_passed"] is True
    assert summary["gates"]["no_value_control_passed"] is True
    assert summary["gates"]["scope_guard_passed"] is True
    assert summary["gates"]["integration_readiness_passed"] is True
    assert summary["roles"]["positive_value"]["top_layer"] == "task_checkpoint"
    assert summary["roles"]["no_value_control"]["winner"] != "memory_backed"
    assert "privacy_leak_failure" not in summary["roles"]["scope_guard"]["failure_families"]
    assert "## Manual Run" in report
    assert "`integration_readiness_passed`: PASS" in report
