from __future__ import annotations

import json
import time
from pathlib import Path

from app.config import AppConfig
from evals.semantic_runner import run_semantic_eval
from providers.llm.base import LLMJsonResponse
from semantic.llm_agent_memory import LLMAgentMemoryPlugin


class VariantAwareStubLLMProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if 'Investigation found that ingestion-time progress tracking skipped records during lag.' in user_prompt:
            parsed_json = {
                "summary": "Investigation summary",
                "candidate_type": "investigation_outcome",
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": "ingestion-time progress tracking skipped records during lag",
                "investigation_evidence_text": "Investigation found that ingestion-time progress tracking skipped records during lag",
                "rationale_text": "because EventHub lag delayed ingestion",
            }
        elif 'Classify candidate_type as \"decision\" only when the source explicitly records a committed choice' in system_prompt:
            parsed_json = {
                "summary": "Strict summary",
                "candidate_type": None,
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
            }
        else:
            parsed_json = {
                "summary": "Baseline summary",
                "candidate_type": "decision",
                "decision_text": "use event timestamp watermarking",
                "decision_evidence_text": "Decision: use event timestamp watermarking",
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": "to avoid skipped records during lag",
            }
        return LLMJsonResponse(raw_text=json.dumps(parsed_json), parsed_json=parsed_json)


class DelayedVariantAwareStubLLMProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if 'Investigation found that ingestion-time progress tracking skipped records during lag.' in user_prompt:
            time.sleep(0.02)
            parsed_json = {
                "summary": "Investigation summary",
                "candidate_type": "investigation_outcome",
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": "ingestion-time progress tracking skipped records during lag",
                "investigation_evidence_text": "Investigation found that ingestion-time progress tracking skipped records during lag",
                "rationale_text": None,
            }
        else:
            time.sleep(0.08)
            parsed_json = {
                "summary": "Decision summary",
                "candidate_type": "decision",
                "decision_text": "use event timestamp watermarking",
                "decision_evidence_text": "Decision: use event timestamp watermarking",
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
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
        "metadata": {"topic": "watermarking", "expected_kind": expected_kind},
    }


def _investigation_record(source_id: str, content: str, *, expected_kind: str = "investigation_outcome") -> dict[str, object]:
    return {
        "source_type": "investigation_summary",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "tool_use_summary",
        "role": "assistant",
        "metadata": {"topic": "watermarking", "expected_kind": expected_kind},
    }


def test_run_semantic_eval_writes_summary_and_jsonl_results(tmp_path: Path) -> None:
    input_file = tmp_path / "items.jsonl"
    output_dir = tmp_path / "output"
    _write_input_file(input_file, _decision_record("decision-1", "Decision: use event timestamp watermarking."))

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
            llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
        ),
        suite_name="semantic smoke",
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = _read_jsonl(run_dir / "results.jsonl")

    assert summary["suite_name"] == "semantic smoke"
    assert summary["items_succeeded"] == 1
    assert summary["promoted_counts"]["decision"] == 1
    assert summary["input_file"] == str(input_file)
    assert summary["results_file"] == "results.jsonl"
    assert summary["prompt_schema_id"] == "typed_memory_extraction"
    assert summary["prompt_schema_version"] == "v4"
    assert summary["split_output"] is False
    assert summary["split_outputs"] == []
    assert summary["prompt_variants"] == ["strict_typed_memory_v4_evidence_guarded"]
    assert summary["max_concurrency"] == 1
    variant = summary["per_variant"]["strict_typed_memory_v4_evidence_guarded"]
    assert variant["prompt_schema_id"] == "typed_memory_extraction"
    assert variant["prompt_schema_version"] == "v4"
    assert variant["promoted_counts"]["decision"] == 1
    assert variant["type_metrics"]["decision"]["correct"] == 1
    assert summary["run_id"].startswith("semantic-smoke__openai-compatible__fake-model__")
    assert len(results) == 1
    assert results[0]["status"] == "ok"
    assert results[0]["request"]["prompt_schema_id"] == "typed_memory_extraction"
    assert results[0]["request"]["prompt_schema_version"] == "v4"
    assert results[0]["normalized_extraction"]["candidate_type"] == "decision"
    assert results[0]["artifacts"]["memory_objects"][0]["type"] == "decision"


def test_run_semantic_eval_can_compare_prompt_variants_in_one_run(tmp_path: Path) -> None:
    input_file = tmp_path / "items.jsonl"
    output_dir = tmp_path / "output"
    _write_input_file(
        input_file,
        _decision_record("decision-1", "Decision: use event timestamp watermarking."),
        _investigation_record("investigation-1", "Investigation found that ingestion-time progress tracking skipped records during lag."),
    )

    plugin = LLMAgentMemoryPlugin(provider=VariantAwareStubLLMProvider())
    run_dir = run_semantic_eval(
        input_file=input_file,
        output_root=output_dir,
        plugin=plugin,
        config=AppConfig(default_use_case="llm_agent_memory", llm_prompt_variant="strict_typed_memory_v4_evidence_guarded"),
        run_name="variant-run",
        prompt_variants=["baseline", "strict_decision_v1"],
        split_output=True,
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = _read_jsonl(run_dir / "results.jsonl")

    assert summary["prompt_variants"] == ["baseline", "strict_decision_v1"]
    assert len(summary["split_outputs"]) == 4
    assert len(results) == 4
    assert summary["per_variant"]["baseline"]["promoted_counts"]["decision"] == 1
    assert summary["per_variant"]["baseline"]["promoted_counts"]["investigation_outcome"] == 1


def test_run_semantic_eval_parallel_keeps_stable_result_order(tmp_path: Path) -> None:
    input_file = tmp_path / "items.jsonl"
    output_dir = tmp_path / "output"
    _write_input_file(
        input_file,
        _decision_record("decision-1", "Decision: use event timestamp watermarking."),
        _investigation_record("investigation-1", "Investigation found that ingestion-time progress tracking skipped records during lag."),
    )

    plugin = LLMAgentMemoryPlugin(provider=DelayedVariantAwareStubLLMProvider())
    run_dir = run_semantic_eval(
        input_file=input_file,
        output_root=output_dir,
        plugin=plugin,
        config=AppConfig(default_use_case="llm_agent_memory", llm_prompt_variant="strict_typed_memory_v4_evidence_guarded"),
        run_name="parallel-order-run",
        prompt_variants=["baseline", "strict_decision_v1"],
        max_concurrency=4,
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = _read_jsonl(run_dir / "results.jsonl")

    assert summary["max_concurrency"] == 4
    assert [
        (row["input_index"], row["prompt_variant"], row["input_key"])
        for row in results
    ] == [
        (1, "baseline", "001-decision-1"),
        (1, "strict_decision_v1", "001-decision-1"),
        (2, "baseline", "002-investigation-1"),
        (2, "strict_decision_v1", "002-investigation-1"),
    ]


def test_run_semantic_eval_records_errors(tmp_path: Path) -> None:
    input_file = tmp_path / "items.jsonl"
    output_dir = tmp_path / "output"
    _write_input_file(input_file, _decision_record("decision-2", "Decision: use event timestamp watermarking."))

    plugin = LLMAgentMemoryPlugin(provider=ErrorLLMProvider())
    run_dir = run_semantic_eval(
        input_file=input_file,
        output_root=output_dir,
        plugin=plugin,
        config=AppConfig(default_use_case="llm_agent_memory", llm_prompt_variant="strict_typed_memory_v4_evidence_guarded"),
        run_name="error-run",
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = _read_jsonl(run_dir / "results.jsonl")

    assert summary["items_failed"] == 1
    assert summary["per_variant"]["strict_typed_memory_v4_evidence_guarded"]["items_failed"] == 1
    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert results[0]["error"]["type"] == "RuntimeError"
