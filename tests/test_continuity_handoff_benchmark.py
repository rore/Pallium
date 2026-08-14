from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from evals.continuity_handoff_benchmark import (
    ARM_MANUAL_SUMMARY,
    ARM_MANUAL_TRANSCRIPT,
    ARM_NO_MEMORY,
    ARM_PULL_BACKED,
    run_continuity_handoff_benchmark,
)
from providers.llm.base import LLMJsonResponse
from tests.config_helpers import build_llm_test_config
from tests.tiered_memory_stub_providers import TieredMemorySemanticProvider

pytestmark = pytest.mark.slow

SCENARIOS = Path("evals/continuity_handoff/scenarios.json")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _config():
    return build_llm_test_config(default_use_case="agent_conversation_memory", model="fake-answer-model")


def _empty() -> dict[str, object]:
    return {
        "answer": "", "task_orientation": "", "reused_findings": [], "blocker_state": "",
        "preserved_progress": "", "next_step": "", "evidence_used": [], "freshness_notes": "",
    }


# Rich payloads keyed by scenario id: memory/manual arms return these (all
# expected-dimension signals present) so they tie on correctness; the no_memory
# arm returns an empty payload. On a correctness tie the harness prefers the
# lowest user-orchestration-cost arm (pull), which the assertions check.
_RICH: dict[str, dict[str, object]] = {
    "resume-investigation-after-pause": {
        "answer": "Resume the delayed catalog sync duplicate holds investigation.",
        "task_orientation": "delayed catalog sync duplicate holds",
        "reused_findings": ["arrival-time ordering reused stale hold state", "item event time"],
        "blocker_state": "", "preserved_progress": "",
        "next_step": "Switch ordering to item event time.",
        "evidence_used": ["prior source turns"], "freshness_notes": "",
    },
    "resume-after-tool-failure": {
        "answer": "Resume the catalog sync retry.",
        "task_orientation": "catalog sync retry",
        "reused_findings": [],
        "blocker_state": "stopped with a 401 because the token expired",
        "preserved_progress": "refreshed 312 reservation records",
        "next_step": "refresh the token and resume from batch 313",
        "evidence_used": ["prior source turns"], "freshness_notes": "",
    },
    "resume-implementation-ticket": {
        "answer": "Continue ticket LIB-241.",
        "task_orientation": "LIB-241 use_item_event_time flag",
        "reused_findings": [],
        "blocker_state": "",
        "preserved_progress": "schema change and backfill done",
        "next_step": "wire the admin toggle and add retry-path coverage",
        "evidence_used": ["prior source turns"], "freshness_notes": "",
    },
    "parallel-session-debugging-handoff": {
        "answer": "Continue the duplicate-hold debugging.",
        "task_orientation": "duplicate-hold debugging",
        "reused_findings": ["cache invalidation", "reservation cache is warm"],
        "blocker_state": "",
        "preserved_progress": "local replay confirmed the bug",
        "next_step": "compare cache invalidation between delayed and immediate workers",
        "evidence_used": ["prior source turns"], "freshness_notes": "",
    },
    "same-thread-sufficient-no-value": {
        "answer": "The plan is a 3-attempt retry cap with a page on the third failure.",
        "task_orientation": "retry plan",
        "reused_findings": [],
        "blocker_state": "",
        "preserved_progress": "",
        "next_step": "3-attempt retry cap and page on the third failure",
        "evidence_used": [], "freshness_notes": "",
    },
}


class StubHandoffAnswerProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        scenario_id = _extract(user_prompt, "Scenario ID:")
        branch = _extract(user_prompt, "Branch:")
        if branch == ARM_NO_MEMORY and scenario_id != "same-thread-sufficient-no-value":
            payload = _empty()
        else:
            payload = _RICH.get(scenario_id, _empty())
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def _extract(text: str, prefix: str) -> str:
    m = re.search(rf"^{re.escape(prefix)}\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def test_handoff_benchmark_emits_four_arms_and_consensus(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_continuity_handoff_benchmark(
        scenario_file=SCENARIOS,
        output_root=tmp_path / "output",
        config=_config(),
        run_name="handoff-smoke",
        answer_provider=StubHandoffAnswerProvider(),
        seeds=2,
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = {r["scenario_id"]: r for r in _read_jsonl(run_dir / "results.jsonl")}
    report = (run_dir / "report.md").read_text(encoding="utf-8")

    assert summary["scenarios_total"] == 5
    assert summary["value_scenarios"] == 4
    assert summary["arms"] == [ARM_NO_MEMORY, ARM_PULL_BACKED, ARM_MANUAL_TRANSCRIPT, ARM_MANUAL_SUMMARY]
    assert "# Cross-Context Work-Continuity Handoff Experiment" in report

    # Every scenario reports all four arms with a 2-seed correctness sample.
    for r in results.values():
        assert set(r["arm_summaries"]) == {ARM_NO_MEMORY, ARM_PULL_BACKED, ARM_MANUAL_TRANSCRIPT, ARM_MANUAL_SUMMARY}
        for arm in r["arm_summaries"].values():
            assert len(arm["per_seed_correctness"]) == 2

    # Orchestration-cost proxy: no_memory routes nothing; pull routes only the
    # pointer/ask, strictly cheaper than pasting a summary or a transcript.
    for sid, r in results.items():
        cost = r["orchestration_cost_tokens"]
        assert cost[ARM_NO_MEMORY] == 0
        if r["should_memory_help"]:
            assert cost[ARM_PULL_BACKED] < cost[ARM_MANUAL_SUMMARY]
            assert cost[ARM_PULL_BACKED] < cost[ARM_MANUAL_TRANSCRIPT]

    # Pull arm actually recovered raw source context via source_only + expansion.
    for sid, r in results.items():
        if r["should_memory_help"]:
            assert r["pull_source_hit_count"] > 0, f"{sid} recovered no source hits"
            assert r["pull_agent_roundtrips"] >= 2  # 1 search + >=1 expansion

    # On a correctness tie among memory arms the harness prefers lowest-cost pull.
    for sid, r in results.items():
        if r["should_memory_help"]:
            assert r["consensus_winner"] == ARM_PULL_BACKED, f"{sid} winner {r['consensus_winner']}"

    # No-value scenario: current thread already sufficient -> no_memory wins.
    nv = results["same-thread-sufficient-no-value"]
    assert nv["consensus_winner"] == ARM_NO_MEMORY

    # Headline booleans are computed and coherent.
    assert isinstance(summary["pull_preserves_manual_correctness"], bool)
    assert summary["pull_cheaper_than_manual"] is True


def test_handoff_benchmark_is_seed_stable_under_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())
    cache_dir = tmp_path / "llm-cache"

    def run(name: str):
        return run_continuity_handoff_benchmark(
            scenario_file=SCENARIOS,
            output_root=tmp_path / name,
            config=_config(),
            run_name=name,
            answer_provider=StubHandoffAnswerProvider(),
            seeds=3,
            cache_dir=cache_dir,
        )

    first = json.loads((run("r1") / "summary.json").read_text(encoding="utf-8"))
    second = json.loads((run("r2") / "summary.json").read_text(encoding="utf-8"))
    assert first["consensus_winner_counts"] == second["consensus_winner_counts"]
    assert first["arm_mean_correctness"] == second["arm_mean_correctness"]
