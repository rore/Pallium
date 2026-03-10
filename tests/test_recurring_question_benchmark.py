from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig
from evals.recurring_question_benchmark import run_recurring_question_benchmark
from providers.llm.base import LLMJsonResponse


class StubSemanticLLMProvider:
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


class StubAnswerLLMProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if "Branch: baseline" in user_prompt and "Why do we use item event time for reservation ordering?" in user_prompt:
            payload = {
                "answer": "We use item event time for reservation ordering.",
                "evidence_used": [],
            }
        elif "Branch: memory_backed" in user_prompt and "Why do we use item event time for reservation ordering?" in user_prompt:
            payload = {
                "answer": "We use item event time for reservation ordering because arrival-time ordering skipped holds during catalog sync delays.",
                "evidence_used": [
                    "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.",
                    "Investigation found that arrival-time ordering skipped hold updates during catalog sync delays.",
                ],
            }
        elif "Branch: baseline" in user_prompt and "Have we already answered why overdue notices are batched?" in user_prompt:
            payload = {
                "answer": "Yes, we already answered that overdue notices are sent in batches.",
                "evidence_used": [],
            }
        elif "Branch: memory_backed" in user_prompt and "Have we already answered why overdue notices are batched?" in user_prompt:
            payload = {
                "answer": "Yes. We previously decided to send overdue notices in 30-minute batches to avoid staff inbox spam.",
                "evidence_used": ["Decision: send overdue notices in 30-minute batches to avoid staff inbox spam."],
            }
        else:
            payload = {
                "answer": "The 48-hour cutoff reduces no-show holds before weekend pickups and gives the next patron time to collect the item.",
                "evidence_used": [],
            }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_recurring_question_benchmark_outputs_expected_shape(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config: StubSemanticLLMProvider())

    run_dir = run_recurring_question_benchmark(
        scenario_file=Path("evals/recurring_question/scenarios.json"),
        output_root=tmp_path / "output",
        config=AppConfig(
            default_use_case="agent_conversation_memory",
            llm_provider="openai_compatible",
            llm_model="fake-answer-model",
            llm_base_url="http://fake-provider.local",
            llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
        ),
        run_name="recurring-question-smoke",
        answer_provider=StubAnswerLLMProvider(),
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = _read_jsonl(run_dir / "results.jsonl")

    assert summary["scenarios_total"] == 3
    assert summary["value_scenarios"] == 2
    assert summary["non_value_scenarios"] == 1
    assert len(results) == 3
    assert "baseline_answer" in results[0]
    assert "memory_backed_answer" in results[0]
    assert results[0]["rubric"]["comparison"]["winner"]


def test_cross_thread_scenario_marks_memory_backed_as_winner(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config: StubSemanticLLMProvider())

    run_dir = run_recurring_question_benchmark(
        scenario_file=Path("evals/recurring_question/scenarios.json"),
        output_root=tmp_path / "output",
        config=AppConfig(
            default_use_case="agent_conversation_memory",
            llm_provider="openai_compatible",
            llm_model="fake-answer-model",
            llm_base_url="http://fake-provider.local",
            llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
        ),
        run_name="recurring-question-cross-thread",
        answer_provider=StubAnswerLLMProvider(),
    )
    results = _read_jsonl(run_dir / "results.jsonl")
    cross_thread = next(item for item in results if item["scenario_id"] == "cross-thread-prior-conclusion")

    assert cross_thread["winner"] == "memory_backed"
    assert cross_thread["rubric"]["memory_backed"]["memory_carry_forward"] == 2
    assert cross_thread["expected_memory_types_found"] is True


def test_same_thread_low_value_does_not_mark_memory_as_winner(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config: StubSemanticLLMProvider())

    run_dir = run_recurring_question_benchmark(
        scenario_file=Path("evals/recurring_question/scenarios.json"),
        output_root=tmp_path / "output",
        config=AppConfig(
            default_use_case="agent_conversation_memory",
            llm_provider="openai_compatible",
            llm_model="fake-answer-model",
            llm_base_url="http://fake-provider.local",
            llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
        ),
        run_name="recurring-question-low-value",
        answer_provider=StubAnswerLLMProvider(),
    )
    results = _read_jsonl(run_dir / "results.jsonl")
    low_value = next(item for item in results if item["scenario_id"] == "same-thread-low-value")

    assert low_value["winner"] != "memory_backed"
    assert low_value["rubric"]["comparison"]["delta"] == 2


def test_repeated_answer_consistency_rewards_prior_conclusion_carry_forward(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config: StubSemanticLLMProvider())

    run_dir = run_recurring_question_benchmark(
        scenario_file=Path("evals/recurring_question/scenarios.json"),
        output_root=tmp_path / "output",
        config=AppConfig(
            default_use_case="agent_conversation_memory",
            llm_provider="openai_compatible",
            llm_model="fake-answer-model",
            llm_base_url="http://fake-provider.local",
            llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
        ),
        run_name="recurring-question-repeat",
        answer_provider=StubAnswerLLMProvider(),
    )
    results = _read_jsonl(run_dir / "results.jsonl")
    repeated = next(item for item in results if item["scenario_id"] == "repeated-answer-consistency")

    assert repeated["winner"] == "memory_backed"
    assert repeated["rubric"]["memory_backed"]["consistency"] == 2
