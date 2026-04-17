from __future__ import annotations

from evals.benchmark_architecture import (
    DatasetTier,
    BenchmarkLane,
    annotate_result,
    build_aggregate_summary,
    build_suite_summary,
    suite_benchmark_config,
)


def test_suite_benchmark_catalog_maps_expected_lanes_and_tiers() -> None:
    memory_routing = suite_benchmark_config('memory_routing')
    recurring_question = suite_benchmark_config('recurring_question')
    work_resumption = suite_benchmark_config('work_resumption')
    external_memory_pressure = suite_benchmark_config('external_memory_pressure')

    assert memory_routing.dataset_tier is DatasetTier.CONFIDENCE
    assert memory_routing.primary_lane is BenchmarkLane.TRACE
    assert [lane.value for lane in memory_routing.scored_lanes] == ['contract', 'trace']

    assert recurring_question.dataset_tier is DatasetTier.ITERATION
    assert recurring_question.primary_lane is BenchmarkLane.USEFULNESS
    assert [lane.value for lane in recurring_question.scored_lanes] == ['usefulness', 'realism']

    assert work_resumption.dataset_tier is DatasetTier.CONFIDENCE
    assert [lane.value for lane in work_resumption.scored_lanes] == [
        'contract',
        'trace',
        'usefulness',
        'realism',
        'operational',
    ]

    assert external_memory_pressure.dataset_tier is DatasetTier.CONFIDENCE
    assert external_memory_pressure.primary_lane is BenchmarkLane.REALISM
    assert [lane.value for lane in external_memory_pressure.scored_lanes] == ['realism', 'operational']
    assert [lane.value for lane in external_memory_pressure.hard_gate_lanes] == []


def test_aggregate_summary_reports_hard_gate_rollups_and_zero_replay_assets() -> None:
    results = [
        annotate_result(
            {
                'scenario_id': 'memory-routing-green',
                'query_contract_consistent': True,
                'injection_contract': {'contract_success': True, 'injected_block_count': 1},
                'thin_agent_boundary_success': True,
                'intent_match': True,
                'query_family_match': True,
                'top_layer_match': True,
                'top_memory_type_match': True,
                'false_merge_occurred': False,
                'higher_level_overuse': False,
                'failure_families': [],
                'policy_success': True,
            },
            suite_id='memory_routing',
        )
    ]

    summary = build_aggregate_summary(results=results)

    assert summary['hard_gate_summary'] == {
        'lanes': ['contract', 'trace'],
        'coverage_complete': True,
        'missing_lanes': [],
        'all_green': True,
        'no_new_regressions': True,
        'new_failures': 0,
        'known_fail_matched': 0,
        'known_fail_unexpected_pass': 0,
        'failing_lanes': [],
    }
    assert summary['lane_aggregates']['contract']['successes'] == 1
    assert summary['lane_aggregates']['trace']['successes'] == 1
    assert summary['tier_aggregates']['confidence']['scenarios_total'] == 1
    assert summary['tier_aggregates']['replay']['scenarios_total'] == 0
    assert summary['replay_summary'] == {
        'supported': True,
        'assets_total': 0,
        'has_replay_assets': False,
    }
    assert summary['dominant_lane'] is None


def test_hard_gate_summary_fails_closed_when_required_coverage_is_missing() -> None:
    summary = build_aggregate_summary(results=[])

    assert summary['hard_gate_summary'] == {
        'lanes': ['contract', 'trace'],
        'coverage_complete': False,
        'missing_lanes': ['contract', 'trace'],
        'all_green': False,
        'no_new_regressions': True,
        'new_failures': 0,
        'known_fail_matched': 0,
        'known_fail_unexpected_pass': 0,
        'failing_lanes': [],
    }


def test_suite_summary_keeps_realism_and_operational_distinct_from_contract() -> None:
    result = annotate_result(
        {
            'scenario_id': 'reviewed-pressure-case',
            'should_memory_help': True,
            'winner': 'memory_backed',
            'query_contract_consistent': True,
            'injection_contract': {'contract_success': False, 'injected_block_count': 2},
            'thin_agent_boundary_success': True,
            'failure_families': ['wrong_memory_selection_failure'],
        },
        suite_id='public_corpus',
    )

    summary = build_suite_summary(suite_id='public_corpus', results=[result])

    assert summary['lane_aggregates']['contract']['failures'] == 1
    assert summary['lane_aggregates']['realism']['successes'] == 1
    assert summary['lane_aggregates']['operational']['failures'] == 1

def test_external_memory_pressure_suite_stays_out_of_hard_gate_rollups() -> None:
    result = annotate_result({
        "episode_id": "external-pressure-case",
        "policy_success": False,
        "failure_families": ["temporal_reasoning_failure"],
    }, suite_id="external_memory_pressure")

    summary = build_suite_summary(suite_id="external_memory_pressure", results=[result])

    assert summary["hard_gate_summary"]["lanes"] == []
    assert summary["lane_aggregates"]["realism"]["scenarios_total"] == 1
    assert summary["lane_aggregates"]["operational"]["scenarios_total"] == 1
    assert summary["lane_aggregates"]["contract"]["scenarios_total"] == 0
    assert summary["lane_aggregates"]["trace"]["scenarios_total"] == 0
