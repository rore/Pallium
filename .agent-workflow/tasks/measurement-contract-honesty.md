# Work Record — measurement-contract-honesty

Task branch: `worktree-agent-aa35e0b95cdbe0c75`
Roadmap item: `roadmap/ideas/idea-measurement-contract-honesty.md`

<!-- agent-workflow:start -->
**Outcome:**
The historical-reuse measurement contract states honestly what it measures, so the first live Experiment-1 numbers are read correctly. Three fixes land in one PR: (S1) the guidance-strength arms are labelled so both are known to carry a block-level permit nudge — the contrast is *permit-nudge* (base) vs *permit-nudge + call-it-first* (strong), with no false "zero-guidance" baseline implied; (S2) the KPI's stated meaning in the design + contract matches the implemented *session-incidence* metric (fraction of eligible sessions with >=1 confirmed reuse x 100, capped at 100), pinned by a test; (S3) the deterministic per-path DB round-trip count-compare runs in the DEFAULT CI lane so a regression on the shared retrieval chokepoint auto-fails. No product-behaviour, retrieval, or funnel-computation change.

**Target:**
Pallium repo, one PR. Guarded touch is confined to `app/cli/setup_claude_code.py` + `app/cli/setup_codex.py` (CLI arg/label/default only — no core/persistence/contract behaviour). Non-guarded: `integrations/claude-code/claude_md_block.py`, `evals/vnext_perf_harness.py`, `tests/`, `pyproject.toml`, and docs (`docs/designs/015-*.md`, `docs/specs/2026-08-13-historical-lookup-measurement-contract.md`, `roadmap/`).

**Scope:**
S1 — rename the weak arm value `tool-only` -> `base` across the two setup CLIs and `integrations/claude-code/claude_md_block.py`; keep `tool-only` as a DEPRECATED ALIAS (argparse still accepts it, normalises to `base`, prints a deprecation note); rename the roadmap label "tool-description-only" -> "base (permit-nudge)"; document in the measurement contract that BOTH arms carry a block-level permit nudge. S2 — reconcile KPI wording in design 015 (lines ~3, 23, 178, 289), `roadmap/scope.md`, and the measurement-contract rollup section to the session-incidence semantics; add a test explicitly pinning "session-incidence, capped at 100". S3 — add a default-lane (non-slow) test that runs the full-mode count-compare against `evals/vnext_perf_baseline.json` and asserts no regression; add an `include_latency=False` path to the harness so the gated run computes no advisory latency; keep `tests/test_vnext_perf_harness.py` slow.
MAY NOT touch: the KPI COMPUTATION itself (`compute_reuse_rollup`), guidance-block CONTENT beyond arm naming/marker, retrieval/funnel behaviour, the count baseline VALUES.

**Constraints:**
No product-behaviour change. No internal/external product names in committed artifacts. The live `strong` deployment (installed today) must remain valid — only the `tool-only`/`base` arm is renamed; the `strong` value and its embedded marker are unchanged. Renaming the default means fresh base-arm installs need a `pallium setup` re-run to pick up the new `guidance-strength=base` marker (deployed-block staleness — see Discovery). Tests run via the real cpython interpreter + `PYTHONPATH=".local/test-env/site-packages;."` (this box blocks venv python stubs). Block invariants (no "MANDATORY"/banned legacy strings on the strong variant) must still hold.

**Completion criteria:**
Idea "Done When" 1–3: (1) arm labels reflect that both carry a block-level permit; the contract states this; `tool-only` still works as a deprecated alias; existing integration tests updated + green. (2) design/contract KPI wording matches the implemented session-incidence metric, pinned by a passing test. (3) the deterministic count-compare runs in the default CI lane (proven: it fails when the baseline is perturbed, passes otherwise). Plus `python -m pytest tests/ -q` green (modulo known-benign `test_config.py::test_prompt_variants_legacy_fallback_unaffected`).

**Risk:** Elevated

**Complexity:** Moderate

**Reason:**
Guarded path `app/cli/` is touched (setup CLIs), but only arg-parsing / help-text / default-value / label surface — no core, persistence, retrieval, or contract behaviour → Elevated (gray/red-CLI), not High. Moderate: several coordinated components (2 setup CLIs + 1 integration block + 2 integration test files + measurement test + harness + pyproject + several docs) in one coherent PR, with a breaking-change surface (flag rename) that needs an alias + deprecation path.

**Discovery:**
See `## Discovery`. Verified file:line. Key facts: (a) the base `CLAUDE_MD_BLOCK` already carries a resume nudge to call `pallium_search_history` (`integrations/claude-code/claude_md_block.py:12-15`); `_STRONG_DIRECTIVE` (`:114-123`) only ADDS a second imperative — so "tool-only" is a misnomer; the real contrast is permit-nudge vs permit-nudge+call-first. (b) The arm value is embedded verbatim into every installed block as `<!-- pallium:guidance-strength=tool-only -->` (`claude_md_block.py:138`, `setup_codex.py:374`) — an operator reads it directly, so documentation alone cannot de-mislead it; the VALUE must change. (c) `--guidance-strength` with `choices=["tool-only","strong"] default="tool-only"` lives in `app/cli/setup_claude_code.py:345-347` and `app/cli/setup_codex.py:561-563`; internal fn defaults at `setup_claude_code.py:172,203,266`, `setup_codex.py:361,389,465`, `claude_md_block.py:126,135`. (d) Integration tests assert the marker value: `tests/test_claude_code_integration.py:13,32,35,59,61,80` and `tests/test_codex_integration.py:300-338`. (e) KPI is session-incidence: `compute_reuse_rollup` dedups by session (`evals/historical_lookup_measurement.py:143-144,177-182,200`); the contract rollup formula ALREADY states session-incidence (`docs/specs/2026-08-13-historical-lookup-measurement-contract.md:146-147`) but design 015 (`:3,23,178,289`) + `roadmap/scope.md:58,63` + `docs/context/strategy-vnext.md:157` still say "events per 100 sessions". (f) Dedup semantics are ALREADY pinned by `TestDedup` in `tests/test_historical_lookup_measurement.py:252-308` (same-rung dedup, denominator dedup, cross-rung independence, raw n_reuse_events) — so S2's test ask is largely met; only an explicit "session-incidence / capped-at-100" naming test is missing. (g) The count-compare gate is `evals/vnext_perf_harness.py` compare mode vs `evals/vnext_perf_baseline.json`, guarded only by `tests/test_vnext_perf_harness.py` which is `pytest.mark.slow` (`:20`); default addopts `-m 'not slow' -n 4` (`pyproject.toml:60`) excludes it. MEASURED: full `run_measurements()` = 4.72s (incl. 25-rep advisory latency), `compare_to_baseline` = 0.0007s, seeds 900 items, PASS vs committed baseline — fast enough for the default lane.

**Material assumptions:**
- A1: Renaming `tool-only`->`base` with a deprecated alias breaks nothing live, because the architect's deployed arm is `strong` (unchanged) and argparse will still accept `tool-only`. Disproof: a caller/script depends on the literal default marker `guidance-strength=tool-only` in a base install → the alias preserves the flag input; only the WRITTEN marker changes, and that is the intended honesty fix — note in PR that base installs must re-run setup.
- A2: The KPI computation is correct and only its stated meaning is wrong; no code-behaviour change is in scope for S2. Disproof: reconciling wording reveals the code actually diverges from the contract formula → STOP, raise scope (idea says do NOT change computation).
- A3: A full-mode count-compare at ~4.7s (or ~3.5s without advisory latency) is acceptable in the default `-n 4` lane. Disproof: CI budget forbids a ~5s pipeline test in the default lane → fall back to keeping it slow but adding a dedicated fast CI *step* (`python -m evals.vnext_perf_harness`) in the workflow, and record that.
- A4: `run_measurements()` can gain an `include_latency=False` path in `evals/` (non-guarded) to drop advisory-latency computation from the gated run without touching the count logic. Disproof: the latency computation is entangled with the count seams → gate on the as-is 4.72s full run instead (still acceptable per A3).

**Plan:**
See `## Plan` below (decision-complete: S1 = rename+alias; S3 = new fast default-lane test + `include_latency` kwarg).

**Verification plan:**
See `## Verification plan` below. Real-interpreter commands for: the two integration test files (arm rename + alias), the measurement test (session-incidence pin), the new count-gate test (passes; and fails on a perturbed baseline to prove it gates), a `--guidance-strength tool-only` deprecation-alias smoke, and the full default-lane `pytest -m 'not slow'`.

**Plan review:**
Pending — architect (human) review requested per task instructions before any code edit. (Elevated normally takes a clean-context agent review; the architect is the designated reviewer here.)

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Discovery

(Recorded in the marker block Discovery field above; file:line verified during planning. No code edited.)

## Plan

**S1 — arm labels (rename + deprecated alias).**
1. `integrations/claude-code/claude_md_block.py`: `get_claude_md_block` accepts `"base"` (and `"strong"`); validation set becomes `{"base","strong"}`; default `"base"`. The `base` block is the current `CLAUDE_MD_BLOCK` unchanged (content is out of scope).
2. `app/cli/setup_claude_code.py` + `app/cli/setup_codex.py`: argparse `choices=["base","strong","tool-only"]`, `default="base"`; a normaliser maps the deprecated `tool-only` -> `base` and prints a one-line deprecation note; internal fn defaults updated to `"base"`; help text describes `base` (permit-nudge) vs `strong` (adds call-first directive) and notes `tool-only` is a deprecated alias.
3. Arm marker becomes `<!-- pallium:guidance-strength=base -->` for the base arm; `strong` marker unchanged.
4. `roadmap/features/add-agent-historical-lookup-exposure.md` + `add-historical-lookup-reuse-funnel.md`: replace "tool-description-only" with "base (permit-nudge)"; state both arms carry a block-level permit.
5. `docs/specs/2026-08-13-historical-lookup-measurement-contract.md`: add a short "Guidance arms" note — both arms carry a block-level permit nudge; the KPI delta between arms measures the *call-first* directive, not presence-vs-absence of guidance.
Decision & justification: RENAME (not document-only), because the misleading token is embedded in every installed block as a marker an operator reads directly; documentation cannot fix a marker. The alias contains the breaking-change cost. A genuine third zero-guidance arm (stripping the base nudge) is the noted ALTERNATIVE, explicitly out of scope per the idea.

**S2 — KPI wording + test.**
1. Reword design 015 (`:3` date-header untouched; `:23`, `:178`, `:289`) + `roadmap/scope.md:58,63` + `docs/context/strategy-vnext.md:157` from "events per 100 sessions" to "fraction of eligible sessions with >=1 confirmed reuse x 100 (session incidence, capped at 100)"; keep the three-rung framing.
2. Confirm the contract rollup formula (`:146-147`) already matches; add one clarifying sentence naming the metric "session incidence" + the 100 cap.
3. Add `tests/test_historical_lookup_measurement.py::TestDedup::test_session_incidence_capped_at_100` (or a new `TestSessionIncidence` class): many raw same-rung events in a single eligible session yield numerator==1 and `reuse_per_100_eligible <= 100`. Reference the existing dedup tests rather than duplicate them.

**S3 — count-gate in default CI.**
1. `evals/vnext_perf_harness.py`: add `include_latency: bool = True` to `run_measurements`/`_run_measurements_in`; when False, skip the `latency_advisory` block only (counts/index/N+1 untouched). Non-guarded.
2. New `tests/test_vnext_perf_count_gate.py` (NOT slow): call `run_measurements(include_latency=False)`, load `evals/vnext_perf_baseline.json`, assert `compare_to_baseline(...) == []`. Deterministic; ~3.5s.
3. Leave `tests/test_vnext_perf_harness.py` slow (structural seams + small mode). Latency/benchmark stay advisory, never gated.
Decision & justification: a dedicated fast test (not de-slow-marking the existing one) because the existing slow test uses `--small` (30-turn corpus, shape differs, never gates); the real gate needs full mode (900 items) to match the committed baseline. Measured 4.72s full / ~3.5s without latency — inside the default `-n 4` lane budget.

## Verification plan

Real-interpreter form (from repo root):
`PYTHONPATH="C:/Dev/rore/Pallium/.local/test-env/site-packages;." "C:/Users/I347041/AppData/Roaming/uv/python/cpython-3.13-windows-x86_64-none/python.exe" -m pytest ...`

- S1: `pytest tests/test_claude_code_integration.py tests/test_codex_integration.py -q` (updated marker assertions to `=base`; add an assertion that `tool-only` alias still resolves to the base block).
- S1 alias smoke: run `python -m app.cli.setup_claude_code claude-code --guidance-strength tool-only` dry path / unit-invoke the normaliser and assert the deprecation note + `base` marker.
- S2: `pytest tests/test_historical_lookup_measurement.py -q` (new session-incidence-capped test + existing TestDedup green).
- S3 pass: `pytest tests/test_vnext_perf_count_gate.py -q`; and prove it GATES by temporarily perturbing an in-memory baseline copy in the test-run and asserting `compare_to_baseline` returns problems (kept inside the test, baseline file untouched).
- Full lane: `pytest -m 'not slow' -q` green (modulo the known-benign config test). Confirm the new count-gate test is collected in this lane and the harness slow test is not.

## Implementation

(Not started — planning only. Awaiting architect plan review.)
