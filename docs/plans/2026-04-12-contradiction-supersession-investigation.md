# Contradiction Supersession — Investigation Brief

## Problem

When Pallium ingests a newer fact that contradicts an older one, it creates the
new memory object (atomic_fact or fact_summary) but leaves all older memory
objects intact. At query time, the retrieved context contains multiple old objects
asserting the original value and one new object asserting the updated value.

This causes the consuming agent (or benchmark evaluator) to pick the majority
answer — the stale one — even though the newer contradictory fact was
successfully retrieved.

## Evidence from MABench 6k benchmark (2026-04-12)

SF-SH (single-hop) results:
- **82/100 gold_in_context** — Pallium retrieved the updated fact in 82% of cases
- **51/82 correct** when gold was present — 31 failures where the updated fact
  was retrieved but the evaluator picked the old answer
- **31 cases** where older memory objects outnumbered the newer contradictory fact

Example: "What is the official language of Japan?"
- Gold answer: "Swedish" (counterfactual injected as newer fact)
- Retrieved context contains: 4 objects saying "Japanese" (thread_summary,
  turn_summary, older atomic_facts) + 1 object saying "Swedish" (newer atomic_fact)
- Evaluator picks "Japanese" because it appears in more objects and has higher-priority
  types (thread_summary, consolidated facts)

This is a production-relevant concern: if a user corrects a fact ("actually our
deployment target is now us-east-2, not us-west-1"), the old answer will persist
in thread summaries and consolidated facts, drowning out the correction.

## How to reproduce

### 1. Run the MABench 6k benchmark

```bash
python -m evals.mabench_benchmark --context-depth 6k \
  --db-cache-dir evals/mabench/db_cache \
  --cache-dir .local/llm-cache \
  --verbose-results
```

This takes ~25 minutes. The DB cache is saved so subsequent runs skip ingestion.
Results go to `evals/mabench/output/mabench-sf__6k__*/`.

### 2. Find the gold-in-context misses

```python
import json

results_path = "evals/mabench/output/mabench-sf__6k__anthropic-claude__anthropic--claude-sonnet-latest__20260412T144829Z/results.jsonl"
results = [json.loads(l) for l in open(results_path)]

# SF-SH cases where gold was in context but answer was wrong
misses = [r for r in results
          if r.get('gold_in_context')
          and not r.get('correct')
          and r['dataset_id'] == 'sf-sh']

print(f"Gold in context but wrong: {len(misses)}")
for r in misses[:5]:
    print(f"Q: {r['question']}")
    print(f"Gold: {r['gold_answers']}")
    print(f"Predicted: {r['predicted_answer']}")
    print(f"Reasoning: {r['answer_reasoning'][:200]}")
    print("---")
```

### 3. Inspect the retrieved context for a specific miss

Each result in the JSONL has `retrieved_results` (list of memory objects returned
by Pallium) and `justifier_context` (the formatted text sent to the judge). Look
for cases where multiple objects have the old value and only one has the new value.

```python
miss = misses[0]
print(f"Question: {miss['question']}")
print(f"Gold: {miss['gold_answers']}")
print(f"\nRetrieved objects ({len(miss['retrieved_results'])}):")
for i, obj in enumerate(miss['retrieved_results']):
    mem = obj.get('memory_payload', {})
    print(f"  [{i}] type={mem.get('memory_type','?')}, subject={mem.get('subject','?')}")
    print(f"       summary={mem.get('summary','?')[:120]}")
```

### 4. Trace what happened during ingestion (optional deep dive)

Use the cached DB to query what memory objects exist for a given subject:

```bash
# Start server with the cached DB
cp evals/mabench/db_cache/sf-sh-row0.db pallium.db
python -m app.run serve --host 127.0.0.1 --port 8000

# Query for a specific subject
curl -s http://127.0.0.1:8000/query/debug -H 'Content-Type: application/json' \
  -d '{"text": "official language of Japan", "use_case": "agent_conversation_memory", "limit": 20}' | python -m json.tool
```

This shows all memory objects Pallium created for that subject, including their
types, timestamps, and which thread they came from.

## What the data shows

The 31 SF-SH misses break down into:
- **Consolidation created summaries with old facts**: thread_summary and
  turn_summary objects are generated from the full thread, which contains
  many facts with original (true) values. The one counterfactual (newer value)
  gets drowned out in the summary.
- **Multiple atomic_facts with old value**: The same true fact may appear in
  slightly different forms across the 455-fact context, producing several
  atomic_facts that all agree on the old value.
- **fact_summary consolidation picks majority**: When FactConsolidationStrategy
  consolidates across threads, if multiple threads have the old value and one
  has the new, the consolidated summary may keep the old value.

## Key code paths to investigate

1. **Contradiction detection** — `core/consolidation_runner.py` and
   `semantic/agent_conversation_memory_consolidation.py`: The consolidation LLM
   call already detects contradictions (added in commit 7d8f0e0). Check what
   happens when a contradiction is detected — does it set any flag on the older
   objects?

2. **FactConsolidationStrategy** — `semantic/strategies/fact_consolidation.py`:
   This creates `fact_summary` objects from groups of related `atomic_fact`
   objects. When facts in a group contradict each other, what does the LLM
   produce? Does it pick the newer one or merge them?

3. **Memory object lifecycle** — `storage/sqlite.py` and `core/service.py`:
   Is there an existing mechanism to mark memory objects as superseded or to
   reduce their retrieval weight? Check for any `status`, `superseded_by`, or
   `active` fields on the memory_objects table.

4. **Thread summary generation** — `semantic/agent_conversation_memory.py`
   `_rebuild_thread`: When generating thread_summary objects, could the prompt
   be instructed to note which facts are the most recent if contradictions exist?

5. **Retrieval scoring** — `semantic/agent_conversation_memory_routing_scoring.py`:
   Could superseded objects be deprioritized during scoring? Check if there's a
   type weight or recency boost that could be leveraged.

## Possible fix directions

1. **Supersession marking**: When consolidation detects a contradiction, mark
   the older memory objects with a `superseded_by` reference. Retrieval filters
   or deprioritizes superseded objects.

2. **Recency-aware consolidation prompt**: Instruct the consolidation LLM to
   always prefer the more recent fact when contradictions are detected, and to
   explicitly note "supersedes fact from [date]" in the output.

3. **Retrieval-time deduplication**: When multiple objects cover the same
   subject+attribute, keep only the most recent in the returned context.

4. **Thread summary recency bias**: When generating thread_summary, instruct
   the prompt to flag which facts are the latest version when contradictions
   exist within the thread.

Option 1 is the most architecturally clean. It solves the problem at the source
rather than working around it at retrieval time.

## Success criteria

- SF-SH gold_in_context-correct rate improves from 62% (51/82) toward 80%+
- Old contradicted memory objects are demoted or filtered in retrieval results
- No regression on LoCoMo or LongMemEval benchmarks
- Production behavior: when a user corrects a fact, subsequent queries return
  the correction, not the old value
