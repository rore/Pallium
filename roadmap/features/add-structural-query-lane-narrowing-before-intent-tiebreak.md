---
id: add-structural-query-lane-narrowing-before-intent-tiebreak
title: Structural query lane narrowing before intent tie-break
status: in-progress
priority: high
commitment: committed
milestone: Next
lane: stabilization-foundation
---

## Summary

Move `agent_conversation_memory` query routing from phrase-derived family
control to structural lane narrowing.

The routing hot path should determine which memory lanes are structurally
eligible before family weighting runs. If exactly one lane remains strongly
eligible, Pallium should bypass family competition entirely. If multiple lanes
remain plausible, intent may be used only as a bounded tie-break hint. If
ambiguity still remains after narrowing, Pallium should abstain rather than
inject the wrong memory.

The first slice should focus on the highest-signal lanes that Pallium already
supports with shipped structure:

- `constraint_policy`
- `work_resumption`
- `evidence_trace`

This feature is an architectural correction, not another cue-table hardening
pass. It should reduce wrong-memory injection by moving routing authority from
phrase heuristics to typed structure that Pallium already owns.

## Why

Recent paraphrase and noisy-query failures exposed a structural weakness in the
current routing path:

- broad retrieval
- phrase-derived intent guess
- intent-selected layer weights
- wrong layer wins
- support gate still packages the wrong memory

That failure mode is harmful for Pallium's current product slice. A sidecar
that injects wrong memory is worse than one that abstains on ambiguous queries.

Pallium's current roadmap truth already points to a better hot path:

- cheap pre-guards
- hard scope and visibility filtering
- kind-aware filtering
- subject or workstream filtering
- typed constraint compatibility
- direct retrieval inside the narrowed set
- bounded ambiguity handling only when still unresolved

What is still missing is the routing feature that makes that staged contract
authoritative inside the current selection stack.

This feature should do that without:

- re-expanding cue lists
- turning support-threshold tuning into the main work
- adding an always-on model router

## In Scope

- add an explicit structural lane-eligibility phase before family-weight
  competition
- define a small initial lane set for the current product slice:
  - `constraint_policy`
  - `work_resumption`
  - `evidence_trace`
  - one residual recall path for cases not clearly captured by the first three;
    this residual lane must stay conservative by default, lose ties unless
    positively supported, and must not become a silent catch-all winner
- model lane eligibility with explicit internal states:
  - `excluded`
  - `plausible`
  - `strongly_eligible`
- make structural signals primary for lane eligibility, including:
  - memory kinds and lane-owned candidate shapes
  - typed constraint compatibility state
  - same-thread, same-session, and current-state signals
  - evidence-backed source-vs-memory distinctions
  - subject and workstream anchors when present
- allow query-shape or phrase signals only as weak supporting evidence during
  lane narrowing
- never allow query-shape or phrase cues alone to make a lane strongly eligible
- cap query-shape influence so it cannot outweigh structural evidence for or
  against a lane
- if exactly one lane is `strongly_eligible`:
  - bypass broad family competition
  - route directly into that lane's candidate shaping and packaging path
- if multiple lanes are `strongly_eligible`, or only `plausible` lanes remain:
  - allow intent or family inference only as a bounded tie-break hint inside
    the narrowed set
  - record whether intent was used and how it affected the result
- if ambiguity remains after bounded tie-break, or no lane is eligible:
  - abstain conservatively rather than inject the wrong memory
- keep support gating separate from lane ambiguity:
  - lane ambiguity decides whether a lane is trusted
  - support gating decides whether the best candidate inside that lane is
    strong enough to inject
- extend query/debug routing trace with lane narrowing visibility, including at
  least:
  - `eligible_lanes`
  - `excluded_lanes`
  - `lane_exclusion_reasons`
  - `selected_lane`
  - `selection_mode`
  - `intent_used`
  - `intent_effect`
  - `abstain_reason`
- add focused deterministic tests and benchmark coverage for:
  - paraphrased routing failures
  - work-resumption ambiguity
  - evidence-trace vs summary competition
  - abstention on unresolved multi-lane cases

## Out of Scope

- broad cue-list expansion
- a support-threshold tuning campaign as the main deliverable
- a mandatory LLM router on every query
- write-path redesign for new anchor extraction
- graph traversal or broader retrieval-substrate changes
- public API expansion beyond debug-trace additions needed to explain lane
  narrowing
- splitting every existing recall behavior into a fully separate lane taxonomy
  in one step

## Done When

1. Queries with clear structural lane signals no longer rely on phrase-derived
   family routing to reach the correct packaging path.
2. Single-lane cases bypass broad family competition entirely.
3. Intent or family inference is used only when more than one lane remains
   plausible after structural narrowing.
4. Query-shape signals do not independently force lane eligibility and do not
   outweigh structural evidence.
5. Residual recall stays conservative and does not win ties without positive
   support.
6. Query/debug trace shows lane eligibility, lane exclusion, selected lane,
   selection mode, whether intent was used, and why abstention happened.
7. Paraphrased routing failures decrease materially because clear structural
   cases no longer depend on cue matches.
8. Ambiguous multi-lane cases abstain conservatively rather than injecting the
   wrong memory.
9. Existing clean query-contract and routing regressions remain stable.

## Notes

Lane-narrowing rules should follow these design locks:

- structural signals are primary
- lane eligibility prefers exclusion over inclusion
- query-shape signals may strengthen or weaken an already plausible lane, but
  may not independently make a lane strongly eligible or outweigh structural
  evidence
- ambiguity abstention and low-support abstention are separate failure classes
- abstain reasons should stay explicit in trace, at minimum:
  - `lane_ambiguity`
  - `low_support_within_lane`
  - `no_lane_eligible`
- intent is a bounded tie-break hint, not the switchboard

Smallest valuable implementation slice:

1. add a structured lane-eligibility pass to the current routing module
2. carve out `constraint_policy`, `work_resumption`, and `evidence_trace` as
   explicit structural lanes
3. if exactly one lane is eligible, bypass family competition
4. if multiple lanes remain, allow intent only as a bounded tie-break
5. if ambiguity remains, abstain and trace the explicit abstain reason

Recommended sequencing relative to other roadmap work:

1. land this structural-routing correction before the live miss-capture and
   replay-promotion loop
2. move the live loop up again once captured misses are more likely to reflect
   residual ambiguity and operational drift rather than known structural router
   weaknesses
3. keep later retrieval-substrate work bounded by this structural narrowing so
   vector and hybrid retrieval do not become an unconstrained semantic fallback

Implementation defaults:

- keep this package-owned in `agent_conversation_memory`
- prefer one explicit lane helper and one explicit trace contract over
  scattering lane heuristics across multiple scoring call sites
- start with the highest-signal lanes first; do not force a full lane taxonomy
  rewrite in the first slice
- keep the residual recall path conservative so it does not become the new
  broad catch-all winner
- treat benchmark and replay traces as the acceptance gate rather than intent
  match counts alone
