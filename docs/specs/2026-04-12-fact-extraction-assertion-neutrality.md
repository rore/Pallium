# Fact Extraction Assertion Neutrality

## Problem

When Pallium ingests a user correction that contradicts a previously stated fact, the `conversational_knowledge` package's fact extraction LLM prompt may silently reject the correction because the LLM's world knowledge disagrees with it. The correction never becomes an `atomic_fact`, so it never enters the consolidation pipeline, and the old value persists unchallenged.

MABench SF-SH data: in 77% of misses (24/31), the corrected value did not appear in any retrieved `atomic_fact` or `fact_summary`, and no `fact_summary` existed for any of the 31 missed subjects — indicating consolidation never fired, which implies the corrected value was never extracted as an `atomic_fact`. The corrected value was only captured in `discussion_summary` (produced by the separate `agent_conversation_memory` package). The existing consolidation and supersession infrastructure works correctly when facts enter the pipeline. The gap is that facts don't enter the pipeline.

In production, most user corrections are domain-specific ("deployment target is now us-east-2") and wouldn't trigger LLM resistance. But edge cases exist where the LLM's world knowledge conflicts with a legitimate domain correction. Pallium's role is to record what was stated, not judge accuracy.

## Scope

- One prompt change in `semantic/conversational_knowledge.py` (`FACT_EXTRACTION_SYSTEM_PROMPT`)
- Prompt schema version bump for provenance traceability
- Four new test snippets in `evals/prompt_variant_eval.py` (1 targeted + 3 regression guards)
- Documentation update to `docs/context/prompt-improvement.md` (fast evaluator pattern)
- No schema changes, no architecture changes, no changes outside `conversational_knowledge`

### What about `FACT_CONSOLIDATION_SYSTEM_PROMPT`?

The consolidation prompt's "when in doubt, do NOT supersede" clause could theoretically let the LLM refuse supersession based on world knowledge. However, we have no data showing this happens — consolidation never fires for the missed subjects because the atomic_fact was never created in the first place. The disciplined approach: fix extraction first, measure whether consolidation handles the corrected facts correctly, and only change the consolidation prompt if data shows it's needed.

## Design

### Prompt change: FACT_EXTRACTION_SYSTEM_PROMPT

Add a minimal clause after the existing first sentence ("Extract specific, atomic facts from the conversation below."). The exact wording is determined by the eval, but the intent is:

- Extract what participants stated, not what is objectively true
- Do not use world knowledge to filter out assertions that seem incorrect
- Corrections and updates to previously stated facts should be extracted like any other fact

The addition should be as small as possible — the eval determines whether one sentence suffices. All existing extraction rules (specificity, dedup, skip greetings, category schema, language matching) remain unchanged.

### Prompt schema version bump

Bump `FACT_PROMPT_SCHEMA_VERSION` from `"v1"` to `"v2"` so stored `atomic_fact` objects created under the new prompt are distinguishable from those created under the old one. This follows the prompt provenance decision (decisions.md, 2026-03-09).

### Documentation update: prompt-improvement.md

Add a new section "Fast Evaluators" between "Evaluation Surfaces" and "Working Rules":

> **Fast Evaluators**
>
> When changing a prompt, build or extend a focused evaluator that tests the specific behavior you are changing plus regression scenarios for existing behavior, before running any full benchmark. Fast evaluators use synthetic scenarios with concrete assertions (~10-20 LLM calls, under a minute with cache). Full benchmarks (LoCoMo, MABench, LongMemEval) are expensive integration checks — run them only after the fast evaluator passes clean.
>
> Existing fast evaluators:
> - Fact extraction: `evals/prompt_variant_eval.py` (4 snippets, ~16 LLM calls)

### Existing evaluator extension: prompt_variant_eval.py

Add new snippets to the existing `SNIPPETS` list. The new snippets serve two purposes: testing the targeted behavior (correction extraction) and guarding against the most likely regressions from a "don't judge accuracy" clause.

**Targeted behavior snippet:**

**correction_handling**: A thread where the user states a fact, then later corrects it (e.g., "We moved to Portland" then later "Actually we moved to Seattle, not Portland"). Assertions: the correction IS extracted as an atomic_fact (`must_contain` the corrected value), and the original IS also extracted (both should exist as separate atomic_facts — consolidation handles supersession later, not extraction).

**Regression guard snippets:**

The prompt change tells the LLM "don't filter by accuracy." The risk is the LLM also stops filtering things it currently correctly excludes. The existing eval covers greeting/filler filtering and dedup, but has no coverage for:

**opinion_not_fact**: A thread with opinions, hypotheticals, and hedged statements mixed with real facts. (e.g., "I think we might move to Denver someday" alongside "We live in Portland"). Assertions: the concrete fact IS extracted, opinions/hypotheticals are NOT (`must_not_contain` the hedged claims, `must_contain` the concrete fact). Guards against the prompt change causing over-extraction of non-factual assertions.

**assistant_utterances_not_facts**: A thread where the assistant restates or paraphrases user facts (e.g., user says "My daughter Emma is 7", assistant says "That's a great age! Emma must be in second grade"). Assertions: the user's fact IS extracted, the assistant's paraphrase/inference is NOT extracted as a separate fact (`count_containing` Emma = 1). Guards against the prompt change causing assistant restatements to be double-counted.

**specificity_preservation**: A thread with specific details that could be vaguely summarized (e.g., "We saw abstract oil paintings at the downtown gallery" not "went to a gallery"). Assertions: `must_contain` the qualifying details ("abstract", "oil", "downtown"), `must_not_contain` vague versions without qualifiers. Guards against the prompt change reducing extraction discipline. The existing `dense_facts` snippet checks proper noun presence but has no negative test for specificity degradation.

## Validation plan

### Step 1: Fast evaluator (minutes)

Run `prompt_variant_eval.py` with `current` vs `v2_assertion_neutral` variants.

Regression checks (must pass for BOTH variants):
- All 4 existing snippets (date resolution, dedup, trivial filtering, dense facts)
- `opinion_not_fact` — opinions/hypotheticals still excluded
- `assistant_utterances_not_facts` — assistant restatements still excluded
- `specificity_preservation` — qualifying details still preserved

Targeted check (must pass for v2):
- `correction_handling` — user corrections extracted as atomic_facts

If `correction_handling` also passes for `current`, the extraction prompt change may not be needed — measure before changing.

### Step 2: Stub tests (seconds)

Run the existing stub-backed test suite for `conversational_knowledge`:
```
python -m pytest tests/test_conversational_knowledge.py tests/test_incremental_fact_extraction.py -x -q
```
These use stub LLM providers so they validate code-path correctness (version bump doesn't break parsing, etc.), not prompt quality. They must remain green.

### Step 3: Integration check (if fast eval passes)

Run MABench SF-SH 6k with the new prompt to see if the targeted improvement materializes. This is a measurement, not a gate. MABench uses real-world counterfactuals (Japan→Swedish, Modi→Australian) which are extreme — even a perfectly neutral prompt may not fully resolve these because the LLM has very strong priors against recording absurd claims. Partial improvement is expected; the production scenario (domain-specific corrections) is less adversarial than the benchmark.

If MABench shows cases where `atomic_fact` is now correctly created but the `fact_summary` still picks the old value, that's the signal to revisit the consolidation prompt as a follow-up.

## Accepted limitations

- `agent_conversation_memory`'s `discussion_summary` may still editorialize ("User states X, which is factually incorrect"). This is out of scope — it's a different package with a different prompt. The `discussion_summary` is a low-trust type that doesn't feed into fact consolidation, so its editorialization doesn't block the correction pipeline.
- The prompt change is defense-in-depth for edge cases. In production, most domain corrections don't trigger LLM world-knowledge resistance.

## What this does NOT change

- No changes to `agent_conversation_memory` package or its prompts
- No changes to `FACT_CONSOLIDATION_SYSTEM_PROMPT` (conditional follow-up if data warrants)
- No changes to thread summary, pattern memory, continuity memory, or write extraction prompts
- No changes to consolidation runner, retrieval, scoring, or routing code
- No schema changes to `atomic_fact` or `fact_summary` payload structure
- No cross-package concerns — all changes are within `conversational_knowledge`
