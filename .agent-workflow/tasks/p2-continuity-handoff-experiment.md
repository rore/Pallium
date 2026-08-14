<!-- agent-workflow:start -->
**Outcome:**
A committed, CI-self-tested measurement harness for Experiment 2 (cross-context work-continuity handoff) plus a real-provider evaluation run and committed report that answer: does a pointer+pull handoff (identified source + `source_only` search + `/source/{id}/context` expansion) beat the manual baselines (paste-a-summary / read-the-transcript) and the no-memory baseline on correctness-of-understanding and user-orchestration cost. Measurement only — no continuity mechanism.

**Target:**
`evals/` (new `continuity_handoff_benchmark.py` + `evals/continuity_handoff/` scenarios), `tests/` (deterministic self-test), `docs/reports/` (evaluation report), `roadmap/` (promote idea to an experiment-scoped feature + board move).

**Scope:**
- NEW `evals/continuity_handoff_benchmark.py` reusing `work_resumption_benchmark` scorer/compare/generate functions.
- NEW `evals/continuity_handoff/scenarios.json` (+ optional noisy variant).
- NEW `tests/test_continuity_handoff_benchmark.py` (deterministic, no live LLM).
- NEW `docs/reports/vnext-p2-continuity-handoff-experiment.md`.
- Roadmap: promote `idea-cross-context-work-continuity` to `roadmap/features/measure-cross-context-handoff-experiment.md` (experiment-scoped) + board.md move via minimap-roadmap skill; idea retained for the deferred mechanism.

**Constraints:**
- Do NOT build session correlation, `agent_ref` routing, or continuation packaging (downstream mechanism, deferred).
- Do NOT modify `evals/historical_lookup_measurement.py` or `evals/historical_lookup_judge.py` (other in-flight items own them).
- Do NOT modify `work_resumption_benchmark.py` — reuse by import; seed via a provider wrapper in the new module.
- Committed artifacts: no internal/external product names (generic mechanism language).
- Run Python only via the real CPython path with `PYTHONPATH=".local/test-env/site-packages;."`; never bare `python`/`uv venv`/`uv sync`.

**Completion criteria:**
1. New harness runs the 4 arms (no-memory / pull-backed / read-transcript / paste-summary), scores correctness via reused rubric, computes an orchestration-cost proxy, and emits results.jsonl + summary.json + report.md.
2. Deterministic self-test passes with no live LLM (stub answer + stub semantic providers), asserting arm presence, orchestration-cost ordering, pull-arm source recovery, and a multi-seed consensus winner field.
3. A real-provider run (>=3 seeds) produces genuine per-arm correctness means ± spread, orchestration-cost numbers, and a consensus winner — OR, if no credentialed provider is available at run time, the run is a clearly flagged follow-up (never faked).
4. Committed report states results and the honest realism/variance ceiling.
5. Roadmap promotion + board move landed.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:**
Architect-declared Elevated; judgment holds. All intended paths are outside `agent-workflow.yaml` guarded zones (evals/, tests/, docs/, roadmap/ are blue → redline Routine), but the deliverable produces a committed measurement claim + published report + a roadmap commitment, which warrant Elevated review. Moderate complexity: multiple new components (harness + scenarios + self-test + real run + report + roadmap move) with real-provider-availability uncertainty; single-session-feasible.

**Discovery:**
- `work_resumption_benchmark._run_scenario` (lines 157-275) already implements the comparison SHAPE: TestClient + temp DB, post `prior_events`, drain queue, then `baseline` vs `memory_backed` continuations via `_generate_continuation` (424-477), scored by `_score_continuation` (485-532), verdict by `_compare_continuations` (602-645). These + `_format_retrieval_results` (812-849), `DIMENSION_ORDER`, `CONTINUATION_SCHEMA` are importable and reused verbatim.
- Its current memory arm feeds proactive `/query/debug` results; Experiment 2 needs a PULL arm fed from `source_only=true` search + `/source/{id}/context`.
- Shipped primitives confirmed: `QueryRequest.source_only` (api/schemas.py:116); `/query` honors it (api/routes.py:432,461); `GET /source/{source_item_id}/context` (api/routes.py:672-727) returns anchor+neighbors raw turns (`before`/`after`/`max_chars`/`include_supported_memories` params), response `SourceContextResponse` (api/schemas.py:240). `source_hit` results carry `source_item_id` + `raw_rank` (api/schemas.py:147,162).
- Provider config: main `pallium.local.toml` defines `hai` (`anthropic_claude`) at `http://localhost:6655/anthropic/v1`, key `PALLIUM_HAI_API_KEY`; default use case `agent_conversation_memory` → hai/claude-sonnet-4-6. Proxy is UP (probe returned HTTP 401 = reachable, auth-gated). BUT worktree has no `pallium.local.toml`/`.env.local` and `PALLIUM_HAI_API_KEY` is not set in this session; `AppConfig.from_env` (app/config.py:284,455-462) reads both from CWD or `PALLIUM_CONFIG_FILE`/`PALLIUM_ENV_FILE`. Real run is therefore gated on the operator supplying config + key.
- Self-test pattern to mirror: `tests/test_work_resumption_benchmark.py` (StubWorkResumptionAnswerProvider keyed by Scenario ID + Branch; `TieredMemorySemanticProvider`; `build_llm_test_config`). Report to mirror: `docs/reports/vnext-perf-e2e-validation.md`.
- Scenario schema (`evals/work_resumption/scenarios.json`, 19 scenarios): has `prior_events`, `current_thread_context`, `current_query`, `target_question`, `expected_dimensions`, `must_preserve`, `forbidden_terms`, `should_memory_help`. New handoff scenarios add `handoff_summary`.

**Material assumptions:**
- A1: `source_only` search over posted `prior_events` returns `source_hit`s with resolvable `source_item_id`s under the test config. Disproof: self-test shows source_hit_count==0. Follow: fall back to feeding pull-arm context from `/source/{id}/context` seeded by evidence links, or mark pull arm inconclusive with a logged reason.
- A2: A credentialed real provider is reachable at run time. Disproof: `PALLIUM_HAI_API_KEY` unset / proxy 401 at run. Follow: emit deterministic self-test + harness only; real run + numbers become a flagged follow-up; report ships with a "PENDING real run" banner rather than fabricated numbers.
- A3: Orchestration cost is defensibly proxied by deterministic user-supplied-token count per arm. Disproof: reviewer rejects the proxy definition. Follow: revise definition before the real run (cheap; pre-run).

**Plan:**
See `## Plan` prose below (decision-complete).

**Verification plan:**
- C1/C2 → deterministic self-test `tests/test_continuity_handoff_benchmark.py` via real CPython, no live LLM.
- C1 → `python -m pytest tests/test_work_resumption_benchmark.py` still green (proves reused functions untouched).
- C3/C4 → real-provider run commands (gated on credential); report generated from run outputs.
- C5 → minimap-roadmap validation of board/feature file.

**Plan review:**
Elevated → returned to the architect (task issuer) for clean review before any code edit. This Work Record + the returned plan ARE the review input.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Branch renamed to `feat/p2-continuity-handoff-experiment`; Work Record committed before code.
- New harness `evals/continuity_handoff_benchmark.py`: four context-source arms (`no_memory`, `pull_backed`, `manual_transcript`, `manual_summary`) feeding the reused `_generate_continuation`/`_score_continuation`/`_compare_continuations` from `work_resumption_benchmark` (imported, NOT modified). Arms differ only in context source (apples-to-apples). Pull arm assembled from the actual API response surface: `source_only` `/query` → top-K source hits → `GET /source/{id}/context` (before/after=2) neighbor turns. Seeding via an in-module `_SeededCachingProvider` wrapper (per-seed prompt nonce + on-disk cache) so no edit to the reused module.
- Orchestration-cost proxy = deterministic chars/4 tokens of user-supplied context per arm (pull = query text only; manual = summary / full transcript). Consensus winner over ≥3 seeds; tie broken by lower cost.
- Discovery correction: cross-session continuity is private + container-scoped — raw turns carry `actor_ref` and public retrieval requires `actor_ref is None`, so the harness ingests + queries under private visibility (was the cause of an initial 0-hit pull arm; verified fix restores 3 hits). Assumption A1 held after this fix.
- `evals/continuity_handoff/scenarios.json`: 5 authored scenarios (4 value + 1 no-value guard), private/container-scoped, with `handoff_summary` for the paste-a-summary arm.
- Deterministic self-test `tests/test_continuity_handoff_benchmark.py` (2 tests): no live LLM; asserts 4 arms, cost ordering, pull source-recovery, tie-break-to-pull consensus, no-value guard, cache stability.
- `.gitignore`: added `evals/continuity_handoff/output/` (matches per-eval convention); run output stays local, numbers captured in the committed report.
- Real run `real-run-s3` (`claude-sonnet-4-6`, 3 seeds) executed in-process via TestClient with scratch temp DB + scratch vector index (never touched the live service/DB). Report at `docs/reports/vnext-p2-continuity-handoff-experiment.md`.
- Roadmap: promoted to `roadmap/features/measure-cross-context-handoff-experiment.md`; `idea-cross-context-work-continuity` updated to track only the deferred mechanism. `board.md` intentionally NOT edited (coordinator drives the board move post-merge).

## Evidence

- Self-test + cache-stability: `pytest tests/test_continuity_handoff_benchmark.py -m slow -n0` → 2 passed.
- Reuse-regression guard `tests/test_work_resumption_benchmark.py`: 4 pre-existing failures on this checkout, independent of this change — `work_resumption_benchmark.py` and its test are byte-identical to HEAD (empty diff), run in isolation (this change's code uninvolved), and the first failure is a committed scenario-count drift (`assert 19 == 13`) plus downstream semantic drift. Non-regression of the reused functions is additionally shown by this change's own passing self-test, which exercises those exact functions. Flagged to the coordinator.
- Real run `real-run-s3`: mean correctness no_memory 0.58 vs pull/transcript/summary 6.00; mean user-orchestration cost tokens no_memory 0 / pull 18.8 / transcript 50.2 / summary 47.6; consensus winner `pull_backed` in all 4 value scenarios (3/3 seeds); no-value guard kept `no_memory`.

## Plan

### Arms (receiving-session continuation modes)
- **A — no-memory baseline**: current-thread context only. Reuse `_generate_continuation(..., memory_backed_results=[], branch="baseline")` verbatim.
- **B — pointer+pull (Pallium P1)**: POST `/query` with `source_only=true` + `current_query.text` + `container_ref` → take top-K `source_hit`s → `GET /source/{sid}/context?before=2&after=2` per hit → assemble expanded raw turns as `source_hit`-shaped dicts → `_generate_continuation(..., branch="pull_backed")`. Models identified-source + pull-on-demand; no session-identity solving.
- **C — manual read-the-transcript**: feed ALL `prior_events` as `source_hit`-shaped dicts → `branch="manual_transcript"`.
- **D — manual paste-a-summary**: feed authored `handoff_summary` as a single context dict → `branch="manual_summary"`.

### Orchestration-cost proxy (deterministic)
Primary metric = **user-supplied context tokens** (char/4 estimate, no tokenizer dep) the orchestrator must route into the receiving session:
- A = 0 (nothing routed).
- B = tokens(`current_query.text`) only — the user identifies source + asks; Pallium pulls the raw context (agent-side, not user cost).
- C = tokens(full transcript) — user pastes/points at everything.
- D = tokens(`handoff_summary`) — user authors + pastes a summary.
Secondary (reported, not headline): agent-side pull round-trips for B (1 search + K expansions). Headline claim = B preserves correctness comparable to C/D at far lower user-orchestration cost.

### Seed / consensus policy
LLM continuation generation is the only stochastic step (rubric scorer is deterministic-lexical). Run N≥3 seeds per arm per scenario. Seeding without editing `work_resumption_benchmark.py`: a `_SeededProvider` wrapper in the new module appends a `Run variant: {seed}` nonce line to `user_prompt` before delegating to the real provider, so `_generate_continuation` is reused verbatim. Consensus = majority vote of per-seed pairwise verdicts (`_compare_continuations`, B vs each of A/C/D); report per-arm mean correctness ± spread; never gate on a single seed.

### New module + scenarios + self-test
- `evals/continuity_handoff_benchmark.py`: imports reused helpers from `work_resumption_benchmark`; runs the TestClient+temp-DB setup (mirrors `_run_scenario` 165-196), the 4 arms × N seeds, orchestration-cost proxy, consensus verdict; writes results.jsonl/summary.json/report.md.
- `evals/continuity_handoff/scenarios.json`: derived from the work-resumption cross-session cases; adds `handoff_summary`; drops injection-contract expectation fields (not relevant to this experiment).
- `tests/test_continuity_handoff_benchmark.py`: stub answer provider keyed by Scenario ID + Branch, `TieredMemorySemanticProvider`, `build_llm_test_config`, N=2 seeds; asserts 4 arms present, orchestration-cost ordering A<B<{D,C} and C≥D, pull-arm source_hit recovery >0, consensus-winner field present, report headings present. No live LLM.

### Real-provider run + report (gated)
Provider `hai` configured + proxy live, but this session lacks the credential. Run is executed by the operator with `PALLIUM_CONFIG_FILE`→main toml and `PALLIUM_HAI_API_KEY` set: `--seeds 3` over all arms → genuine numbers. Report `docs/reports/vnext-p2-continuity-handoff-experiment.md` mirrors `vnext-perf-e2e-validation.md`: question, method+arms, results table (per-arm mean correctness ± spread, orchestration-cost tokens, consensus winner), honest ceiling (authored scenarios bound realism; ~20pp judge variance → ≥3 seeds; `source_only` lexical-retrieval realism; single container / small N; proves relative arm ordering on authored scenarios, NOT real cross-context continuity or session correlation), re-run commands. If uncredentialed at run time: ship harness + self-test; report carries a PENDING banner; run becomes a flagged follow-up (no fabricated numbers).

### Roadmap promotion decision
DECISION: promote. Create `roadmap/features/measure-cross-context-handoff-experiment.md` scoped to Experiment 2 measurement only; move it on `board.md` via the minimap-roadmap skill; retain `idea-cross-context-work-continuity` for the deferred mechanism (session correlation / `agent_ref` / eager-synthesis packaging) with a pointer to the feature. One PR for this item.

## Review response (CodeRabbit, PR #23)

Addressed all 10 threads. Substantive methodology fixes + corrected re-run
(`real-run-s3-v2`): no-value guard made falsifiable (unified winner rule);
pull expansion turns de-duplicated across overlapping windows (seed the
seen-set with all ranked-hit ids up front); cost aggregate scoped to value
scenarios; headline predicates tightened to exact preservation + strict cost
reduction; explicit consensus tie policy (`_majority`, returns "tie" on a split)
used in both places; seed control replaced with fixed-prompt independent samples
via the repo `CachedLLMProvider` (per-sample subdir + model_tag identity, since
the Anthropic API exposes no seed param); self-test extended (expansion>0 +
dedup invariant + `_seed_winner`/`_majority` unit tests); report reports
mean ± spread and a generic re-run command (stripped machine path + product
name). Corrected result unchanged in direction: pull ties manual correctness
(6.00 ± 0.00) at strictly lower orchestration cost (19.75 vs 55.0/70.75), guard
held.
