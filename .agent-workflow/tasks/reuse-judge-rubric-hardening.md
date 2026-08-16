# reuse-judge-rubric-hardening

Aligns the historical-lookup reuse judge's rubric with the gold set's incorporation
definition, closing the rung-1/rung-2 collapse a read-only diagnosis identified as
predominantly a rubric/prompt weakness.

<!-- agent-workflow:start -->
**Outcome:**
The reuse judge's `JUDGE_SYSTEM_PROMPT` applies the SAME incorporation definition
the gold fixture uses — a concrete detail from RETRIEVED HISTORY reproduced
verbatim/near-verbatim in WORK AFTER — so influence cases stop riding up to
incorporation. Re-calibration is re-run and its κ reported honestly (provisional).

**Target:**
Pallium — `evals/historical_lookup_judge.py` (offline shadow eval only; no runtime path).

**Scope:**
`JUDGE_SYSTEM_PROMPT` wording in `evals/historical_lookup_judge.py` (rung definitions,
rung-selection instruction, evidence_span requirement). No change to code logic,
schema, sampling, consensus rule, model, or the gold fixture.

**Constraints:**
- No change to `JUDGE_SCHEMA`, `run_judge` logic, consensus, or the gold fixture.
- No product/internal names in committed text.
- Do NOT present a resulting κ≥0.6 as "calibrated" — on n=12 single-author gold it
  is necessary-not-sufficient; keep the existing honesty caveats intact.
- Offline eval only — never touches injection/retrieval runtime behavior.

**Completion criteria:**
Judge rubric anchors incorporation to a reproduced RETRIEVED-HISTORY span + a tie-break
preferring influence absent such a span; `evals/reuse_judge_calibration.py` re-run
(seeds 0,1,2) with κ reported; existing judge tests green.

**Risk:** Routine

**Complexity:** Simple

**Reason:** —

**Approach:**
Three coordinated `JUDGE_SYSTEM_PROMPT` wording changes: (1) anchor "incorporation"
to a concrete detail from RETRIEVED HISTORY reproduced verbatim/near-verbatim in
WORK AFTER (matching the gold `_meta.labelling_scheme`); (2) replace "the strongest
supportable reuse claim" with a neutral instruction + explicit tie-break "prefer
influence unless a concrete detail from RETRIEVED HISTORY is reproduced"; (3) tighten
`evidence_span` to require a span that appears in BOTH RETRIEVED HISTORY and WORK
AFTER (cross-text overlap), not just any WORK-AFTER quote.

**Verification:**
`python -m pytest tests/ -k "reuse_judge_calibration or historical_lookup" -x -q`;
real re-calibration run `python -m evals.reuse_judge_calibration --seeds 0,1,2`
(scratch DB) with before/after κ recorded in Evidence. CI: test(3.12/3.13),
agent-workflow, redline.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Diagnosis (read-only subagent, pre-compaction): the rung-1/rung-2 collapse is
  predominantly a rubric weakness. The judge's incorporation definition has no
  span-from-history requirement (line ~87-89), "the strongest supportable reuse
  claim" (line ~86) biases upward, and `evidence_span` anchors only to WORK AFTER
  (line ~92-94, no cross-text overlap). The gold `_meta.labelling_scheme` defines
  incorporation as "a specific detail from retrieved_history reappears
  verbatim/near-verbatim in after_turns" — a stricter test the rubric never stated.
  All 4 gold influence cases map to incorporation (κ=0.50). A prior cleaner gold
  label (#24 rewrite) did not move it → rubric, not gold.
- Applied 3 coordinated `JUDGE_SYSTEM_PROMPT` wording changes (rung selection now
  neutral + tie-break preferring influence; incorporation anchored to a reproduced
  RETRIEVED-HISTORY detail; evidence_span must overlap BOTH blocks). Also aligned
  the module-docstring summary. No code/schema/logic change.

## Evidence

Unit tests: `pytest tests/ -k "reuse_judge_calibration or historical_lookup"` →
82 passed, 3 skipped (wording change breaks nothing).

Real re-calibration, same-day before/after under identical conditions (seeds 0,1,2,
scratch DB, `.local/llm-cache`; OLD via `git stash` of the uncommitted rubric edits):

| rubric | judge-vs-gold κ | calibrated | incorporation / influence | seed-vs-seed κ | failures |
|---|---|---|---|---|---|
| OLD | 0.50 | False | 8 / 0 (all 4 influence collapsed up) | 1.0 | 0 |
| NEW | 0.75 | True  | 6 / 2 (2 of 4 influence recovered)   | 1.0 | 0 |

**Honesty caveat (unchanged, load-bearing):** κ=0.75 on n=12 single-author synthetic
gold is *necessary-not-sufficient* — the CI is wide, and 2 of 4 influence cases still
collapse to incorporation. This PR aligns the judge's rubric to the gold's
incorporation definition (a real consistency fix) and moves κ past the project
threshold, but does NOT constitute full calibration. The real remedy remains a larger,
multi-rater gold set with a genuine second human rater (needs the user; tracked in
`idea-reuse-judge-calibration`). Rung rates must continue to carry the uncalibrated/
provisional framing until that lands.
