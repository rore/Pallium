from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig
from evals.agent_conversation_runner import run_agent_conversation_scenarios
from providers.llm.base import LLMJsonResponse

import pytest

pytestmark = pytest.mark.slow


class StubAgentConversationLLMProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if "Investigation found that arrival-time ordering skipped hold updates during catalog sync delays." in user_prompt:
            payload = {
                "summary": "Prior investigation about missing holds.",
                "candidate_type": "investigation_outcome",
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": "arrival-time ordering skipped hold updates during catalog sync delays",
                "investigation_evidence_text": "Investigation found that arrival-time ordering skipped hold updates during catalog sync delays.",
                "rationale_text": None,
            }
        elif "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays." in user_prompt:
            payload = {
                "summary": "Prior reservation-ordering decision.",
                "candidate_type": "decision",
                "decision_text": "use item event time for reservation ordering",
                "decision_evidence_text": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.",
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": "to avoid skipped holds during sync delays",
            }
        elif "Decision: send overdue notices in 30-minute batches to avoid staff inbox spam." in user_prompt:
            payload = {
                "summary": "Prior notification batching decision.",
                "candidate_type": "decision",
                "decision_text": "send overdue notices in 30-minute batches",
                "decision_evidence_text": "Decision: send overdue notices in 30-minute batches to avoid staff inbox spam.",
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": "to avoid staff inbox spam",
            }
        else:
            payload = {
                "summary": "Conversation summary.",
                "candidate_type": None,
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
            }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def test_agent_conversation_runner_outputs_expected_shape(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: StubAgentConversationLLMProvider(),
    )

    run_dir = run_agent_conversation_scenarios(
        scenario_file=Path("evals/agent_conversation/scenarios.json"),
        output_root=tmp_path / "output",
        config=AppConfig(
            storage_backend="sqlite",
            default_use_case="agent_conversation_memory",
            llm_provider="openai_compatible",
            llm_model="fake-model",
            llm_base_url="http://fake-provider.local",
            llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
        ),
        run_name="agent-conversation-smoke",
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = [
        json.loads(line)
        for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert summary["scenarios_total"] == 3
    assert len(results) == 3
    assert results[0]["baseline_context"]
    assert "memory_backed_results" in results[0]


def test_cross_thread_value_scenario_returns_expected_memory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: StubAgentConversationLLMProvider(),
    )

    run_dir = run_agent_conversation_scenarios(
        scenario_file=Path("evals/agent_conversation/scenarios.json"),
        output_root=tmp_path / "output",
        config=AppConfig(
            storage_backend="sqlite",
            default_use_case="agent_conversation_memory",
            llm_provider="openai_compatible",
            llm_model="fake-model",
            llm_base_url="http://fake-provider.local",
            llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
        ),
        run_name="agent-conversation-value",
    )
    results = [
        json.loads(line)
        for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    value_case = next(item for item in results if item["scenario_id"] == "cross-thread-decision-recall")

    assert value_case["expected_memory_types_found"] is True
    assert "decision" in value_case["returned_memory_types"]
    assert "investigation_outcome" in value_case["returned_memory_types"]


def test_same_thread_low_value_scenario_adds_little_or_nothing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: StubAgentConversationLLMProvider(),
    )

    run_dir = run_agent_conversation_scenarios(
        scenario_file=Path("evals/agent_conversation/scenarios.json"),
        output_root=tmp_path / "output",
        config=AppConfig(
            storage_backend="sqlite",
            default_use_case="agent_conversation_memory",
            llm_provider="openai_compatible",
            llm_model="fake-model",
            llm_base_url="http://fake-provider.local",
            llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
        ),
        run_name="agent-conversation-no-value",
    )
    results = [
        json.loads(line)
        for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    low_value_case = next(item for item in results if item["scenario_id"] == "same-thread-answer-already-present")

    assert low_value_case["expected_value"] is False
    assert low_value_case["memory_was_unnecessary"] is True


def test_repeated_answer_consistency_scenario_returns_prior_assistant_memory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: StubAgentConversationLLMProvider(),
    )

    run_dir = run_agent_conversation_scenarios(
        scenario_file=Path("evals/agent_conversation/scenarios.json"),
        output_root=tmp_path / "output",
        config=AppConfig(
            storage_backend="sqlite",
            default_use_case="agent_conversation_memory",
            llm_provider="openai_compatible",
            llm_model="fake-model",
            llm_base_url="http://fake-provider.local",
            llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
        ),
        run_name="agent-conversation-repeat",
    )
    results = [
        json.loads(line)
        for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    repeat_case = next(item for item in results if item["scenario_id"] == "repeated-answer-consistency")

    assert repeat_case["expected_memory_types_found"] is True
    assert "decision" in repeat_case["returned_memory_types"]

