# Prompt Improvement Workflow

Use this workflow when changing any live semantic prompt in Pallium.

Current live prompt-backed roles:

- `write_extraction`
- `write_enrichment`
- `fact_extraction` (in `conversational_knowledge` package)

Current default variants:

- `write_extraction`: `strict_typed_memory_v8b_work_refs_separate`
- `write_enrichment`: `search_context_v2_compact`

## Goals

When improving prompts, optimize for all of the following together:

- schema-valid output
- behavior on representative replay fixtures
- thin-agent contract correctness
- low false promotion / low overreach
- token-conscious prompts
- stable prompt provenance and replayability

Do not optimize for shorter prompts alone. The winning prompt is the smallest one that still preserves the required behavior on the representative eval slice.

## Where Prompt Variants Live

Extraction variants:

- [semantic/llm_agent_memory.py](C:/Dev/rore/Pallium/semantic/llm_agent_memory.py)

Enrichment variants:

- [semantic/agent_conversation_memory_enrichment.py](C:/Dev/rore/Pallium/semantic/agent_conversation_memory_enrichment.py)

Prompt-role contracts and provenance:

- [semantic/prompt_roles.py](C:/Dev/rore/Pallium/semantic/prompt_roles.py)
- [semantic/prompt_provenance.py](C:/Dev/rore/Pallium/semantic/prompt_provenance.py)

Prompt text metrics:

- [semantic/prompt_variant_metrics.py](C:/Dev/rore/Pallium/semantic/prompt_variant_metrics.py)

## Evaluation Surfaces

Extraction runner:

- [evals/semantic_runner.py](C:/Dev/rore/Pallium/evals/semantic_runner.py)
- input fixtures: [evals/semantic/input/items.jsonl](C:/Dev/rore/Pallium/evals/semantic/input/items.jsonl)

Extraction runner currently reports:

- overall typed-memory correctness
- per-kind metrics
- prompt text metrics
- per-signal metrics for:
  - `is_low_value_meta`
  - `constraint_text`
  - `next_step_text`
  - `blocker_text`
  - `progress_text`
  - `key_finding_text`
  - `subject_hints`
  - `constraint_candidates`

Enrichment runner:

- [evals/write_enrichment_runner.py](C:/Dev/rore/Pallium/evals/write_enrichment_runner.py)
- input fixtures: [evals/write_enrichment/input/scenarios.jsonl](C:/Dev/rore/Pallium/evals/write_enrichment/input/scenarios.jsonl)

Enrichment runner currently reports:

- `ENRICH` vs `NO_OP` action correctness
- scenario success counts
- required-term hits and misses
- forbidden-term violations
- prompt text metrics

## Fast Evaluators

When changing a prompt, build or extend a focused evaluator that tests the specific behavior you are changing plus regression scenarios for existing behavior, before running any full benchmark. Fast evaluators use synthetic scenarios with concrete assertions (~10-20 LLM calls, under a minute with cache). Full benchmarks (LoCoMo, MABench, LongMemEval) are expensive integration checks — run them only after the fast evaluator passes clean.

Existing fast evaluators:

- Fact extraction: `evals/prompt_variant_eval.py` (8 snippets, ~32 LLM calls with 2 variants)

## Working Rules

1. Keep prompts role-specific.
   Do not fold extraction, reconciliation, enrichment, and query-time ambiguity handling into one large prompt.

2. Preserve structured outputs.
   Prompt changes should not broaden the schema contract or weaken fail-closed behavior.

3. Prefer plain task wording over internal architecture wording.
   Use terms like `stored record`, `search-friendly context line`, or `explicit proof` instead of abstract internal terms when clearer.

4. Add examples only when they materially improve measured behavior.
   Do not add examples by default if the compact prompt already performs well enough.

5. Keep abstain and `NO_OP` behavior explicit.
   The prompt should make it easy for the model to do nothing when no durable value is present.

6. Evaluate before changing defaults.
   Do not switch the repo default prompt variant based only on intuition or local prompt text preference.

## Recommended Prompt-Change Loop

1. Add one or more candidate variants in the role implementation file.
2. Keep the schema unchanged unless the feature explicitly changes the contract.
3. Add or adjust deterministic fixtures only when the current fixture set misses the behavior you are trying to improve.
4. Run the focused stub-backed tests first.
5. Run the role-specific eval runner with multiple variants.
6. If live provider access is available, run a compact representative live bakeoff before changing defaults.
7. Compare:
   - correctness
   - false positives / false negatives
   - `NO_OP` discipline where relevant
   - prompt size
8. Choose the smallest variant that still wins on the behavior that matters.
9. Update defaults only after that comparison.
10. Record the conclusion in commit summary, PR notes, or docs when the winner changed.

## Commands

Focused prompt-related tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_prompt_variant_metrics.py tests\test_semantic_llm_plugin.py tests\test_semantic_runner.py tests\test_semantic_write_enrichment.py tests\test_write_enrichment_runner.py -q
```

Broader prompt-related verification:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_config.py tests\test_prompt_variant_metrics.py tests\test_semantic_llm_plugin.py tests\test_semantic_runner.py tests\test_semantic_write_enrichment.py tests\test_thread_aggregation.py tests\test_tiered_memory.py tests\test_write_enrichment_runner.py -q
```

Extraction bakeoff:

```powershell
.\.venv\Scripts\python.exe -m evals.semantic_runner --suite-name semantic-prompt-bakeoff --input-file evals\semantic\input\items.jsonl --output-dir tmp\semantic-prompt-bakeoff --prompt-variants strict_typed_memory_v4_evidence_guarded,strict_typed_memory_v5_compact_contract,strict_typed_memory_v5_compact_examples
```

Enrichment bakeoff:

```powershell
.\.venv\Scripts\python.exe -m evals.write_enrichment_runner --input-file evals\write_enrichment\input\scenarios.jsonl --output-dir tmp\write-enrichment-bakeoff --prompt-variants baseline_v1,search_context_v2_compact,search_context_v2_handles
```

To run against the live provider, set the same environment/config values used by the normal live semantic path before invoking the runner.

## Current Known Choices

Current extraction decision:

- `strict_typed_memory_v5_compact_examples` won because it stayed much smaller than `strict_typed_memory_v4_evidence_guarded` while preserving the representative live behavior that `strict_typed_memory_v5_compact_contract` lost.

- `strict_typed_memory_v8b_work_refs_separate` replaced v5 as the default. A separate "External References" section in the prompt avoids decision classification interference that occurred when work_refs were inlined with the main fields. Cost: +86 tokens. Benefit: 100% work_ref extraction accuracy.

Current enrichment decision:

- `search_context_v2_compact` remains the best default because it preserved strong live scenario performance with fewer forbidden/filler outcomes than `baseline_v1`, while the more restrictive handle-focused variants overused `NO_OP`.

## Anti-Patterns

Avoid these prompt-improvement patterns:

- changing defaults without a comparative eval run
- judging prompts only by token count
- adding lots of examples without showing measurable benefit
- fixing one scenario by encoding scenario-specific nouns or one-off wording into the prompt
- moving deterministic policy from code into prompt prose
- broadening query-time prompt usage just because write-time prompts improved
