# correct-vnext-findings-and-sharpen-pull-experiment

Corrects two over-stated magnitudes in the just-merged findings doc (they conflict with
prior FAIR studies) and upgrades the pull-value ticket to the sharpened 4-metric +
contamination framing. Docs/roadmap only.

<!-- agent-workflow:start -->
**Outcome:**
The findings doc demotes the biased/uncalibrated magnitudes (raw 16:1 recovery; 74%
misleading) to direction-only, cross-referencing the fair prior studies (~29% misleading;
raw≈derived tied at top-5). The pull-value ticket carries the 4-metric + contamination-
danger + real-history framing.

**Target:**
Pallium — `docs/research/2026-08-16-injection-vs-pull-validation.md` + `roadmap/ideas/
idea-measure-pull-filtering-accuracy-and-cost.md`. Docs/roadmap only.

**Scope:**
Edit the findings doc's Finding #3 + caveats to defer to the fair studies; rewrite the
ticket's In Scope / Done When to the 4 measurements (pull selectivity, returned-result
precision, agent filtering, cost) + the "irrelevant result materially influences agent"
danger metric + a requirement to run on REAL history.

**Constraints:**
- No new claims beyond what the fair prior studies support; no internal/product names.
- Keep the solid results (38% precision, non-discriminative score, 81% nothing, over-pull)
  as-is — only the two biased magnitudes are demoted.

**Completion criteria:**
Doc cross-references design 006 (retrieval tie) + strategy-vnext/design 015 (~29%
misleading); ticket reflects the 4-metric framing; CI green.

**Risk:** Routine

**Complexity:** Simple

**Reason:** —

**Approach:**
Edit the two files; cross-reference `docs/designs/006-vector-retrieval-validation-report.md`
and `docs/context/strategy-vnext.md` / `docs/designs/015-vnext-historical-work-execution.md`
for the fair numbers. No code.

**Verification:**
Doc name-scan clean; cross-refs resolve; CI: agent-workflow, redline (BLUE), test lanes.

**State:** Ready to implement
<!-- agent-workflow:end -->
