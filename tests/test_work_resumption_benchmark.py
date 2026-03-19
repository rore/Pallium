from __future__ import annotations

import json
import re
from pathlib import Path

from tests.config_helpers import build_llm_test_config
from evals.work_resumption_benchmark import run_work_resumption_benchmark
from providers.llm.base import LLMJsonResponse
from tests.stub_providers import TieredMemorySemanticProvider


SCENARIOS = Path("evals/work_resumption/scenarios.json")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _benchmark_config(prompt_variant: str = "strict_typed_memory_v6_work_state_examples"):
    return build_llm_test_config(
        default_use_case="agent_conversation_memory",
        model="fake-answer-model",
        agent_conversation_prompt_variant=prompt_variant,
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


def _empty_payload(answer: str = "", *, task_orientation: str = "", blocker_state: str = "", next_step: str = "") -> dict[str, object]:
    return {
        "answer": answer,
        "task_orientation": task_orientation,
        "reused_findings": [],
        "blocker_state": blocker_state,
        "preserved_progress": "",
        "next_step": next_step,
        "evidence_used": [],
        "freshness_notes": "",
    }


def _payload_for(*, scenario_id: str, branch: str) -> dict[str, object]:
    baseline = branch == "baseline"

    if scenario_id == "resume-investigation-after-pause":
        if baseline:
            return _empty_payload("Resume the delayed catalog sync investigation first.", task_orientation="Delayed catalog sync investigation")
        return {
            "answer": "Resume the delayed catalog sync investigation from the duplicate-hold conclusion: arrival-time ordering reused stale hold state, so we switched to item event time.",
            "task_orientation": "Delayed catalog sync investigation and duplicate holds",
            "reused_findings": ["arrival-time ordering reused stale hold state", "item event time"],
            "blocker_state": "",
            "preserved_progress": "",
            "next_step": "",
            "evidence_used": ["investigation_outcome", "decision"],
            "freshness_notes": "",
        }

    if scenario_id == "debugging-continued-from-partial-findings":
        if baseline:
            return _empty_payload("Resume duplicate-hold debugging on the delayed sync workers.", task_orientation="Duplicate-hold debugging")
        return {
            "answer": "Resume duplicate-hold debugging on delayed sync workers from the warm-cache finding: local replay already confirmed the bug and narrowed it to cache invalidation, so compare invalidation between delayed and immediate workers next.",
            "task_orientation": "Duplicate-hold debugging on delayed sync workers",
            "reused_findings": ["reservation cache is warm", "cache invalidation"],
            "blocker_state": "",
            "preserved_progress": "Local replay confirmed the bug and narrowed it to cache invalidation.",
            "next_step": "Compare cache invalidation between delayed and immediate sync workers.",
            "evidence_used": ["task_checkpoint", "investigation_outcome"],
            "freshness_notes": "",
        }

    if scenario_id == "resume-after-auth-tool-failure":
        if baseline:
            return _empty_payload("The retry is queued again.")
        return {
            "answer": "Resume the catalog sync retry from batch 313 after refreshing the catalog service token; the prior run refreshed 312 reservation records before a 401 from the expired token.",
            "task_orientation": "Catalog sync retry",
            "reused_findings": [],
            "blocker_state": "401 because the service token expired",
            "preserved_progress": "Refreshed 312 reservation records and should rerun the sync from batch 313.",
            "next_step": "Refresh the catalog service token and rerun the sync from batch 313.",
            "evidence_used": ["task_checkpoint"],
            "freshness_notes": "The current blocker is still the expired token.",
        }

    if scenario_id == "resume-implementation-ticket-after-interruption":
        if baseline:
            return _empty_payload("Resume ticket LIB-241.", task_orientation="Ticket LIB-241")
        return {
            "answer": "Resume ticket LIB-241 with the reservation ordering fix still behind the use_item_event_time flag: the schema change and backfill are done, and the next step is wiring the admin toggle plus retry-path coverage.",
            "task_orientation": "Ticket LIB-241 with the use_item_event_time flag",
            "reused_findings": ["reservation ordering fix"],
            "blocker_state": "",
            "preserved_progress": "Schema change and backfill done.",
            "next_step": "Wire the admin toggle and add retry-path coverage before enabling the flag.",
            "evidence_used": ["task_checkpoint", "decision"],
            "freshness_notes": "",
        }

    if scenario_id == "resume-review-follow-up-after-feedback":
        if baseline:
            return _empty_payload("Resume the LIB-241 review follow-up.", task_orientation="Ticket LIB-241 review")
        return {
            "answer": "Resume the LIB-241 review follow-up with the branch kiosk constraint still in place: the admin toggle wiring is ready, but the branch kiosk fallback is still missing, so add that coverage before re-requesting review.",
            "task_orientation": "Ticket LIB-241 review for branch kiosks",
            "reused_findings": ["keep the use_item_event_time flag off", "branch kiosk fallback is still missing"],
            "blocker_state": "Review is blocked because the branch kiosk fallback is still missing.",
            "preserved_progress": "Admin toggle wiring is ready.",
            "next_step": "Add the branch kiosk fallback coverage and re-request review before enabling the flag.",
            "evidence_used": ["task_checkpoint", "decision"],
            "freshness_notes": "The current review blocker is the missing branch kiosk fallback.",
        }

    if scenario_id == "prefer-fresh-blocker-over-stale-checkpoint":
        if baseline:
            return _empty_payload("The retry moved forward, but the visible thread does not show the latest blocker.")
        return {
            "answer": "The current blocker is no longer the expired token. The token is refreshed, the retry resumed from batch 313, and the latest blocker is a 429 after batch 417, so wait 15 minutes and resume from batch 418.",
            "task_orientation": "Catalog sync retry",
            "reused_findings": ["the service token is refreshed"],
            "blocker_state": "429 because the retry window was exhausted after batch 417.",
            "preserved_progress": "The sync resumed from batch 313 after the token refresh.",
            "next_step": "Wait 15 minutes and resume from batch 418.",
            "evidence_used": ["task_checkpoint"],
            "freshness_notes": "The current blocker is 429 after auth refresh; the older 401 is stale.",
        }

    if scenario_id == "wrong-thread-implementation-guard":
        if baseline:
            return _empty_payload("Resume ticket LIB-241.", task_orientation="Ticket LIB-241")
        return {
            "answer": "Stay on ticket LIB-241: the use_item_event_time flag is still gated, the schema change and backfill are done, and the next step is wiring the admin toggle plus retry-path coverage.",
            "task_orientation": "Ticket LIB-241 with the use_item_event_time flag",
            "reused_findings": [],
            "blocker_state": "",
            "preserved_progress": "Schema change and backfill done.",
            "next_step": "Wire the admin toggle and add retry-path coverage before enabling the flag.",
            "evidence_used": ["task_checkpoint"],
            "freshness_notes": "",
        }

    if scenario_id == "same-thread-review-no-value-guard":
        return {
            "answer": "Add the branch kiosk fallback coverage first, then ask for review again.",
            "task_orientation": "",
            "reused_findings": [],
            "blocker_state": "branch kiosk fallback",
            "preserved_progress": "",
            "next_step": "Add the branch kiosk fallback coverage, then review again.",
            "evidence_used": [],
            "freshness_notes": "",
        }

    if scenario_id == "resume-exact-evidence-for-review-blocker":
        if baseline:
            return _empty_payload("The current thread asks for exact prior evidence, but it does not restate it.")
        return {
            "answer": "The exact prior evidence was the review progress artifact saying that admin toggle wiring was ready, but the branch kiosk fallback was still missing.",
            "task_orientation": "",
            "reused_findings": ["branch kiosk fallback is still missing"],
            "blocker_state": "",
            "preserved_progress": "",
            "next_step": "",
            "evidence_used": ["source evidence", "branch kiosk fallback is still missing"],
            "freshness_notes": "",
        }

    if scenario_id == "public-query-must-not-leak-limited-rollout-state":
        if baseline:
            return _empty_payload("The rollout was paused before enablement.", task_orientation="LIB-241 rollout")
        return {
            "answer": "The public conclusion was to keep the LIB-241 rollout paused until retry-path coverage exists.",
            "task_orientation": "LIB-241 rollout",
            "reused_findings": ["keep the LIB-241 rollout paused", "retry-path coverage exists"],
            "blocker_state": "",
            "preserved_progress": "",
            "next_step": "",
            "evidence_used": ["decision"],
            "freshness_notes": "",
        }

    if scenario_id == "limited-query-can-use-same-limited-rollout-state":
        if baseline:
            return _empty_payload("The rollout is still paused.", task_orientation="LIB-241 rollout")
        return {
            "answer": "In rollout channel alpha, LIB-241 is still blocked because partner approval code ALPHA-PRIVATE is pending, so wait for alpha approval and rerun rollout validation next.",
            "task_orientation": "LIB-241 rollout in rollout channel alpha",
            "reused_findings": ["ALPHA-PRIVATE is pending in rollout channel alpha"],
            "blocker_state": "Partner approval code ALPHA-PRIVATE is still pending in rollout channel alpha.",
            "preserved_progress": "",
            "next_step": "Wait for alpha approval, then rerun rollout validation in rollout channel alpha.",
            "evidence_used": ["task_checkpoint", "decision"],
            "freshness_notes": "",
        }

    if scenario_id == "user-private-query-stays-isolated-from-limited-channel":
        if baseline:
            return _empty_payload("The rollout is still paused.", task_orientation="Private rollout follow-up")
        return {
            "answer": "For the private rollout follow-up, the remaining blocker is the USER-PRIVATE vendor approval reply, so wait for the vendor reply and then continue the private rollout checklist.",
            "task_orientation": "Private rollout follow-up",
            "reused_findings": ["USER-PRIVATE still needs the vendor approval reply"],
            "blocker_state": "USER-PRIVATE still needs the vendor approval reply.",
            "preserved_progress": "",
            "next_step": "Wait for the vendor reply, then continue the private rollout checklist.",
            "evidence_used": ["task_checkpoint", "decision"],
            "freshness_notes": "",
        }

    return {
        "answer": "Refresh the catalog service token first, then rerun the sync.",
        "task_orientation": "Catalog sync",
        "reused_findings": [],
        "blocker_state": "Refresh auth first",
        "preserved_progress": "",
        "next_step": "Refresh the catalog service token, then rerun the sync.",
        "evidence_used": [],
        "freshness_notes": "",
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

    assert summary["scenarios_total"] == 13
    assert summary["value_scenarios"] == 11
    assert summary["non_value_scenarios"] == 2
    assert len(results) == 13
    assert summary["query_family_matches"] >= 10
    assert summary["injection_contract_successes"] >= 9
    assert summary["thin_agent_boundary_successes"] >= 9
    assert summary["privacy_guard_successes"] == 3
    assert summary["dominant_tuning_bottleneck"] == "packaging"
    assert summary["failure_family_counts"]["retrieval_recall_failure"] == 0
    assert summary["failure_family_counts"]["injectability_packaging_failure"] >= 1
    assert summary["failure_family_counts"]["thin_agent_boundary_failure"] >= 1
    assert summary["failure_family_counts"]["routing_layer_choice_failure"] == 0
    assert summary["benchmark"]["suite_id"] == "work_resumption"
    assert summary["benchmark"]["dataset_tier"] == "confidence"
    assert summary["benchmark"]["primary_lane"] == "realism"
    assert summary["benchmark"]["hard_gate_summary"]["lanes"] == ["contract", "trace"]
    assert summary["benchmark"]["lane_aggregates"]["contract"]["scenarios_total"] == 13
    assert summary["benchmark"]["lane_aggregates"]["realism"]["scenarios_total"] == 13
    assert summary["benchmark"]["lane_aggregates"]["operational"]["scenarios_total"] == 13
    assert "## Failure Families" in report



def test_work_resumption_benchmark_captures_successes_and_attributed_packaging_failures(monkeypatch, tmp_path: Path) -> None:
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
    assert resumed["suite_id"] == "work_resumption"
    assert resumed["dataset_tier"] == "confidence"
    assert resumed["primary_lane"] == "realism"
    assert resumed["scored_lanes"] == ["contract", "trace", "usefulness", "realism", "operational"]
    assert resumed["winner"] == "memory_backed"
    assert resumed["expected_memory_types_found"] is True
    assert resumed["top_layer"] == "lower_level_memory"
    assert resumed["should_inject"] is True
    assert resumed["decision_reason"] == "carry_forward_available"
    assert resumed["injection_contract"]["contract_success"] is True
    assert resumed["query_contract_mismatch_fields"] == []
    assert set(resumed["failure_families"]).issubset({"routing_layer_choice_failure", "paraphrase_or_indirect_query_failure"})

    review = results["resume-review-follow-up-after-feedback"]
    assert review["winner"] == "memory_backed"
    assert review["top_layer"] == "task_checkpoint"
    assert review["query_family"] == "resumed_session_continuation"
    assert review["labels"]["scenario_family"] == "review_continuity"
    assert review["failure_families"] == []
    assert review["expected_memory_types_found"] is True

    stale = results["prefer-fresh-blocker-over-stale-checkpoint"]
    assert stale["top_layer"] == "task_checkpoint"
    assert stale["stale_guard_success"] is True
    assert stale["failure_families"] == []

    wrong_thread = results["wrong-thread-implementation-guard"]
    assert wrong_thread["top_layer"] == "task_checkpoint"
    assert wrong_thread["wrong_memory_guard_success"] is True
    assert wrong_thread["failure_families"] == []

    evidence_followup = results["resume-exact-evidence-for-review-blocker"]
    assert evidence_followup["winner"] == "memory_backed"
    assert evidence_followup["routing_intent"] == "evidence_trace"
    assert evidence_followup["should_inject"] is True
    assert evidence_followup["injection_contract"]["contract_success"] is True

    public_guard = results["public-query-must-not-leak-limited-rollout-state"]
    assert public_guard["winner"] == "memory_backed"
    assert public_guard["should_inject"] is True
    assert public_guard["decision_reason"] == "carry_forward_available"
    assert "injectability_packaging_failure" in public_guard["failure_families"]
    assert "thin_agent_boundary_failure" in public_guard["failure_families"]

    limited_guard = results["limited-query-can-use-same-limited-rollout-state"]
    assert limited_guard["winner"] == "memory_backed"
    assert limited_guard["failure_families"] == []
    assert limited_guard["expected_memory_types_found"] is True

    user_guard = results["user-private-query-stays-isolated-from-limited-channel"]
    assert user_guard["top_layer"] == "task_checkpoint"
    assert user_guard["winner"] == "memory_backed"
    assert user_guard["failure_families"] == []
    assert user_guard["expected_memory_types_found"] is True



def test_work_resumption_benchmark_v5_and_v6_control_runs_match_on_current_retrieval_recall_gap(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())

    summaries: dict[str, dict[str, object]] = {}
    review_results: dict[str, dict[str, object]] = {}
    for prompt_variant in ("strict_typed_memory_v5_compact_examples", "strict_typed_memory_v6_work_state_examples"):
        run_dir = run_work_resumption_benchmark(
            scenario_file=SCENARIOS,
            output_root=tmp_path / prompt_variant,
            config=_benchmark_config(prompt_variant),
            run_name=f"work-resumption-control-{prompt_variant}",
            answer_provider=StubWorkResumptionAnswerProvider(),
        )
        summaries[prompt_variant] = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        review_results[prompt_variant] = {item["scenario_id"]: item for item in _read_jsonl(run_dir / "results.jsonl")}["resume-review-follow-up-after-feedback"]

    v5_summary = summaries["strict_typed_memory_v5_compact_examples"]
    v6_summary = summaries["strict_typed_memory_v6_work_state_examples"]
    assert v5_summary["dominant_tuning_bottleneck"] == "packaging"
    assert v6_summary["dominant_tuning_bottleneck"] == "packaging"
    assert v5_summary["failure_family_counts"]["retrieval_recall_failure"] == v6_summary["failure_family_counts"]["retrieval_recall_failure"]

    v5_review = review_results["strict_typed_memory_v5_compact_examples"]
    v6_review = review_results["strict_typed_memory_v6_work_state_examples"]
    assert v5_review["top_layer"] == "task_checkpoint"
    assert v6_review["top_layer"] == "task_checkpoint"
    assert v5_review["failure_families"] == []
    assert v6_review["failure_families"] == []


def test_work_resumption_benchmark_keeps_no_value_continuation_guards(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_work_resumption_benchmark(
        scenario_file=SCENARIOS,
        output_root=tmp_path / "output",
        config=_benchmark_config(),
        run_name="work-resumption-guard",
        answer_provider=StubWorkResumptionAnswerProvider(),
    )
    results = {item["scenario_id"]: item for item in _read_jsonl(run_dir / "results.jsonl")}

    auth_no_value = results["same-thread-no-value-continuation"]
    assert auth_no_value["winner"] == "baseline"
    assert auth_no_value["non_value_guard_success"] is True
    assert auth_no_value["should_inject"] is False
    assert auth_no_value["decision_reason"] == "same_thread_context_sufficient"
    assert auth_no_value["failure_families"] == []
    assert auth_no_value["query_contract_mismatch_fields"] == []

    review_no_value = results["same-thread-review-no-value-guard"]
    assert review_no_value["winner"] == "baseline"
    assert review_no_value["non_value_guard_success"] is True
    assert review_no_value["should_inject"] is False
    assert review_no_value["decision_reason"] == "same_thread_context_sufficient"
    assert review_no_value["failure_families"] == []