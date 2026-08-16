# Injection vs. pull: vNext assumption validation (2026-08-16)

Data-driven validation of the vNext premise — *deprecate proactive derived-memory
injection; give the agent an on-demand raw-history pull tool* — run against a read-only
snapshot of a live memory database (8,328 source turns, 7,276 recorded query decisions,
1,292 human/agent feedback ratings). All evals ran against the snapshot copy; production
was never touched.

Container types referenced generically: a **focused single-project repo** (one codebase,
mostly one topic) and a **multi-topic monorepo container** (many parallel topics/services
sharing one container).

## Summary

The data supports the pivot, and **relocates the risk**. Proactive derived-injection is
broken (noisy, mostly absent, and low-quality when present). Raw retrieval is a better
surface. A guided agent readily pulls — so the *trigger* is not the bottleneck. The new
open risks are the **cost of probing on nearly every task** and the **unsolved retrieval
precision inside the pull** (the win depends on the agent filtering irrelevant returns,
not on better ranking).

## Findings

### 1. Injection is noise-broken, and tuning can't fix it

- Baseline injection precision **38%** (≈62% of injected memories with feedback rated
  not-relevant).
- The retrieval score **does not separate** relevant from not-relevant: relevant median
  vector score **878** vs not-relevant **877** (gap = 1). Every score-floor variant holds
  at ~38% precision (±0.3%) while shedding up to 25.7% recall. Precision cannot be
  recovered by thresholding because the ranking signal is not discriminative.

### 2. Injection is mostly absent

- Of 7,276 query decisions, only **19%** inject anything; **81% surface nothing** — 51%
  suppressed because the current thread already had the context, 29% because no relevant
  memory existed.
- The failure is two-sided by container type: the **focused repo** over-injects (~45%, and
  ~52% of those not-relevant), while the **multi-topic monorepo** is already sparse (~6%
  inject rate — the system suppresses hard there). Precision is not fixable in the first;
  coverage is near-zero in the second.

### 3. Raw retrieval beats derived memory (the payload)

- Candidate recovery on real lookups: raw-only vs derived-only recovery ≈ **16:1**
  (`neither` = 0). Raw representation recovers far more relevant candidates.
- Representation quality (LLM judge, 30 queries, 148 derived objects), scoring the derived
  object against the full raw turns: derived usability **0.08 / 1.0**, **74% flagged
  misleading**, 65% unsupported. Derived memory's only advantage is packing density (more
  small units per token budget).

### 4. The pull trigger is not the bottleneck — the agent over-probes

- Decision-agent harness with a **neutral** search prompt. Cold-framed tasks (continuation
  cues removed) still produced a **1.0** pull rate when relevant history existed.
- An over-pull control (neutral tasks with no relevant history and no "self-contained"
  anti-cues) produced a **0.75** pull rate, with searches returning non-empty results even
  when nothing was relevant.
- Interpretation: a guided agent readily — even over-eagerly — probes history on ordinary
  cold tasks. The pull model's advantage over injection is therefore **agent-in-the-loop
  filtering** (the agent evaluates returns and can discard noise), not better ranking.

## Implications

- **Deprecating proactive derived-injection is well-justified**: broken precision, mostly
  absent, low-quality representation.
- **Pull-from-raw is supported** on both retrieval quality and agent trigger behavior.
- **New make-or-break questions** (not yet measured): (a) how reliably the agent discards
  irrelevant pull returns, and the token/latency cost of probing on ~every task; (b) raw
  ranking is still non-discriminative (returns top-k regardless of true relevance) — the
  win rests entirely on the agent's filtering; (c) ~half the time the context is already
  in-thread, so the pull adds nothing there.

## Caveats

- Simulations are small (n = 4–30), synthetic, single-container, single-run — directional,
  not definitive.
- Raw's recall edge is partly **structural** (a raw turn literally contains the matched
  text; a summary matches less directly).
- The representation judge is **itself uncalibrated** — trust the *direction* (raw >
  derived), not the magnitude (0.08 usability is not a validated absolute).
- The injection-value/redundancy eval was **not completed** (it lacks a query cap and did
  not finish); it would refine, not change, the conclusion.

## Reproduction

- Injection precision/coverage: `python -m evals.injection_precision_eval --db <snapshot>`
  and SQL over `query_audit_log` / `memory_feedback`.
- Raw vs derived: `python -m evals.raw_derived_hybrid --db <snapshot> --container <ref>
  --trigger-origin all [--no-judge]`.
- Trigger behavior: `python -m evals.history_pull_decision.harness --scenarios
  evals/history_pull_decision/scenarios_cold.json` (and `scenarios_overpull_control.json`).

## Follow-ups

- `idea-measure-pull-filtering-accuracy-and-cost` — the new make-or-break: agent filtering
  accuracy on irrelevant returns + per-task probe cost.
- `fix-add-limit-to-injection-replay-simulation` — add a query cap so the injection-value
  eval is runnable.
