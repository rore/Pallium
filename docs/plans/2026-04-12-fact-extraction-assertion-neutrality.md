# Fact Extraction Assertion Neutrality — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the fact extraction prompt record user corrections as atomic_facts regardless of whether the LLM's world knowledge disagrees, with full regression coverage.

**Architecture:** One prompt constant change + version bump in `semantic/conversational_knowledge.py`, four new eval snippets in `evals/prompt_variant_eval.py`, one doc update. No schema, architecture, or cross-package changes.

**Spec:** `docs/specs/2026-04-12-fact-extraction-assertion-neutrality.md`

---

### Task 1: Add regression guard snippets to the eval

These snippets must pass for the CURRENT prompt (establishing a baseline) before we change anything. They guard against regressions from the prompt change we'll make in Task 3.

**Files:**
- Modify: `evals/prompt_variant_eval.py:31-110` (append to `SNIPPETS` list)

- [ ] **Step 1: Add the `opinion_not_fact` snippet**

Add after the `dense_facts` entry (after line 110, before the closing `]`):

```python
    {
        "id": "opinion_not_fact",
        "description": "Opinions and hypotheticals not extracted as facts",
        "thread_text": (
            "Session date: 2024-02-10\n"
            "[user]: We live in Portland. I work at Reed College.\n"
            "[assistant]: Nice! Do you like it there?\n"
            "[user]: Yeah it's great. I think we might move to Denver someday though. "
            "My wife sometimes talks about maybe going back to school. "
            "I wonder if the kids would like it there.\n"
            "[assistant]: Denver is a great city!"
        ),
        "assertions": {
            "must_contain_any": [["Portland"], ["Reed College"]],
            "must_not_contain": [
                "Denver",
                "back to school",
            ],
            "max_facts": 4,
        },
    },
```

- [ ] **Step 2: Add the `assistant_utterances_not_facts` snippet**

```python
    {
        "id": "assistant_utterances_not_facts",
        "description": "Assistant paraphrases not double-counted as facts",
        "thread_text": (
            "Session date: 2024-03-01\n"
            "[user]: My daughter Emma just turned 7. She started at Lincoln Elementary this year.\n"
            "[assistant]: That's a great age! Emma must be in second grade at Lincoln Elementary. "
            "Seven-year-olds are so curious.\n"
            "[user]: Yeah, she loves her science class there.\n"
            "[assistant]: Science is wonderful at that age!"
        ),
        "assertions": {
            "must_contain_any": [["Emma", "7"], ["Lincoln Elementary"], ["science"]],
            "count_containing": {"Emma": 1},
            "must_not_contain": ["second grade", "curious", "wonderful"],
            "max_facts": 4,
        },
    },
```

- [ ] **Step 3: Add the `specificity_preservation` snippet**

```python
    {
        "id": "specificity_preservation",
        "description": "Qualifying details preserved, not vaguely summarized",
        "thread_text": (
            "Session date: 2024-04-15\n"
            "[user]: We went to the Belmont Gallery downtown last weekend. "
            "They had an amazing exhibit of abstract oil paintings by a local artist named Tomoko Sato.\n"
            "[assistant]: That sounds lovely!\n"
            "[user]: Yeah, we also stopped by the Japanese garden in Washington Park afterward. "
            "The cherry blossoms were in full bloom."
        ),
        "assertions": {
            "must_contain_any": [
                ["Belmont Gallery"],
                ["abstract", "oil"],
                ["Tomoko Sato"],
                ["Japanese garden"],
                ["cherry blossoms"],
            ],
            "min_must_contain_hits": 4,
            "max_facts": 6,
            "must_contain_pattern": [r"2024-04-0[6-9]|2024-04-1[0-4]|April\s*(6|7|8|9|10|11|12|13|14)"],
        },
    },
```

- [ ] **Step 4: Run eval with current prompt to establish baseline**

```bash
python -m evals.prompt_variant_eval --cache-dir .local/llm-cache
```

Expected: all 7 snippets PASS for the `current` variant. If any new snippet fails, adjust its assertions — the baseline must be clean before we change the prompt.

- [ ] **Step 5: Commit the eval extension**

```bash
git add evals/prompt_variant_eval.py
git commit -m "eval: add regression guard snippets for fact extraction prompt change

Three new snippets: opinion_not_fact, assistant_utterances_not_facts,
specificity_preservation. All pass against the current prompt, establishing
a baseline before the assertion neutrality prompt change."
```

---

### Task 2: Add the targeted `correction_handling` snippet

This snippet tests the behavior we want to improve. It may FAIL for the current prompt — that's expected and confirms the problem.

**Files:**
- Modify: `evals/prompt_variant_eval.py` (append to `SNIPPETS` list)

- [ ] **Step 1: Add the `correction_handling` snippet**

Add after the `specificity_preservation` entry:

```python
    {
        "id": "correction_handling",
        "description": "User corrections extracted as facts alongside originals",
        "thread_text": (
            "Session date: 2024-05-20\n"
            "[user]: Our team just deployed the backend to the us-west-1 region.\n"
            "[assistant]: Got it, deployed to us-west-1.\n"
            "[user]: Actually wait, I got that wrong. We deployed to us-east-2, not us-west-1. "
            "The migration finished last Thursday.\n"
            "[assistant]: Thanks for the correction, noted."
        ),
        "assertions": {
            "must_contain_any": [["us-east-2"], ["us-west-1"]],
            "min_must_contain_hits": 2,
            "must_contain_pattern": [r"2024-05-1[4-6]|May\s*(14|15|16)"],
            "max_facts": 4,
        },
    },
```

- [ ] **Step 2: Run eval and record whether `correction_handling` passes or fails for current prompt**

```bash
python -m evals.prompt_variant_eval --cache-dir .local/llm-cache
```

Record the result. If `correction_handling` passes for `current`, the prompt change may not be needed for domain-specific corrections (only for world-knowledge conflicts). Either way, proceed with the prompt change.

- [ ] **Step 3: Commit**

```bash
git add evals/prompt_variant_eval.py
git commit -m "eval: add correction_handling snippet for fact extraction

Tests that user corrections are extracted as atomic_facts alongside the
original values. Extraction owns recording; consolidation owns supersession."
```

---

### Task 3: Prompt change and version bump

**Files:**
- Modify: `semantic/conversational_knowledge.py:36` (version bump)
- Modify: `semantic/conversational_knowledge.py:106-130` (prompt change)

- [ ] **Step 1: Bump FACT_PROMPT_SCHEMA_VERSION**

In `semantic/conversational_knowledge.py`, change line 36:

```python
FACT_PROMPT_SCHEMA_VERSION = "v2"
```

- [ ] **Step 2: Add the assertion neutrality clause to FACT_EXTRACTION_SYSTEM_PROMPT**

In `semantic/conversational_knowledge.py`, change the first two lines of `FACT_EXTRACTION_SYSTEM_PROMPT` (lines 107-108) from:

```python
    "Extract specific, atomic facts from the conversation below. "
    "Each fact should answer a possible future question about these people, places, events, or preferences. "
```

to:

```python
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true — if a statement contradicts common knowledge or a prior fact, still extract it. "
    "Each fact should answer a possible future question about these people, places, events, or preferences. "
```

This is one sentence, 25 words, placed right after the opening instruction.

- [ ] **Step 3: Run stub tests to verify code-path correctness**

```bash
python -m pytest tests/test_conversational_knowledge.py tests/test_incremental_fact_extraction.py -x -q
```

Expected: all pass. The version bump doesn't affect stub tests (they construct `MemoryObject` instances with hardcoded schema_version, not from the constant).

- [ ] **Step 4: Run the eval with the new prompt and compare against baseline**

Run the eval again with a separate cache dir so v1 cached results from Tasks 1/2 aren't reused:

```bash
python -m evals.prompt_variant_eval --cache-dir .local/llm-cache-v2
```

Compare the terminal output against the Task 1/Task 2 baseline run. Both runs print the same comparison table format.

Expected results:
- **v2 (new prompt)**: All 8 snippets PASS (including `correction_handling`).
- **v1 baseline (from Tasks 1/2)**: All 7 regression snippets PASS. `correction_handling` may have PASSED or FAILED.

If any regression snippet FAILS for v2, the prompt wording needs adjustment — iterate on the clause until regressions are clean.

- [ ] **Step 5: Commit the prompt change**

```bash
git add semantic/conversational_knowledge.py
git commit -m "feat(conversational_knowledge): assertion-neutral fact extraction prompt

Add one clause: 'Record what participants stated, not what is objectively
true — if a statement contradicts common knowledge or a prior fact, still
extract it.'

Bump FACT_PROMPT_SCHEMA_VERSION v1 → v2 for provenance traceability.

Motivation: MABench SF-SH showed 77% of contradiction misses never reached
atomic_fact because the extraction LLM dropped corrections that conflicted
with its world knowledge.

Spec: docs/specs/2026-04-12-fact-extraction-assertion-neutrality.md"
```

---

### Task 4: Documentation update

**Files:**
- Modify: `docs/context/prompt-improvement.md:80-82` (insert new section)

- [ ] **Step 1: Add "Fast Evaluators" section to prompt-improvement.md**

Insert between the line ending the "Evaluation Surfaces" section (line 80, after `- prompt text metrics`) and the `## Working Rules` heading (line 82):

```markdown

## Fast Evaluators

When changing a prompt, build or extend a focused evaluator that tests the specific behavior you are changing plus regression scenarios for existing behavior, before running any full benchmark. Fast evaluators use synthetic scenarios with concrete assertions (~10-20 LLM calls, under a minute with cache). Full benchmarks (LoCoMo, MABench, LongMemEval) are expensive integration checks — run them only after the fast evaluator passes clean.

Existing fast evaluators:

- Fact extraction: `evals/prompt_variant_eval.py` (8 snippets, ~32 LLM calls with 2 variants)

```

- [ ] **Step 2: Update the "Existing fast evaluators" list in prompt-improvement.md to include the conversational_knowledge fact extraction role**

Also add `fact_extraction` to the "Current live prompt-backed roles" list near the top of the file (line 7-8). Change:

```markdown
Current live prompt-backed roles:

- `write_extraction`
- `write_enrichment`
```

to:

```markdown
Current live prompt-backed roles:

- `write_extraction`
- `write_enrichment`
- `fact_extraction` (in `conversational_knowledge` package)
```

- [ ] **Step 3: Commit**

```bash
git add docs/context/prompt-improvement.md
git commit -m "docs: add fast evaluator pattern to prompt improvement workflow

Document that prompt changes should use focused evaluators before full
benchmarks. Register fact_extraction as a live prompt-backed role."
```

---

### Task 5: Integration measurement (optional, not a gate)

This task runs MABench to measure the effect. It does NOT block the prompt change — it's a measurement.

**Files:** None modified

- [ ] **Step 1: Run MABench SF-SH 6k with the new prompt**

Delete the cached DB first so ingestion re-runs with the new prompt:

```bash
rm -rf evals/mabench/db_cache/
python -m evals.mabench_benchmark --context-depth 6k \
  --db-cache-dir evals/mabench/db_cache \
  --cache-dir .local/llm-cache \
  --verbose-results
```

This takes ~25 minutes. Record the SF-SH results.

- [ ] **Step 2: Compare against baseline**

Baseline (from the investigation):
- SF-SH: 51/100 correct, 82/100 gold_in_context, 51/82 correct when gold present
- 31 gold-in-context misses, 24 with gold only in turn_summary

Check:
1. Did overall accuracy improve?
2. Did gold_in_context rate improve? (more corrections reaching atomic_fact)
3. Of the remaining misses, are there cases where atomic_fact was created but fact_summary still has the old value? (signal to revisit consolidation prompt)

- [ ] **Step 3: Record results**

Add a brief note to the spec file with the measurement results. No separate doc needed — the spec already has the MABench context.
