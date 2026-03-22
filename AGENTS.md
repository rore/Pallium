# AGENTS.md

For roadmap planning and roadmap file updates in this repo, follow `tools/minimap/SKILL.md`.
For architecture review, feature shaping, and cross-thread coordination, follow `tools/pallium-architect-review/SKILL.md`.
For delegated work, subagent work, or cross-thread worker coordination, follow the delegation and review loop in `tools/pallium-architect-review/SKILL.md`.

Treat `roadmap/` as the canonical repo-local roadmap workspace for humans and agents.
Use `docs/context/` for broader design context, but keep roadmap state and queue changes in the minimap files.

Repo-level non-negotiables:

- use `README.md`, `docs/context/*`, relevant `docs/designs/*`, and `roadmap/*` as the source of truth
- optimize for the smallest valuable slice that strengthens the current product claim
- protect the generic core, reusable capability, and package-specific semantic boundaries
- call out roadmap, docs, and code drift explicitly before endorsing a change
- treat concrete downstream incidents as bug sources, but generalize fixes into reusable memory-system capabilities before proposing roadmap or implementation work
- avoid proposing or implementing scenario-specific features keyed to product names, tool names, ticket ids, or one-off phrasing unless the work is explicitly integration-scoped
- keep new tests, fixtures, replay assets, and benchmark cases anonymized and domain-generic by default
- translate scenario-specific reproductions into generalized retrieval, routing, packaging, lifecycle, compatibility, or benchmark failure classes before defining the work
- delegated work is not complete until it has been reviewed, findings have been addressed, and roadmap/docs have been aligned when the feature status changed
- if `apply_patch` fails because of sandbox or environment limitations on this machine, delegated workers may use the smallest deterministic local file-write fallback and must report that fallback explicitly

Test marking — any new test file that falls into one of these categories MUST be marked `pytestmark = pytest.mark.slow` at module level:

- **eval harnesses**: tests that run scenario files through a full pipeline and assert on aggregate metrics (e.g. `run_*_benchmark`, `run_*_validation`, `run_*_scenarios`)
- **polling wait loops**: tests that use `BackgroundProcessor`, `wait_for_item_processing`, or any sleep/poll loop with a timeout
- **corpus/dataset runners**: tests that load external fixtures or large datasets and iterate over them

Add `import pytest` if not already present. The `slow` marker is registered in `pyproject.toml`. The default `pytest tests/` run excludes slow tests (`addopts = "-m 'not slow' -n 4 --import-mode=importlib"`). Run them explicitly with `pytest tests/ -m slow`.

Test vector index — the shared test helpers (`build_llm_test_config` in `tests/config_helpers.py`, the `client` fixture in `tests/conftest.py`) use `VectorIndexConfig(enabled=False)` by default. Do not change this. Tests that specifically exercise vector retrieval, embedding, or composite retrieval must create their own `AppConfig` with an explicit `VectorIndexConfig(enabled=True, index_path=...)`. This keeps the default test run fast (~20s) by avoiding ONNX model inference and usearch index creation in tests that don't need them.

