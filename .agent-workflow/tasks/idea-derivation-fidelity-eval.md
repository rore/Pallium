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
from source items (not from existing derived objects). **Coverage is segmented by
linkage semantics, never blended into one rate:** per-item producers
(`producer_kind=item_extraction`) are measured at *item* granularity; whole-thread
producers (`thread_aggregation`, `consolidation`) link to ALL thread items
(verified `semantic/conversational_knowledge.py:501-511`,
`agent_conversation_memory_threads.py:705-714`) so their coverage is measured at
*thread* granularity. Four-state classification (not_processed / processed_nothing /
extracted / extracted_then_demoted) uses `SourceItem.processing_status`/
`processing_completed_at` + `list_memory_objects_for_source_items(...,
include_candidates=True, include_soft_deleted=True)`; "demoted" is defined precisely:
a linked object counts as demoted iff `is_soft_deleted` or `lifecycle=='superseded'`;
an item with ANY active linked object → `extracted`; linked objects all demoted →
`extracted_then_demoted`. Every emitted number is labelled by seam (coverage vs
fidelity) and never conflated with retrieval recall or downstream use
(`docs/context/lessons.md` invariant). Judge variance (~20pp, `lessons.md`) is
handled explicitly AND correctly: because `CachedLLMProvider`'s key
(`providers/llm/cached.py:106-116`) has no sample slot, each of the N judge samples
carries a distinct sample-ordinal in its prompt so samples get distinct cache keys
(genuinely independent draws, still reproducible per (prompt, ordinal)); the runner
builds the judge provider directly (`build_llm_provider`) + optional
`CachedLLMProvider`, not `build_eval_providers`, to control this and avoid the
default-package coupling. Single-sample judge numbers are not reported as ground
truth. The fidelity "unsupported" axis is scoped honestly: the judge is shown the
linked evidence turns PLUS a bounded same-thread neighbor window (marked as context
vs linked), and the axis is named **unsupported-by-provided-context** — not a raw
hallucination rate — so a claim grounded in an adjacent non-linked turn is not a
false positive. Case *selection* is seeded (`--seed`, default fixed) for
reproducibility. Source→derived linkage uses `relation_type='supported_by'`
(from_kind=memory_object → to_kind=source_item) — NOT the stale
`relations.source_id/kind='derived_from'` shape in `typed_extraction_shadow`. No
internal/external product names in committed code/tests (domain-neutral synthetic
fixtures only).

**Completion criteria:**
1. Running `python -m evals.derivation_fidelity --db <path>` on a populated DB
   emits a report with, per memory type: four-state coverage counts (not-processed /
   processed-nothing / extracted / extracted-then-demoted) and a coverage rate at the
   granularity matching the type's producer_kind (item-level for item_extraction,
   thread-level for thread_aggregation/consolidation) — never one blended overall
   rate — and, for extracted objects, fidelity aggregates (completeness,
   unsupported-by-context rate, drift rate, deterministic compression ratio), each
   stamped with the derivation schema/prompt-variant/producer-role and the report-time
   model. → runner test against a synthetic DB with a stub judge.
2. The coverage scoring function is pure (in-memory rows in, metrics out), classifies
   the four states correctly (demoted rule as in Constraints), computes the
   granularity-appropriate coverage rate per producer_kind class, and is
   empty-data-safe. → unit test.
3. The fidelity aggregation is pure: compression ratio is deterministic from
   source/derived text lengths; N judge samples are genuinely independent (distinct
   sample-ordinal → distinct cache key) and aggregated (majority for booleans,
   mean/median for scores); empty-data-safe. → unit test (incl. a test that N samples
   with a cache produce N independent draws, not one repeated).
4. A DERIVED loss can be attributed to extraction/coverage vs (elsewhere) retrieval/
   representation: the report cleanly separates the coverage seam from the fidelity
   seam and never emits a single blended "derivation quality" number. → assertion in
   runner test + doc note.
5. Coverage/fidelity are reported against the recorded derivation version
   (schema/prompt-variant/producer-role from `envelope.derivation`; concrete model
   resolved from `AppConfig` at report time, with the per-object-model limitation
   documented). → unit test on the provenance-extraction helper + doc note.

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
   measured at the granularity matching each type's producer_kind — item granularity
   for `item_extraction`, thread granularity for `thread_aggregation`/`consolidation`
   (whole-thread producers link to every thread item, so per-item coverage would
   inflate). Disproof: reviewer/user wants a finer episode segmentation. Action: add a
   segmentation step; report unit changes; no production impact.
3. Assumption: the honest denominators are (a) processed source items for item-level
   coverage and (b) threads with ≥1 processed item for thread-level coverage, with the
   pending-item count reported alongside. No single blended overall coverage rate is
   emitted. Disproof: user wants a different denominator. Action: change the
   denominator; doc + test update; no code-structure change.
4. Assumption: N-sample judge aggregation with a per-sample distinct cache key
   (sample-ordinal embedded in the prompt) gives genuine independent draws + caching;
   the "unsupported" axis scoped to linked-evidence-plus-neighbor-context avoids false
   positives. Disproof: variance remains too high, or the neighbor window still misses
   grounding. Action: raise N / widen window / add a second judge model / mark
   fidelity numbers advisory — eval-layer only, no production impact.

**Plan:**
Sequence (all under `evals/derivation_fidelity/` unless noted):
1. `coverage.py` — pure functions: `classify_source_item(item, derived_objects) ->
   CoverageState` (not_processed / processed_nothing / extracted /
   extracted_then_demoted; demoted iff `is_soft_deleted` or `lifecycle=='superseded'`;
   any active linked object → extracted) and `aggregate_coverage(records) -> per-type
   counts + granularity-appropriate coverage rate per producer_kind class` — item-level
   for item_extraction, thread-level for thread_aggregation/consolidation; NO blended
   overall rate. No DB, no LLM. Survivorship-bias-free.
2. `fidelity.py` — `FIDELITY_SCHEMA` + `build_fidelity_prompt(linked_turns,
   context_turns, derived_text, *, sample_ordinal)` (judge returns
   {completeness_score, unsupported_by_context: bool, unsupported_snippets:[...],
   drift: bool, drift_reason, notes}; the sample_ordinal is embedded so each of N
   samples gets a distinct cache key; context_turns are marked as context vs linked);
   `compression_ratio(source_chars, derived_chars)` (deterministic);
   `aggregate_fidelity(judge_samples) -> majority (bool) / mean+median (scores)` over
   the N genuinely-independent samples; `extract_derivation_version(memory_object) ->
   {schema_id, schema_version, prompt_variant, model_role, producer_kind}`. Pure.
3. `runner.py` — read-only load (SQLAlchemy engine `SELECT ... FROM source_items`
   with seeded sampling + optional container/thread/type filters + `--limit`), forward
   linkage via `list_memory_objects_for_source_items(include_candidates=True,
   include_soft_deleted=True)`, evidence via `get_evidence_for_memory_object`, neighbor
   context via `list_source_items_for_thread`; judge provider built DIRECTLY via
   `build_llm_provider` (provider/model resolved from the default package config;
   degrade gracefully if LLM config absent → coverage-only run) + optional
   `CachedLLMProvider` when `--cache-dir`; `--judge-samples N` (default 3),
   `--no-eval-cache`; resolve report-time model from `AppConfig`; assemble the report
   and write JSON to `--out` (default under `.local/`). `main(argv)`/`build_parser()`;
   `__main__.py` delegates.
4. `docs/context/validation.md` — one Eval Toolbox row: "Derivation coverage +
   fidelity (source-episode-first)" → `evals/derivation_fidelity` (Replay coverage +
   LLM-judge fidelity; judge stochastic, N samples; coverage segmented by producer
   granularity).
5. `tests/test_derivation_fidelity.py` — unit tests for (1)+(2)+(3) pure functions
   (four-state classification incl. demoted rule + mixed active/demoted, per-producer
   granularity coverage rate, empty safety, compression math, N-sample
   majority/median, distinct-cache-key-per-sample independence, provenance extraction)
   + a runner test: build a tiny synthetic DB via the real `SQLiteStorageProvider`
   (ingest source items across two threads; create `supported_by` relations — some
   item_extraction, some thread_aggregation-to-all-items; leave some items uncovered;
   soft-delete one object), stub the judge provider (deterministic canned JSON keyed
   on sample-ordinal) via monkeypatch, run the runner, assert the report segments
   coverage by granularity, separates coverage vs fidelity seams (no blended number),
   and stamps version.

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
Clean-context agent review completed — verdict APPROVE-WITH-CHANGES. All three
required changes incorporated (per-sample distinct cache key; coverage segmented by
producer granularity, no blended rate; fidelity axis scoped to
unsupported-by-provided-context with a neighbor window) plus the demoted-rule and
judge-provider-coupling nice-to-haves. See `## Plan review` below.

**Approvals:**
Not required at this risk level (Elevated). Proceeding under the standing overnight
mandate to drive the next board item to completion.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

New offline package `evals/derivation_fidelity/` (no guarded path touched):
- `coverage.py` — pure. `LinkedObject`/`ItemRecord` reduce live rows to what coverage
  needs; `object_is_demoted` (soft-deleted OR lifecycle=='superseded'); `_classify`
  four states; `aggregate_coverage` emits TWO segmented lenses — `item_extraction`
  (source-item granularity) and `thread_aggregation` (thread granularity, folding in
  `consolidation`, deduped across the thread's items) — plus `pending_items`. No
  blended overall rate key (guard-tested).
- `fidelity.py` — pure. `FIDELITY_SCHEMA`/`FIDELITY_SYSTEM_PROMPT`;
  `build_fidelity_prompt(..., sample_ordinal)` embeds the ordinal so N samples get
  distinct `CachedLLMProvider` cache keys (marks LINKED vs CONTEXT turns);
  `compression_ratio` deterministic; `parse_fidelity_response` clamps/tolerates junk;
  `aggregate_fidelity` = strict-majority booleans + mean/median completeness + an
  agreement figure exposing residual variance; `derived_text_of` (write-time field
  priority); `extract_derivation_version` reads `envelope.derivation`.
- `runner.py` — read-only. `load_source_rows` = single STATIC parameterized SELECT
  (NULL bind disables a filter; S608-safe) on its own disposable engine; forward
  linkage via `list_memory_objects_for_source_items(include_candidates=True,
  include_soft_deleted=True)`; fidelity dedupes to active objects, gathers linked
  evidence + a bounded same-thread context window, runs the judge N× and aggregates;
  judge built DIRECTLY via `build_llm_provider` (+ optional `CachedLLMProvider`),
  degrading to coverage-only when LLM config is absent or errors. `main`/`build_parser`
  + `__main__.py`.
- `docs/context/validation.md` — one Eval Toolbox row.

Discovery deltas found during implementation (both were TEST-fixture issues, not
eval/production bugs, and are documented so the next agent doesn't re-hit them):
1. The storage codec drops a `MemoryEnvelope` on read unless its OWN
   `schema_id`/`schema_version` equal the canonical constants
   (`core.memory_envelope`/`v1`, `storage/sqlite_codec.py:31-32`). Real objects use
   them; the fixture now does too.
2. `create_memory_object` persists `lifecycle` but NOT `is_soft_deleted`; tombstoning
   is a separate `soft_delete_memory(id, reason=...)` call. The fixture uses it to
   exercise the `extracted_then_demoted` state via a real tombstone.

## Evidence

- New: `evals/derivation_fidelity/{__init__,coverage,fidelity,runner,__main__}.py`,
  `tests/test_derivation_fidelity.py` (14 tests), one `docs/context/validation.md` row.
- `python -m pytest tests/test_derivation_fidelity.py -q` → **14 passed**. Covers:
  four-state classification incl. mixed active/demoted → extracted; thread-producer
  coverage measured at thread granularity (NOT inflating the item lens); thread with
  no processed item excluded from the thread denominator; empty-data safety; no
  blended-rate key; deterministic compression + zero-safety; majority/median
  aggregation + tie→False + empty safety; junk-tolerant clamped parsing;
  distinct-prompt-per-ordinal; provenance extraction; and a runner test on a synthetic
  DB (real `SQLiteStorageProvider`) with a counting stub judge asserting seam
  separation, correct per-lens counts, version stamping, and — critically — 2 objects ×
  3 samples = **6 independent judge calls** (proving the cache/N-sample fix), plus a
  coverage-only run with judge=None.
- CLI smoke: `python -m evals.derivation_fidelity --help` parses.
- Full suite: `python -m pytest tests/ -q` → **3422 passed, 1 failed, 15 skipped, 2
  xfailed**. The single failure `tests/test_config.py::test_prompt_variants_legacy_
  fallback_unaffected` is the known pre-existing local-env artifact (fails on `main`,
  passes in CI), unrelated to this offline-only change; +14 new tests, no regression.

## Plan review

Clean-context reviewer (fresh subagent; read the Work Record + ticket + design 015 +
lessons.md, and verified every Discovery code claim against source). Verdict:
**APPROVE-WITH-CHANGES**. Discovery confirmed factually accurate (all cited
signatures/line-refs verified; all three ticket Done-When map to completion
criteria). Scope/guarded-path claim (read-only SQL selector, not a storage method)
judged defensible given strictly-SELECT enumeration.

Three required changes — all incorporated into the marker block before implementation:

1. **Cache vs N-sampling mutually defeating.** `CachedLLMProvider` key
   (`providers/llm/cached.py:106-116`) has no sample slot, so N identical judge
   prompts return byte-identical cache hits → majority/median is trivially sample 1
   and the ~20pp variance is left unaddressed while reported as handled. → Resolved:
   embed a sample-ordinal in each judge prompt so the N samples get distinct cache
   keys (genuinely independent draws, still reproducible per (prompt, ordinal)).
   Criterion 3 + Constraints updated; a unit test asserts N independent draws under a
   cache.
2. **Per-item coverage inflated for whole-thread producers.** `thread_summary` and
   knowledge/fact producers link the derived object to EVERY source item in the thread
   (`semantic/conversational_knowledge.py:501-511`,
   `agent_conversation_memory_threads.py:705-714`), so per-item coverage over-counts
   "extracted" for those types, and a single blended overall rate mixes two linkage
   semantics. → Resolved: coverage segmented by producer_kind granularity (item-level
   for `item_extraction`, thread-level for `thread_aggregation`/`consolidation`); no
   blended overall rate emitted. Criterion 1/2, Constraints, assumptions #2/#3 updated.
3. **"Unsupported claims" false positives.** `get_evidence_for_memory_object`
   (`sqlite.py:1200-1216`) returns only linked turns; a claim grounded in an adjacent
   non-linked turn would read as unsupported — worst for narrow-linkage per-item types.
   → Resolved: the judge is shown linked evidence PLUS a bounded same-thread neighbor
   window (marked context vs linked), and the axis is renamed
   **unsupported-by-provided-context** (not a raw hallucination rate). Constraints +
   criterion 1 updated.

Nice-to-haves incorporated: precise "demoted" definition (`is_soft_deleted` or
`lifecycle=='superseded'`; mixed active/demoted → `extracted`); judge provider built
directly via `build_llm_provider` (not `build_eval_providers`) to control the cache
key and avoid the default-package LLM-config coupling; report-time-model caveat kept
(per-object concrete model is not recoverable from the DB).
