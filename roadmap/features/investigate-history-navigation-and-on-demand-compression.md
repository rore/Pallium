---
id: investigate-history-navigation-and-on-demand-compression
title: Investigate Session History navigation and on-demand compression
status: queued
priority: high
commitment: committed
milestone: pallium-vnext-session-history
lane: investigation
---

## Question

After the raw Session History core and its two search operations are reliable, what
is the smallest access and representation model that helps agents recover the right
work with less noise, time, and token cost?

## Time-boxed comparisons

Compare access structures:

1. Flat raw-turn search, the baseline.
2. Results grouped by exact work references or request-centered landmarks.
3. Index-first navigation: show a compact list of historical work, then open the
   selected raw evidence.

Compare representations after relevant evidence is selected:

1. Raw retrieved turns.
2. Request-specific on-demand compression.
3. Existing persistent derived memories.

On-demand compression runs only after raw selection, is temporary or explicitly
cache-bounded, and is never persisted globally without later evidence.

## Method

- Start from real Pallium search-audit data and characterize actual short agent
  queries before designing fixtures.
- Reuse the existing raw retrieval, expansion, and RAW/DERIVED/HYBRID evaluation
  seams. Do not create a production index or parallel retrieval stack for the test.
- Pre-register task/session diversity, privacy handling, model/call/token ceilings,
  early-stop gates, and the human review rubric.
- Measure candidate recovery, agent-visible precision, and downstream task effect
  separately. Also report necessary-evidence recovery, wrong-stage/harmful/
  misleading/duplicate results, index use, returned tokens, model calls and output
  tokens, search latency, and end-to-end latency.

## Out of scope

- Semantic episode inference during ingestion.
- Treating a session as one task.
- Committing to a durable index, global generated summaries, a cache, or a new
  semantic abstraction before the comparison produces evidence.
- Re-running broad paid tests when the corpus lacks independent task/session
  diversity.

## Done when

1. The study includes a flat-search control and comparable work-grouped/index-first
   arms over the same eligible evidence.
2. Raw, on-demand-compressed, and persistent-derived representations are compared at
   equal or explicitly reported token budgets.
3. Every result labels whether it measures candidate recovery, injection precision,
   or downstream task effect; retrieval or expansion alone is never called use.
4. Private corpus text remains local, every paid call stays under the preregistered
   cap, and a no-call preflight stops an underpowered run.
5. The conclusion chooses one next action: retain flat search, implement the smallest
   validated navigation aid, investigate a specific failure further, or stop.

## Dependencies

Runs after `decouple-session-history-from-derived-packages`. It reuses rather than
duplicates `idea-raw-derived-hybrid-shadow-eval`,
`idea-derivation-fidelity-eval`, and `investigate-lexical-retrieval-scaling`.
