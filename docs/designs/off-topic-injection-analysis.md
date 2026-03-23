# Off-Topic Injection Analysis

## Finding

Generated exploratory QA scenarios surfaced 4 cases where completely off-topic
queries (weather, rain, umbrella) get library catalog memories injected. This
happens in both lexical-only and composite retrieval modes.

## Root Causes (7 Weak Spots)

### 1. Lexical-only mode bypasses the relevance floor entirely
`_any_candidate_passes_retrieval_relevance_floor` in `routing_selection.py:217-219`
returns `True, "lexical_only_retrieval"` immediately for any item with
`retrieval_source=None`. In lexical-only mode (no vector provider), ALL items
have `retrieval_source=None`. The floor is dead code.

### 2. Floor is a batch gate, not per-item
If ANY candidate passes the floor, ALL candidates proceed to injection. A weak
candidate (score=1, single shared word like "tomorrow") rides through on a
strong candidate's score.

### 3. Small corpus IDF degradation
Below `_IDF_MIN_CORPUS_SIZE = 5` (sqlite_search.py:22), IDF is disabled and
`score = len(matched_tokens)`. Two common words yield score=2 = the floor.

### 4. Floor threshold of 2 is low
In small-corpus token-count mode, 2 common words pass. In IDF mode, a
moderately common word (IDF ~1.5) rounds to 2 and passes.

### 5. `is_query_topic_signal_empty` is a stub
`routing_constants.py:340-342` always returns `True`. Topic signal classification
was removed (cue-free control plane). No path checks query-to-candidate topical
relationship in the signal envelope.

### 6. `_candidate_is_injection_eligible` is unconditional for structured memory
`routing_selection.py:690-691`: any decision, investigation_outcome, etc. passes
injection eligibility regardless of topical relationship.

### 7. `low_value` detection only catches greetings and ultra-short queries
`routing_signals.py:400-407`: only `len < 3` and empty queries. "Is it going to
rain tomorrow?" is 30+ chars and passes all checks.

## Attempted Fix and Why It Regressed

**Fix A**: Activate the floor for lexical-only mode by checking `item.score >= floor`.
This correctly blocks weather queries (score=1 from "tomorrow") but also blocks
legitimate cross-thread recall queries where:
- Thread-scoped lexical search can't find cross-thread content
- Memory text views have generic text, not domain words
- Single domain abbreviations ("db") score 1

The fundamental tension: **lexical-only scoring can't distinguish "db" (relevant
abbreviation) from "tomorrow" (generic bridging word) when IDF is disabled in
small corpora.** Cross-thread recall depends on memory text views that often
don't carry the original domain vocabulary.

## Possible Fixes (Owner Decision Needed)

### Option 1: Keep floor bypass for lexical-only, accept off-topic risk
Status quo. Off-topic injection only matters in production when composite
retrieval is enabled (which has the floor). Lexical-only mode is primarily
for testing/development.

**Tradeoff**: No regression risk, but off-topic injection in lexical-only
deployments and in the invariant runner.

### Option 2: Activate floor for lexical-only with source-item-only scope
Only apply the floor to `source_hit` results, not `memory_hit`. Memory objects
surface through routing based on their own text views; source items carry raw
content where lexical overlap is meaningful.

**Tradeoff**: Narrower fix, less regression risk. But memory-hit injection from
zero-overlap queries is still possible.

### Option 3: IDF scoring for small corpora
Remove the `_IDF_MIN_CORPUS_SIZE` fallback — always compute IDF. With 1-3 items,
the IDF formula still produces meaningful weights (rare terms get high scores,
common terms get low scores). The token-count fallback was a conservative choice
that eliminates the discriminative power of IDF exactly when it's most needed.

**Tradeoff**: Changes the scoring behavior for all small-corpus deployments.
Needs validation against existing benchmarks.

### Option 4: Query-to-candidate semantic check in injection decision
Add a lightweight check in `_build_injectable_blocks`: if the query's content
tokens have zero overlap with the injected block's content tokens (after
stopword removal), suppress that block. Similar to INV-03 but in the production
path.

**Tradeoff**: Per-block check, catches the exact bug. But adds computation to
the injection hot path.

## Recommendation
Option 3 is the most principled fix. The small-corpus IDF fallback to token count
is the root cause — it removes the scoring system's ability to discriminate. The
existing floor (2) and escape hatch (cosine >= 0.70) are correctly calibrated for
IDF-weighted scores. They just need IDF to actually be computed.

## Test Infrastructure
- `tests/test_retrieval_relevance_floor.py` has 2 pre-existing failures (composite
  mode off-topic tests) caused by the mock using unrealistically high vector scores
  (800/750 vs the 700 threshold). Fix: parameterize mock vector scores.
- New lexical-only tests needed for whatever fix is chosen.
- The invariant runner's `--composite-retrieval` flag exercises the production path.

## Reproducing Scenarios
The 4 failing scenarios from the generated batch:
- `gen-off-topic-summary-suppress`
- `gen-ambiguous-off-topic-suppress`
- `gen-suppress-single-topic-noise`
- `gen-suppress-topic-switch`

Run with:
```bash
python -m evals.generated_exploratory.invariant_runner \
    --scenario-file evals/generated_exploratory/scenarios/high_risk_batch.json \
    --composite-retrieval \
    --output-dir evals/generated_exploratory/output/offtopic_validation
```
