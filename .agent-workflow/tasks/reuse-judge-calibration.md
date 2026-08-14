# Work Record — reuse-judge-calibration

Task branch: `worktree-agent-a173ba3ca3341a535`
Roadmap item: `roadmap/ideas/idea-reuse-judge-calibration.md`

<!-- agent-workflow:start -->
**Outcome:**
The retrospective reuse KPI stops being presented as confident until the LLM-judge is shown to agree with a human-labelled gold set. Delivered: (1) a small committed, synthetic/generic gold fixture of hand-labelled lookups (before/after turns + retrieved history + correct rung); (2) judge-vs-gold Cohen's kappa reported alongside the existing seed-vs-seed kappa in the judge output, computed by reusing the existing judge (no new judge); (3) a documented minimum agreement threshold below which the rollup embeds a `calibration` block marking rung rates "uncalibrated" and the dashboard reuse-KPI panel surfaces that distinction; (4) an ACTUAL multi-seed (>=3) real-provider run of the judge against the gold fixture, with the measured kappa + calibrated/uncalibrated verdict recorded in a committed report section (number not fabricated). No change to the judge rubric/model or to the rollup's numerator/denominator/Wilson COMPUTATION.

**Target:**
Pallium repo, one PR. Guarded touch confined to `app/dashboard.py` + `app/dashboard.html` (read-only report wiring + panel copy — the same last-written-report pattern already used for the derivation panels; no core/persistence/contract/retrieval behaviour). Non-guarded: `evals/historical_lookup_judge.py`, `evals/historical_lookup_measurement.py`, new `evals/reuse_judge_calibration.py`, new fixture `evals/fixtures/reuse_gold/gold_lookups.json`, `tests/`, and docs (`docs/context/validation.md`, roadmap idea status).

**Scope:**
(A) FIXTURE — `evals/fixtures/reuse_gold/gold_lookups.json`: N=12 hand-labelled lookups, generic synthetic software-engineering scenarios (no product names), ~4 incorporation / 4 influence / 4 none (incl. 1-2 abandoned/empty lookups). Each record: `id`, `container_ref`, `before_turns[]`, `retrieved_history[]`, `after_turns[]`, `gold_rung`, `note`.
(B) JUDGE — `evals/historical_lookup_judge.py`: add `GOLD_KAPPA_THRESHOLD = 0.6`; add optional `gold_labels: dict[event_id -> rung|None]` param to `run_judge`; when supplied, compute judge-CONSENSUS-vs-gold kappa (reusing `cohens_kappa`), populate new `JudgeReport` fields (`gold_kappa`, `gold_kappa_n`, `calibrated`), and emit a `judge_vs_gold` block in `to_dict()` alongside the existing `cohens_kappa` block.
(C) CALIBRATION RUNNER — new `evals/reuse_judge_calibration.py`: load the fixture, seed a temp scratch DB (generalised `_seed_two_lookups`: source_items + one lookup event per record, `eligibility_n=0`), build the `event_id -> gold_rung` map, call `run_judge(gold_labels=...)`, write `.local/research/reuse_judge_calibration.json`. Reuses the judge end-to-end.
(D) ROLLUP — `evals/historical_lookup_measurement.py`: add optional `calibration: dict | None` param to `compute_reuse_rollup`, embedded verbatim (mirrors the existing `visibility_report` seam) with an empty-safe `_empty_calibration_report()` default; when `calibration["calibrated"] is False`, stamp each rung entry `"calibrated": False`. Numerator/denominator/Wilson untouched.
(E) DASHBOARD — `app/dashboard.py`: add `"reuse_judge_calibration"` -> `.local/research/reuse_judge_calibration.json` to `_EFFECTIVENESS_REPORT_PATHS` (same traversal-proof, empty-safe read). `app/dashboard.html`: reword the `hh-reuse-kpi` empty state so rung rates read as "uncalibrated" until judge-vs-gold clears the threshold, and add a minimal calibration status line (kappa / threshold / calibrated) fed from the calibration report.
(F) REPORT — record the measured real-run kappa + calibrated verdict in a new "Reuse judge calibration" subsection of `docs/context/validation.md`; flip roadmap idea status.
MAY NOT touch: the judge rubric/prompt/model, the rollup numerator/denominator/Wilson math, rung-3 (stays controlled-exposure-only), the baseline label/consensus semantics.

**Constraints:**
No judge rubric/model change; no rollup computation change (presentation flag only). Gold fixture must be synthetic + generic — NO internal/external product names. Real run must use the actual provider (>=3 seeds) with `--cache-dir .local/llm-cache` against a SCRATCH DB only; never touch the live service/DB on port 19836. Real-run number must be measured, never fabricated; if judge-vs-gold kappa < 0.6 the honest recorded outcome is "judge not yet calibrated -> rung rates uncalibrated". Tests run via the real cpython interpreter with `PYTHONPATH="C:/Dev/rore/Pallium/.local/test-env/site-packages;."` (this worktree has no `.local/test-env`; point at the MAIN repo path). `.local/` is gitignored — the committed record is the prose + number, not the raw JSON.

**Completion criteria:**
Idea "Done When" 1-3: (1) committed gold fixture exists and `run_judge` reports judge-vs-gold agreement in its output; (2) a documented threshold (0.6) gates whether rung rates present as calibrated; (3) rollup embeds a calibration block and the dashboard panel distinguishes calibrated from uncalibrated. Plus: deterministic self-test (stub judge, no live LLM) asserts the agreement math + the uncalibrated-gating logic; the gated real multi-seed run executed and its measured kappa + verdict committed to validation.md; `python -m pytest tests/ -q` green.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:**
Only guarded surface is `app/dashboard.py` (+ dashboard.html data), and only the existing read-only last-written-report presentation pattern — no core/persistence/retrieval/contract behaviour -> gray, Elevated (not High; no contract/security/persistence surface). Moderate: several coordinated components (fixture + judge extension + new runner + rollup param + dashboard + tests + a gated real provider run + committed report) in one coherent PR.

**Discovery:**
See `## Discovery`. file:line verified. Key facts: (a) the judge reads a SQLite DB — eligible sessions from `source_items`, lookup contexts from `historical_lookup_reuse_event` + `source_items` — and `run_judge` already produces `report.consensus_rung` per event (`evals/historical_lookup_judge.py:612-618`) and seed-vs-seed kappa (`:632-645`); `cohens_kappa` is a reusable pure fn (`:468-487`). (b) The test suite already seeds a scratch DB exactly the way the calibration runner needs (`tests/test_historical_lookup_judge.py:78-153` `_storage`/`_insert_turn`/`_write_lookup`/`_seed_two_lookups`, `write_historical_lookup_event_row`); the stub-judge marker pattern (`:40-70`) gives deterministic verdicts with no network. (c) `compute_reuse_rollup` already takes an optional report param embedded verbatim with an empty-safe default (`visibility_report`, `evals/historical_lookup_measurement.py:122-217`, `_empty_visibility_report:498-508`) — the exact seam for a `calibration` block; the calibrated flag is presentation, the numerators are untouched. (d) The dashboard `hh-reuse-kpi` panel (`app/dashboard.html:904-918`) is a STATIC empty-state placeholder — no JS renders live rung rates yet; effectiveness panels are fed read-only from `.local/research/*.json` via `_EFFECTIVENESS_REPORT_PATHS` + `_read_effectiveness_report` (`app/dashboard.py:37-83`), traversal-proof + empty-safe. So the dashboard change is: add a calibration report key + a minimal status line/copy — NOT build the full rung table that does not exist. (e) `build_eval_providers` (`evals/eval_common.py:593`) returns (main, judge) providers from config; `--dry-run` uses `_NullProvider` (`historical_lookup_judge.py:767-779`). (f) `HistoricalLookupReuseEventRecord` columns (`storage/sqlite_schema.py:333-350`) confirm the seed row shape; `write_historical_lookup_label_row` (`storage/sqlite.py:1271`) is the append-only label sink. (g) Auth confirmed available in this shell (`ANTHROPIC_AUTH_TOKEN` present, len 36) — the gated real run is executable here, no hand-off needed.

**Material assumptions:**
- A1: A `calibration` block + per-rung `calibrated` flag in `compute_reuse_rollup` output is PRESENTATION, not the forbidden "computation" change, because it mirrors the existing embedded `visibility_report` seam and leaves numerator/denominator/Wilson byte-identical. Disproof: architect deems any rollup-output change out of scope -> move the calibrated flag entirely to the calibration report file + dashboard, leave the rollup untouched.
- A2: Judge-CONSENSUS-vs-gold (one gold rater vs the >=3-seed consensus, over N events, categories {incorporation, influence, none}) is the right agreement metric, matching how the rollup consumes consensus. Disproof: architect prefers per-seed-vs-gold averaged -> report both, headline the consensus-vs-gold.
- A3: N=12 is the smallest fixture that yields a meaningful (non-single-flip-dominated) kappa across 3 categories. Disproof: kappa proves too unstable at 12 on the real run -> note the small-N caveat and the honest verdict stays "uncalibrated"; do NOT silently grow the fixture past the "smallest meaningful" bound without architect sign-off.
- A4: Threshold 0.6 as a project-defined minimum agreement threshold (just below the Landis & Koch "substantial" boundary of 0.61, used only as a rough reference — not a claim 0.6 IS "substantial") is the right minimum, given the repo's documented ~20pp single-seed variance + >=3-seed consensus rule (`docs/context/validation.md:96,104`). Disproof: architect wants a stricter/looser bar or a lower-CI-bound rule -> adjust the constant + justification; the gating mechanism is unchanged.
- A5: The gold fixture stays generic. Disproof: a self-test banned-substring scan hits a product name -> rewrite the offending scenario before commit.

**Plan:**
See `## Plan` (decision-complete: fixture format/size/authoring, agreement metric + threshold value + justification, calibrated-flag location, dashboard change, real-run + report).

**Verification plan:**
See `## Verification plan` — deterministic stub-judge self-test (agreement math + uncalibrated gating, no live LLM), fixture structural/generic test, rollup calibration-embed tests, then the gated real multi-seed run + committed number.

**Plan review:**
APPROVED by architect (coordinator message, 2026-08-14): "Plan APPROVED — implement it, and the real calibration run is a GO. It's decision-complete." Guardrails: keep diff to fixture + runner + judge gold-param + rollup presentation flag + minimal dashboard status line + tests + validation.md subsection (NO rung-table build, NO computation change); the committed report subsection MUST state the honesty limitations — (a) N=12 → wide kappa CI / small-N, (b) gold labels are SINGLE-AUTHOR SYNTHETIC (no second human rater, may not mirror real-lookup distributions); if measured kappa < 0.6 ship "uncalibrated" and do NOT grow/tweak the fixture to force a pass.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Discovery

(Recorded in the marker-block Discovery field above; every file:line verified during planning. No code edited.)

## Plan

**A — Gold fixture (`evals/fixtures/reuse_gold/gold_lookups.json`).**
- 12 records, generic synthetic software-engineering scenarios (config/caching/retry/schema decisions), NO product names. Distribution: 4 `incorporation`, 4 `influence`, 4 `none` (2 of the `none` are abandoned/empty lookups — `retrieved_history: []`).
- Record shape: `{ "id", "container_ref", "before_turns": [{role,content}], "retrieved_history": [text], "after_turns": [{role,content}], "gold_rung": "incorporation"|"influence"|"none", "note" }`. `gold_rung` is the hand label; `note` records the human rationale (subjectivity is made explicit, not hidden).
- Authoring: I hand-write each lookup so the correct rung is defensible — `incorporation` records contain a verbatim reuse of the retrieved history in `after_turns`; `influence` records shape the work without a verbatim quote; `none` records either surface irrelevant history or are abandoned.
- Consumability: the fixture is loaded into a temp scratch DB (source_items for retrieved history + before/after turns, one `historical_lookup_reuse_event` per record) so the REAL `run_judge` path runs against it — the "loadable into a scratch DB" option from the ticket.

**B — Judge extension (`evals/historical_lookup_judge.py`).**
- Add module constant `GOLD_KAPPA_THRESHOLD = 0.6`.
- `run_judge(..., gold_labels: dict[str, str | None] | None = None)`: after per-event consensus is computed, if `gold_labels` is given, build two aligned vectors over the sampled events — `judge = _rung_category(consensus_rung[ev])`, `gold = _rung_category(gold_labels[ev])` — and set `report.gold_kappa = cohens_kappa(judge, gold)`, `report.gold_kappa_n = len(vec)`, `report.calibrated = (gold_kappa is not None and gold_kappa >= GOLD_KAPPA_THRESHOLD)`.
- New `JudgeReport` fields (`gold_kappa`, `gold_kappa_n`, `calibrated`) default None/0/None so the non-gold path is unchanged. `to_dict()` gains a `judge_vs_gold` block `{kappa, n, threshold, calibrated, categories}` sitting alongside the existing `cohens_kappa` block.
- Rubric/prompt/model/`_judge_once` untouched.
Decision & justification: extend `run_judge` (not a parallel judge) so judge-vs-gold uses the identical prompt, provider, sampling, consensus and cache path — anything else would calibrate a different judge than the one the KPI uses.

**C — Calibration runner (new `evals/reuse_judge_calibration.py`).**
- `load_gold_fixture(path) -> list[GoldLookup]`; `seed_scratch_db(gold, db_path)` (generalised `_seed_two_lookups`: synthesise monotonic timestamps — history < before < lookup-pivot < after; one thread per record; `eligibility_n=0`); `run_calibration(...)` builds the `event_id -> gold_rung` map, calls `run_judge(gold_labels=..., write_labels=False)`, returns the report.
- CLI: `--fixture` (default the committed path), `--seeds` (>=3, default 0,1,2), `--cache-dir`, `--dry-run` (uses `_NullProvider`), `--output` (default `.local/research/reuse_judge_calibration.json`). Writes the judge report + a top-level calibration summary `{kappa, n, threshold, calibrated}`.
Decision & justification: a thin CONSUMER of the judge (imports `run_judge`, `cohens_kappa`, `GOLD_KAPPA_THRESHOLD`) — keeps `historical_lookup_judge.py` the single judge while giving the ticket its own runnable entry point.

**D — Rollup (`evals/historical_lookup_measurement.py`).**
- `compute_reuse_rollup(..., calibration: dict | None = None)`: embed `calibration` verbatim under a top-level `"calibration"` key, with `_empty_calibration_report()` (`{"calibrated": None, "note": "no calibration report"}`) as the empty-safe default so the field is always present and never hardcoded. When `calibration.get("calibrated") is False`, add `"calibrated": False` to each rung entry (presentation stamp).
- Numerator/denominator/Wilson unchanged; no loader change.

**E — Dashboard.**
- `app/dashboard.py`: add `"reuse_judge_calibration": Path(".local")/"research"/"reuse_judge_calibration.json"` to `_EFFECTIVENESS_REPORT_PATHS` (traversal-proof hardcoded path, empty-safe via `_read_effectiveness_report`).
- `app/dashboard.html`: reword the `hh-reuse-kpi` empty state so rung rates are described as UNCALIBRATED until judge-vs-gold clears the threshold; add a minimal `renderReuseCalibration()` that, when the calibration report is available, shows `judge-vs-gold kappa = X (threshold 0.60) -> calibrated / UNCALIBRATED`. No full rung table (it does not exist yet) — this is the honest calibration affordance, matching the existing derivation-panel wiring.

**F — Real run + report.**
- Execute the gated real run (see Verification), record the measured judge-vs-gold kappa, n, and calibrated verdict in a new "Reuse judge calibration" subsection of `docs/context/validation.md`. If kappa < 0.6, the committed outcome states "judge not yet calibrated -> rung rates marked uncalibrated". Flip the roadmap idea status.

## Verification plan

Real-interpreter form (from repo root):
`PYTHONPATH="C:/Dev/rore/Pallium/.local/test-env/site-packages;." "C:/Users/I347041/AppData/Roaming/uv/python/cpython-3.13-windows-x86_64-none/python.exe" -m ...`

Deterministic (no live LLM):
- `pytest tests/test_reuse_judge_calibration.py -q -n 0`:
  - fixture loads; N in [10,20]; every `gold_rung` valid; spans all 3 categories; each record has non-empty before+after turns; banned-substring scan (internal + external product names) passes.
  - stub judge + inline marker fixture with gold labels that MATCH -> `gold_kappa == 1.0`, `calibrated is True`.
  - stub judge with gold labels that MISMATCH -> `gold_kappa < 0.6`, `calibrated is False`.
  - `run_judge(gold_labels=...)` `to_dict()` carries a `judge_vs_gold` block with kappa/threshold/calibrated.
  - `GOLD_KAPPA_THRESHOLD == 0.6` (guards accidental drift).
- `pytest tests/test_historical_lookup_measurement.py -q -n 0`: new `calibration`-embed tests — `calibration={"calibrated":False}` stamps rung entries uncalibrated and leaves numerators identical to the no-calibration call; no-arg path yields the empty-safe calibration block.
- `python -m evals.historical_lookup_measurement --dry-run` and `python -m evals.historical_lookup_judge --dry-run` still succeed.
- `python -m evals.reuse_judge_calibration --dry-run` runs the fixture->scratch->judge path with `_NullProvider` (no calls) and writes a report.

Gated real run (provider; only after plan approval):
- `PALLIUM_CONFIG_FILE="C:/Dev/rore/Pallium/pallium.local.toml" PALLIUM_HAI_API_KEY="$ANTHROPIC_AUTH_TOKEN" python -m evals.reuse_judge_calibration --seeds 0,1,2 --cache-dir .local/llm-cache --output .local/research/reuse_judge_calibration.json`
- Record measured kappa/n/calibrated in `docs/context/validation.md`; scratch DB only; live service/DB (port 19836) untouched.

- Full lane: `pytest -m 'not slow' -q` green.

## Implementation

Planning committed first (commit-order predicate); WR-approval + idea->in-progress committed before code. Then, in code commits:

- **Fixture** `evals/fixtures/reuse_gold/gold_lookups.json`: 12 hand-labelled synthetic lookups (4 incorporation / 4 influence / 4 none, 2 of the none abandoned/empty), generic software-engineering scenarios, `_meta.honesty_limitations` embedded.
- **Judge** `evals/historical_lookup_judge.py`: added `GOLD_KAPPA_THRESHOLD = 0.6`; `run_judge(..., gold_labels=...)` computes judge-consensus-vs-gold kappa (reusing `cohens_kappa` + `_rung_category`), sets `JudgeReport.gold_kappa/gold_kappa_n/calibrated`, and `to_dict()` emits a `judge_vs_gold` block next to `cohens_kappa`. Rubric/prompt/model/sampling/consensus untouched.
- **Runner** new `evals/reuse_judge_calibration.py`: loads + validates the fixture, seeds a temp scratch DB (source_items + one lookup event per record, monotonic timestamps, `eligibility_n=0`, `write_labels=False`), runs the real judge with `gold_labels`, writes `.local/research/reuse_judge_calibration.json`. Thin consumer — not a second judge.
- **Rollup** `evals/historical_lookup_measurement.py`: `compute_reuse_rollup(..., calibration=...)` embeds the block verbatim with `_empty_calibration_report()` default; stamps each rung `"calibrated": False` ONLY on explicit `calibrated is False`. Numerator/denominator/Wilson untouched.
- **Dashboard** `app/dashboard.py`: `reuse_judge_calibration` added to `_EFFECTIVENESS_REPORT_PATHS` (traversal-proof, empty-safe). `app/dashboard.html`: reworded the reuse-KPI empty state to "uncalibrated until judge-vs-gold clears threshold" and added `renderReuseCalibration()` showing kappa/threshold/verdict. No rung table built (none exists yet); no computation change.
- **Tests** new `tests/test_reuse_judge_calibration.py` (10 tests): fixture structure + genericness scan, judge-vs-gold perfect-agreement->calibrated / disagreement->uncalibrated, `judge_vs_gold` block emission, no-gold path leaves calibration None, threshold constant guard, and rollup calibration embed/stamp tests (uncalibrated stamps rungs without changing numerators; calibrated does not stamp; default empty-safe).
- **Report** `docs/context/validation.md`: new "Reuse Judge Calibration" section with the measured real-run result + honesty limitations. Roadmap idea status -> in-progress.

## Evidence

Real cpython interpreter (`PYTHONPATH="C:/Dev/rore/Pallium/.local/test-env/site-packages;."`, cpython-3.13):
- `pytest tests/test_reuse_judge_calibration.py -q -n 0` -> **10 passed** (0.72s).
- `pytest tests/test_historical_lookup_judge.py tests/test_historical_lookup_measurement.py -q -n 0` -> **44 passed** (1.33s) — no regression from the judge/rollup changes.
- `python -m evals.reuse_judge_calibration --dry-run` -> loads all 12 gold lookups, `judge_vs_gold` block present (NullProvider -> kappa 0.0, plumbing only).
- **REAL calibration run** (`--seeds 0,1,2 --cache-dir .local/llm-cache`, real provider, scratch DB): **judge-vs-gold kappa = 0.50, n = 12, threshold 0.60 -> UNCALIBRATED**; seed-vs-seed kappa on the same run = 1.0; 36 labels, 0 judge failures. Honest outcome: judge not yet calibrated -> rung rates uncalibrated. Recorded in `docs/context/validation.md`.
- Full-lane `pytest -m 'not slow' -q` -> **3528 passed, 15 skipped, 2 xfailed** after updating two `tests/test_dashboard.py` key-set assertions to include the new `reuse_judge_calibration` report key (the only fallout of the new dashboard report path). Known-benign `test_config.py::test_prompt_variants_legacy_fallback_unaffected` not triggered this run.

### CodeRabbit review round (PR #24)

Addressed all 6 findings: (1) threshold reworded to "project-defined minimum agreement threshold" (kept 0.6) in judge constant + WR + validation.md; (2) `gold-influence-3` after_turns rewritten to carry only high-level direction (genuine influence, not near-verbatim incorporation); (3) `run_judge` now excludes all-failed events from the gold comparison vectors (added regression test with a provider that fails one event); (4) `compute_reuse_rollup` reads `calibrated` via a shape-tolerant extractor (flat OR the runner's nested `judge_vs_gold`), with a regression test feeding the runner's ACTUAL serialized summary; (5) runner-owned scratch DB removed via try/finally; (6) `--sample-size` forwarded to `run_calibration`. Re-run self-tests -> **57 passed**. RE-RAN real calibration on the corrected gold set (seeds 0,1,2): **judge-vs-gold kappa = 0.50, n=12, 0 failures -> UNCALIBRATED** (unchanged; the judge collapses influence->incorporation regardless of the fixture). validation.md updated.
