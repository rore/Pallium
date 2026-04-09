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
from evals.recurring_question_benchmark import HIGHER_LEVEL_MEMORY_TYPES, run_recurring_question_benchmark
from providers.llm.base import LLMProvider


DEFAULT_SCENARIO_FILE = Path('evals/consolidation/scenarios.json')
DEFAULT_BENCHMARK_SCENARIO_FILE = Path('evals/recurring_question/scenarios.json')
DEFAULT_OUTPUT_DIR = Path('evals/consolidation/output')
DEFAULT_STRATEGIES = (
    'thread_local_carry_forward',
    'container_topic_window',
    'thread_summary_anchored',
)


def main() -> int:
    parser = argparse.ArgumentParser(description='Run tiered-memory strategy comparisons.')
    parser.add_argument('--scenario-file', type=Path, default=DEFAULT_SCENARIO_FILE)
    parser.add_argument('--benchmark-scenario-file', type=Path, default=DEFAULT_BENCHMARK_SCENARIO_FILE)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument('--run-name', default=None)
    parser.add_argument('--strategies', default=','.join(DEFAULT_STRATEGIES))
    args = parser.parse_args()

    strategies = tuple(item.strip() for item in args.strategies.split(',') if item.strip())
    run_dir = run_consolidation_strategy_comparison(
        scenario_file=args.scenario_file,
        benchmark_scenario_file=args.benchmark_scenario_file,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
        strategies=strategies,
    )
    print(run_dir)
    return 0


def run_consolidation_strategy_comparison(
    *,
    scenario_file: Path,
    benchmark_scenario_file: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
    strategies: tuple[str, ...] = DEFAULT_STRATEGIES,
    answer_provider: LLMProvider | None = None,
) -> Path:
    scenarios = _load_scenarios(scenario_file)
    run_id = run_name or _build_run_id()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / 'results.jsonl'

    modes: list[str | None] = [None, *strategies]
    summary: dict[str, Any] = {
        'run_id': run_id,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'scenario_file': str(scenario_file),
        'benchmark_scenario_file': str(benchmark_scenario_file),
        'results_file': results_path.name,
        'modes': [],
    }

    with results_path.open('w', encoding='utf-8') as results_file:
        for strategy_name in modes:
            mode_label = strategy_name or 'no_tiered'
            mode_results = [
                _run_consolidation_scenario(
                    scenario=scenario,
                    config=config,
                    strategy_name=strategy_name,
                )
                for scenario in scenarios
            ]
            for result in mode_results:
                results_file.write(json.dumps(result) + '\n')

            benchmark_dir = run_consolidation_benchmark_mode(
                benchmark_scenario_file=benchmark_scenario_file,
                output_root=run_dir / 'benchmark',
                config=config,
                run_name=f'{run_id}__{mode_label}',
                answer_provider=answer_provider,
                strategy_name=strategy_name,
            )
            benchmark_summary = json.loads((benchmark_dir / 'summary.json').read_text(encoding='utf-8'))
            benchmark_results = _read_jsonl(benchmark_dir / 'results.jsonl')

            false_merges = sum(1 for item in mode_results if item['false_merge_occurred'])
            context_improvements = sum(1 for item in mode_results if item['improved_context_shape'])
            higher_level_created = sum(1 for item in mode_results if item['higher_level_memory_created'])
            pattern_created = sum(1 for item in mode_results if 'pattern_memory' in item['higher_level_memory_types'])
            continuity_created = sum(1 for item in mode_results if 'continuity_memory' in item['higher_level_memory_types'])
            aggregate_delta = sum(
                int(item['rubric']['memory_backed']['total']) - int(item['rubric']['baseline']['total'])
                for item in benchmark_results
            )

            summary['modes'].append(
                {
                    'mode': mode_label,
                    'strategy_name': strategy_name,
                    'scenarios_total': len(mode_results),
                    'higher_level_memory_created': higher_level_created,
                    'pattern_memory_created': pattern_created,
                    'continuity_memory_created': continuity_created,
                    'false_merges': false_merges,
                    'context_improvements': context_improvements,
                    'benchmark': {
                        'summary': benchmark_summary,
                        'aggregate_delta': aggregate_delta,
                    },
                }
            )

    (run_dir / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return run_dir


def run_consolidation_benchmark_mode(
    *,
    benchmark_scenario_file: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str,
    answer_provider: LLMProvider | None,
    strategy_name: str | None,
) -> Path:
    return run_recurring_question_benchmark(
        scenario_file=benchmark_scenario_file,
        output_root=output_root,
        config=config,
        run_name=run_name,
        answer_provider=answer_provider,
        consolidation_strategy=strategy_name,
    )


def _run_consolidation_scenario(
    *,
    scenario: dict[str, Any],
    config: AppConfig,
    strategy_name: str | None,
) -> dict[str, Any]:
    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'consolidation.db'}"
        vector_index_config = replace(config.vector_index, index_path=str(Path(temp_dir) / "vector.index"))
        scenario_config = replace(
            config,
            sqlite_url=database_url,
            default_use_case='agent_conversation_memory',
            vector_index=vector_index_config,
        )
        with TestClient(create_app(scenario_config)) as client:
            try:
                for event in scenario.get('prior_events', []):
                    response = client.post('/items', json=[_with_default_visibility(event)])
                    response.raise_for_status()
                client.app.state.pallium_service.drain_processing_queue(worker_id='consolidation-strategy-runner')

                before_response = client.post('/query', json=_with_default_visibility(scenario['current_query']))
                before_response.raise_for_status()
                before_payload = before_response.json()

                consolidation_result = None
                if strategy_name:
                    consolidation_result = client.app.state.pallium_service.run_consolidation_pass(
                        use_case='agent_conversation_memory',
                        strategy_name=strategy_name,
                    )

                after_response = client.post('/query', json=_with_default_visibility(scenario['current_query']))
                after_response.raise_for_status()
                after_payload = after_response.json()
            finally:
                engine = getattr(client.app.state.pallium_service._storage, '_engine', None)
                if engine is not None:
                    engine.dispose()

    before_memory_types = _returned_memory_types(before_payload)
    after_memory_types = _returned_memory_types(after_payload)
    higher_level_hits = [
        item for item in after_payload['results']
        if item.get('result_kind') == 'memory_hit' and item.get('type') in HIGHER_LEVEL_MEMORY_TYPES
    ]
    higher_level_memory_types = sorted({item.get('type') for item in higher_level_hits if item.get('type')})
    higher_level_payload_text = ' '.join(
        json.dumps(item.get('payload') or {}).lower()
        for item in higher_level_hits
    )
    unexpected_terms = [term for term in scenario.get('unexpected_terms', []) if term.lower() in higher_level_payload_text]

    return {
        'scenario_id': scenario['scenario_id'],
        'description': scenario['description'],
        'strategy_name': strategy_name or 'no_tiered',
        'before_memory_types': before_memory_types,
        'after_memory_types': after_memory_types,
        'higher_level_memory_created': bool(higher_level_hits),
        'higher_level_memory_types': higher_level_memory_types,
        'higher_level_memory_payloads': [item.get('payload') for item in higher_level_hits],
        'consolidation_run': _serialize_consolidation_result(consolidation_result),
        'false_merge_occurred': bool(unexpected_terms),
        'unexpected_terms_found': unexpected_terms,
        'improved_context_shape': (not higher_level_hits and False) or (bool(higher_level_hits) and len(before_memory_types) > 1),
    }


def _with_default_visibility(payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    updated.setdefault('visibility', 'public')
    return updated


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


def _returned_memory_types(payload: dict[str, Any]) -> list[str]:
    return sorted(
        {
            item['type']
            for item in payload['results']
            if item.get('result_kind') == 'memory_hit' and item.get('type')
        }
    )


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding='utf-8'))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _build_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return f'consolidation-strategy-comparison__{timestamp}'


if __name__ == '__main__':
    raise SystemExit(main())