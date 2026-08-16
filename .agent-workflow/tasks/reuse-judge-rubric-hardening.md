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
rung-selection instruction, evidence_span requirement) + the module-docstring summary.
No change to code logic, schema, sampling, consensus rule, model, or the gold fixture.

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

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Redline verdict on the final diff is GRAY (the `.agent-workflow/tasks/*.md`
Work Record path is unclassified → defaults to gray), which maps to Elevated. The code
change itself is a blue-zone eval prompt-string edit; complexity stays Simple (one
coherent wording change + a re-run, single session).

**Discovery:**
Gold `_meta.labelling_scheme` defines incorporation as "a specific detail from
retrieved_history reappears verbatim/near-verbatim in after_turns"; the judge rubric
only said "verifiably appears" + "the strongest supportable reuse claim" and anchored
`evidence_span` to WORK AFTER alone. The definitions were genuinely different, so the
judge applied the looser one and mapped all 4 gold influence cases to incorporation
(κ=0.50). A prior cleaner gold label (#24 rewrite) did not move it → rubric, not gold.

**Material assumptions:**
- ASSUMPTION: the collapse is a rubric weakness, not a model-capability ceiling.
  DISPROVED BY: κ failing to move after the rubric alignment. ACTION IF DISPROVED:
  stop rubric edits, escalate to model/gold-set work. (Held: κ moved 0.50→0.75.)
- ASSUMPTION: aligning the judge's incorporation definition to the gold's is a
  correctness fix independent of the κ arithmetic. DISPROVED BY: the gold `_meta`
  definition being the outlier vs the measurement-contract spec. ACTION: re-derive the
  canonical definition from the spec first. (Held: gold matches the spec's ladder.)

**Plan:**
Three coordinated `JUDGE_SYSTEM_PROMPT` wording changes: (1) anchor "incorporation" to
a concrete detail from RETRIEVED HISTORY reproduced verbatim/near-verbatim in WORK
AFTER (matching the gold `_meta.labelling_scheme`); (2) replace "the strongest
supportable reuse claim" with a neutral instruction + explicit tie-break "prefer
influence unless a concrete detail from RETRIEVED HISTORY is reproduced"; (3) tighten
`evidence_span` to require a span present in BOTH RETRIEVED HISTORY and WORK AFTER
(cross-text overlap). Align the module-docstring summary to match. Stop condition: if
κ does not move, revert and escalate (do not tune wording to the 12 gold cases).

**Verification plan:**
- Rubric matches gold definition → clean-context reviewer confirms alignment + no
  logic/schema change.
- No behavior regression → `pytest tests/ -k "reuse_judge_calibration or historical_lookup"`.
- κ effect measured honestly → same-day before/after re-calibration (seeds 0,1,2,
  scratch DB; OLD via git-stash of uncommitted edits), κ recorded in Evidence with the
  necessary-not-sufficient caveat.

**Plan review:** Clean-context Explore subagent — see `## Plan review` below.

**Approvals:** Not required at this risk level (Elevated).

**Exceptions:** —

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
- CI re-classification on the final diff returned GRAY (Work Record path defaults to
  gray) → Risk raised Routine→Elevated, Work Record migrated to expanded shape, and a
  clean-context Plan review added. Implementation was already complete + verified when
  the re-classification landed; the review therefore covers the completed change.

## Evidence

Unit tests: `pytest tests/ -k "reuse_judge_calibration or historical_lookup"` →
82 passed, 3 skipped (wording change breaks nothing).

Real re-calibration, same-day before/after under identical conditions (seeds 0,1,2,
scratch DB, `.local/llm-cache`; OLD via `git stash` of the uncommitted rubric edits):

| rubric | judge-vs-gold κ | threshold_met | incorporation / influence | seed-vs-seed κ | failures |
|---|---|---|---|---|---|
| OLD | 0.50 | no  | 8 / 0 (all 4 influence collapsed up) | 1.0 | 0 |
| NEW | 0.75 | yes | 6 / 2 (2 of 4 influence recovered)   | 1.0 | 0 |

("threshold_met" is the calibration runner's `calibrated` field = `gold_kappa >=
GOLD_KAPPA_THRESHOLD`. Named "threshold_met" here deliberately: crossing the 0.60
gate is NOT the same as being truly calibrated — see the caveat below.)

**Honesty caveat (unchanged, load-bearing):** κ=0.75 on n=12 single-author synthetic
gold is *necessary-not-sufficient* — the CI is wide, and 2 of 4 influence cases still
collapse to incorporation. This PR aligns the judge's rubric to the gold's
incorporation definition (a real consistency fix) and moves κ past the project
threshold, but does NOT constitute full calibration. The real remedy remains a larger,
multi-rater gold set with a genuine second human rater (needs the user; tracked in
`idea-reuse-judge-calibration`). Rung rates must continue to carry the uncalibrated/
provisional framing until that lands.

## Plan review

Clean-context Explore subagent (read-only; read the WR, `historical_lookup_judge.py`,
the gold fixture, and `reuse_judge_calibration.py` fresh). Verdict: **no blocking
concerns** across all five review axes.

1. **Alignment correctness — OK.** Reworded rungs match the gold `_meta.labelling_scheme`
   almost word-for-word; no residual mismatch. (The terse "none" omits gold's
   "irrelevant/abandoned" clause, but that path is carried by `genuine_opportunity=false`
   forcing `rung=None`, so it still resolves — not a substantive gap.)
2. **No unintended behavior change — OK.** Diff touches only the docstring +
   `JUDGE_SYSTEM_PROMPT`. `JUDGE_SCHEMA`, `_coerce_rung`, and `evidence_span` handling
   untouched; the tightened evidence_span semantics are words-only (no code enforces them).
3. **Evidence soundness — OK.** Confirmed `providers/llm/cached.py` hashes `system_prompt`
   into the cache key, so OLD (git-stashed) and NEW get distinct keys — OLD replays cached
   verdicts, NEW is a genuine fresh generation. Same model/seeds/fixture/user-prompts
   isolates the rubric as the only variable; no cross-contamination.
4. **Honesty framing — OK.** "necessary-not-sufficient on n=12 single-author gold" caveat
   preserved across Constraints/Evidence/commit; `GOLD_KAPPA_THRESHOLD` not touched to
   manufacture a pass; no over-claim.
5. **Overfitting risk — OK.** Wording is definitional (generic "value, name, decision, or
   phrase" + principled tie-break), references no specific gold payloads. Strongest
   anti-tuning evidence: 2 of 4 influence cases STILL collapse — a rubric fit to the 12
   cases would have recovered all 4. Genuine alignment that should generalize.
