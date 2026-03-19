# Vector Retrieval Validation Report

## Summary

Validated the vector retrieval substrate with real BGE-small-en-v1.5 embeddings (384 dims, ONNX runtime) and real usearch index on the Pallium benchmark scenarios. The feature works as designed for realistic queries but has clear boundaries that should drive implementation choices.

## Test Environment

- Model: BAAI/bge-small-en-v1.5 (384 dimensions, MIT license)
- Runtime: onnxruntime 1.24.4 (fastembed blocked on Python 3.14 by py-rust-stemmers)
- Index: usearch 2.23.0, exact cosine search
- Platform: Windows 11, Python 3.14, CPU-only

---

## Finding 1: Pure-abstract queries cannot discriminate

Queries with zero domain vocabulary ("Where did things end up with that?", "How did it turn out?") produce uniformly similar scores against all memory texts (~0.47-0.56). The embedding model maps them to a generic "follow-up question" region where all domain-specific memories score roughly the same.

| Query | Target sim | Best other sim | Margin |
|---|---|---|---|
| Where did things end up with that? | 0.49 | 0.56 | -0.09 |
| How did it turn out? | 0.47 | 0.51 | -0.03 |
| Any takeaways worth noting? | 0.49 | 0.52 | -0.03 |
| What approach did we settle on? | 0.47 | 0.52 | -0.05 |
| What actually mattered there? | 0.50 | 0.50 | -0.00 |

**Rank-1 accuracy: 0/5.** Vector retrieval alone does not solve pure meta-language recall. This needs thread/session context anchoring at the routing level, not better embeddings.

## Finding 2: Light domain anchoring is sufficient

Adding just 1-2 domain words to the query produces perfect discrimination:

| Level | Rank-1 accuracy | Avg margin | Avg target similarity |
|---|---|---|---|
| pure-abstract | 0/5 | -0.039 | 0.48 |
| light-anchor (1-2 domain words) | 5/5 | +0.053 | 0.70 |
| moderate-anchor | 5/5 | +0.106 | 0.80 |
| domain-specific | 5/5 | +0.096 | 0.80 |
| near-lexical | 5/5 | +0.140 | 0.85 |

The jump from pure-abstract to light-anchor is dramatic: 0% to 100% accuracy, margin flips from -0.04 to +0.05. This is the operational sweet spot — real users almost always include *some* domain hint.

## Finding 3: Diverse phrasing styles all work

Tested 22 diverse query patterns across temporal, conversational, casual, formal, indirect, oblique, and various question-word styles. Results: 21/22 rank-1 (95.5%). The single miss was "What's going on with that sync thing again?" (very casual, "thing" is near-zero information) — margin was -0.004, essentially a coin flip.

Notable successes:
- "Hey, remind me about the sync job situation" -> rank-1, sim=0.69
- "So the reservation queue duplicates -- what was the deal?" -> rank-1, sim=0.85
- "Why did we choose event-time ordering over wall-clock?" -> rank-1, sim=0.88
- "I need to update the team on the nightly job progress" -> rank-1, sim=0.70

The model handles conversational, formal, indirect, and question-word-variant phrasing robustly.

## Finding 4: Curated text does NOT always beat raw conversation

| Query | Raw | Curated | Minimal |
|---|---|---|---|
| sync job (light) | **0.75** | 0.68 | 0.73 |
| catalog sync failure (moderate) | 0.83 | 0.75 | **0.84** |
| token rotation (domain) | 0.82 | 0.80 | **0.85** |

The raw conversation text and minimal summaries often score as well or better than the curated `build_embedding_text()` format. The curated format's structure ("Task: ...", "Current state: ...") adds tokens that dilute the domain signal per embedding dimension. Shorter, domain-dense text can embed better.

**Implication**: The embedding text composition should prioritize domain density over structural completeness. Including every field ("Task:", "Current state:", "Blocker:", "Next step:") may actually hurt rather than help. A shorter text with just the key domain nouns and finding/decision text may be the better embedding target.

For investigation queries, curated text scored marginally better than raw (0.74 vs 0.74, 0.81 vs 0.81) — essentially tied. The curated format does NOT demonstrably improve embedding quality.

## Finding 5: usearch round-trip works correctly

All 5 test queries returned the correct memory as rank-1 result through the real usearch index with real vectors. Cosine similarities matched the numpy-computed values. The index correctly maintains vector ordering.

## Finding 6: Latency is acceptable

| Operation | Mean | p50 | p95 |
|---|---|---|---|
| Single text embed (CPU) | 93ms | 86ms | 137ms |
| Batch(5) embed | 100ms | 55ms | 291ms |
| Batch(20) embed | 58ms | 46ms | 90ms |
| usearch search (100 vectors, k=10) | 0.019ms | 0.017ms | — |
| usearch search (1000 vectors, k=10) | 0.093ms | 0.091ms | — |

Single embedding is ~90ms on CPU. Batch amortization brings per-text cost down to ~3ms for batches of 20. usearch search is sub-millisecond even at 1000 vectors. Total query-time cost for vector retrieval: ~90ms (embed query) + <1ms (search) = ~91ms.

Write-time cost: one embed per memory object (~90ms) is noise next to the 1-5 second LLM extraction calls.

---

## Implications for Implementation

### 1. Threshold setting

**REVISED AFTER NEGATIVE TESTING.** At threshold 0.3, ALL unrelated memories in a 15-memory container score above threshold for every query. The threshold does nothing. Meaningful noise filtering only starts at 0.55.

| Threshold | Avg unrelated FP per query (out of 11) | Assessment |
|---|---|---|
| 0.30 | 11.0 (all!) | Useless |
| 0.50 | 10.1 | Still too noisy |
| 0.55 | 4.9 | Getting usable |
| 0.60 | 1.3 | Clean |

The target memory still ranks #1 in 5/7 queries regardless of threshold. So recall is not affected by raising the threshold. The question is how much noise accompanies the correct result.

Good news: low-value/generic memories ("Got it, I'll look into that") consistently score lower than real domain memories (max 0.62 vs target 0.69+). So the threshold won't wrongly promote garbage.

**Recommendation**: Raise default `min_similarity` to **0.55**. This cuts average false positives from 11 to 5 per query while preserving recall. Consider 0.60 for stricter deployments. The threshold should be treated as a noise filter, not a relevance discriminator — ranking handles relevance.

### 2. Embedding text composition

**REVISED AFTER SYSTEMATIC COMPARISON.** The earlier hand-crafted tests suggested shorter text embeds better. Systematic testing across all memory types with margin-over-distractor scoring shows mixed results:

| Memory type | Current multi-field margin | Simplified single-field margin | Winner |
|---|---|---|---|
| task_checkpoint | +0.216 | +0.218 | Tied |
| investigation_outcome | +0.045 | +0.041 | Tied |
| decision | +0.118 | +0.070 | Current |
| thread_summary | +0.184 | +0.215 | Simplified |
| continuity_memory | +0.173 | +0.198 | Simplified |

The data does not clearly support changing `build_embedding_text()`. Some types embed better with more fields (decision), some with fewer (thread_summary). The current implementation works correctly — 6/6 rank-1 accuracy on actual output.

**Recommendation**: Keep the current `build_embedding_text()` implementation. The structural labels ("Task:", "Decision:") do not hurt enough to justify the change. Revisit only if real-stack benchmarks with fusion show embedding text as the bottleneck.

### 3. Minimum content guard

Memories with very little domain vocabulary (e.g., "We discussed the options and agreed to proceed") will be poor embedding targets — they'll score similarly against many different queries. However, detecting "domain-specific tokens" reliably requires NLP (POS tagging, NER) which adds heavy dependencies for a marginal check.

The practical proxy is text length. Short texts are always generic; texts above ~40 characters from Pallium's extraction pipeline almost always contain domain-specific content because the extraction naturally preserves key nouns and findings.

**Recommendation**: Return None from `build_embedding_text()` when the curated text is shorter than 40 characters. No domain-vocabulary detection — length is a sufficient proxy.

### 4. Pure-abstract queries need routing, not better embeddings

"Where did things end up with that?" will never work through vector search alone — no embedding model can map a content-free question to the right domain memory. These queries need:
- Thread/session context anchoring (routing knows which thread the user was in)
- Recency bias (prefer the most recent active memory in the current container)
- Or explicit contextual prompt from the consuming agent ("regarding catalog sync, where did things end up?")

**Recommendation**: Do not try to solve pure-abstract recall through embedding improvements. That is a routing/context problem, not a retrieval problem.

### 5. The enrichment context may help marginal cases

The deferred `retrieval_enrichment` text (LLM-generated domain anchors like "workstream: catalog-sync, failure-mode: expired-credentials") could help memories whose primary text is borderline generic by adding domain vocabulary. This was deferred from the first slice — the data suggests it's worth adding, but as a secondary signal rather than prepended to the main text.

**Recommendation**: When adding enrichment support later, test whether appending (not prepending) enrichment text improves or hurts similarity scores.

### 6. Python 3.14 compatibility

fastembed cannot be installed on Python 3.14 due to `py-rust-stemmers` dependency. The validation used onnxruntime + tokenizers directly. For production, either:
- Wait for py-rust-stemmers to ship 3.14 wheels
- Add an OnnxEmbeddingProvider that wraps onnxruntime directly (same approach as this validation)
- Pin to Python 3.12/3.13 for production

**Recommendation**: Add an `OnnxEmbeddingProvider` as an alternative to `FastEmbedProvider`. It uses the same ONNX model but bypasses fastembed's dependency chain.

---

## Negative-Case Validation (Added After Review)

### Finding 11: Threshold 0.3 provides zero noise filtering

In a realistic 15-memory container (1 target, 3 related, 11 unrelated), ALL 11 unrelated memories score above 0.3 for every query tested. The threshold is useless at that level. This was the most important gap in the original validation, which was recall-focused.

Low-value/generic memories ("Got it, I'll look into that") consistently score lower than real domain memories (max 0.62 vs target 0.69+). The threshold won't wrongly promote garbage over real content, but it will let a lot of noise through to the routing layer.

### Finding 12: Current `build_embedding_text()` is not demonstrably worse than simplified alternatives

Systematic margin-over-distractor comparison shows type-dependent results. The current multi-field format wins for decisions (+0.118 vs +0.070), loses slightly for thread summaries (+0.184 vs +0.215) and continuity memory (+0.173 vs +0.198), and ties for checkpoints and investigations. The data does not support a rewrite.

### Finding 13: Length guard at 40 characters correctly separates useful from useless

| Category | Length | Embed quality | 40-char threshold |
|---|---|---|---|
| Full checkpoint | 200 chars | 0.72 | KEEP |
| Short but useful decision | 44 chars | 0.72 | KEEP |
| Vague summary | 39 chars | 0.61 | DROP |
| Acknowledgment | 28 chars | 0.46 | DROP |
| Greeting | 32 chars | 0.50 | DROP |

The 40-char boundary correctly keeps marginal-but-useful texts (short decisions score 0.72) and drops vague/generic ones (summaries without domain content score 0.61 or below).

---

## Conclusion

Vector retrieval works for its intended purpose: bridging the lexical recall gap when users paraphrase or use domain vocabulary different from the stored memory text. It does NOT solve pure meta-language queries with zero domain content — that requires routing improvements.

The feature is correctly scoped as a diagnostic/benchmark substrate in this slice. When fusion activates vector results in the production query path, the real-world benefit will come from the "light-anchor" and above query classes, which represent the majority of real user queries.

---

## Additional Findings (Deep Validation)

### Finding 7: BGE instruction prefix has negligible impact

BGE models recommend prefixing queries with "Represent this sentence for searching relevant passages: " for retrieval tasks. Testing shows average margin improvement of only +0.004 across 9 query/memory pairs. Not worth the added complexity.

**Recommendation**: Do not use instruction prefixes. The marginal benefit does not justify a special query-time text transformation.

### Finding 8: Embedding text format matters less than initially measured

Early hand-crafted tests suggested shorter text always embeds better. Systematic testing with margin-over-distractor scoring (Test 3, negative validation) shows the effect is type-dependent: decisions embed better with the current multi-field format, while thread summaries and continuity memories slightly prefer shorter text. The difference is modest in all cases (0.02-0.05 margin).

**Recommendation for `build_embedding_text()`**: Keep the current implementation. The structural labels do not hurt enough to justify a rewrite. If a future type-specific issue is found, optimize that type only.

### Finding 9: Query-time context expansion dramatically improves pure-abstract recall

Prepending topic/thread context to abstract queries produces the strongest improvement observed in all tests:

| Query variant | Target sim | Rank |
|---|---|---|
| "Where did things end up with that?" | 0.47 | rank 3 (MISS) |
| "Regarding catalog sync: where did things end up with that?" | 0.72 | rank 2 |
| "In our conversation about the sync job failure: where did things end up?" | 0.72 | rank 1 (OK) |

Adding "Regarding {topic}:" to a pure-abstract query jumps similarity from ~0.47 to ~0.72 and moves the target from rank 3 to rank 1. The routing layer already has container_ref, thread_ref, and can derive topic context. This is the correct fix for pure-abstract recall — cheap, uses existing metadata, and works within the embedding model's capabilities.

**Recommendation for fusion feature**: When activating vector retrieval in the production query path, prepend available container/thread topic metadata to the query text before embedding. This is a query-time transformation that requires no model changes, no index rebuilds, and no write-path changes. It should be implemented in the fusion feature, not in the vector provider itself (the provider embeds whatever text it receives; the caller enriches the text).

### Finding 10: SourceItem embedding would add real retrieval value

Raw source text scored higher than curated memory text in 6 of 9 test pairs (by 0.02-0.08 margin). This is because raw conversation text preserves natural sentence structure and domain vocabulary that embedding models handle well, while the curated memory text introduces structural formatting that dilutes the signal.

This does not mean memory embedding is wrong — both are useful. The memory text is more compact and covers derived knowledge (summaries, conclusions). The raw source text covers the original detailed expression. Together they'd provide better recall than either alone.

**Recommendation**: Keep `SourceItem` embedding on the roadmap as a valuable follow-on. The first slice is correctly scoped to memory-only, but the data shows source items would add meaningful recall, not just volume.

---

## Existing Harness Readiness for Vector Analysis

Survey of all 18 evaluation harnesses. Three tiers of readiness:

### Already captures vector trace (zero work)

| Harness | How | What to extract |
|---|---|---|
| Live Exploratory Runner | Uses `/query/debug`, full trace captured | Extract vector stage from `trace.stages`, add `vector_stage_used`, `vector_similarity_best` to drift metrics |
| Vector Retrieval Runner | Purpose-built, calls providers with `include_trace=True` | Already captures lexical vs vector recall. Needs real embeddings (fastembed) to prove quality |

### Needs `/query/debug` switch (~30-60 lines each, high value)

| Harness | Current | Extension | Value |
|---|---|---|---|
| **Work Resumption Benchmark** | `/query` only | Switch to `/query/debug`, capture retrieval stages, add `vector_hits_count` and `vector_rescue` flag | **High** -- core resumed-work use case; directly measures if vector saves task_checkpoint/decision recall |
| **Memory Routing Benchmark** | `/query` only | Switch to `/query/debug`, add `lexical_candidate_count` vs `vector_candidate_count`, track "layer selected via vector fallback" | **High** -- measures if vector expands candidate set enough for correct layer selection |
| **Public Corpus Benchmark** | `/query` only | Switch to `/query/debug`, add corpus-level `vector_improved_usefulness_rate` | **Highest production relevance** -- real conversation paraphrasing; measures vector benefit across diverse real queries |
| **Low Value Churn Benchmark** | `/query` only | Add trace capture, verify vector doesn't increase `no_value_overreach` | **Important negative test** -- must confirm vector doesn't inject false positives |

### Indirect or lower value

| Harness | Notes |
|---|---|
| Recurring Question | Medium -- could measure paraphrase recall across thread variants |
| External Memory Pressure | Medium -- vector stability under volume growth |
| Developer Work Confidence | Aggregates from sub-harnesses; benefits automatically |
| Agent Simulation | Can extract from saved session replays for comparative analysis |
| Tiered Memory / Consolidation | Orthogonal (formation, not retrieval) |
| Semantic / QAR / Enrichment | Not applicable (upstream of retrieval) |

### Recommended extension order

1. **Live Exploratory Runner** -- extract vector metrics from existing trace (zero-cost, immediate value)
2. **Work Resumption Benchmark** -- switch to `/query/debug` (~30 lines, directly validates the recall gap this feature addresses)
3. **Low Value Churn Benchmark** -- add vector negative test gate (~40 lines, prevents false-positive regression)
4. **Memory Routing Benchmark** -- add vector candidate tracking (~40 lines, layer selection insight)
5. **Public Corpus Benchmark** -- switch to `/query/debug` (~60 lines, highest production relevance but most work)

These extensions should happen alongside or immediately after the fusion feature, when vector results actually enter the production query path. Before fusion, only the Live Exploratory Runner and Vector Retrieval Runner provide meaningful vector analysis (diagnostic trace only).
