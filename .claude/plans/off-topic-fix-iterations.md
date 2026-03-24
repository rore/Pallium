# Off-Topic Injection Fix — Iterative Improvement Plan

## Problem Statement
Memory objects (thread_summary, interest, decision, constraint_memory) pass
`_candidate_is_injection_eligible` unconditionally (weak spot #6). The justification
check runs BEFORE eligibility, so if justification passes, off-topic memory objects
get injected.

Currently the justification gate1b in lexical-only mode passes ANY retrieval_score >= 1,
which matches the old floor bypass behavior. This means single-bridging-word matches
("tomorrow", "weather") still inject memory objects.

## Root Cause Chain
1. Off-topic query → lexical search matches on bridging word → score=1
2. Routing scores the memory object (e.g. thread_summary layer weight + score*10 = ~292)
3. Justification gate1b: is_lexical_only=True, score >= 1 → justified=True
4. `_candidate_is_injection_eligible`: memory types → True unconditionally
5. Memory object injected into off-topic query

## Test Plan

### A. Direct unit tests (fast, no pipeline)
Build QueryResultItem memory_hit candidates directly (like existing routing tests)
and call route_query_results() to test the full path including justification + eligibility.

Cases to cover:
1. **Off-topic weather + thread_summary** (retrieval_score=1, weak support) → MUST suppress
2. **Off-topic politics + interest** (retrieval_score=1, weak support) → MUST suppress
3. **Off-topic idiom + decision** (retrieval_score=1, weak support) → MUST suppress
4. **Zero-overlap + thread_summary** (retrieval_score=0) → MUST suppress
5. **On-topic recall + thread_summary** (retrieval_score=3+, supported) → MUST inject
6. **Vague recall + task_checkpoint with work signals** (retrieval_score=1, blocker) → MUST inject
7. **On-topic + decision** (retrieval_score=4+, strong support) → MUST inject
8. **Cross-thread recall with weak score but checkpoint** (retrieval_score=1, checkpoint) → MUST inject

### B. Canary preservation
The 5 cross-thread recall tests — run after every change.

### C. Full regression
Fast suite (684+) + slow benchmarks + invariant runner (15 seed + 167 batch).

## Fix Approach
Gate1b should not be a flat threshold. It should consider retrieval score + candidate quality:
- score=1 + only summaries/interests + weak support → suppress (off-topic)
- score=1 + task_checkpoint with work signals → inject (work resumption)
- score=1 + supported/strong evidence → inject (legitimate recall)
- score >= 2 → inject regardless (meaningful content overlap)

This means gate1b becomes conditional: in lexical-only mode, score=1 passes ONLY IF
the candidate set has structural evidence of relevance (high-value types, work signals,
or non-weak support).

## Iteration Strategy
1. Write failing tests first (A.1-A.4 should fail currently, A.5-A.8 should pass)
2. Tune gate1b to fix A.1-A.4 without breaking A.5-A.8 and canaries
3. Full regression
4. If issues found, investigate signal differences and adjust
5. Repeat
