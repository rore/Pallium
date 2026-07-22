# Investigation: Does `task_trace` (agent work-trace) reduce agent cost across sessions?

**Date:** 2026-07-22
**Data:** live production DB (106 sessions with work-trace turns across 12+ repos), regime-segmented.

## Conclusion

**As built, `task_trace` targets real but small and lopsided waste, and its useful
payload is broken. Do not invest heavily in the current design.**

The feature's stated purpose is to make the agent cheaper by reusing prior discovery
(files, commands, failures) instead of re-deriving it. Measured against production data:

- **File re-discovery is real but small.** ~28% of a later session's pre-productive file
  reads target a file a prior session already read. But files are only ~22% of total
  orientation ops, so the realistic ceiling is **~6% of orientation tool calls**.
- **Command and error reuse is ~nil.** Commands almost never repeat across sessions
  (~1% recoverable); of 178 failed commands, **zero** re-failed in a later session. The
  "repeated-error avoidance" half of the feature targets waste that does not occur.
- **The valuable payload (`productive_files`/`exploratory_files`) is broken.** The
  exploratory/productive split collapses to empty on ~78% of traces (structural bug,
  persistent across all regimes — see below).
- **It has delivered 0 times in the current regime.** `task_trace` injected into 0 of 89
  eligible later sessions; its only delivery path (session-resume recency) went dark after
  mid-June. Its historical effect on cost is therefore un-measurable — it was never given
  a chance to work in production.

**The higher-value direction is structural/lexical-first retrieval**, which external
evidence supports and which also fixes a larger, cross-cutting problem (system-wide
under-injection). See Recommendation.

---

## Purpose (restated)

`task_trace` exists to reduce agent cost — tool calls, tokens, wasted error-retries — by
reusing prior discovery rather than re-deriving it. Session-resume injection is the first
delivery path, not the definition. (Spec updated 2026-07-22:
[docs/specs/2026-05-05-agent-work-trace-design.md](../specs/2026-05-05-agent-work-trace-design.md).)

---

## Findings (regime-segmented)

The live DB spans multiple config regimes. The injection-policy abstention landed
~2026-06-27 (cross-validated: audit-log inject-rate cliff at ISO week W26/W27 matches
commit `bcc1765`). All "does it work now" claims below use the current regime.

### Q1 — Is the waste real?

| Waste type | Result |
|---|---|
| Cross-session file re-discovery | **Real.** ~17-21% of explored files re-read in a later session; hub files re-read in 7-9 distinct sessions |
| Cross-session repeated command failures | **~Nil.** 178 failed commands, 0 re-failed in another session |

### Q2 — Orientation cost baseline (discovery ops before first productive action)

- Median 9 ops/session, mean 19.5, p90 58; 31% of sessions burn 21+ ops.
- **Dominated by commands** (median 6) not file reads (median 1).
- 42% of sessions never reach a productive action (pure analysis/planning).

### Q3 — Does surfacing a trace reduce cost?

- **Un-measurable from history:** `task_trace` injected into 0 of 89 eligible later sessions.
- Orientation cost does **not** decline with session order within a repo (medians 3,4,13,1,4,12),
  so the re-discovery waste is not being absorbed by anything else.

### Q4 — Recoverable-cost upper bound (counterfactual)

Of a later session's pre-productive discovery ops, fraction that hit something a prior
session already saw:

- File reads: **28% recoverable**
- Commands: **1% recoverable**
- Combined: **~7%** — and since files are ~22% of orientation ops, the real ceiling is
  single-digit %, entirely in file reads.

### Related: the split-collapse bug

`exploratory_files`/`productive_files` are empty on ~78% of traces because the split keys
on `first_write_action_at_turn`; when an Edit/Write happens in the first turn (or never),
the slice `turns[:first_write]` is empty and all files land in one bucket or none. Raw hook
capture is healthy (files_read ~47%, commands ~91%, cwd 100%) — the derivation discards it.
This is a small fix but it disables the feature's one valuable payload.

---

## External landscape (web research, 2026-07)

- **Cross-session discovery reuse for coding agents is largely unaddressed.** No system
  publishes a controlled result showing raw execution-trace recall cuts orientation cost.
  Our ~6% ceiling is not contradicted by any public evidence and is more directly relevant
  than vendors' conversational-memory benchmarks (LoCoMo/LongMemEval/BEAM).
- **Others built the same shape and did not prove cross-session benefit.** Cognee's Claude
  Code plugin captures near-identical tool traces; ContextSniper has richer action/failure
  memory but explicitly scopes it *within* a task (cross-task deferred) — independently
  echoing our "commands don't repeat across sessions" finding.
- **The evidence for reducing orientation cost comes from structural code indexes, not
  episodic trace memory.** Codebase-Memory reports 2.3 vs 4.8 tool calls and ~1K vs 10K
  tokens on structural questions; Aider's repo-map localizes a gold edit file ~70% of the
  time. A vector store of trace prose (what `task_trace` is) is the weak pattern — it
  retrieves sessions that "sound similar" but concern different modules/versions.

This converges with an independent finding from the same investigation: an underinjection
judge (Sonnet) over current-regime user turns found ~30-43% of the highest-ranked
suppressed memories would have helped, and a re-admission counterfactual showed
**lexical grounding (recovery precision ~0.53) beats routing-score thresholds (~0.42)**.
Two separate lines of evidence point at structural/lexical-first retrieval.

---

## Recommendation

1. **Cut the command/error half from scope** (including the repeated-error secondary metric
   added to the spec on 2026-07-22). It targets ~zero waste.
2. **Fix the split-collapse bug** only if delivery is also restored (the 2026-07-22
   session-start orientation repair, commit `0198a78`, is a start). It buys the single-digit
   file-read win — modest but cheap.
3. **Do not build more episodic trace-as-vector capture.** If we invest in "make the agent
   cheaper," build **structural/lexical-first retrieval**: match on filenames, symbols, and
   error strings before embeddings; distill repeated reads into navigation knowledge
   ("for auth work, start at these files") rather than replaying raw Read sequences; store
   command failures as invalidated signatures, not reusable strings.
4. **The bigger lever is system-wide under-injection**, not `task_trace`. Lexical-grounded
   re-admission of demoted candidates helps *every* memory type. Prioritize that.

## `operational_fact` (sibling feature) — retire or narrow

Current-regime content is noise: 21/23 active facts are shell directory/file probes
(`ls ~/.claude/`, `README.md`), 0 test-command or service-port facts. It never surfaces
(0 candidates in the current regime). The `directory_probe` reconnaissance verb mints a
"fact" from nearly every `ls`/`stat`/`find`. It overlaps `constraint_memory` and `CLAUDE.md`,
which already work. Retire, or narrow the predicate hard.

---

## Method notes / reproducibility

- Analysis scripts: `evals/anchor_probe/underinjection_judge.py` (added `--exclude-internal`,
  JSONL sidecar), `evals/anchor_probe/readmission_counterfactual.py`.
- Regime cutoff derived from `query_audit_log` inject-rate by ISO week, cross-checked vs git.
- Segmentation matters: analyzing the DB as one blob mixes pre/post-abstention regimes and
  the operational_fact pre/post-redesign batches; always exclude agent-internal/monitoring
  prompts (self-echoing "check progress" turns) when judging value.
