---
id: add-robust-query-family-inference-beyond-phrase-cues
title: Robust query-family inference beyond phrase cues
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Reduce `agent_conversation_memory`'s dependence on hardcoded phrase cues so
Pallium can add value for messy real interactions, paraphrases, and indirect
continuation questions rather than only for queries that happen to match
explicit cue tables.

This feature should harden query-family inference and final routing by using
more of the information Pallium already has:

- retrieved candidate shape
- memory-kind competition
- evidence and rationale presence
- freshness and scope signals
- benchmarked paraphrase behavior

The goal is not to remove all deterministic routing hints. The goal is to make
phrase cues a narrow precision-biased signal instead of the hidden foundation of
real interaction quality.

## Why

The current hardening work made Pallium materially better for live downstream
interaction, but query-family routing still leans on hardcoded cue lists such
as investigative or broad-recall phrases.

Those cues are useful scaffolding because they are:

- cheap
- debuggable
- easy to regression-test

They are still not enough for real interaction quality.

Real conversations will include:

- paraphrases of known question shapes
- indirect requests that imply continuation without saying it cleanly
- mixed-intent questions
- broad wording with sharp retrieved evidence
- sharp wording with only weak or stale candidates

If Pallium depends too heavily on cue tables, it will appear to work in authored
scenarios while missing real interaction value. That would break the north-star
use cases around architecture recall, investigation continuity, resumed work,
and thin-agent memory decisions.

So Pallium needs an explicit routing-hardening slice that moves it from:

- phrase-driven query-family selection

toward:

- query plus candidate evidence shaping
- paraphrase-robust routing behavior
- benchmark-proven generalization beyond literal cue text

## In Scope

- treat hardcoded query cues as one routing signal among others, not as the
  primary source of truth for query-family selection
- add a candidate-aware query-family inference layer for
  `agent_conversation_memory` that can use at least:
  - retrieved candidate kinds
  - candidate score distribution
  - presence of rationale/evidence fields
  - freshness and same-thread signals
  - whether sharp lower-level memory exists in scope
- harden routing for the highest-value query families first:
  - broad recurring recall
  - investigative conclusion
  - work resumption
  - evidence trace
  - same-thread no-value continuation
- ensure broad recurring recall can still succeed on paraphrased historical
  conclusion questions without depending on exact cue overlap
- ensure investigative routing is not triggered only by literal investigative
  words when the retrieved candidates clearly indicate prior investigation
  memory
- ensure resumed-work routing can be pulled by strong `task_checkpoint` /
  blocker / next-step / progress candidate shape even when the user phrasing is
  vague
- add one explicit routing-score or routing-feature trace in `/query/debug` so
  it is explainable why a query family was chosen beyond "matched phrase X"
- add benchmark-driven paraphrase and indirect-query coverage for routing
  decisions, including:
  - indirect historical conclusion prompts
  - indirect continuation prompts
  - vague resumed-work prompts
  - messy wording around exact evidence follow-up
- prefer deterministic feature scoring first over immediately introducing a new
  opaque learned or LLM-only routing step
- if a learned or LLM-assisted routing helper is still needed later, make this
  feature establish the benchmark and trace shape it must satisfy rather than
  shipping prompt magic first
- keep routing package-owned inside `agent_conversation_memory`; generic core
  layers should continue to carry mechanical runtime context and candidate data,
  not semantic policy

## Out of Scope

- removing all phrase cues entirely
- global contradiction resolution across all memory
- replacing benchmark-driven routing hardening with one prompt-only router
- moving routing policy back into downstream agents
- broad retrieval architecture changes such as vector indexes or hybrid fusion
- full natural-language understanding claims beyond what the benchmark can prove

## Done When

1. Pallium can route the main query families correctly for a meaningful set of
   paraphrased and indirect real-interaction question shapes, not only exact
   cue matches.
2. Query-family decisions are materially influenced by candidate evidence shape
   and sharp-memory competition, not only by hardcoded phrase tables.
3. Broad recurring recall, investigative conclusion, work resumption, and
   evidence-trace behavior all have regression coverage for paraphrases and
   indirect wording.
4. `/query/debug` can explain routing-family choice with candidate-aware trace,
   not only literal cue matches.
5. Routing quality for real interaction phrasing improves without pushing local
   semantic compensation back into the downstream agent.
6. This feature leaves phrase cues as bounded high-precision hints rather than
   the main source of real interaction success.

## Notes

Recommended sequencing:

1. land the agent memory-decision benchmark program first so routing misses are
   measured against the real north-star use cases
2. then land this routing-hardening slice so Pallium improves beyond literal
   cue matches before broader public-benchmark and live-miss work expands
3. after that, use the external pressure pack and live miss-capture loop to
   keep routing honest against fresh real and public phrasing

Implementation defaults:

- prefer candidate-aware deterministic routing features before optional
  LLM-assisted routing
- benchmark and debug trace should be the gate for any future learned router
- do not expand cue tables endlessly as the main response to new phrasing
- every newly discovered real-phrasing miss should become either a benchmark
  case or a replay case, not just one more ad hoc cue addition
