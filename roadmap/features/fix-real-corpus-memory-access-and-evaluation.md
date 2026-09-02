---
id: fix-real-corpus-memory-access-and-evaluation
title: Make historical access and real-corpus evaluation faithful
status: in_progress
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

The corrected four-case current replay completed on 2026-09-02: all four pairs ran within the fixed eight-call and 10,000-estimated-input-token caps. Manual review found genuine improvement in three cases, one harmful irrelevant-history case, and no adoption of obsolete guidance; the replacement case followed the current instruction. This passes the narrow expansion gate but does not support a broad product claim. The next 8-12-case run must focus on irrelevant-history harm and best-evidence placement, not merely increase sample size.

A zero-model-call audit then replayed the same 12 historical searches across five requester sessions against an isolated database/vector snapshot. It found that all 12 searches ranked a legacy duplicate row for the active request first: the internal row ID differed, but (source_type, source_id) was identical. After excluding that validated request identity before visible top-K selection, the exact replay completed with zero failures, zero request-identity slots, zero full-content duplicate slots, and zero unknown-session slots. A primary-agent qualitative review labelled the 36 post-fix slots as 10 directly useful, 12 useful background, 10 irrelevant or potentially misleading, and four redundant; seven of 12 cases had at least one direct result. Three workflow-heavy cases found the right topic but the wrong chronological stage. These are injection-precision observations, not downstream-task-effect evidence.

The follow-up signal assessment used the same cases and no model calls. Newest-first
ranking reduced direct top-one results from five cases to four; oldest-first reduced
them to two; same-session preference changed nothing. Five of the six timestamped
wrong-stage results were created after the historical request, so most of that
failure is current-data leakage into an old-request replay, not evidence for a
production recency rule. Limiting the delivered preview to the first two results
retained all seven cases with direct evidence, reduced irrelevant/redundant slots
from 14 to six, and reduced the compact response by 26.7%. The third result remains
an offline measurement candidate; two results is the budgeted setting for the next
experiment, not yet a global product default.

The budget-capped expansion then completed eight paired cases across five requester
sessions with 16 answer calls, zero failures, no automatic judge, and 4,603
estimated input tokens. A primary-agent non-blind review preferred the history arm
in five cases, the no-history arm in two, and tied one. One apparent history win
contained the active request itself and one useful case exactly duplicated another;
after excluding both, the directional independent estimate was three helped, two
harmed, and one neutral. Both harmful cases treated old workflow text as proof of
current inbox state or completed actions. This is not a broad ROI result: it shows
that history can restore missing context, but agent-facing packaging must prevent
past records from masquerading as live state.

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
   `idea-raw-duplicate-ingestion-and-result-diversity`: collapse exact and
   normalization-equivalent duplicates before the visible top-K while preserving
   source provenance and without deleting raw history. "Normalization-equivalent"
   means equal after Unicode, case, whitespace, and punctuation normalization; it
   does not authorize fuzzy semantic matching.
5. **Compact relevance and freshness cues.** Do not present the internal fusion
   score as confidence. Prefer small interpretable fields such as match channel,
   distinctive matched terms, record time, same/different source session, and a
   reminder that current-state questions require live verification.
6. **Prominent replacement and expansion semantics.** Put current replacement
   guidance before an outdated excerpt. Clearly distinguish the search-matched
   anchor from chronological neighbours, which may be unrelated.
7. **Active-request identity exclusion.** When a lookup is linked to the current
   request, exclude every legacy row with the same canonical source identity before
   visible top-K selection and refill from the existing bounded candidate window.
8. **Wrong-stage and weak-result assessment.** Complete: simple recency and
   same-session rules do not improve this corpus, while most wrong-stage results
   did not exist at the original request time. Do not change production ranking or
   add a learned reranker from this sample.
9. **Budget-capped rerun.** Complete: eight as-of-lookup pairs used two delivered
   previews, retained the third offline, disabled the automatic judge, and stayed
   within fixed call/token caps. The clean directional estimate was three helped,
   two harmed, and one neutral across six independent uncontaminated cases.
10. **Historical-evidence boundary.** Complete in PR #96: the compact history
    contract states that recalled workflow text cannot confirm current messages,
    live checks, approvals, or completed actions, and requires live verification.
    A capped four-pair replay retained both useful controls and prevented both
    observed false live-state claims (eight answer calls; 2,489 estimated input
    tokens in the final run).

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
5. Exact and normalization-equivalent source items cannot occupy multiple visible
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
10. A lookup linked to the active request never returns another row with the same
    canonical source identity within the bounded candidate window; focused HTTP E2E
    and the fixed 12-case replay both prove refill and zero self-identity slots.
11. Before the paid expansion, deterministic evidence rejects unsupported global
    recency/session reranking and fixes the experimental delivery budget. The paid
    run cannot mix post-request sources into an as_of_lookup case.
12. The eight-case expansion reports its contaminated and duplicate cases rather
    than counting them as independent evidence. A focused follow-up must retain the
    useful controls while preventing both observed false live-state claims before
    the 20-case product gate can open.

## Sequencing

1. Ship truthful delivery telemetry and faithful replay together; neither is useful
   as evaluation evidence without the other.
2. Add time modes before interpreting replacement behavior.
3. Add diversity and compact presentation changes under deterministic tests.
4. Run the capped four-case replay.
5. Complete the eight-case as_of_lookup experiment with two delivered previews and
   the third candidate retained only for offline precision measurement.
6. Complete: add and test the historical-evidence boundary on the harmful cases
   and useful controls.
7. Return to `idea-pull-real-corpus-validation` only after this item is done.
