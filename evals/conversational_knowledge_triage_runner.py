from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from capabilities.consolidation import ConsolidationCandidate, ConsolidationPolicy, FactConsolidationStrategy
from capabilities.thread_aggregation import ThreadAggregate
from core.models import MemoryObject, SourceItem, new_id, utc_now
from providers.llm.base import LLMJsonResponse
from semantic.conversational_knowledge import ConversationalKnowledgePlugin


DEFAULT_SCENARIO_FILE = Path("evals/conversational_knowledge/structural_triage_scenarios.json")
DEFAULT_OUTPUT_DIR = Path("evals/conversational_knowledge/output")


class _StubFactExtractionProvider:
    def __init__(self, facts: list[dict[str, Any]]) -> None:
        self._facts = facts

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        payload = {"facts": self._facts}
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic conversational-knowledge triage structural scenarios.")
    parser.add_argument("--scenario-file", type=Path, default=DEFAULT_SCENARIO_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    args = parser.parse_args()

    run_dir = run_eval(
        scenario_file=args.scenario_file,
        output_root=args.output_dir,
        run_name=args.run_name,
    )
    print(run_dir)
    return 0


def run_eval(*, scenario_file: Path, output_root: Path, run_name: str | None = None) -> Path:
    scenarios = json.loads(scenario_file.read_text(encoding="utf-8"))
    run_id = run_name or _build_run_id()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    results = [_run_scenario(scenario) for scenario in scenarios]
    passed = sum(1 for item in results if item["passed"])

    with results_path.open("w", encoding="utf-8") as handle:
        for item in results:
            handle.write(json.dumps(item) + "\n")

    summary = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario_file": str(scenario_file),
        "results_file": results_path.name,
        "scenarios_total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return run_dir


def _run_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    kind = str(scenario["kind"])
    if kind == "thread_summary":
        return _run_thread_summary_scenario(scenario)
    if kind == "fact_consolidation_grouping":
        return _run_grouping_scenario(scenario)
    raise ValueError(f"Unsupported scenario kind: {kind}")


def _run_thread_summary_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    source_items = [
        SourceItem(
            source_type="chat",
            source_id=f"{scenario['scenario_id']}-item-{index}",
            content_type="text/plain",
            content=str(item["content"]),
            role=str(item["role"]),
            artifact_kind=str(item["artifact_kind"]),
            container_ref="c1",
            thread_ref="t1",
            visibility="public",
            occurred_at=utc_now(),
        )
        for index, item in enumerate(scenario["source_items"], start=1)
    ]
    aggregate = ThreadAggregate(
        container_ref="c1",
        thread_ref="t1",
        source_items=source_items,
        source_item_ids=[item.id for item in source_items],
        latest_occurred_at=utc_now(),
        aggregate_text="",
        visibility="public",
    )
    plugin = ConversationalKnowledgePlugin(provider=_StubFactExtractionProvider(list(scenario["facts"])))
    result = plugin.build_thread_summary(aggregate, conclusions=[])
    actual_subjects = [memory.payload["subject"] for memory in result.memory_objects]
    actual_statements = [memory.payload["statement"] for memory in result.memory_objects]
    expected_subjects = list(scenario["expected_subjects"])
    expected_statements = list(scenario["expected_statements"])

    return {
        "scenario_id": scenario["scenario_id"],
        "kind": scenario["kind"],
        "description": scenario["description"],
        "expected_subjects": expected_subjects,
        "actual_subjects": actual_subjects,
        "expected_statements": expected_statements,
        "actual_statements": actual_statements,
        "passed": actual_subjects == expected_subjects and actual_statements == expected_statements,
    }


def _run_grouping_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    strategy = FactConsolidationStrategy()
    policy = ConsolidationPolicy(max_candidates_per_run=200)
    candidates = [
        _make_fact_candidate(
            subject=str(scenario["subject"]),
            category=str(scenario["category"]),
            container_ref=str(scenario["container_ref"]),
            thread_ref=str(thread_ref),
            visibility=str(scenario.get("visibility", "public")),
        )
        for thread_ref in scenario["thread_refs"]
    ]
    groups = strategy.group_candidates(strategy.select_candidates(candidates, policy), policy)
    actual_scopes = [group.merge_rationale.get("grouping_scope") for group in groups]
    expected_group_count = int(scenario["expected_group_count"])
    expected_scope = str(scenario["expected_grouping_scope"])

    return {
        "scenario_id": scenario["scenario_id"],
        "kind": scenario["kind"],
        "description": scenario["description"],
        "expected_group_count": expected_group_count,
        "actual_group_count": len(groups),
        "expected_grouping_scope": expected_scope,
        "actual_grouping_scopes": actual_scopes,
        "passed": len(groups) == expected_group_count and actual_scopes == [expected_scope],
    }


def _make_fact_candidate(
    *,
    subject: str,
    category: str,
    container_ref: str,
    thread_ref: str,
    visibility: str,
) -> ConsolidationCandidate:
    memory_object = MemoryObject(
        id=new_id(),
        type="atomic_fact",
        schema_id="conversational_knowledge.atomic_fact",
        schema_version="v1",
        payload={
            "subject": subject,
            "statement": f"{subject} fact in {thread_ref}",
            "category": category,
            "thread_ref": thread_ref,
        },
        lifecycle="active",
        visibility=visibility,
        container_ref=container_ref,
    )
    return ConsolidationCandidate(
        memory_object=memory_object,
        evidence=(),
        text_view=f"{subject} fact in {thread_ref}",
        tokens=frozenset(f"{subject} fact in {thread_ref}".lower().split()),
        container_ref=container_ref,
        thread_ref=thread_ref,
        latest_occurred_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        visibility=visibility,
    )


def _build_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"conversational-knowledge-triage__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())