---
id: fix-real-corpus-memory-access-and-evaluation
title: Make historical access and real-corpus evaluation faithful
status: queued
priority: high
commitment: committed
---

## Product outcome

Before Pallium uses real activity to decide whether historical memory is valuable,
the experiment must replay what the agent actually received and explain retrieved
history well enough for the agent to use it safely. Search should spend its small
context budget on distinct, answer-bearing evidence rather than repeated discussion,
and evaluation must distinguish what was true at the original lookup time from what
is current now.

This is the next vNext item. The larger
`idea-pull-real-corpus-validation` product gate waits for it.

## Evidence

A four-case private audit covered four task shapes across three requester sessions.
A blinded reviewer preferred the history-assisted answer in all four pairs, but
manual review found clear task-level value in two and partial orientation value in
two. That is encouraging, not decision-grade.

The audit exposed measurement and retrieval defects that must be fixed before more
model spend:

- every real lookup used source expansion, while the evaluator replayed only the
  initial short search excerpts;
- lookup telemetry records results before the MCP response budget can remove them,
  and expansion telemetry omits the selected anchor, so Pallium cannot reconstruct
  the exact memory shown to the agent;
- one result page spent several positions on near-duplicate progress messages and
  pushed stronger answer-bearing evidence below the evaluator's visible window;
- the evaluator applied a replacement created after an older lookup, mixing
  "what helped then" with "what is safe today";
- rank-fusion scores were nearly flat and are not calibrated relevance confidence;
  exposing them as confidence would mislead the agent;
- replacement details and the difference between an expansion anchor and its
  chronological neighbours are too easy to overlook.

The private task text and generated answers remain local and must not be committed.

## Ordered work

1. **Truthful delivery telemetry.** Make one layer own final response selection and
   exposure recording. Lookup events record only the ordered source items actually
   delivered after response-budget trimming. Expansion events record the delivered
   anchor and neighbours with their roles.
2. **Faithful access replay.** Reconstruct the full linked access journey--search plus
   expansion--and give history/no-history arms identical agent capability and tool
   context. Report search relevance, expansion value/noise, correct use, downstream
   task effect, added context, and latency separately.
3. **Time-correct evaluation.** Support explicit `as_of_lookup` and `current_replay`
   modes. The former excludes later memories and replacements; the latter includes
   current replacements and is labelled as a present-day safety replay.
4. **Distinct result selection.** Complete the work formerly tracked by
   `idea-raw-duplicate-ingestion-and-result-diversity`: collapse exact and strong
   near-duplicates before the visible top-K while preserving source provenance and
   without deleting raw history.
5. **Compact relevance and freshness cues.** Do not present the internal fusion
   score as confidence. Prefer small interpretable fields such as match channel,
   distinctive matched terms, record time, same/different source session, and a
   reminder that current-state questions require live verification.
6. **Prominent replacement and expansion semantics.** Put current replacement
   guidance before an outdated excerpt. Clearly distinguish the search-matched
   anchor from chronological neighbours, which may be unrelated.
7. **Budget-capped rerun.** Replay the same four private cases with no automatic
   judge, at most eight answer calls, and at most 10,000 estimated input tokens.
   Expand only if the corrected pilot is informative.

## Out of scope

- A learned relevance predictor or reranker before simpler defects are measured.
- Publishing private task text, source history, generated answers, or local provider
  details.
- Repeating paid runs to increase sample size without better measurement integrity
  or task/session diversity.
- Treating retrieval or expansion by itself as downstream use or improved work.

## Done when

1. An MCP search whose response budget removes results records exactly the delivered
   IDs in delivered order; no trimmed, forgotten, invalid, or out-of-scope ID is
   recorded as exposed.
2. MCP expansion telemetry includes the delivered anchor and every delivered
   neighbour, distinguishes their roles, and records nothing removed by character,
   visibility, lifecycle, or forgotten-item gates.
3. The evaluator replays the exact delivered search and linked expansion bundle.
   Both answer arms receive the same non-memory capability/tool context, and reports
   state that they measure offline controlled downstream-task effect.
4. `as_of_lookup` excludes a replacement created after the lookup, while
   `current_replay` includes it. A direct A -> B -> C replacement chain, equal-time
   boundary, missing timestamp, and conflicting replacement all terminate safely
   and are covered end to end.
5. Exact and strong near-duplicate source items cannot occupy multiple visible
   positions. Freed positions contain the next distinct eligible results, while
   provenance retains all contributing source IDs. Similar wording with a different
   decision is not collapsed.
6. Agent-facing history stays within the existing search and expansion response
   budgets. It exposes no numeric confidence unless that value is calibrated for
   the stated meaning. Current guidance precedes outdated evidence, and expansion
   neighbours are visibly labelled as context rather than search matches.
7. Public HTTP and MCP E2E coverage includes empty, one, max, over-max, Unicode,
   missing entity, invalid scope, visibility isolation, forgotten items, duplicate
   sources, response trimming, replacement conflicts, and full
   ingest -> search -> expand -> replay -> forget lifecycle journeys.
8. The four-case rerun uses no automatic judge, no more than eight answer calls, and
   no more than 10,000 estimated input tokens. One blinded review is followed by a
   qualitative audit. At least three cases must show genuine task improvement and
   no current-replay case may adopt outdated guidance before an 8-12 case expansion
   is authorized.
9. The 8-12 case expansion reports best-evidence top-three rate, duplicate-slot
   rate, expansion usefulness/noise, correct-use rate, task effect, added tokens,
   latency, task-shape diversity, and requester-session diversity. The 20-case
   product gate remains blocked until that smaller run is informative.

## Sequencing

1. Ship truthful delivery telemetry and faithful replay together; neither is useful
   as evaluation evidence without the other.
2. Add time modes before interpreting replacement behavior.
3. Add diversity and compact presentation changes under deterministic tests.
4. Run the capped four-case replay.
5. Expand to 8-12 cases only if the replay is informative; otherwise fix the
   observed failure rather than buying more samples.
6. Return to `idea-pull-real-corpus-validation` only after this item is done.
