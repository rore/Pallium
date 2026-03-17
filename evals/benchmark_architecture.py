from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class BenchmarkLane(StrEnum):
    CONTRACT = "contract"
    TRACE = "trace"
    USEFULNESS = "usefulness"
    REALISM = "realism"
    OPERATIONAL = "operational"


class DatasetTier(StrEnum):
    ITERATION = "iteration"
    CONFIDENCE = "confidence"
    REPLAY = "replay"


HARD_GATE_LANES = (BenchmarkLane.CONTRACT, BenchmarkLane.TRACE)
TRACE_FAILURE_FAMILIES = {
    "retrieval_recall_failure",
    "routing_layer_choice_failure",
    "low_value_promotion_failure",
    "thread_rebuild_churn_failure",
    "stale_memory_failure",
    "wrong_memory_selection_failure",
    "privacy_leak_failure",
}
OPERATIONAL_FAILURE_FAMILIES = {
    "no_value_overreach_failure",
    "stale_memory_failure",
    "wrong_memory_selection_failure",
    "low_value_promotion_failure",
    "thread_rebuild_churn_failure",
}


@dataclass(frozen=True)
class SuiteBenchmarkConfig:
    suite_id: str
    dataset_tier: DatasetTier
    primary_lane: BenchmarkLane
    scored_lanes: tuple[BenchmarkLane, ...]
    hard_gate_lanes: tuple[BenchmarkLane, ...]


SUITE_BENCHMARK_CONFIGS: dict[str, SuiteBenchmarkConfig] = {
    "memory_routing": SuiteBenchmarkConfig(
        suite_id="memory_routing",
        dataset_tier=DatasetTier.CONFIDENCE,
        primary_lane=BenchmarkLane.TRACE,
        scored_lanes=(BenchmarkLane.CONTRACT, BenchmarkLane.TRACE),
        hard_gate_lanes=HARD_GATE_LANES,
    ),
    "work_resumption": SuiteBenchmarkConfig(
        suite_id="work_resumption",
        dataset_tier=DatasetTier.CONFIDENCE,
        primary_lane=BenchmarkLane.REALISM,
        scored_lanes=(
            BenchmarkLane.CONTRACT,
            BenchmarkLane.TRACE,
            BenchmarkLane.USEFULNESS,
            BenchmarkLane.REALISM,
            BenchmarkLane.OPERATIONAL,
        ),
        hard_gate_lanes=HARD_GATE_LANES,
    ),
    "public_corpus": SuiteBenchmarkConfig(
        suite_id="public_corpus",
        dataset_tier=DatasetTier.CONFIDENCE,
        primary_lane=BenchmarkLane.REALISM,
        scored_lanes=(
            BenchmarkLane.CONTRACT,
            BenchmarkLane.TRACE,
            BenchmarkLane.USEFULNESS,
            BenchmarkLane.REALISM,
            BenchmarkLane.OPERATIONAL,
        ),
        hard_gate_lanes=HARD_GATE_LANES,
    ),
    "low_value_churn": SuiteBenchmarkConfig(
        suite_id="low_value_churn",
        dataset_tier=DatasetTier.CONFIDENCE,
        primary_lane=BenchmarkLane.OPERATIONAL,
        scored_lanes=(BenchmarkLane.TRACE, BenchmarkLane.OPERATIONAL),
        hard_gate_lanes=(BenchmarkLane.TRACE,),
    ),
    "recurring_question": SuiteBenchmarkConfig(
        suite_id="recurring_question",
        dataset_tier=DatasetTier.ITERATION,
        primary_lane=BenchmarkLane.USEFULNESS,
        scored_lanes=(BenchmarkLane.USEFULNESS, BenchmarkLane.REALISM),
        hard_gate_lanes=(),
    ),
    "external_memory_pressure": SuiteBenchmarkConfig(
        suite_id="external_memory_pressure",
        dataset_tier=DatasetTier.CONFIDENCE,
        primary_lane=BenchmarkLane.REALISM,
        scored_lanes=(BenchmarkLane.REALISM, BenchmarkLane.OPERATIONAL),
        hard_gate_lanes=(),
    ),
}


def suite_benchmark_config(suite_id: str) -> SuiteBenchmarkConfig:
    try:
        return SUITE_BENCHMARK_CONFIGS[suite_id]
    except KeyError as exc:
        raise KeyError(f"Unknown benchmark suite: {suite_id}") from exc


def annotate_result(
    row: dict[str, Any],
    *,
    suite_id: str,
    dataset_tier: str | DatasetTier | None = None,
) -> dict[str, Any]:
    config = suite_benchmark_config(suite_id)
    resolved_tier = _normalize_dataset_tier(dataset_tier or row.get("dataset_tier") or config.dataset_tier)
    annotated = dict(row)
    annotated["suite_id"] = suite_id
    annotated["dataset_tier"] = resolved_tier.value
    annotated["primary_lane"] = config.primary_lane.value
    annotated["scored_lanes"] = [lane.value for lane in config.scored_lanes]
    return annotated


def build_suite_summary(
    *,
    suite_id: str,
    results: list[dict[str, Any]],
    dataset_tier: str | DatasetTier | None = None,
) -> dict[str, Any]:
    config = suite_benchmark_config(suite_id)
    default_tier = _normalize_dataset_tier(dataset_tier or config.dataset_tier)
    lane_aggregates = _build_lane_aggregates(results=results, suite_id=suite_id)
    tier_aggregates = _build_tier_aggregates(results=results, default_tier=default_tier)
    return {
        "suite_id": config.suite_id,
        "dataset_tier": default_tier.value,
        "primary_lane": config.primary_lane.value,
        "scored_lanes": [lane.value for lane in config.scored_lanes],
        "hard_gate_lanes": [lane.value for lane in config.hard_gate_lanes],
        "lane_aggregates": lane_aggregates,
        "tier_aggregates": tier_aggregates,
        "hard_gate_summary": _build_hard_gate_summary(lane_aggregates, config.hard_gate_lanes),
        "tuning_summary": _build_tuning_summary(lane_aggregates, config.hard_gate_lanes),
        "operational_summary": _build_operational_summary(results),
        "replay_summary": {
            "supported": True,
            "assets_total": tier_aggregates[DatasetTier.REPLAY.value]["scenarios_total"],
            "has_replay_assets": tier_aggregates[DatasetTier.REPLAY.value]["scenarios_total"] > 0,
        },
    }


def build_aggregate_summary(
    *,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    lane_aggregates = _build_lane_aggregates(results=results, suite_id=None)
    tier_aggregates = _build_tier_aggregates(results=results, default_tier=None)
    hard_gate_summary = _build_hard_gate_summary(lane_aggregates, HARD_GATE_LANES)
    tuning_summary = _build_tuning_summary(lane_aggregates, HARD_GATE_LANES)
    operational_summary = _build_operational_summary(results)
    dominant_lane = _dominant_lane(lane_aggregates)
    return {
        "lane_aggregates": lane_aggregates,
        "tier_aggregates": tier_aggregates,
        "hard_gate_summary": hard_gate_summary,
        "tuning_summary": tuning_summary,
        "operational_summary": operational_summary,
        "replay_summary": {
            "supported": True,
            "assets_total": tier_aggregates[DatasetTier.REPLAY.value]["scenarios_total"],
            "has_replay_assets": tier_aggregates[DatasetTier.REPLAY.value]["scenarios_total"] > 0,
        },
        "dominant_lane": dominant_lane.value if dominant_lane is not None else None,
    }


def _build_lane_aggregates(
    *,
    results: list[dict[str, Any]],
    suite_id: str | None,
) -> dict[str, dict[str, Any]]:
    totals: dict[BenchmarkLane, dict[str, int]] = {
        lane: {"scenarios_total": 0, "successes": 0}
        for lane in BenchmarkLane
    }
    for row in results:
        config = suite_benchmark_config(str(row.get("suite_id") or suite_id))
        for lane in config.scored_lanes:
            success = _lane_success(row=row, suite_id=config.suite_id, lane=lane)
            if success is None:
                continue
            totals[lane]["scenarios_total"] += 1
            totals[lane]["successes"] += int(success)
    aggregates: dict[str, dict[str, Any]] = {}
    for lane in BenchmarkLane:
        scenarios_total = totals[lane]["scenarios_total"]
        successes = totals[lane]["successes"]
        failures = scenarios_total - successes
        aggregates[lane.value] = {
            "scenarios_total": scenarios_total,
            "successes": successes,
            "failures": failures,
            "success_rate": round(successes / scenarios_total, 4) if scenarios_total else None,
        }
    return aggregates


def _build_tier_aggregates(
    *,
    results: list[dict[str, Any]],
    default_tier: DatasetTier | None,
) -> dict[str, dict[str, int]]:
    counts = {tier: 0 for tier in DatasetTier}
    for row in results:
        tier = _normalize_dataset_tier(row.get("dataset_tier") or default_tier or DatasetTier.CONFIDENCE)
        counts[tier] += 1
    return {
        tier.value: {"scenarios_total": counts[tier]}
        for tier in DatasetTier
    }


def _build_hard_gate_summary(
    lane_aggregates: dict[str, dict[str, Any]],
    hard_gate_lanes: tuple[BenchmarkLane, ...],
) -> dict[str, Any]:
    missing_lanes = [
        lane.value
        for lane in hard_gate_lanes
        if lane_aggregates[lane.value]["scenarios_total"] == 0
    ]
    failing_lanes = [
        lane.value
        for lane in hard_gate_lanes
        if lane_aggregates[lane.value]["failures"] > 0
    ]
    coverage_complete = not missing_lanes
    return {
        "lanes": [lane.value for lane in hard_gate_lanes],
        "coverage_complete": coverage_complete,
        "missing_lanes": missing_lanes,
        "all_green": coverage_complete and not failing_lanes,
        "failing_lanes": failing_lanes,
    }


def _build_tuning_summary(
    lane_aggregates: dict[str, dict[str, Any]],
    hard_gate_lanes: tuple[BenchmarkLane, ...],
) -> dict[str, Any]:
    tuning_lanes = [lane for lane in BenchmarkLane if lane not in hard_gate_lanes]
    pressure_lanes = [
        lane.value
        for lane in tuning_lanes
        if lane_aggregates[lane.value]["failures"] > 0
    ]
    return {
        "lanes": [lane.value for lane in tuning_lanes],
        "pressure_lanes": pressure_lanes,
    }


def _build_operational_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    injected_block_distribution: dict[str, int] = {}
    no_value_total = 0
    no_value_overreach_failures = 0
    stale_failures = 0
    wrong_memory_failures = 0
    low_value_promotion_failures = 0
    thread_rebuild_churn_failures = 0

    for row in results:
        failure_families = set(row.get("failure_families", []))
        expected_value = row.get("should_memory_help")
        if expected_value is None:
            expected_value = row.get("expected_value")
        if expected_value is False:
            no_value_total += 1
            if "no_value_overreach_failure" in failure_families:
                no_value_overreach_failures += 1

        if "stale_memory_failure" in failure_families:
            stale_failures += 1
        if "wrong_memory_selection_failure" in failure_families:
            wrong_memory_failures += 1
        if "low_value_promotion_failure" in failure_families:
            low_value_promotion_failures += 1
        if "thread_rebuild_churn_failure" in failure_families:
            thread_rebuild_churn_failures += 1

        injection_contract = row.get("injection_contract")
        if isinstance(injection_contract, dict):
            count = int(injection_contract.get("injected_block_count", 0))
            bucket = str(count)
            injected_block_distribution[bucket] = injected_block_distribution.get(bucket, 0) + 1

    total_results = len(results)
    return {
        "injected_block_count_distribution": {
            bucket: injected_block_distribution[bucket]
            for bucket in sorted(injected_block_distribution, key=lambda item: int(item))
        },
        "no_value_scenarios": no_value_total,
        "no_value_overreach_failures": no_value_overreach_failures,
        "no_value_overreach_rate": round(no_value_overreach_failures / no_value_total, 4) if no_value_total else None,
        "stale_memory_failures": stale_failures,
        "stale_memory_failure_rate": round(stale_failures / total_results, 4) if total_results else None,
        "wrong_memory_selection_failures": wrong_memory_failures,
        "wrong_memory_selection_failure_rate": round(wrong_memory_failures / total_results, 4) if total_results else None,
        "low_value_promotion_failures": low_value_promotion_failures,
        "low_value_promotion_failure_rate": round(low_value_promotion_failures / total_results, 4) if total_results else None,
        "thread_rebuild_churn_failures": thread_rebuild_churn_failures,
        "thread_rebuild_churn_failure_rate": round(thread_rebuild_churn_failures / total_results, 4) if total_results else None,
    }


def _dominant_lane(lane_aggregates: dict[str, dict[str, Any]]) -> BenchmarkLane | None:
    candidates = [
        lane
        for lane in HARD_GATE_LANES
        if lane_aggregates[lane.value]["failures"] > 0
    ]
    if not candidates:
        candidates = [
            lane
            for lane in BenchmarkLane
            if lane not in HARD_GATE_LANES and lane_aggregates[lane.value]["failures"] > 0
        ]
    if not candidates:
        return None
    return max(candidates, key=lambda lane: lane_aggregates[lane.value]["failures"])


def _lane_success(
    *,
    row: dict[str, Any],
    suite_id: str,
    lane: BenchmarkLane,
) -> bool | None:
    if lane is BenchmarkLane.CONTRACT:
        return _contract_success(row)
    if lane is BenchmarkLane.TRACE:
        return _trace_success(row, suite_id=suite_id)
    if lane is BenchmarkLane.USEFULNESS:
        return _usefulness_success(row)
    if lane is BenchmarkLane.REALISM:
        return _realism_success(row, suite_id=suite_id)
    if lane is BenchmarkLane.OPERATIONAL:
        return _operational_success(row, suite_id=suite_id)
    return None


def _contract_success(row: dict[str, Any]) -> bool | None:
    if "query_contract_consistent" not in row and "injection_contract" not in row:
        return None
    injection_contract = row.get("injection_contract") or {}
    return bool(
        row.get("query_contract_consistent", True)
        and injection_contract.get("contract_success", True)
        and row.get("thin_agent_boundary_success", True)
    )


def _trace_success(row: dict[str, Any], *, suite_id: str) -> bool | None:
    if suite_id == "memory_routing":
        return bool(
            row.get("intent_match", True)
            and row.get("query_family_match", True)
            and row.get("top_layer_match", True)
            and row.get("top_memory_type_match", True)
            and not row.get("false_merge_occurred", False)
            and not row.get("higher_level_overuse", False)
        )
    failure_families = set(row.get("failure_families", []))
    if failure_families:
        return not any(name in failure_families for name in TRACE_FAILURE_FAMILIES)
    if suite_id == "low_value_churn":
        return not bool(row.get("failure_families"))
    if "intent_match" in row or "query_family_match" in row or "top_layer_match" in row:
        return bool(
            row.get("intent_match", True)
            and row.get("query_family_match", True)
            and row.get("top_layer_match", True)
        )
    return None


def _usefulness_success(row: dict[str, Any]) -> bool | None:
    if "winner" not in row:
        return None
    expected_value = row.get("should_memory_help")
    if expected_value is None:
        expected_value = row.get("expected_value")
    if expected_value is None:
        return None
    if expected_value:
        return row.get("winner") == "memory_backed"
    return row.get("winner") != "memory_backed"


def _realism_success(row: dict[str, Any], *, suite_id: str) -> bool | None:
    if "realism_success" in row:
        return bool(row["realism_success"])
    if suite_id in {"work_resumption", "public_corpus", "recurring_question"}:
        return _usefulness_success(row)
    if suite_id == "external_memory_pressure":
        if "policy_success" in row:
            return bool(row["policy_success"])
        return _usefulness_success(row)
    return None

def _operational_success(row: dict[str, Any], *, suite_id: str) -> bool | None:
    failure_families = set(row.get("failure_families", []))
    if suite_id == "low_value_churn":
        return not any(name in failure_families for name in OPERATIONAL_FAILURE_FAMILIES)
    if suite_id in {"work_resumption", "public_corpus"}:
        return not any(name in failure_families for name in OPERATIONAL_FAILURE_FAMILIES)
    if suite_id == "external_memory_pressure":
        if "policy_success" in row:
            return bool(row["policy_success"])
        return not any(name in failure_families for name in OPERATIONAL_FAILURE_FAMILIES)
    if row.get("should_memory_help") is False or row.get("expected_value") is False:
        return "no_value_overreach_failure" not in failure_families
    return None

def _normalize_dataset_tier(value: str | DatasetTier) -> DatasetTier:
    if isinstance(value, DatasetTier):
        return value
    return DatasetTier(str(value))

