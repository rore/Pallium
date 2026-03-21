from __future__ import annotations

import json
import time
from typing import Any
from pathlib import Path

from app.config import AppConfig
from evals.semantic_runner import run_semantic_eval
from providers.llm.base import LLMJsonResponse
from semantic.llm_agent_memory import LLMAgentMemoryPlugin, PROMPT_VARIANTS, describe_prompt_variants
from semantic.prompt_roles import get_prompt_role_contract


WRITE_EXTRACTION_PROMPT_ROLE = get_prompt_role_contract("write_extraction")
DEFAULT_VARIANT = "strict_typed_memory_v5_compact_examples"


class VariantAwareStubLLMProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        parsed_json = {
            "summary": "Semantic summary",
            "candidate_type": None,
            "decision_text": None,
            "decision_evidence_text": None,
            "investigation_text": None,
            "investigation_evidence_text": None,
            "rationale_text": None,
            "is_low_value_meta": False,
            "constraint_text": None,
            "next_step_text": None,
            "blocker_text": None,
            "progress_text": None,
            "key_finding_text": None,
            "subject_hints": [],
            "constraint_candidates": [],
        }
        if 'Investigation found that arrival-time ordering missed hold updates during sync delays.' in user_prompt:
            parsed_json.update(
                {
                    "candidate_type": "investigation_outcome",
                    "investigation_text": "arrival-time ordering missed hold updates during sync delays",
                    "investigation_evidence_text": "Investigation found that arrival-time ordering missed hold updates during sync delays.",
                    "rationale_text": "because the catalog provider delivered updates late",
                    "key_finding_text": "arrival-time ordering missed hold updates during sync delays",
                }
            )
        elif 'Task complete. No Slack message needed. Nothing new to report.' in user_prompt:
            parsed_json.update(
                {
                    "is_low_value_meta": True,
                }
            )
        elif 'Constraint: do not open a browser.' in user_prompt:
            parsed_json.update(
                {
                    "constraint_text": "Do not open a browser.",
                    "next_step_text": "Compare ledger-query vs transaction-transformer locally.",
                }
            )
        elif 'Classify candidate_type as "decision" only when the source explicitly records a committed choice' in system_prompt:
            parsed_json["summary"] = "Strict summary"
        else:
            parsed_json.update(
                {
                    "candidate_type": "decision",
                    "decision_text": "use item item event time reservation ordering",
                    "decision_evidence_text": "Decision: use item item event time reservation ordering",
                    "rationale_text": "to avoid missed hold updates during sync delays",
                }
            )
        return LLMJsonResponse(raw_text=json.dumps(parsed_json), parsed_json=parsed_json)


class DelayedVariantAwareStubLLMProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if 'Investigation found that arrival-time ordering missed hold updates during sync delays.' in user_prompt:
            time.sleep(0.02)
            parsed_json = {
                "summary": "Investigation summary",
                "candidate_type": "investigation_outcome",
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": "arrival-time ordering missed hold updates during sync delays",
                "investigation_evidence_text": "Investigation found that arrival-time ordering missed hold updates during sync delays.",
                "rationale_text": None,
                "is_low_value_meta": False,
                "constraint_text": None,
                "next_step_text": None,
                "blocker_text": None,
                "progress_text": None,
                "key_finding_text": None,
                "subject_hints": [],
                "constraint_candidates": [],
            }
        else:
            time.sleep(0.08)
            parsed_json = {
                "summary": "Decision summary",
                "candidate_type": "decision",
                "decision_text": "use item item event time reservation ordering",
                "decision_evidence_text": "Decision: use item item event time reservation ordering",
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
                "is_low_value_meta": False,
                "constraint_text": None,
                "next_step_text": None,
                "blocker_text": None,
                "progress_text": None,
                "key_finding_text": None,
                "subject_hints": [],
                "constraint_candidates": [],
            }
        return LLMJsonResponse(raw_text=json.dumps(parsed_json), parsed_json=parsed_json)


class ErrorLLMProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        raise RuntimeError("provider exploded")


def _write_input_file(path: Path, *records: dict[str, object]) -> None:
    content = "\n".join(json.dumps(record) for record in records)
    path.write_text(content + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _decision_record(source_id: str, content: str, *, expected_kind: str = "decision") -> dict[str, object]:
    return {
        "source_type": "decision_note",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "assistant_output",
        "role": "assistant",
        "metadata": {"topic": "reservation ordering", "expected_kind": expected_kind},
    }


def _investigation_record(source_id: str, content: str, *, expected_kind: str = "investigation_outcome") -> dict[str, object]:
    return {
        "source_type": "investigation_summary",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "tool_use_summary",
        "role": "assistant",
        "metadata": {
            "topic": "reservation ordering",
            "expected_kind": expected_kind,
            "expected_signal_truths": {"key_finding_text": True},
        },
    }


def _signal_record(source_id: str, content: str, expected_signal_truths: dict[str, bool], *, expected_kind: str | None = "discussion_summary") -> dict[str, object]:
    return {
        "source_type": "assistant_output",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "assistant_output",
        "role": "assistant",
        "metadata": {key: value for key, value in {"topic": "ops", "expected_kind": expected_kind, "expected_signal_truths": expected_signal_truths}.items() if value is not None},
    }


def test_run_semantic_eval_writes_summary_and_jsonl_results(tmp_path: Path) -> None:
    input_file = tmp_path / "items.jsonl"
    output_dir = tmp_path / "output"
    _write_input_file(input_file, _decision_record("decision-1", "Decision: use item item event time reservation ordering."))

    plugin = LLMAgentMemoryPlugin(provider=VariantAwareStubLLMProvider())
    run_dir = run_semantic_eval(
        input_file=input_file,
        output_root=output_dir,
        plugin=plugin,
        config=AppConfig(
            default_use_case="llm_agent_memory",
            llm_provider="openai_compatible",
            llm_model="fake-model",
            llm_base_url="http://fake.local/v1",
            llm_prompt_variant=DEFAULT_VARIANT,
        ),
        suite_name="semantic smoke",
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = _read_jsonl(run_dir / "results.jsonl")
    metrics = describe_prompt_variants()

    assert summary["suite_name"] == "semantic smoke"
    assert summary["items_succeeded"] == 1
    assert summary["promoted_counts"]["decision"] == 1
    assert summary["input_file"] == str(input_file)
    assert summary["results_file"] == "results.jsonl"
    assert summary["prompt_role"] == WRITE_EXTRACTION_PROMPT_ROLE.role
    assert summary["prompt_schema_id"] == WRITE_EXTRACTION_PROMPT_ROLE.schema_id
    assert summary["prompt_schema_version"] == WRITE_EXTRACTION_PROMPT_ROLE.schema_version
    assert summary["split_output"] is False
    assert summary["split_outputs"] == []
    assert summary["prompt_variants"] == [DEFAULT_VARIANT]
    assert summary["prompt_text_metrics"][DEFAULT_VARIANT] == metrics[DEFAULT_VARIANT]
    assert summary["max_concurrency"] == 1
    variant = summary["per_variant"][DEFAULT_VARIANT]
    assert variant["prompt_role"] == WRITE_EXTRACTION_PROMPT_ROLE.role
    assert variant["prompt_schema_id"] == WRITE_EXTRACTION_PROMPT_ROLE.schema_id
    assert variant["prompt_schema_version"] == WRITE_EXTRACTION_PROMPT_ROLE.schema_version
    assert variant["prompt_text_metrics"] == metrics[DEFAULT_VARIANT]
    assert variant["promoted_counts"]["decision"] == 1
    assert variant["type_metrics"]["decision"]["correct"] == 1
    assert summary["run_id"].startswith("semantic-smoke__openai-compatible__fake-model__")
    assert len(results) == 1
    assert results[0]["status"] == "ok"
    assert results[0]["request"]["prompt_role"] == WRITE_EXTRACTION_PROMPT_ROLE.role
    assert results[0]["request"]["prompt_schema_id"] == WRITE_EXTRACTION_PROMPT_ROLE.schema_id
    assert results[0]["request"]["prompt_schema_version"] == WRITE_EXTRACTION_PROMPT_ROLE.schema_version
    assert results[0]["normalized_extraction"]["candidate_type"] == "decision"
    assert results[0]["artifacts"]["memory_objects"][0]["type"] == "decision"


def test_run_semantic_eval_can_compare_prompt_variants_and_signal_metrics(tmp_path: Path) -> None:
    input_file = tmp_path / "items.jsonl"
    output_dir = tmp_path / "output"
    _write_input_file(
        input_file,
        _decision_record("decision-1", "Decision: use item item event time reservation ordering."),
        _investigation_record("investigation-1", "Investigation found that arrival-time ordering missed hold updates during sync delays."),
        _signal_record(
            "signal-1",
            "Constraint: do not open a browser. Next step: compare ledger-query vs transaction-transformer locally.",
            {"constraint_text": True, "next_step_text": True, "is_low_value_meta": False},
        ),
        _signal_record(
            "signal-2",
            "Task complete. No Slack message needed. Nothing new to report.",
            {"is_low_value_meta": True, "constraint_text": False, "next_step_text": False},
        ),
    )

    plugin = LLMAgentMemoryPlugin(provider=VariantAwareStubLLMProvider())
    run_dir = run_semantic_eval(
        input_file=input_file,
        output_root=output_dir,
        plugin=plugin,
        config=AppConfig(default_use_case="llm_agent_memory", llm_prompt_variant=DEFAULT_VARIANT),
        run_name="variant-run",
        prompt_variants=["strict_typed_memory_v7_claude_minimal", "strict_typed_memory_v7_claude_structured", DEFAULT_VARIANT],
        split_output=True,
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = _read_jsonl(run_dir / "results.jsonl")

    assert summary["prompt_variants"] == ["strict_typed_memory_v7_claude_minimal", "strict_typed_memory_v7_claude_structured", DEFAULT_VARIANT]
    assert len(summary["split_outputs"]) == 12
    assert len(results) == 12
    assert summary["per_variant"]["strict_typed_memory_v7_claude_minimal"]["promoted_counts"]["decision"] == 1
    assert summary["per_variant"]["strict_typed_memory_v7_claude_minimal"]["promoted_counts"]["investigation_outcome"] == 1
    assert summary["per_variant"][DEFAULT_VARIANT]["signal_cases_total"] == 3
    assert summary["per_variant"][DEFAULT_VARIANT]["signal_cases_correct"] == 3
    assert summary["per_variant"][DEFAULT_VARIANT]["signal_metrics"]["constraint_text"]["correct"] == 2
    assert summary["per_variant"][DEFAULT_VARIANT]["signal_metrics"]["is_low_value_meta"]["correct"] == 2
    metrics = describe_prompt_variants()
    assert summary["prompt_text_metrics"][DEFAULT_VARIANT]["estimated_tokens"] == metrics[DEFAULT_VARIANT]["estimated_tokens"]
    assert metrics[DEFAULT_VARIANT]["estimated_tokens"] < metrics["strict_typed_memory_v4_evidence_guarded"]["estimated_tokens"]


def test_run_semantic_eval_parallel_keeps_stable_result_order(tmp_path: Path) -> None:
    input_file = tmp_path / "items.jsonl"
    output_dir = tmp_path / "output"
    _write_input_file(
        input_file,
        _decision_record("decision-1", "Decision: use item item event time reservation ordering."),
        _investigation_record("investigation-1", "Investigation found that arrival-time ordering missed hold updates during sync delays."),
    )

    plugin = LLMAgentMemoryPlugin(provider=DelayedVariantAwareStubLLMProvider())
    run_dir = run_semantic_eval(
        input_file=input_file,
        output_root=output_dir,
        plugin=plugin,
        config=AppConfig(default_use_case="llm_agent_memory", llm_prompt_variant=DEFAULT_VARIANT),
        run_name="parallel-order-run",
        prompt_variants=["strict_typed_memory_v7_claude_minimal", "strict_typed_memory_v7_claude_structured"],
        max_concurrency=4,
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = _read_jsonl(run_dir / "results.jsonl")

    assert summary["max_concurrency"] == 4
    assert [
        (row["input_index"], row["prompt_variant"], row["input_key"])
        for row in results
    ] == [
        (1, "strict_typed_memory_v7_claude_minimal", "001-decision-1"),
        (1, "strict_typed_memory_v7_claude_structured", "001-decision-1"),
        (2, "strict_typed_memory_v7_claude_minimal", "002-investigation-1"),
        (2, "strict_typed_memory_v7_claude_structured", "002-investigation-1"),
    ]


def test_run_semantic_eval_records_errors(tmp_path: Path) -> None:
    input_file = tmp_path / "items.jsonl"
    output_dir = tmp_path / "output"
    _write_input_file(input_file, _decision_record("decision-2", "Decision: use item item event time reservation ordering."))

    plugin = LLMAgentMemoryPlugin(provider=ErrorLLMProvider())
    run_dir = run_semantic_eval(
        input_file=input_file,
        output_root=output_dir,
        plugin=plugin,
        config=AppConfig(default_use_case="llm_agent_memory", llm_prompt_variant=DEFAULT_VARIANT),
        run_name="error-run",
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = _read_jsonl(run_dir / "results.jsonl")

    assert summary["items_failed"] == 1
    assert summary["per_variant"][DEFAULT_VARIANT]["items_failed"] == 1
    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert results[0]["error"]["type"] == "RuntimeError"

def _extract_source_id(user_prompt: str) -> str:
    for line in user_prompt.splitlines():
        if line.startswith("Source id:"):
            return line.split(":", 1)[1].strip()
    return ""


class WorkStateVariantAwareStubLLMProvider:
    _VARIANT_BY_PROMPT = {prompt: name for name, prompt in PROMPT_VARIANTS.items()}

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        variant = self._VARIANT_BY_PROMPT.get(system_prompt)
        source_id = _extract_source_id(user_prompt)
        parsed_json: dict[str, Any] = {
            "summary": "Semantic summary",
            "candidate_type": None,
            "decision_text": None,
            "decision_evidence_text": None,
            "investigation_text": None,
            "investigation_evidence_text": None,
            "rationale_text": None,
            "is_low_value_meta": False,
            "constraint_text": None,
            "next_step_text": None,
            "blocker_text": None,
            "progress_text": None,
            "key_finding_text": None,
            "subject_hints": [],
            "constraint_candidates": [],
        }
        if source_id == "signal-work-state-1":
            if variant in {"strict_typed_memory_v6_compact_work_state_negatives", "strict_typed_memory_v6_work_state_examples"}:
                parsed_json.update(
                    {
                        "summary": "Natural-language resumed-work state.",
                        "progress_text": "The token refresh worked and the sync got through batch 417.",
                        "blocker_text": "The retry window is exhausted now.",
                        "next_step_text": "Wait 15 minutes and resume from batch 418.",
                    }
                )
            elif variant == "strict_typed_memory_v6_compact_work_state":
                parsed_json.update(
                    {
                        "summary": "Partial work-state extraction.",
                        "blocker_text": "The retry window is exhausted now.",
                        "next_step_text": "Wait 15 minutes and resume from batch 418.",
                    }
                )
            else:
                parsed_json.update(
                    {
                        "summary": "Baseline work-state extraction misses progress.",
                        "blocker_text": "The retry window is exhausted now.",
                        "next_step_text": "Wait 15 minutes and resume from batch 418.",
                    }
                )
        elif source_id == "signal-work-state-2":
            if variant == "strict_typed_memory_v6_compact_work_state":
                parsed_json.update(
                    {
                        "summary": "Weak work-state overreach.",
                        "next_step_text": "Confirm which worker you mean first.",
                    }
                )
            else:
                parsed_json["summary"] = "Tentative guidance without durable state."
        return LLMJsonResponse(raw_text=json.dumps(parsed_json), parsed_json=parsed_json)


def test_run_semantic_eval_compares_work_state_prompt_candidates(tmp_path: Path) -> None:
    input_file = tmp_path / "items.jsonl"
    output_dir = tmp_path / "output"
    _write_input_file(
        input_file,
        _signal_record(
            "signal-work-state-1",
            "The token refresh worked and the sync got through batch 417, but the retry window is exhausted now. Wait 15 minutes and resume from batch 418.",
            {"progress_text": True, "blocker_text": True, "next_step_text": True, "key_finding_text": False, "is_low_value_meta": False},
        ),
        _signal_record(
            "signal-work-state-2",
            "I can lower concurrency or bump memory, but I need to confirm which worker you mean first.",
            {"progress_text": False, "blocker_text": False, "next_step_text": False, "key_finding_text": False, "is_low_value_meta": False},
        ),
    )

    plugin = LLMAgentMemoryPlugin(provider=WorkStateVariantAwareStubLLMProvider())
    variants = [
        DEFAULT_VARIANT,
        "strict_typed_memory_v6_compact_work_state",
        "strict_typed_memory_v6_compact_work_state_negatives",
        "strict_typed_memory_v6_work_state_examples",
    ]
    run_dir = run_semantic_eval(
        input_file=input_file,
        output_root=output_dir,
        plugin=plugin,
        config=AppConfig(default_use_case="llm_agent_memory", llm_prompt_variant=DEFAULT_VARIANT),
        run_name="work-state-variant-run",
        prompt_variants=variants,
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))

    assert summary["prompt_variants"] == variants
    assert summary["per_variant"][DEFAULT_VARIANT]["signal_metrics"]["progress_text"]["correct"] == 1
    assert summary["per_variant"][DEFAULT_VARIANT]["signal_metrics"]["next_step_text"]["correct"] == 2
    assert summary["per_variant"]["strict_typed_memory_v6_compact_work_state"]["signal_metrics"]["progress_text"]["correct"] == 1
    assert summary["per_variant"]["strict_typed_memory_v6_compact_work_state_negatives"]["signal_metrics"]["progress_text"]["correct"] == 2
    assert summary["per_variant"]["strict_typed_memory_v6_compact_work_state_negatives"]["signal_metrics"]["blocker_text"]["correct"] == 2
    assert summary["per_variant"]["strict_typed_memory_v6_compact_work_state_negatives"]["signal_metrics"]["next_step_text"]["correct"] == 2
    assert summary["per_variant"]["strict_typed_memory_v6_work_state_examples"]["signal_metrics"]["progress_text"]["correct"] == 2
