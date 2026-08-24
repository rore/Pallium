---
id: add-outdated-history-guard
title: Mark outdated historical guidance and surface its current replacement
status: in-progress
priority: high
commitment: committed
milestone: Pallium vNext Phase 1
---

## Product outcome

When Pallium gives an agent an older decision or convention, the result must not
look like current guidance after that decision has been replaced. The agent should
see when the information was recorded, that it is outdated, and what replaced it.

This is the next vNext item. It must ship before the larger real-corpus validation
run in `idea-pull-real-corpus-validation`.

## Evidence

The first real-corpus pilot was directionally positive: history won 11 of 12 paired
cases and was judged useful in 10 of 12. However, a focused stale-history probe
showed that plausible older guidance from the same lineage changed the answer to
the outdated value in 9 of 10 contaminating trials. The text already described the
guidance as earlier, so age wording alone was not a dependable guard.

Today, agent-facing history includes `occurred_at` only when the integration supplied
it. Pallium has an ingestion time but does not expose it as a fallback. Raw-history
results also do not tell the agent that a supported decision was superseded or show
its current replacement.

## In scope

- Give every agent-facing history result the best available date: the original
  event time when present, otherwise Pallium's ingestion time, with the date type
  made clear.
- When a returned passage supports a decision that has been superseded, attach a
  clear structured status and the current replacement (or a bounded pointer that
  the agent can follow).
- Make normal current-guidance use prefer the active replacement without deleting
  the older evidence.
- Keep older evidence available for explicitly historical questions such as
  "what did we use before?"
- Add compact agent guidance: outdated material is historical evidence, not current
  instruction.

## Out of scope

- Treating age alone as proof that information is wrong.
- Globally hiding or deleting the source turn.
- A general contradiction-resolution engine or freshness score.
- Reclassifying an entire source as outdated when only one supported claim was
  superseded.

## Done when

1. Search and source expansion always return the best available date, including a
   tested fallback when `occurred_at` is absent.
2. A superseded decision is clearly marked outdated and the active replacement is
   available in the same bounded agent workflow.
3. For a chain A -> B -> C, A and B are outdated and C is identified as current.
4. A normal current-guidance query does not present A or B as usable current
   instruction; an explicitly historical query can still retrieve them.
5. Old but still-active information and unrelated older information are not marked
   superseded merely because of age.
6. Mixed-source cases are safe: one superseded supported claim does not incorrectly
   mark every claim in the source as outdated.
7. Missing dates, missing replacement targets, forgotten evidence, visibility
   boundaries, duplicate hits, Unicode content, and replacement state conflicts
   have end-to-end coverage through the public MCP search and expansion tools.
8. The existing focused stale-history probe is rerun unchanged as a regression
   comparison. Outdated guidance may influence at most 1 of 10 contaminating trials,
   down from the 9-of-10 baseline, with no loss of access to explicitly requested
   historical evidence.

## Dependency and next gate

After this item ships, run `idea-pull-real-corpus-validation`. Do not claim general
product value from the 12-case pilot or from this focused regression alone.

## Implementation status — 2026-08-24

The production guard and public MCP lifecycle coverage are implemented locally. The unchanged two-scenario, five-repetition stale probe used the compact MCP renderer and adopted obsolete guidance 0/10 times, down from 9/10. Agent review of the larger run found and closed one over-broad roll-up-summary replacement bug; direct durable claims remain guarded while summary/atomic roll-ups are ignored. Merge remains pending PR closure.
