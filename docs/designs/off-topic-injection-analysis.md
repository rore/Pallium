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

Option 3 + weak spot #6 fix, combined.

**Option 3** (always compute IDF) restores discrimination in small corpora but
has two gaps:

1. **Idiom false match**: "under the weather" scores HIGH because "weather" is
   a rare corpus term. IDF correctly identifies it as important — but can't
   distinguish idiomatic usage from topical usage. IDF makes this case worse.

2. **Zero-overlap structured memory**: "let's talk about something new" has
   zero lexical overlap with any candidate, but structured memory types bypass
   the floor via unconditional injection eligibility (weak spot #6).

**Weak spot #6 fix**: structured memory should not be unconditionally
injection-eligible. If the raw retrieval score (lexical + vector) is near zero,
no memory type should be injected regardless of its structural importance. This
is a per-candidate relevance gate in `_candidate_is_injection_eligible`, not a
batch gate.

Combined, these two fixes address all observed failure classes:
- Common-word bridging ("tomorrow", "the") → Option 3 gives low IDF weight
- Zero-overlap injection → weak spot #6 fix blocks structured memory
- Idiom false match → weak spot #6 fix blocks when the only match is a single
  word, even if IDF is high (per-candidate relevance gate requires minimum
  overlap breadth, not just depth)

## Manual Testing Observations

Extended chat-lite sessions confirmed all weak spots with specific examples:

**Session 1 — Weather query gets vector DB memories:**
- "how about politics?" → injects constraint_memory about sidecar pattern (score=9)
- "how is the weather today?" → injects 3 thread_summaries about vector DBs (score 8-9)
- "i'm kind of fond of weather things" → injects interest: vector databases
- "i'm a winter kind of guy" → injects constraint_memory + vector DB thread_summary

**Session 2 — Idiom false match:**
- "i'm a bit under the weather" → injects decision about ChromaDB (score=8) +
  thread_summary about weather enthusiasm (score=18) + vector DB thread_summary
  (score=9). "weather" is rare in the corpus so IDF scores it HIGH — correct
  identification, wrong topical match.

**Session 3 — Topic change signal ignored:**
- "let's talk about something new" → injects weather thread_summary + weather
  interest + lightweight software interest. Zero topical overlap. Structured
  memory types are unconditionally injection-eligible (weak spot #6).

## What's Already Shipped That Interacts

- **IDF-weighted lexical scoring** — helps for common-word overlap but makes
  rare words (like "weather" in an idiom) score even higher
- **Personal memory cross-container blocking** — public memories with actor_ref
  set no longer leak across containers; shared memories (thread_summary, decision
  with actor_ref=null) still cross containers and cause off-topic injection
- **Interest role guard** — assistant messages can't create interest; reduces
  volume but doesn't fix off-topic injection of existing interests

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
