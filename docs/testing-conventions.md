# Testing Conventions

## Test marking

Any new test file that falls into one of these categories MUST be marked `pytestmark = pytest.mark.slow` at module level:

- **eval harnesses**: tests that run scenario files through a full pipeline and assert on aggregate metrics (e.g. `run_*_benchmark`, `run_*_validation`, `run_*_scenarios`)
- **polling wait loops**: tests that use `BackgroundProcessor`, `wait_for_item_processing`, or any sleep/poll loop with a timeout
- **corpus/dataset runners**: tests that load external fixtures or large datasets and iterate over them

Add `import pytest` if not already present. The `slow` marker is registered in `pyproject.toml`. The default `pytest tests/` run excludes slow tests (`addopts = "-m 'not slow' -n 4 --import-mode=importlib"`). Run them explicitly with `pytest tests/ -m slow`.

## Test vector index

The shared test helpers (`build_llm_test_config` in `tests/config_helpers.py`, the `client` fixture in `tests/conftest.py`) use `VectorIndexConfig(enabled=False)` by default. Do not change this. Tests that specifically exercise vector retrieval, embedding, or composite retrieval must create their own `AppConfig` with an explicit `VectorIndexConfig(enabled=True, index_path=...)`. This keeps the default test run fast (~20s) by avoiding ONNX model inference and usearch index creation in tests that don't need them.

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
