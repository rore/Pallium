from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from evals.recurring_question_benchmark import HIGHER_LEVEL_MEMORY_TYPES, _generate_answer, _score_answer
from providers.llm.base import LLMProvider

DEFAULT_SCENARIO_FILE = Path('evals/tiered_memory_validation/scenarios.json')
DEFAULT_OUTPUT_DIR = Path('evals/tiered_memory_validation/output')
DEFAULT_STRATEGIES = (
    'thread_local_carry_forward',
    'container_topic_window',
    'thread_summary_anchored',
)


def main() -> int:
    parser = argparse.ArgumentParser(description='Run the tiered-memory validation benchmark.')
    parser.add_argument('--scenario-file', type=Path, default=DEFAULT_SCENARIO_FILE)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument('--run-name', default=None)
    parser.add_argument('--strategies', default=','.join(DEFAULT_STRATEGIES))
    args = parser.parse_args()

    strategies = tuple(item.strip() for item in args.strategies.split(',') if item.strip())
    run_dir = run_tiered_memory_validation_benchmark(
        scenario_file=args.scenario_file,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
        strategies=strategies,
    )
    print(run_dir)
    return 0


def run_tiered_memory_validation_benchmark(
    *,
    scenario_file: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
    strategies: tuple[str, ...] = DEFAULT_STRATEGIES,
    answer_provider: LLMProvider | None = None,
) -> Path:
    from app.dependencies import build_llm_provider

    scenarios = _load_scenarios(scenario_file)
    default_package = config.package_config(config.default_use_case)
    if answer_provider is None:
        if not default_package.llm_provider or not default_package.model:
            raise ValueError(f"Default use case '{config.default_use_case}' is missing LLM package config")
        provider = build_llm_provider(config, provider_name=default_package.llm_provider, model=default_package.model)
    else:
        provider = answer_provider

    run_id = run_name or _build_run_id(config)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / 'results.jsonl'

    summary: dict[str, Any] = {
        'run_id': run_id,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'scenario_file': str(scenario_file),
        'results_file': results_path.name,
        'provider': config.llm_provider_for_default_use_case,
        'model': config.llm_model_for_default_use_case,
        'prompt_variant': config.llm_prompt_variant_for_default_use_case,
        'scenarios_total': len(scenarios),
        'strategies': [],
    }

    with results_path.open('w', encoding='utf-8') as results_file:
        for scenario in scenarios:
            result = _run_scenario(
                scenario=scenario,
                config=config,
                answer_provider=provider,
                strategies=strategies,
            )
            results_file.write(json.dumps(result) + '\n')

    result_rows = _read_jsonl(results_path)
    for strategy_name in strategies:
        strategy_rows = [row for row in result_rows if strategy_name in row['strategy_results']]
        false_merges = sum(1 for row in strategy_rows if row['strategy_results'][strategy_name]['false_merge_occurred'])
        expected_to_help = sum(1 for row in strategy_rows if strategy_name in row.get('expected_good_strategies', []))
        helped_as_expected = sum(1 for row in strategy_rows if row['strategy_results'][strategy_name]['as_expected'])
        wins_over_lower = sum(1 for row in strategy_rows if row['strategy_results'][strategy_name]['wins_over_lower_level'])
        lower_beats = sum(1 for row in strategy_rows if row['strategy_results'][strategy_name]['loses_to_lower_level'])
        context_reduction = sum(int(row['strategy_results'][strategy_name]['context_reduction']) for row in strategy_rows)
        policy_successes = sum(1 for row in strategy_rows if row['strategy_results'][strategy_name]['policy_success'])
        evidence_preserved = sum(1 for row in strategy_rows if row['strategy_results'][strategy_name]['evidence_preserved'])
        pattern_present = sum(1 for row in strategy_rows if row['strategy_results'][strategy_name]['pattern_memory_present'])
        continuity_present = sum(1 for row in strategy_rows if row['strategy_results'][strategy_name]['continuity_memory_present'])
        summary['strategies'].append(
            {
                'strategy_name': strategy_name,
                'scenarios_total': len(strategy_rows),
                'expected_to_help': expected_to_help,
                'helped_as_expected': helped_as_expected,
                'wins_over_lower_level': wins_over_lower,
                'lower_level_beats_strategy': lower_beats,
                'false_merges': false_merges,
                'context_reduction_total': context_reduction,
                'policy_successes': policy_successes,
                'evidence_preserved': evidence_preserved,
                'pattern_memory_present': pattern_present,
                'continuity_memory_present': continuity_present,
            }
        )

    (run_dir / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return run_dir


def _run_scenario(
    *,
    scenario: dict[str, Any],
    config: AppConfig,
    answer_provider: LLMProvider,
    strategies: tuple[str, ...],
) -> dict[str, Any]:
    baseline_answer = _generate_answer(
        answer_provider=answer_provider,
        target_question=scenario['target_question'],
        current_thread_context=scenario.get('current_thread_context', []),
        memory_backed_results=[],
        branch='baseline',
    )
    baseline_rubric = _score_answer(
        answer_payload=baseline_answer,
        target_question=scenario['target_question'],
        expected_answer_signals=scenario.get('expected_answer_signals', []),
        scenario_kind=scenario['scenario_kind'],
    )

    lower_level_branch = _run_memory_branch(
        scenario=scenario,
        config=config,
        strategy_name=None,
        answer_provider=answer_provider,
        branch_name='lower_level',
    )

    strategy_results: dict[str, Any] = {}
    for strategy_name in strategies:
        strategy_branch = _run_memory_branch(
            scenario=scenario,
            config=config,
            strategy_name=strategy_name,
            answer_provider=answer_provider,
            branch_name=f'tiered::{strategy_name}',
        )
        strategy_results[strategy_name] = _evaluate_strategy_result(
            scenario=scenario,
            baseline_rubric=baseline_rubric,
            lower_level=lower_level_branch,
            strategy_branch=strategy_branch,
            strategy_name=strategy_name,
        )

    return {
        'scenario_id': scenario['scenario_id'],
        'scenario_kind': scenario['scenario_kind'],
        'description': scenario['description'],
        'preferred_branch': scenario['preferred_branch'],
        'expected_good_strategies': scenario.get('expected_good_strategies', []),
        'baseline': {
            'answer': baseline_answer,
            'rubric': baseline_rubric,
            'current_thread_context': scenario.get('current_thread_context', []),
        },
        'lower_level': lower_level_branch,
        'strategy_results': strategy_results,
    }


def _run_memory_branch(
    *,
    scenario: dict[str, Any],
    config: AppConfig,
    strategy_name: str | None,
    answer_provider: LLMProvider,
    branch_name: str,
) -> dict[str, Any]:
    with TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'tiered-memory-validation.db'}"
        scenario_config = replace(
            config,
            sqlite_url=database_url,
            default_use_case='agent_conversation_memory',
        )
        with TestClient(create_app(scenario_config)) as client:
            try:
                for event in scenario.get('prior_events', []):
                    response = client.post('/items', json=event)
                    response.raise_for_status()

                consolidation_result = None
                if strategy_name:
                    consolidation_result = client.app.state.pallium_service.run_consolidation_pass(
                        use_case='agent_conversation_memory',
                        strategy_name=strategy_name,
                    )

                query_response = client.post('/query', json=scenario['current_query'])
                query_response.raise_for_status()
                retrieval_payload = query_response.json()
            finally:
                engine = getattr(client.app.state.pallium_service._storage, '_engine', None)
                if engine is not None:
                    engine.dispose()

    answer = _generate_answer(
        answer_provider=answer_provider,
        target_question=scenario['target_question'],
        current_thread_context=scenario.get('current_thread_context', []),
        memory_backed_results=retrieval_payload['results'],
        branch=branch_name,
    )
    rubric = _score_answer(
        answer_payload=answer,
        target_question=scenario['target_question'],
        expected_answer_signals=scenario.get('expected_answer_signals', []),
        scenario_kind=scenario['scenario_kind'],
    )
    memory_hits = [item for item in retrieval_payload['results'] if item.get('result_kind') == 'memory_hit']
    higher_level_hits = [item for item in memory_hits if item.get('type') in HIGHER_LEVEL_MEMORY_TYPES]
    higher_level_memory_types = sorted({item['type'] for item in higher_level_hits if item.get('type')})
    pattern_hits = [item for item in higher_level_hits if item.get('type') == 'pattern_memory']
    continuity_hits = [item for item in higher_level_hits if item.get('type') == 'continuity_memory']
    higher_level_payload_text = ' '.join(json.dumps(item.get('payload') or {}).lower() for item in higher_level_hits)
    answer_text = f"{answer.get('answer', '')}\n{' '.join(answer.get('evidence_used', []))}".lower()
    forbidden_terms = [term for term in scenario.get('forbidden_terms', []) if term.lower() in higher_level_payload_text or term.lower() in answer_text]
    expected_pattern_signals = [signal for signal in scenario.get('expected_pattern_signals', []) if signal.lower() in higher_level_payload_text]
    expected_higher_level_types = []
    if strategy_name:
        expected_higher_level_types = scenario.get('expected_higher_level_memory_types_by_strategy', {}).get(strategy_name, [])
    expected_higher_level_types_found = all(item in higher_level_memory_types for item in expected_higher_level_types)
    evidence_preserved = True
    if higher_level_hits:
        evidence_preserved = all(item.get('evidence') for item in higher_level_hits)
        if consolidation_result is not None:
            evidence_preserved = evidence_preserved and all(group.selected_source_item_ids for group in consolidation_result.groups)

    return {
        'strategy_name': strategy_name,
        'retrieval': retrieval_payload['results'],
        'returned_memory_types': sorted({item['type'] for item in memory_hits if item.get('type')}),
        'memory_hit_count': len(memory_hits),
        'higher_level_memory_present': bool(higher_level_hits),
        'higher_level_memory_count': len(higher_level_hits),
        'higher_level_memory_types': higher_level_memory_types,
        'expected_higher_level_types': expected_higher_level_types,
        'expected_higher_level_types_found': expected_higher_level_types_found,
        'pattern_memory_present': bool(pattern_hits),
        'continuity_memory_present': bool(continuity_hits),
        'pattern_memory_count': len(pattern_hits),
        'continuity_memory_count': len(continuity_hits),
        'higher_level_memory_payloads': [item.get('payload') for item in higher_level_hits],
        'expected_pattern_signals_found': expected_pattern_signals,
        'false_merge_occurred': bool(forbidden_terms),
        'forbidden_terms_found': forbidden_terms,
        'evidence_preserved': evidence_preserved,
        'answer': answer,
        'rubric': rubric,
        'consolidation_run': _serialize_consolidation_result(consolidation_result),
    }


def _evaluate_strategy_result(
    *,
    scenario: dict[str, Any],
    baseline_rubric: dict[str, Any],
    lower_level: dict[str, Any],
    strategy_branch: dict[str, Any],
    strategy_name: str,
) -> dict[str, Any]:
    baseline_total = int(baseline_rubric['total'])
    lower_total = int(lower_level['rubric']['total'])
    strategy_total = int(strategy_branch['rubric']['total'])
    preferred_branch = scenario['preferred_branch']
    strategy_expected = strategy_name in scenario.get('expected_good_strategies', [])
    expected_pattern_signals = scenario.get('expected_pattern_signals', [])
    expected_pattern_group_count = scenario.get('expected_pattern_group_count')
    pattern_signal_count = len(strategy_branch['expected_pattern_signals_found'])
    context_reduction = max(0, int(lower_level['memory_hit_count']) - int(strategy_branch['memory_hit_count']))

    tiered_bonus = 0
    if strategy_branch['higher_level_memory_present'] and not strategy_branch['false_merge_occurred']:
        if strategy_branch['expected_higher_level_types'] and strategy_branch['expected_higher_level_types_found']:
            tiered_bonus += 1
        if expected_pattern_signals and pattern_signal_count == len(expected_pattern_signals):
            tiered_bonus += 1
        if expected_pattern_group_count is not None and strategy_branch['higher_level_memory_count'] == int(expected_pattern_group_count):
            tiered_bonus += 1
        if context_reduction > 0:
            tiered_bonus += 1

    effective_strategy_total = strategy_total + tiered_bonus
    matches_expected_pattern_shape = (
        expected_pattern_group_count is None
        or strategy_branch['higher_level_memory_count'] == int(expected_pattern_group_count)
    )
    matches_expected_pattern_signals = (
        not expected_pattern_signals
        or pattern_signal_count == len(expected_pattern_signals)
    )
    matches_expected_higher_level_types = (
        not strategy_branch['expected_higher_level_types']
        or strategy_branch['expected_higher_level_types_found']
    )
    eligible_to_win = (
        strategy_branch['higher_level_memory_present']
        and not strategy_branch['false_merge_occurred']
        and matches_expected_pattern_shape
        and matches_expected_pattern_signals
        and matches_expected_higher_level_types
        and (not scenario.get('expected_good_strategies') or strategy_expected)
    )
    material_improvement = (
        strategy_total > lower_total
        or (
            preferred_branch == 'tiered'
            and strategy_total == lower_total
            and tiered_bonus >= 2
        )
    )
    wins_over_lower = material_improvement and eligible_to_win
    loses_to_lower = (
        lower_total > effective_strategy_total
        or (preferred_branch == 'lower_level' and not (strategy_total > lower_total))
    )

    if preferred_branch == 'tiered':
        policy_success = wins_over_lower if strategy_expected else not wins_over_lower
    elif preferred_branch == 'lower_level':
        policy_success = loses_to_lower and not strategy_branch['false_merge_occurred']
    else:
        policy_success = baseline_total >= effective_strategy_total and not strategy_branch['false_merge_occurred']

    return {
        **strategy_branch,
        'tiered_bonus': tiered_bonus,
        'effective_total': effective_strategy_total,
        'wins_over_lower_level': wins_over_lower,
        'loses_to_lower_level': loses_to_lower,
        'context_reduction': context_reduction,
        'matches_expected_pattern_shape': matches_expected_pattern_shape,
        'matches_expected_pattern_signals': matches_expected_pattern_signals,
        'matches_expected_higher_level_types': matches_expected_higher_level_types,
        'eligible_to_win': eligible_to_win,
        'material_improvement': material_improvement,
        'policy_success': policy_success,
        'as_expected': policy_success,
        'strategy_expected_to_help': strategy_expected,
    }


def _serialize_consolidation_result(result: Any) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        'package_name': result.package_name,
        'strategy_name': result.strategy_name,
        'strategy_version': result.strategy_version,
        'candidate_count': result.candidate_count,
        'selected_candidate_ids': list(result.selected_candidate_ids),
        'groups': [
            {
                'strategy_name': group.strategy_name,
                'strategy_version': group.strategy_version,
                'group_key': group.group_key,
                'selected_candidate_ids': list(group.selected_candidate_ids),
                'selected_source_item_ids': list(group.selected_source_item_ids),
                'candidate_thread_refs': list(group.candidate_thread_refs),
                'created_memory_ids': list(group.created_memory_ids),
                'created_memory_types': list(group.created_memory_types),
                'superseded_memory_ids': list(group.superseded_memory_ids),
                'merge_rationale': group.merge_rationale,
            }
            for group in result.groups
        ],
    }


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding='utf-8'))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _build_run_id(config: AppConfig) -> str:
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    provider = (config.llm_provider_for_default_use_case or 'provider').replace('_', '-')
    model = (config.llm_model_for_default_use_case or 'model').replace('/', '-').replace('.', '-')
    return f'tiered-memory-validation__{provider}__{model}__{timestamp}'


if __name__ == '__main__':
    raise SystemExit(main())