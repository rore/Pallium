# Interest Type Deprecation Analysis

## Summary

Data-driven investigation of the `interest` memory type shows it provides near-zero value in production while consuming extraction resources. This document presents the evidence and recommends deprecating implicit interest extraction in favor of explicit ingest and thread summaries.

## Evidence

### Extraction Quality: 14% Precision

A labeled corpus of all 72 interest memories in the production DB was built and evaluated against the production model (Claude Sonnet via v8b prompt).

| Metric | Value |
|--------|-------|
| Total interest memories | 72 |
| Genuinely useful (labeled "good") | 6 (8%) |
| Noise (labeled "bad") | 66 (92%) |
| Production model precision | 11.4% (5 TP, 39 FP on full corpus) |
| Production model recall | 83.3% (5/6 good items detected) |

**Bad extraction patterns:**
- Task instructions misclassified as interests: 25 items (38% of bad)
- Active work topics in current session: 17 items (26% of bad)
- Questions answered in same session: 16 items (24% of bad)
- IDE events triggering extraction: 4 items (6% of bad)

### Injection Rate: 0.9%

Interest memories are almost never surfaced to the agent:

| Metric | Value |
|--------|-------|
| Active interest memories in DB | 69 |
| Total injecting queries | 346 |
| Queries that included an interest block | 3 |
| Injection rate | 0.9% |
| Feedback ratings received | 2 (both "relevant", but sample too small) |

The routing system assigns interest weight 50 (lowest of all types), so they are deprioritized against decisions (130-230), constraints (120-245), and investigation outcomes (130-235).

### Thread-Level Test: Interest Dissolves Into Main Topic

When the extraction is moved from per-item to thread level (giving the LLM full thread context), interests collapse into the thread's main topic:

- **Short threads** (the user's whole thread IS the exploration): thread-level correctly identifies it as main topic, not a tangential interest
- **Long threads** (interest mentioned in passing): the interest gets absorbed into the broader thread description
- **Result**: thread-level has perfect precision (0 FP) but near-zero recall

This reveals that "interest" as a per-item extraction is trying to solve a retrieval problem, not an extraction problem.

### What the 6 Good Interests Share

The genuinely useful interest items share characteristics:
- Forward-looking language ("I'm thinking that in the future...", "I thought of extending...")
- Topics clearly NOT the current thread's active work
- Would be useful if recalled in a completely different context
- Come from shorter threads (avg ~30 items vs ~90 for bad interests)

But 5 of 6 would be captured by a decent thread summary anyway. The 6th (Copilot integration) literally IS the whole thread — a thread summary captures it naturally.

## Root Cause

The interest definition is semantic ("user signals future attention on a subject") which the LLM interprets too broadly. Any topic the user mentions in a forward-looking way qualifies, including:
- Task instructions ("investigate X" → user "cares about" X)
- Questions ("how do we handle Y?" → user is "interested in" Y)
- Active design discussion → user shows "future attention" on the topic

Tightening the definition to require specific language patterns would violate the no-language-cues principle (must work multilingual). Structural approaches (thread context, position filters) produce high precision but kill recall.

## Two Cases Hidden Under "Interest"

1. **Explicit "remember this later"** — the user consciously flags something for future reference. This is unambiguous and should be handled by explicit ingest (the planned `note` memory type via `pallium_ingest`).

2. **Implicit forward-looking curiosity** — the user muses about something without explicitly asking to remember it. This is what per-item extraction tries to detect, and it fails at 14% precision. Thread summaries + cross-thread retrieval already handle this case: if the user discussed Copilot in a thread, the thread summary captures it, and retrieval surfaces it when they mention Copilot again.

## Recommendation

1. **Deprecate implicit interest extraction** — remove `interest` from the per-item extraction prompt (`candidate_type` options). Stop producing new interest memories.

2. **Handle explicit "remember this" via `note` type** — when the user explicitly calls `pallium_ingest` or says "remember this", store it faithfully as a `note` (design doc: `docs/specs/2026-05-04-note-memory-type.md`).

3. **Rely on thread summaries for implicit recall** — thread summaries already capture "what was discussed" including tangential topics. Cross-thread retrieval can surface these when relevant.

4. **Existing interest memories** — leave them in the DB with current lifecycle. They'll naturally age out or be superseded. No migration needed.

## Cost Savings

Removing interest from the extraction prompt:
- Eliminates ~69 active low-value memory objects from retrieval candidates
- Reduces prompt complexity (fewer types to classify = fewer misclassification modes)
- No additional LLM calls saved (interest is extracted in the same single-prompt call as other types), but reduces false-positive noise in the retrieval pool

## Eval Artifacts

- `evals/interest_quality_corpus.jsonl` — 72 labeled interest items with ground truth
- `evals/interest_quality_eval.py` — runner for testing extraction prompt variants
- `evals/extraction_quality_corpus.jsonl` — 459 multi-type rated items for broader extraction quality work
