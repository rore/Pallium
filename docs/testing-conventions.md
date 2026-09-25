# Testing Conventions

## Development loop

Keep normal edit feedback targeted and serial so pytest does not pay four spawned-worker startups for one file:

```powershell
python -m pytest tests/test_example.py::test_case -q -n 0
```

After a coherent change, run the affected subsystem files. Rerun only recorded failures with `python -m pytest --lf --lfnf=none -q -n 0`. A focused slow-marked target needs `-m slow`.

Before review or PR, select validation using the whole change:

```powershell
python scripts/test-plan.py --base origin/main
```

Use a current trusted base. The local command includes branch changes since the merge base, staged and unstaged changes, and untracked files. Run the commands in its report; selection alone is not validation. Missing or incomplete evidence chooses full validation. Recompute after the diff changes.

| Lane | Eligible change | Required validation |
|---|---|---|
| Documentation | Only explicitly recognized Markdown documentation | Lightweight repository/selection contracts and existing PR governance checks |
| Governance | Only supported Agent Workflow files and documentation | Focused caller-contract tests on Linux and Windows, without application fixtures; existing Redline and Agent Workflow PR checks |
| Full | Application code/tests, mixed changes involving application paths, unknown paths, runtime hooks/configuration, selector/CI/shared test configuration | Full non-slow application suite and existing platform checks |

The selector's explicit allowlist is authoritative. A filename ending in `.md` or living under `.agents/` is not by itself an exemption. Both old and new paths of a rename count; deleted paths still count. Protected behavior-contract tests always select full. Changes to selection policy itself must run full validation. Schedules and manual full CI runs override narrow selection.

For a full local lane, run `python -m pytest tests/ -x -q` once before review. Do not repeat a successful full run at every handoff. Record the revision, relevant dirty diff, command, environment, and result; reuse that evidence while the tested content and dependencies remain unchanged. A changed test target, relevant code, configuration, or integration invalidates the affected evidence. A narrow local run does not replace the required platform CI checks.

Changed features still require E2E coverage of their boundaries and lifecycle. Selection avoids running unrelated features on governance edits; it does not permit dropping regression tests, replacing assertions with weaker proxies, or rerunning flaky failures until green. Diagnose failures and distinguish application bugs, test isolation, and timing assumptions. No test lane guarantees absence of every regression.

## Test marking

Any new test file that falls into one of these categories MUST be marked `pytestmark = pytest.mark.slow` at module level:

- **eval harnesses**: tests that run scenario files through a full pipeline and assert on aggregate metrics (e.g. `run_*_benchmark`, `run_*_validation`, `run_*_scenarios`)
- **polling wait loops**: tests that use `BackgroundProcessor`, `wait_for_item_processing`, or any sleep/poll loop with a timeout
- **corpus/dataset runners**: tests that load external fixtures or large datasets and iterate over them

Add `import pytest` if not already present. The `slow` marker is registered in `pyproject.toml`. The default `pytest tests/` run excludes slow tests (`addopts = "-m 'not slow' -n 4 --import-mode=importlib"`). Run them explicitly with `pytest tests/ -m slow`.

## Test vector index

The shared test helpers (`build_llm_test_config` in `tests/config_helpers.py`, the `client` fixture in `tests/conftest.py`) use `VectorIndexConfig(enabled=False)` by default. Do not change this. Tests that specifically exercise vector retrieval, embedding, or composite retrieval must create their own `AppConfig` with an explicit `VectorIndexConfig(enabled=True, index_path=...)`. This keeps the default test run near its current ~3-minute Linux CI profile by avoiding ONNX model inference and usearch index creation in tests that do not need them.

## CI profiles

Full Linux CI installs the existing `dev`, `vector`, and `mcp` extras, verifies that the MCP server imports, and reports the 20 slowest tests. Windows smoke and full lanes report the same timing diagnostics. Application coverage keeps the existing Python/platform matrix; full Windows runs on push to main and nightly.

Narrow governance checks use `--noconftest` and serial execution so the application fixtures in `tests/conftest.py` are not imported. They exercise governance behavior directly instead of constructing the Pallium service. Existing PR Redline and Agent Workflow checks remain independent and mandatory under the repository workflow.

CI executes the selector from the trusted base revision. If that revision has no selector (including the rollout PR), or selection cannot complete, the fallback is full. A stable `CI result` job checks that every required lane succeeded; unexpected skips or selection-job failure must not produce green. Branch protection is a separate repository setting; this change does not enable it.

Scheduled runs retain the full matrix to check assumptions behind narrow selection. A failure remains actionable: the change owner investigates a PR failure; a scheduled failure needs triage before using that baseline as passing evidence. This rollout does not repair existing unrelated CI failures.

The nightly slow smoke is deliberately an explicit, serial allowlist covering snapshot, SQLite, thread-summary accumulation, and Relay load paths. Do not replace it with the complete `-m slow` suite until the separately tracked stale slow-test expectations are green; opt-in service tests, live providers, model downloads, and generated P2 scenarios remain excluded.

## Exploratory QA

`evals/generated_exploratory/` contains taxonomy-driven invariant testing. Three tiers:

- **P0** (~15-25 authored scenarios): correctness invariants (scope, visibility, actor, role). Run on demand, must pass.
- **P1** (~50-100 authored scenarios): quality invariants (routing, injection, greeting suppression). Run nightly/pre-release.
- **P2** (hundreds+, LLM-generated): coverage expansion. Run on-demand for exploration, never in a build pipeline.

Do not add generated (P2) scenarios to `pytest` or any CI pipeline. The fast test suite (`tests/test_invariant_runner.py`, `tests/test_taxonomy.py`) validates invariant logic against synthetic payloads only. Full pipeline runs go through the CLI runner. Confirmed bugs from any tier get promoted into the P0/P1 set with authored expectations. See `docs/context/decisions.md` for the full rationale.

## Eval performance

The invariant runner supports two performance flags:

- `--workers N` — parallel scenario execution (default 1 = sequential). Each scenario is fully isolated (own DB, own TestClient). Use 4 workers for ~4x speedup on large batches. The bottleneck is LLM network latency, so threads are the right primitive.
- `--cache-dir PATH` — file-backed LLM response cache. Caches drain-time LLM calls (write_extraction, thread_rebuild, consolidation) so repeat runs skip network calls. First run populates the cache; subsequent runs are ~5-8x faster. Cache is keyed on (model, system_prompt, user_prompt, schema_description). Query-time resolver calls are intentionally NOT cached.

Example: `python -m evals.generated_exploratory.invariant_runner --workers 4 --cache-dir .local/llm-cache`

The LLM cache (`providers/llm/cached.py`) wraps any `LLMProvider` and can be reused by other eval runners.

## Driving evals from live failures

When the goal is to validate a routing/extraction/consolidation hypothesis against observed audit failures (rather than authored scenarios), follow the process in [docs/context/eval-from-live-failures.md](context/eval-from-live-failures.md). Live-data replays are stdlib-only, live under `.local/research/<topic>-<YYYY-MM-DD>/`, and produce a normalized `failure_rows.jsonl` plus a `RESULTS.md` verdict before any production change is proposed.
