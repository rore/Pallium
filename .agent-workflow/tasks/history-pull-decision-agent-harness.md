# history-pull-decision-agent-harness

Work Record for the decision-making agent harness that measures unprompted
history-pull (non-circular Experiment 1). Roadmap idea:
`roadmap/ideas/idea-history-pull-decision-agent-harness.md`. Design gate:
`docs/designs/015-vnext-historical-work-execution.md` Phase 1 / decision-point 1.

<!-- agent-workflow:start -->
**Outcome:**
A new, rerunnable eval harness under `evals/` in which an LLM agent — given the
history-search and source-expansion tools and a task + prior turns — DECIDES ON
ITS OWN whether to pull prior history. Agent-chosen pulls flow through the real
service so funnel events persist; the existing rollup + judge (consumed as
libraries) turn them into a simulated lookup rate, unprompted-pull rate,
lookup->useful-result rate, and the three reuse rungs (kappa + Wilson). Ships
with a deterministic no-LLM self-test AND a committed evaluation report from a
real multi-seed run (or a clearly-flagged follow-up if no provider key is
available at run time).

**Target:**
New files only: `evals/history_pull_decision/` (harness + scenarios),
`tests/test_history_pull_decision_harness.py`, and
`docs/reports/history-pull-decision-harness-validation.md`. Consumes existing
`evals/historical_lookup_measurement.py` + `evals/historical_lookup_judge.py`
and `app/agent_simulation_http.py` as libraries.

**Scope:**
- New decision-agent that models `pallium_search_history` / `pallium_expand_source`
  as a JSON decision protocol over `LLMProvider.generate_json` (provider-agnostic,
  mirrors `ThinAgentModel` + the judge — not native tool-use).
- New minimal scenario asset (task + seedable prior turns + optional opportunity
  tag), mixing history-relevant and history-irrelevant tasks.
- Real-provider run path (via `evals.eval_common.build_eval_providers`) AND a
  deterministic scripted-stub path (`--dry-run`) for CI.
- In-process scratch service (scratch SQLite + `historical_lookup_funnel=True`,
  mirroring `scripts/live_funnel_smoke.build_scratch_config`) that the harness
  seeds with prior turns and drives via `POST /query {source_only,agent_pull}` +
  `GET /source/{id}/context?parent_lookup_id=`.
- Multi-seed real run + committed evaluation report.

**Constraints:**
- Do NOT modify `evals/work_resumption_benchmark.py` or
  `evals/historical_lookup_measurement.py` (parallel in-flight items own them).
- Do NOT reimplement the rollup or the reuse-ladder judge — import them.
- No production retrieval/injection behavior change; no touch to guarded paths
  (`api/ app/ capabilities/ core/ providers/ redaction/ retrieval/ semantic/
  storage/`) — new eval + test + report only.
- Windows: never bare `python`/`uv venv`; run via the real CPython path with
  `PYTHONPATH`.
- Committed artifacts: generic mechanism language, no internal/external product
  names.
- Never write to the installed service / real KPI DB — scratch DB only.

**Completion criteria:**
1. `--dry-run` self-test drives a full scenario with the scripted stub (no
   network), persists a lookup event + a parent-linked expansion event to a
   scratch DB, and produces a non-crashing metrics rollup.
2. `pytest tests/test_history_pull_decision_harness.py` green on the real
   interpreter, no live LLM.
3. Real multi-seed (>=3) run produces genuine lookup / unprompted-pull /
   lookup->useful numbers + reuse-ladder rungs with kappa + Wilson — OR a
   clearly-flagged follow-up when no provider key is resolvable at run time.
4. `docs/reports/history-pull-decision-harness-validation.md` written from the
   run, with an explicit honesty/ceiling section (proxy vs live gate; authored-
   scenario realism ceiling; single-seed softness).

**Risk:** Elevated

**Complexity:** Moderate

**Reason:**
Directive from the architect fixes this as Elevated and pre-code review is
required. Judgment concurs: although the code lands only in non-guarded `evals/`
+ `docs/` (redline would read blue), the harness (a) drives the real service
write path so funnel events persist, and (b) spends real LLM calls at multi-seed
volume — behavior/cost surfaces that warrant Elevated. Moderate complexity:
several new components (decision agent, scenario asset, scratch-service wiring,
stub path, real run, report) but one repo, one delivery unit.

**Discovery:**
- The pull tools map to concrete HTTP already proven by
  `scripts/live_funnel_smoke.py`: `POST /query {source_only:true,
  trigger_origin:"agent_pull"}` returns `lookup_event_id` (persisted
  unconditionally in `service.query`); `GET /source/{id}/context?
  parent_lookup_id=<id>` persists the chained expansion event
  (`api/routes.py:415-471, 672-727`).
- `app/agent_simulation_model.ThinAgentModel` only drafts from proactively-
  injected blocks via `query_debug` and never calls the pull tools — confirms
  the decision-agent is net-new (idea file lines 26-30).
- Provider wiring: `evals.eval_common.build_eval_providers(config, ...)` resolves
  the default package (`hai` / `claude-sonnet-4-6`) from `AppConfig.from_env()`
  and optionally wraps with `CachedLLMProvider`. The judge already uses this and
  a `_NullProvider` `--dry-run` stub (`evals/historical_lookup_judge.py:732-743,
  767-780`) — the exact pattern to mirror.
- Rollup + judge are import-ready: `compute_reuse_rollup`,
  `load_events_from_storage` (`historical_lookup_measurement.py`) and `run_judge`
  (`historical_lookup_judge.py`, seeds>=3 enforced, Wilson + Cohen's kappa built
  in).
- Eligibility denominator defaults to 50 prior-indexed turns/container; a
  `--eligibility-n` knob (low, e.g. 1-2) lets small scenarios be eligible.
- Scratch-service recipe exists: `build_scratch_config` +
  `ScratchServer` + `HarnessHttpClient` (`agent_simulation_http.py`).

**Material assumptions:**
- ASSUMPTION: a real LLM provider is usable for the eval run. EVIDENCE FOR:
  `hai` (anthropic_claude, `claude-sonnet-4-6`) is configured in
  `pallium.local.toml`; its proxy at `localhost:6655` is reachable (HTTP 401 =
  up, needs auth). EVIDENCE AGAINST / DISPROVES: `PALLIUM_HAI_API_KEY` is NOT in
  this agent's environment and no `.env.local` exists in the worktree or main
  repo, so `AppConfig` resolves an empty key and real calls would 401 from THIS
  environment. ACTION IF DISPROVED AT RUN TIME: do not fake — run the real eval
  only where the key is resolvable (the maintainer's normal shell), else record
  the run as a flagged follow-up in the report and ship the harness + stub
  self-test + zero/None-rung rollup. The deterministic stub path is kept
  regardless.
- ASSUMPTION: `LLMProvider.generate_json` is the right seam (not native
  tool-use). EVIDENCE: every existing agent/judge uses it. DISPROVES: a provider
  that only supports native tools — none configured. ACTION: n/a.

**Plan:**
See `## Plan` prose below (decision-complete).

**Verification plan:**
See `## Verification` prose below.

**Plan review:**
Elevated → clean-context review satisfied by the architect's own pre-code review
of this plan (the reviewing party has no context from the planning turn's
drafting). Redline to confirm blue/gray at implement-time authorization; scope is
new `evals/` + `tests/` + `docs/reports/` only.

**Approvals:**
Not required at this risk level (Elevated). Implementation is gated on the
architect's authorization of this plan.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

New harness, all under non-guarded trees (no guarded-path edits):
- `evals/history_pull_decision/scenarios.json` — 7 authored scenarios (5 with
  relevant history, 2 self-contained; mix of user-directed / undirected).
- `evals/history_pull_decision/agent.py` — `DecisionAgent` (JSON decision
  protocol over `LLMProvider.generate_json`) + `ScriptedDecisionProvider` stub.
- `evals/history_pull_decision/harness.py` — `InProcessService` (TestClient over
  a scratch SQLite DB, stubbed extraction LLM, no bound port), orchestration,
  behavioural metrics, CLI (`--dry-run`, `--seeds`, `--cache-dir`, `--db`,
  `--keep-db`, `--output`).
- `tests/test_history_pull_decision_harness.py` — 6 deterministic tests.
- `docs/reports/history-pull-decision-harness-validation.md` — real-run report.

Decision log:
- Service driven in-process via `TestClient` (no bound port) instead of a scratch
  uvicorn server on :19942. Rationale in the report §6: binds no port, so the
  live service/DB is unreachable by construction (stronger isolation), and avoids
  Windows uvicorn-thread teardown fragility. Flagged as a deliberate deviation
  for the architect.
- Service extraction LLM stubbed (`TieredMemorySemanticProvider`); only the agent
  decisions + reuse judge use the real provider. Source-only retrieval is
  extraction-independent, so the measured path is unaffected.
- `--eligibility-n` defaulted low (1) so small scenarios are eligible without 50
  seeded prior turns.

## Evidence

- Self-test: `pytest tests/test_history_pull_decision_harness.py` → **6 passed**
  (real interpreter, no live LLM).
- `--dry-run` harness: clean exit; scripted chain persists lookup + linked
  expansion; lookup_rate=1.0.
- REAL run (seeds 0,1,2; 7 scenarios; 21 trials; 0 errors): lookup_rate 0.714,
  unprompted-pull 0.60, opportunity-pull 1.00, no-opportunity-pull 0.00,
  lookup→non-empty 1.00.
- Reuse judge (3 rater seeds over 15 lookups): 15/15 genuine, kappa 1.0,
  incorporation 40.0% [19.8, 64.3], 0 failures.
- Eligibility rollup (eligibility_n=1): 21 eligible / 15 events; rung-1 28.6 per
  100 eligible [13.8, 50.0]; **visibility violations = 0** (72 exposed ids
  checked). Artifacts under `.local/hpd/` (gitignored).
- Honest finding recorded in the report: the judge labels all 15 lookups
  user_directed while 9 were on tag-undirected tasks — soft convention cues read
  as user-directed; the unprompted signal needs cleaner scenarios + rubric.

## Plan

Decision-complete steps (planning only — no code yet; awaiting architect authorization):

1. **Scenario asset** — `evals/history_pull_decision/scenarios.json`. Minimal
   shape per scenario: `{id, prior_turns:[{role,content}], current_task,
   user_directed:bool, opportunity:bool}`. 6-8 scenarios, deliberately mixing
   history-relevant (opportunity=true) and history-irrelevant (opportunity=false)
   tasks, and user-directed vs not, so unprompted-pull rate is meaningful (the
   agent must sometimes correctly decline). Honest note in the report: authored
   scenarios bound realism. Toolbox checked (`validation.md` Eval Toolbox): no
   existing asset carries "task + seedable prior history + free pull decision";
   `work_resumption` is nearest but off-limits and scripts its own pulls — new
   asset justified.

2. **Decision agent** — `evals/history_pull_decision/agent.py`. A `DecisionAgent`
   prompted with a description of two tools (`pallium_search_history`,
   `pallium_expand_source`) and asked to return, via `generate_json`, a stepwise
   JSON decision: (a) search? + query text; (b) after results, expand? + which
   hit; (c) final answer. Decisions are the model's own — pulls are agent-chosen,
   not scripted (non-circularity). Provider-agnostic over `LLMProvider`.

3. **Scratch service + pull execution** — `evals/history_pull_decision/harness.py`.
   Build a scratch app (`build_scratch_config` clone: scratch SQLite + disabled
   vector or onnx, `ObservabilityConfig(historical_lookup_funnel=True)`), seed
   each scenario's `prior_turns` via `POST /items` (await processing), then run
   the agent. When the agent chooses to search, execute `POST /query
   {source_only:true, trigger_origin:"agent_pull", ...}` (persists the lookup
   event, returns `lookup_event_id`); when it expands, `GET /source/{id}/context?
   parent_lookup_id=<lookup_event_id>` (persists the linked expansion event).
   Extend `HarnessHttpClient` with `search_history()` + `expand_source()` helpers
   (new methods, additive). Configurable `--eligibility-n` (default low) so
   scenarios are eligible without 50 seeded turns.

4. **Provider wiring** — real path via `build_eval_providers(config,
   cache_dir=..., no_eval_cache=...)` (default `hai`/`claude-sonnet-4-6` from
   `AppConfig.from_env()`); stub path `_ScriptedDecisionProvider` returning canned
   per-scenario decisions with no network, selected by `--dry-run`. Mirrors the
   judge's `_NullProvider` gate exactly.

5. **Metrics + downstream libraries** — compute lookup rate (scenarios where the
   agent searched), unprompted-pull rate (searched among non-user-directed
   scenarios), lookup->useful-result (of lookups, judge genuine_opportunity /
   rung>=incorporation). Feed persisted events to `run_judge(scratch_db,
   provider, seeds=[..>=3])` (writes labels; Wilson + kappa), then
   `load_events_from_storage` + `compute_reuse_rollup` for the three-rung rollup.
   Emit a JSON report artifact.

6. **Real multi-seed run + committed report** — run harness (real provider) over
   scenarios × >=3 seeds, then judge × >=3 rater seeds, roll up, and write
   `docs/reports/history-pull-decision-harness-validation.md` (same measure-and-
   flag pattern as `vnext-perf-e2e-validation.md`) with genuine numbers, kappa,
   Wilson bands, re-run commands, and an explicit honesty/ceiling section. Gated
   on `PALLIUM_HAI_API_KEY` resolving at run time; else flagged follow-up, never
   faked.

Stop conditions: if the scratch service cannot persist a lookup event in the
stub path, stop (funnel-wiring assumption failed). If no provider key at run
time, stop the real run and flag it — do not fabricate numbers.

## Verification

Deterministic self-test (no live LLM), on the real interpreter:

- `pytest tests/test_history_pull_decision_harness.py -x -q` — unit: scenario
  loader, decision-protocol parser, scripted-stub agent; integration: full
  `--dry-run` scenario against an in-process scratch DB (low `--eligibility-n`)
  asserting (i) a `historical_lookup_reuse_event` lookup row persisted, (ii) an
  expansion row whose `parent_lookup_id` links the lookup, (iii)
  `compute_reuse_rollup(load_events_from_storage(scratch_db, ...))` returns a
  well-formed rollup, (iv) metrics dict shape. Judge wiring smoke via
  `run_judge(..., provider=_NullProvider(), write_labels=False)`.
- `python -m evals.history_pull_decision.harness --dry-run` — end-to-end stub
  run prints the metrics rollup, no network.

Real run (gated on key availability at run time; maintainer environment):

- `python -m evals.history_pull_decision.harness --seeds 0,1,2 --cache-dir
  .local/llm-cache --output .local/history_pull_run.json`
- `python -m evals.historical_lookup_judge --db <scratch_db> --seeds 0,1,2
  --cache-dir .local/llm-cache` (over the harness-produced lookups)
- Then author `docs/reports/history-pull-decision-harness-validation.md`.

Windows invocation for every command above:
`PYTHONPATH=".local/test-env/site-packages;." "C:/Users/I347041/AppData/Roaming/uv/python/cpython-3.13-windows-x86_64-none/python.exe" -m <module|pytest> ...`
