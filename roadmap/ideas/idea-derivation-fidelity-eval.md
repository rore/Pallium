---
id: idea-derivation-fidelity-eval
title: Source-episode derivation coverage + fidelity evaluation
status: in-progress
priority: medium
commitment: committed
milestone: pallium-vnext-derived-eval
---

## Summary

Start from source *episodes*, not from existing derived objects, and ask two things
independent of retrieval: did a relevant episode produce a faithful derived object
**at all** (coverage / extraction), and where one exists, how faithful is it
(completeness, unsupported claims, drift, compression)? This isolates the two
derivation-side failure seams from the retrieval-side seams.

## Why

The strategy demotes derivation to a continuously-evaluated layer, and one live
hypothesis is "maybe derivation itself is lossy." Sampling *existing* derived objects
has survivorship bias: it can never see episodes from which no memory was extracted,
so it structurally overstates coverage. To attribute a DERIVED loss correctly we must
evaluate from the source side. Together with `idea-raw-derived-hybrid-shadow-eval`
(retrieval-side seams), this completes a four-seam decomposition of "why did DERIVED
lose here?" — so we invest in better derivation or simplify around raw history on
evidence, not vibes.

## In Scope (outline — can start immediately; does not depend on Phase 1)

Covers two of the four derivation seams:
- **extraction / derivation coverage:** sample source episodes; for each, did the
  pipeline produce a derived object at all? (catches the survivorship blind spot)
- **derivation fidelity:** where a derived object exists, an offline judge scores
  completeness, unsupported claims (statements not backed by any source turn), drift
  (subject/scope shifted from the source), and compression ratio

Mechanics:
- start from a sample of source episodes (with their turns), then look forward to any
  derived objects they produced — not the reverse
- report per memory type, and record derivation **schema / prompt / model version**
  so coverage/fidelity can be compared across derivation variants
- reuse the study harness pattern (selector ≠ evaluator); no production coupling

## Out of Scope

- retrieval-time RAW vs DERIVED comparison and representation-in-context quality
  (`idea-raw-derived-hybrid-shadow-eval`)
- downstream consumption (needs controlled exposure)
- building a synthetic benchmark to prove derivation superior (explicit non-goal)
- changing the derivation pipeline (this measures; fixes are separate items)

## Done When

1. A source-episode-first report exists (not derived-object-first), per memory type,
   covering extraction coverage and, where present, fidelity (completeness /
   unsupported / drift / compression).
2. We can attribute a DERIVED shadow loss to extraction/coverage vs retrieval vs
   representation, combining this with `idea-raw-derived-hybrid-shadow-eval`.
3. Coverage/fidelity are reported against the recorded derivation version.

## Notes

Continuous track. Unlike the shadow eval, this **does not depend on Phase 1** — it
can start immediately against the current corpus. Paired with
`idea-raw-derived-hybrid-shadow-eval`. Feeds strategy decision-point 3.
Execution context: `docs/designs/015-vnext-historical-work-execution.md`
(Continuous evaluation track).
