from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig
from evals.write_enrichment_runner import run_write_enrichment_eval
from providers.llm.base import LLMJsonResponse


class VariantAwareEnrichmentStubProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if 'already-specific-summary-no-op' in user_prompt.lower() or 'restarting from batch 313' in user_prompt.lower():
            payload = {'action': 'NO_OP', 'retrieval_context': None}
        elif 'batch 313' in user_prompt.lower():
            if 'missing a concrete retrieval handle' in system_prompt.lower():
                payload = {'action': 'ENRICH', 'retrieval_context': 'Resume point for the catalog sync retry after service-token expiry at batch 313.'}
            elif 'retrieval handles' in system_prompt.lower():
                payload = {'action': 'ENRICH', 'retrieval_context': 'Resume point for the catalog sync retry after service-token expiry at batch 313.'}
            else:
                payload = {'action': 'ENRICH', 'retrieval_context': 'Catalog sync retry at batch 313 after service token expiry.'}
        elif 'carry-forward answer' in user_prompt.lower():
            payload = {'action': 'ENRICH', 'retrieval_context': 'Carry-forward answer for overdue notice batching questions that would otherwise recreate inbox spam.'}
        else:
            payload = {'action': 'ENRICH', 'retrieval_context': 'Feature flag rollout with remaining retry coverage work.'}
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def _write_input_file(path: Path, *records: dict[str, object]) -> None:
    content = "\n".join(json.dumps(record) for record in records)
    path.write_text(content + "\n", encoding='utf-8')


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _scenario(
    scenario_id: str,
    *,
    memory_type: str,
    summary: str,
    support_lines: list[str],
    expected_action: str,
    required_terms: list[str],
    forbidden_terms: list[str],
) -> dict[str, object]:
    return {
        'scenario_id': scenario_id,
        'memory_type': memory_type,
        'payload': {'summary': summary, 'container_ref': 'workspace:ops', 'thread_ref': f'thread:{scenario_id}'},
        'support_lines': support_lines,
        'expected_action': expected_action,
        'required_terms': required_terms,
        'forbidden_terms': forbidden_terms,
    }


def test_run_write_enrichment_eval_writes_summary_and_results(tmp_path: Path) -> None:
    input_file = tmp_path / 'scenarios.jsonl'
    output_dir = tmp_path / 'output'
    _write_input_file(
        input_file,
        _scenario(
            'task-restart',
            memory_type='task_checkpoint',
            summary='Catalog sync retry is paused after partial progress.',
            support_lines=[
                'Summary: Catalog sync retry is paused after partial progress.',
                'Current state: Refreshed 312 reservation records before the expired service token failed the run.',
                'Next step: Refresh the service token and rerun from batch 313.',
            ],
            expected_action='ENRICH',
            required_terms=['batch 313', 'service token'],
            forbidden_terms=[],
        ),
        _scenario(
            'already-specific-summary-no-op',
            memory_type='thread_summary',
            summary='Catalog sync retry resume state after service-token expiry, restarting from batch 313.',
            support_lines=['Summary: Catalog sync retry resume state after service-token expiry, restarting from batch 313.'],
            expected_action='NO_OP',
            required_terms=[],
            forbidden_terms=['batch 313'],
        ),
    )

    run_dir = run_write_enrichment_eval(
        input_file=input_file,
        output_root=output_dir,
        provider=VariantAwareEnrichmentStubProvider(),
        config=AppConfig(default_use_case='agent_conversation_memory', llm_prompt_variant='strict_typed_memory_v5_compact_contract'),
        run_name='write-enrichment-variant-run',
        prompt_variants=['baseline_v1', 'search_context_v2_compact', 'search_context_v2_handles', 'search_context_v3_precise_record'],
        split_output=True,
    )

    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    results = _read_jsonl(run_dir / 'results.jsonl')

    assert summary['prompt_variants'] == ['baseline_v1', 'search_context_v2_compact', 'search_context_v2_handles', 'search_context_v3_precise_record']
    assert summary['prompt_role'] == 'write_enrichment'
    assert summary['prompt_schema_id'] == 'semantic.write_enrichment'
    assert summary['prompt_schema_version'] == 'v1'
    assert summary['scenarios_succeeded'] == 8
    assert len(summary['split_outputs']) == 8
    assert len(results) == 8
    assert summary['prompt_text_metrics']['search_context_v2_compact']['estimated_tokens'] < summary['prompt_text_metrics']['baseline_v1']['estimated_tokens']
    assert summary['per_variant']['search_context_v2_handles']['action_correct'] == 2
    assert summary['per_variant']['search_context_v3_precise_record']['action_correct'] == 2
    assert summary['per_variant']['search_context_v2_handles']['scenario_successes'] == 1


def test_run_write_enrichment_eval_records_errors(tmp_path: Path) -> None:
    class ErrorProvider:
        def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
            raise RuntimeError('provider exploded')

    input_file = tmp_path / 'scenarios.jsonl'
    output_dir = tmp_path / 'output'
    _write_input_file(
        input_file,
        _scenario(
            'task-restart',
            memory_type='task_checkpoint',
            summary='Catalog sync retry is paused after partial progress.',
            support_lines=['Summary: Catalog sync retry is paused after partial progress.'],
            expected_action='ENRICH',
            required_terms=['batch 313'],
            forbidden_terms=[],
        ),
    )

    run_dir = run_write_enrichment_eval(
        input_file=input_file,
        output_root=output_dir,
        provider=ErrorProvider(),
        config=AppConfig(default_use_case='agent_conversation_memory', llm_prompt_variant='strict_typed_memory_v5_compact_contract'),
        run_name='write-enrichment-error-run',
        prompt_variants=['search_context_v3_precise_record'],
    )

    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    results = _read_jsonl(run_dir / 'results.jsonl')

    assert summary['scenarios_failed'] == 1
    assert summary['per_variant']['search_context_v3_precise_record']['scenarios_failed'] == 1
    assert results[0]['status'] == 'error'
    assert results[0]['error']['type'] == 'RuntimeError'
