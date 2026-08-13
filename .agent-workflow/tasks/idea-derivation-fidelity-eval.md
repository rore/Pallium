# Task: idea-derivation-fidelity-eval

Source-episode derivation coverage + fidelity eval (Pallium vNext, Continuous
evaluation track — Experiment 3, derivation-side seams).
Ticket: `roadmap/ideas/idea-derivation-fidelity-eval.md`.
Execution context: `docs/designs/015-vnext-historical-work-execution.md`
(Continuous evaluation track).

<!-- agent-workflow:start -->
**Outcome:**
An offline, source-episode-first eval exists that measures the two derivation-SIDE
seams independent of retrieval: (1) extraction/coverage — starting from sampled
source items/episodes, did the pipeline produce a derived memory object at all? —
and (2) fidelity — where a derived object exists, an offline judge scores
completeness, unsupported claims, drift, and (deterministic) compression ratio.
Results are reported per memory type and stamped with the derivation
schema/prompt-variant/producer-role recorded on each object plus the report-time
concrete model. The eval has NO production coupling (read-only on the DB, no
production code changed) and its pure scoring functions are unit-tested with
in-memory rows; a runner path is exercised end-to-end against a synthetic DB with a
stub judge.

**Target:**
pallium

**Scope:**
New package `evals/derivation_fidelity/` (`__init__.py`, `coverage.py` — pure
coverage scoring, `fidelity.py` — judge prompt/schema + pure fidelity/compression
aggregation, `runner.py` — read-only DB load + provider wiring + orchestration +
report emit, `__main__.py` — `python -m evals.derivation_fidelity`). New tests
`tests/test_derivation_fidelity.py`. A short section in `docs/context/validation.md`
Eval Toolbox table (one row) documenting the new tool. NOT: any change under a
guarded path (`api/ app/ capabilities/ core/ providers/ redaction/ retrieval/
semantic/ storage/`); no new storage method (enumeration via read-only SQL through a
SQLAlchemy engine, the established offline-eval precedent); no change to the
derivation pipeline itself (this measures; fixes are separate items); no retrieval-
side RAW/DERIVED/HYBRID comparison (that is `idea-raw-derived-hybrid-shadow-eval`).

**Constraints:**
Read-only on the live DB — zero writes, zero production-code edits, cannot affect
`should_inject`/injection/ranking. Coverage must be survivorship-bias-free: start
from source items (not from existing derived objects), and separate
not-yet-processed vs processed-produced-nothing vs extracted vs extracted-then-
demoted (via `SourceItem.processing_status`/`processing_completed_at` +
`list_memory_objects_for_source_items(..., include_candidates=True,
include_soft_deleted=True)`). Every emitted number is labelled by seam
(coverage vs fidelity) and never conflated with retrieval recall or downstream use
(`docs/context/lessons.md` invariant). Judge variance (~20pp, `lessons.md`) is
handled explicitly — the judge is run N times and aggregated (majority/median) with
`CachedLLMProvider` for reproducibility; single-seed judge numbers are not reported
as ground truth. Case *selection* is seeded (`--seed`, default fixed) for
reproducibility. Source→derived linkage uses `relation_type='supported_by'`
(from_kind=memory_object → to_kind=source_item) — NOT the stale
`relations.source_id/kind='derived_from'` shape in `typed_extraction_shadow`. No
internal/external product names in committed code/tests (domain-neutral synthetic
fixtures only).

**Completion criteria:**
1. Running `python -m evals.derivation_fidelity --db <path>` on a populated DB
   emits a report with, per memory type: coverage classification counts
   (not-processed / processed-nothing / extracted / extracted-then-demoted), a
   coverage rate over *processed* items, and — for extracted objects — fidelity
   aggregates (completeness, unsupported-claim rate, drift rate, compression ratio),
   each stamped with the derivation schema/prompt-variant/producer-role and the
   report-time model. → runner test against a synthetic DB with a stub judge.
2. The coverage scoring function is pure (in-memory rows in, metrics out), classifies
   the four states correctly, computes the processed-item coverage rate, and is
   empty-data-safe. → unit test.
3. The fidelity aggregation is pure: compression ratio is computed deterministically
   from source/derived text lengths; judge outputs are aggregated over N samples
   (majority for booleans, mean/median for scores); empty-data-safe. → unit test.
4. A DERIVED loss can be attributed to extraction/coverage vs (elsewhere) retrieval/
   representation: the report cleanly separates the coverage seam from the fidelity
   seam and never emits a single blended "derivation quality" number. → assertion in
   runner test + doc note.
5. Coverage/fidelity are reported against the recorded derivation version
   (schema/prompt-variant/role from `envelope.derivation`; concrete model resolved
   from `AppConfig` at report time, with the per-object-model limitation documented).
   → unit test on the provenance-extraction helper + doc note.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:**
Redline: all intended paths are blue — the change is confined to `evals/` and
`tests/` (plus one doc row), touching no guarded path (`api/ app/ core/ providers/
redaction/ retrieval/ semantic/ storage/`) and no RED contract/persistence/security
surface. Baseline would be Routine; RAISED to Elevated by engineering judgment: this
is a new measurement instrument whose numbers feed a strategy keep-or-simplify
decision (decision-point 3), and it introduces an offline LLM judge whose variance
must be handled correctly — a wrong measurement misleads the derivation decision.
Moderate complexity: multi-file eval package + judge + coverage/fidelity math +
tests in one coherent slice, with measurement-correctness nuance.

**Discovery:**
- No explicit "episode" entity in core/storage; the only source grouping is
  `(container_ref, thread_ref)` with a non-contiguous `thread_position`. Enumerate/
  window via `(created_at, id)`, never `thread_position`
  (`storage/sqlite.py:248,260-278`). No method lists all/distinct source threads →
  selector uses read-only SQL through a SQLAlchemy engine (precedent:
  `evals/typed_extraction_shadow/compare.py`, `evals/post_routing_selection_audit/`).
- Bidirectional source↔derived linkage exists: forward
  `list_memory_objects_for_source_items(ids, include_candidates=, include_soft_deleted=)
  -> dict[str,list[MemoryObject]]` (`storage/sqlite.py:828`); reverse
  `get_evidence_for_memory_object(id) -> list[EvidenceReference]` (`:1200`). Linkage
  is `relation_type='supported_by'`, from_kind=memory_object → to_kind=source_item
  (`storage/sqlite_schema.py:100-108`).
- Per-object derivation provenance is persisted in `envelope_json` as
  `MemoryEnvelopeDerivation{producer_kind, producer_schema_id, producer_schema_version,
  prompt_variant, model_role, kind_basis}` (`core/models.py:93-100,116-126`); object
  `type`/`schema_id`/`schema_version` are their own fields. **Limitation:** the
  concrete model id (e.g. `claude-*`) is NOT stamped per object — only the logical
  `model_role`. Concrete model must be resolved from `AppConfig.package_config(...)`
  at report time and labelled as report-time, not per-object historical.
- Judge infra exists: `evals/eval_common.py:build_eval_providers(config,...) ->
  (main_provider, judge_provider)` — the selector≠judge split — optionally wrapping
  `CachedLLMProvider`. Judge call surface is `provider.generate_json(system_prompt,
  user_prompt, schema_description)` (`providers/llm/base.py:92-99`); metadata carries
  the actual model. Provider factory `app.dependencies.build_llm_provider` works
  standalone (no FastAPI), always wrapped in the redaction barrier.
- **No seed/temperature control** on the provider API; determinism relies on
  `CachedLLMProvider`; no existing self-consistency judge harness → N-sample
  aggregation is net-new at the eval layer.
- Eval convention: pure scoring function importable with in-memory rows (no DB), CLI
  via `main()`/`build_parser()` + `__main__.py`, report as JSON; evals ARE unit-tested
  under `tests/` and stub the provider via `monkeypatch.setattr` on the factory
  (precedent `tests/test_public_corpus_wildbench_local.py:118`).

**Material assumptions:**
1. Assumption: a read-only SQL enumeration inside the eval (not a new `storage/`
   method) is the right call for the source-episode selector. Evidence for:
   established offline-eval precedent; keeps the change out of guarded paths.
   Disproof: reviewer requires the enumeration to go through `StorageProvider`.
   Action: add a read-only storage method → re-classify (adds persistence-review,
   guarded path), re-plan.
2. Assumption: "episode" = a `(container_ref, thread_ref)` thread; coverage is
   measured at the source-item level and rolled up to the thread level. Disproof:
   reviewer/user wants a finer episode segmentation (e.g. sub-task windows). Action:
   add a segmentation step; report unit changes; no production impact.
3. Assumption: measuring extraction coverage over *processed* items (with a stated
   pending-item count) is the honest denominator. Disproof: user wants coverage over
   all items regardless of processing state. Action: change the denominator; doc +
   test update; no code-structure change.
4. Assumption: N-sample judge aggregation + caching is adequate variance control
   without a seed/temperature API. Disproof: variance remains too high to be useful.
   Action: raise N / add a second judge model / mark fidelity numbers advisory —
   eval-layer only, no production impact.

**Plan:**
Sequence (all under `evals/derivation_fidelity/` unless noted):
1. `coverage.py` — pure functions: `classify_source_item(item, derived_objects) ->
   CoverageState` (one of not_processed / processed_nothing / extracted /
   extracted_then_demoted, from processing fields + derived lifecycle) and
   `aggregate_coverage(records) -> per-type + overall counts + processed-item coverage
   rate`. No DB, no LLM. This is the survivorship-bias-free core.
2. `fidelity.py` — `FIDELITY_SCHEMA` + `build_fidelity_prompt(source_turns,
   derived_text)` (judge returns {completeness_score, unsupported_claims:[...],
   drift: bool, drift_reason, notes}); `compression_ratio(source_chars, derived_chars)`
   (deterministic); `aggregate_fidelity(judge_samples) -> majority/median aggregate`
   for the N-sample variance handling; `extract_derivation_version(memory_object) ->
   {schema_id, schema_version, prompt_variant, model_role, producer_kind}`. Pure.
3. `runner.py` — read-only load (SQLAlchemy engine `SELECT ... FROM source_items`
   with seeded sampling + optional container/thread/type filters + `--limit`), forward
   linkage via `list_memory_objects_for_source_items(include_candidates=True,
   include_soft_deleted=True)`, reverse evidence via `get_evidence_for_memory_object`;
   provider via `build_eval_providers` (judge only; main unused) with
   `--cache-dir`/`--judge-samples`/`--no-eval-cache`; resolve report-time model from
   `AppConfig`; assemble the report and write JSON to `--out` (default under `.local/`).
   `main(argv)`/`build_parser()`; `__main__.py` delegates.
4. `docs/context/validation.md` — one Eval Toolbox row: "Derivation coverage +
   fidelity (source-episode-first)" → `evals/derivation_fidelity` (Scenario/replay +
   LLM-judge; judge is stochastic, run N samples).
5. `tests/test_derivation_fidelity.py` — unit tests for (1)+(2)+(3) pure functions
   (four-state classification, coverage rate, empty safety, compression math, N-sample
   majority/median, provenance extraction) + a runner test: build a tiny synthetic DB
   via the real `SQLiteStorageProvider` (ingest a few source items across two threads,
   create `supported_by` relations for some, leave others uncovered, mark one derived
   object soft-deleted), stub the judge provider (deterministic canned JSON) via
   monkeypatch, run the runner, assert the report separates coverage vs fidelity seams,
   per-type breakdown, and version stamping.

Conventions: labels tethered to `docs/context/lessons.md` (seam-explicit, no
retrieval/downstream conflation); domain-neutral fixtures (AGENTS.md); pure-scoring +
DB-load separation (typed_extraction_shadow precedent).

Stop conditions: if the selector cannot be done read-only and needs a `storage/`
method → stop, re-classify (persistence-review). If linkage cannot be established
without the derivation pipeline emitting a relation I can't find → stop, reconcile.

**Verification plan:**
1. Pure coverage units (four-state classification, processed-item coverage rate, empty-data safety; criterion 2) -> `pytest tests/test_derivation_fidelity.py -q`
2. Pure fidelity units (deterministic compression ratio, N-sample majority/median aggregation, empty safety; criterion 3) -> `pytest tests/test_derivation_fidelity.py -q`
3. Provenance-extraction unit (schema/prompt-variant/role from envelope; criterion 5) -> `pytest tests/test_derivation_fidelity.py -q`
4. Report separates coverage vs fidelity seams with no blended number, per-type counts, version stamping present (criteria 1,4,5) -> runner test against synthetic DB with stub judge
5. No production regression from the offline-only change -> `pytest tests/ -q` (expect only the pre-existing `test_config` failure)
6. CLI parses and a `--limit 5` dry run emits a well-formed report on a local DB -> manual: non-gating smoke, numbers not asserted (real judge stochastic)

**Plan review:**
Pending — Elevated requires a clean-context agent review before implementation. Will
record verdict + reference under `## Plan review`.

**Approvals:**
Not required at this risk level (Elevated). Proceeding under the standing overnight
mandate to drive the next board item to completion.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

(pending plan review, then implementation)
