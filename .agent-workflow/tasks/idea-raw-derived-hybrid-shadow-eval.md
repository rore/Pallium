# Task: idea-raw-derived-hybrid-shadow-eval

RAW / DERIVED / HYBRID retrieval + representation evaluation (Pallium vNext,
Continuous evaluation track — Experiment 3, retrieval-side seams).
Ticket: `roadmap/ideas/idea-raw-derived-hybrid-shadow-eval.md`.
Execution context: `docs/designs/015-vnext-historical-work-execution.md`
(Continuous evaluation track). Paired with the merged `idea-derivation-fidelity-eval`
(derivation-side seams).

<!-- agent-workflow:start -->
**Outcome:**
An offline eval exists that, on REAL historical lookups, constructs three
candidate arms — RAW (source turns), DERIVED (memory objects), HYBRID (mixed) — by
REPLAYING each query through the shipped retrieval stack at candidate level
(`target_kind="source_item"` / `"memory_object"` / mixed), and measures the two
retrieval-time seams a shadow can honestly measure: (1) derived-retrieval / candidate
recovery — did the relevant RAW source vs the relevant DERIVED object enter its arm's
candidate set? — and (2) representation quality — holding information + retrieval
constant, is the rendered DERIVED text correct or misleading/unsupported vs the RAW
turns? Context cost is compared at EQUAL token budget (or as a quality-vs-token
curve) so HYBRID can't win by receiving more context. Each result names the seam,
stores the raw fusion score + source ids/ranks (so the RAW arm is reconstructable),
and records the DERIVED objects' derivation schema/prompt-variant/producer-role.
Downstream/consumption is explicitly OUT (a shadow arm is never shown to the agent).
No production coupling; pure scoring functions unit-tested; a runner path exercised
against a synthetic DB with a stub judge.

**Target:**
pallium

**Scope:**
New package `evals/raw_derived_hybrid/` (`__init__.py`, `arms.py` — pure arm
assembly + candidate-recovery + equal-token-budget scoring, `represent.py` — judge
prompt/schema + pure representation-quality aggregation, `runner.py` — offline
retrieval construction + query replay + orchestration + report, `__main__.py`). New
tests `tests/test_raw_derived_hybrid.py`. One `docs/context/validation.md` Eval
Toolbox row. Reuse: `app.dependencies.build_service`/`build_retrieval_provider` to
construct retrieval offline; `retrieval` provider's `target_kind` (shipped P1);
`evals/derivation_fidelity/fidelity.py` (`extract_derivation_version`, and the
misleading/unsupported judge pattern); `_estimate_tokens` (`ceil(len/4)`) token
model. NOT: any change under a guarded path (`api/ app/ capabilities/ core/
providers/ redaction/ retrieval/ semantic/ storage/`); NO live shadow seam in
`core/query.py`, NO `core/service.py` wiring, NO new `ObservabilityConfig` flag, NO
new storage table (see Plan — deliberate deviation from the ticket's suggested
"subtask_selector_shadow seam" mechanic); NO downstream/consumption measurement; NO
change to derivation/retrieval; NO synthetic benchmark to prove derived superior.

**Constraints:**
Offline + data-read-only: never affects live injection/output (satisfies "shadow-only"
without a live seam). The `SQLiteStorageProvider` constructor performs idempotent
schema-ensure/PRAGMA on init — no row writes (same footprint as the fidelity runner).
RAW arm is candidate-level source-only (`target_kind=
"source_item"` — derived objects excluded BEFORE selection, not post-filtered), so
RAW-vs-DERIVED isn't confounded by derived content leaking into the RAW pool.
Context cost compared at EQUAL token budget (truncate each arm's rendered context to
the same estimated-token budget before the quality judge) or reported as a
quality-vs-token curve — HYBRID must not win merely by receiving more context. Every
number labelled by seam (candidate-recovery vs representation-quality) and never
conflated with downstream/consumption or with end-to-end accuracy
(`docs/context/lessons.md`). Judge variance (~20pp) handled by N independent samples
(distinct per-sample cache key, as in the fidelity eval) + `CachedLLMProvider`;
single-sample numbers not reported as ground truth. DERIVED-arm objects stamped with
`envelope.derivation` version; concrete model resolved at report time with the
per-object-model caveat. Store raw fusion score + source ids/ranks per RAW arm so it
is reconstructable. No internal/external product names in committed code/tests
(domain-neutral synthetic fixtures only).

**Completion criteria:**
1. `python -m evals.raw_derived_hybrid --db <path>` replays a set of real historical
   queries (from `query_audit_log`, filterable to agent-pull lookups) and emits, per
   lookup + aggregate: the three arms' candidate ids/ranks/fusion scores; an OBJECTIVE
   evidence-link candidate-recovery comparison (for each DERIVED object, did its linked
   source turns enter RAW and did the object enter DERIVED → RAW-only/DERIVED-only/both);
   query-conditioned representation-quality aggregates on the DERIVED arm
   (misleading/unsupported-vs-retrieved-RAW rate, judged usability) ; and context cost
   at equal token budget. → runner test against a synthetic DB with a stub judge.
2. Arms are built at CANDIDATE level via `target_kind` (RAW=source_item,
   DERIVED=memory_object, HYBRID=mixed); the RAW arm contains NO memory objects. →
   unit + runner test asserting arm purity.
3. Equal-token-budget comparison is pure and deterministic: given per-arm rendered
   items + a token budget, it truncates by the `ceil(len/4)` estimate to the same
   budget AT ITEM BOUNDARIES (drops whole items that don't fit, never splits one) and
   reports each arm's retained item count + tokens; a unit test covers the RAW
   (many-small) vs DERIVED (few-dense) asymmetry. This axis is NOT fed into the
   representation judge (which sees full retrieved RAW turns). → unit test.
4. Representation-quality judge aggregation is pure: N independent samples (distinct
   cache key per sample), majority booleans + mean/median scores, empty-data-safe;
   the axis is "misleading/unsupported vs provided RAW turns", not a raw hallucination
   rate. → unit test (incl. N-independent-draw-under-cache).
5. Every emitted metric names its seam (candidate-recovery vs representation-quality)
   and the report carries the DERIVED derivation version + report-time model; no
   blended "derived is better" number and no downstream/consumption claim. → assertion
   in runner test + doc note.

**Risk:** Elevated

**Complexity:** Large

**Reason:**
Redline: all intended paths are blue — confined to `evals/` + `tests/` + one doc row;
no guarded path and no RED contract/persistence/security surface. (This is the direct
consequence of the offline-replay scoping decision below: the ticket's suggested live
`subtask_selector_shadow` seam would touch `core/query.py` [watch], `core/service.py`
[RED architecture-review] and add a storage table [persistence] — pushing toward High
and a human-approval gate. Offline replay achieves the same MEASUREMENT with zero
production surface.) Baseline Routine; RAISED to Elevated by judgment: a measurement
instrument feeding strategy decision-point 3 (keep-or-simplify derivation) with an LLM
judge whose variance must be handled — a wrong number misleads the decision. LARGE
complexity: offline retrieval construction + three-arm replay + candidate-recovery +
equal-token-budget + representation judge + report + tests.

**Discovery:**
- `app.dependencies.build_retrieval_provider(storage)` (`app/dependencies.py:305`)
  and `build_service(config, enable_vector=)` (`:309`) construct the retrieval stack
  offline (no FastAPI). The composite `retrieval.query(..., target_kind=...)` (shipped
  P1) filters to a kind at CANDIDATE level (lexical pushes into SQL; vector over-fetches
  then skips other kinds before threshold) — so RAW=source_item / DERIVED=memory_object
  / HYBRID=mixed are all candidate-level, not post-filtered.
- **BLOCKER (why replay, not mine-audit):** the stored audit CANNOT reconstruct a RAW
  arm — `query_audit_log.candidate_scores_json` records `memory_object_id` only (no
  `source_item_id`/`raw_rank`), and `source_only` queries write no candidate snapshot.
  So the eval must RE-RUN retrieval (replay), which is also the correct semantics for
  evaluating current/new derivation variants. (Confirmed via landscape investigation.)
- The live-seam alternative (`subtask_selector_shadow` template) attaches in
  `core/query.py`'s routed branch only (source_only returns earlier), is threaded via
  `core/service.py` (RED) + `app/config.py` flag + `app/dependencies.py` + a new
  `storage` table — multiple guarded/persistence surfaces. Deliberately NOT taken (see
  Plan / assumption 1).
- Reuse: `evals/derivation_fidelity/fidelity.py` — `extract_derivation_version`,
  `parse_fidelity_response`/`aggregate_fidelity` pattern, distinct-per-sample cache
  key, and the misleading/unsupported judge shape. `_estimate_tokens=ceil(len/4)`
  (`semantic/agent_conversation_memory_subtask_selector_shadow.py:133`) is the repo's
  token model (no tiktoken); no shared helper — duplicate locally in the eval.
- Historical queries live in `query_audit_log` (query_text, container_ref, thread_ref,
  actor_ref, visibility, trigger_origin). agent-pull lookups are `trigger_origin in
  {agent_pull, mcp_pull}`.
- `evals/retrieval_ablation/` is the sibling A/B precedent (variant→metrics→report),
  but it reads `candidate_scores_json` (memory-only) and cannot host a RAW arm; this is
  a new package rather than a variant bolt-on (its data source can't carry source ids).

**Material assumptions:**
1. Assumption: offline REPLAY (re-run retrieval per historical query) is an acceptable
   substitute for the ticket's suggested live shadow seam, and is preferable because it
   (a) resolves the RAW-not-reconstructable blocker, (b) keeps the change out of guarded
   paths (no High/approval gate), and (c) evaluates current/new derivation — which is
   what decision-point 3 needs. Evidence to disprove: user/reviewer specifically wants
   arms captured at live query time (e.g. to measure the exact production candidate pool
   including routing effects). Action: STOP; the live seam is a separate,
   guarded/High-risk item needing human approval — surface for the user rather than
   building it autonomously.
2. Assumption: candidate-recovery uses a SYMMETRIC signal across both arms — the
   PRIMARY metric is the objective, judge-free derivation EVIDENCE LINK: for each
   DERIVED object, resolve its linked `source_item_id`s via
   `get_evidence_for_memory_object`, then ask "did those source turns enter the RAW
   arm, and did the object enter the DERIVED arm?" (RAW-only vs DERIVED-only vs both
   recovery of the same underlying episode). `memory_feedback` is DERIVED-side only
   (no source column, `storage/sqlite_schema.py:319-334`) → demoted to a SECONDARY
   signal, never mixed as the primary recovery label. Disproof: evidence links are too
   sparse in the corpus to compute recovery. Action: fall back to descriptive
   RAW-vs-DERIVED candidate-set overlap and mark recovery advisory.
3. Assumption: equal-token-budget truncation on the `ceil(len/4)` estimate is a fair
   context-cost control. Disproof: reviewer wants real tokenizer counts. Action: note
   the estimate; the comparison is relative, not absolute.
4. Assumption: replaying against the CURRENT index/config (not query-time state) is
   correct for a derivation A/B. Disproof: user wants point-in-time replay. Action:
   document; point-in-time needs the live-seam item.

**Plan:**
Sequence (all under `evals/raw_derived_hybrid/` unless noted):
1. `arms.py` — pure: `Arm`/`Candidate` structs; `partition_candidates` guarding RAW
   purity (no memory objects in the RAW arm); `evidence_link_recovery(raw_ids,
   derived_objs_with_evidence)` → for each DERIVED object, whether its linked source
   turns entered RAW and whether the object entered DERIVED (RAW-only / DERIVED-only /
   both), the objective symmetric recovery metric; `equal_token_budget(items, budget)`
   → deterministic `ceil(len/4)` truncation at ITEM BOUNDARIES (drop whole items that
   don't fit, never split), returning retained-count + total tokens (a
   quality-vs-token point; the runner may sweep several budgets for a coarse curve).
2. `represent.py` — `REPRESENTATION_SCHEMA` + `build_representation_prompt(query,
   raw_turns, derived_text, *, sample_ordinal)` where `raw_turns` are the FULL
   retrieved RAW turns (generously per-turn-capped like fidelity's 800 chars), NOT the
   token-budget-truncated set — the judge scores, query-conditioned, whether the
   DERIVED text is a correct/non-misleading answer surface FOR THIS LOOKUP vs the
   retrieved RAW turns (retrieval-conditioned usability), which is DISTINCT from the
   merged fidelity eval's query-agnostic source-fidelity axis (this eval does not
   re-publish a source-fidelity unsupported rate). `aggregate_representation(samples)`
   (majority/median + agreement, N independent samples w/ distinct per-sample cache
   key); reuse `extract_derivation_version`. Pure.
3. `runner.py` — offline: `build_service`/retrieval construction from `--db`+config
   (vector optional); load historical queries from `query_audit_log`
   (`--trigger-origin`, default `{agent_pull,mcp_pull}` with a report caveat that this
   may include proactive MCP pulls; `--limit`, seeded sample); for each: call
   `retrieval.query(target_kind=...)` three times → arms with ids/ranks/fusion scores;
   resolve DERIVED objects' evidence via `get_evidence_for_memory_object` → evidence-link
   recovery; render each arm, equal-token-budget compare (separate axis, NOT fed to the
   judge); representation judge on DERIVED vs FULL retrieved RAW (judge built directly
   via `build_llm_provider` + optional `CachedLLMProvider`; degrade to no-judge); stamp
   derivation version + report-time model; write JSON to `--out` with a header caveat
   that arms were REPLAYED against the CURRENT index/config (not the point-in-time
   pool). `main`/`build_parser` + `__main__.py`.
4. `docs/context/validation.md` — one Eval Toolbox row. Also add a Notes line to the
   roadmap ticket reconciling the deviation (new package, not a `retrieval_ablation`
   variant, because that harness's `candidate_scores_json` data source is memory-only
   and cannot host a RAW arm).
5. `tests/test_raw_derived_hybrid.py` — pure units (arm purity / no memory in RAW;
   evidence-link recovery RAW-only/DERIVED-only/both; equal-token-budget boundary
   truncation incl. the RAW-many-small vs DERIVED-few-dense asymmetry case; empty
   safety; representation aggregation incl. N-independent-draw-under-cache; provenance)
   + a runner test on a synthetic DB (real storage + lexical-only retrieval, vector
   disabled) with a stub judge: ingest source turns + linked memory objects, replay a
   query, assert RAW arm has no memory objects, three arms produced, evidence-link
   recovery computed, seam-labelled report with version stamp + current-index caveat,
   and NO blended/downstream number.

Scoped OUT (deliberate, consistent with downstream/consumption being out): actually
RE-DERIVING new derivation variants and scoring them (ticket In-Scope "evaluate new
derivation variants" / Done-When 3 second clause). This eval STAMPS the derivation
version so variants are DISTINGUISHABLE and the harness is variant-ready, but swapping
the DERIVED arm for freshly re-derived objects requires parameterizing the derivation
pipeline — a separate follow-up. Recorded so Done-When 3 is not overclaimed.

Conventions: seam-explicit labels (`lessons.md`); domain-neutral fixtures (AGENTS.md);
pure-scoring + IO separation (derivation_fidelity precedent).

Stop conditions: if offline retrieval construction can't reproduce candidate-level
arms without a guarded-path change → STOP, reconsider. If the user requires the live
seam (assumption 1 disproved) → STOP, surface as a separate High-risk item.

**Verification plan:**
1. Pure arm units — RAW purity (no memory objects), candidate-recovery RAW-only/DERIVED-only/both, empty safety (criteria 2) -> `pytest tests/test_raw_derived_hybrid.py -q`
2. Equal-token-budget truncation is deterministic and budget-respecting (criterion 3) -> `pytest tests/test_raw_derived_hybrid.py -q`
3. Representation aggregation pure: N independent samples (distinct cache key), majority/median, empty safety (criterion 4) -> `pytest tests/test_raw_derived_hybrid.py -q`
4. Report names each seam, stamps DERIVED derivation version + report-time model, emits no blended/downstream number (criteria 1,5) -> runner test on synthetic DB with stub judge
5. No production regression (offline-only change) -> `pytest tests/ -q` (expect only the pre-existing `test_config` failure)
6. CLI parses and a `--limit 3` dry run emits a well-formed report on a local DB -> manual: non-gating smoke, numbers not asserted (real judge stochastic)

**Plan review:**
Clean-context agent review completed — verdict APPROVE-WITH-CHANGES. CRUCIALLY it
confirmed the offline-replay scoping is SOUND and the live `subtask_selector_shadow`
seam is NOT required (no High-risk / human-approval stop condition; the
RAW-not-reconstructable-from-audit claim was independently verified, as was offline
retrieval feasibility). All seven required changes incorporated (symmetric recovery
labeling via the derivation evidence link; representation judge sees full RAW turns
decoupled from token-budget truncation; item-boundary truncation; axis delineation
vs the fidelity eval; new-variant re-derivation scoped OUT with a pointer;
current-index caveat). See `## Plan review` below.

**Approvals:**
Not required at this risk level (Elevated). Proceeding under the standing overnight
mandate to drive the next board item to completion. NOTE: if the clean-context review
or CI redline determines the live-seam mechanic is required (making this a
guarded/High change), that needs human approval — STOP and surface, do not self-approve.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Built the new offline package `evals/raw_derived_hybrid/` exactly per the Plan,
mirroring `evals/derivation_fidelity`'s pure-scoring + IO-separation structure.

- `arms.py` (pure, DB-free/LLM-free): `Candidate`/`Arm`/`DerivedObjectEvidence`
  structs; `partition_candidates(name, candidates)` assembles an arm and HARD-ERRORS
  if a memory object leaks into RAW (purity re-asserted, not assumed);
  `evidence_link_recovery(raw_source_ids, derived_objs_with_evidence)` — the objective
  symmetric metric labelling each episode both/raw_only/derived_only/neither;
  `equal_token_budget(items, budget)` — deterministic `ceil(len/4)` truncation at item
  boundaries (drops whole items, never splits), returns retained count + total tokens;
  `estimate_tokens` duplicated locally (no shared helper, per Discovery).
- `represent.py` (pure): `REPRESENTATION_SCHEMA` + system prompt;
  `build_representation_prompt(query, raw_turns, derived_text, *, sample_ordinal)`
  (raw_turns = FULL retrieved RAW turns, per-turn-capped 800, distinct per-sample cache
  key); `RepresentationSample`/`parse_representation_response`;
  `aggregate_representation` (majority bool + mean/median usability + agreement, empty
  safe). Axis is query-conditioned answer-surface usability/misleadingness vs the
  RETRIEVED RAW arm — NOT a source-fidelity re-measurement. `extract_derivation_version`
  re-imported from `evals.derivation_fidelity.fidelity`.
- `runner.py`: offline retrieval built via `build_storage_provider(config)` +
  `build_retrieval_provider(storage)` (config pointed at `--db` via
  `dataclasses.replace`; frozen AppConfig). Historical queries loaded read-only from
  `query_audit_log` via a single static parameterized SELECT (expanding IN bind for
  `--trigger-origin`, default `agent_pull/mcp_pull`; `all` disables). Per query: 3
  replays with `target_kind` source_item/memory_object/None → arms with
  ids/ranks/fusion scores; DERIVED evidence resolved via
  `get_evidence_for_memory_object`; recovery universe unions DERIVED-arm objects with
  objects linked to RAW-arm source turns (via `list_memory_objects_for_source_items`)
  so all four recovery labels are reachable; equal-token-budget over rendered arm items
  (separate axis, not judged); representation judge on each DERIVED object vs FULL RAW
  turns (N samples, `--judge-samples` default 3; degrades to no-judge). Report stamps
  derivation version per object + report-time model, seam_note, and header caveats
  (current-index replay, agent-pull-may-include-MCP-pulls, token-estimate).
  `main(argv)`/`build_parser()` + `__main__.py`.
- `docs/context/validation.md`: one new Eval Toolbox row (mirrors the
  derivation_fidelity row style).
- `roadmap/ideas/idea-raw-derived-hybrid-shadow-eval.md`: one Notes line reconciling
  the new-package-vs-`retrieval_ablation`-extension deviation. Frontmatter `status`
  left `in-progress` (untouched).

Discovery deltas (no Plan deviation, additive detail):
- Retrieval `query(...)` signature/return type confirmed (see Evidence). Fusion score
  is `QueryResultItem.score`; candidate id is `source_item_id` (source_hit) or
  `memory_object_id` (memory_hit); rank = 1-based order in `results`.
- `run_eval` gained an optional `queries: list[QueryRow]` param so the runner can be
  tested without seeding `query_audit_log` (the synthetic-DB test seeds one audit row
  via `write_query_audit_row` AND also covers the explicit-queries bypass).
- `memory_feedback` secondary signal (WR assumption 2) intentionally NOT consumed —
  it is a DERIVED-only signal, demoted to advisory, and is not required by any
  Completion criterion; noted in `seam_note`/caveats rather than mixed into recovery.

## Evidence

Files created:
- `evals/raw_derived_hybrid/__init__.py`
- `evals/raw_derived_hybrid/arms.py`
- `evals/raw_derived_hybrid/represent.py`
- `evals/raw_derived_hybrid/runner.py`
- `evals/raw_derived_hybrid/__main__.py`
- `tests/test_raw_derived_hybrid.py`

Files edited (allowed blue paths only):
- `docs/context/validation.md` (one Eval Toolbox row)
- `roadmap/ideas/idea-raw-derived-hybrid-shadow-eval.md` (one Notes line; status untouched)

Tests: `tests/test_raw_derived_hybrid.py` — **19 passed** (arm purity + target_kinds;
recovery both/raw_only/derived_only/neither + no-evidence + empty; equal-token-budget
item-boundary + RAW-many-small-vs-DERIVED-few-dense asymmetry + empty; representation
aggregation + parse + distinct-per-ordinal prompt + provenance; N-independent-draws
under real `CachedLLMProvider` (misses==N/hits==0); runner three-arms/purity/recovery/
seam-labels/no-blended-number + no-judge degrade + cached independent draws + explicit
queries bypass). Run:
`PYTHONPATH=".local/test-env/site-packages;." <cpython-3.13> -m pytest tests/test_raw_derived_hybrid.py -q` → `19 passed`.
`python -m evals.raw_derived_hybrid --help` parses.
Full suite: `3443 passed, 1 failed (pre-existing unrelated test_config), 15 skipped, 2 xfailed` — no regression.

Discovered retrieval signature (P1 `target_kind`):
```
RetrievalProvider.query(
    text: str, limit: int, filters: QueryFilters | None = None, *,
    visibility: str | None = None, query_container_ref: str | None = None,
    include_trace: bool = False, require_visibility: bool = False,
    query_actor_ref: str | None = None, target_kind: str | None = None,
) -> RetrievalQueryResult
```
Return type `RetrievalQueryResult(results: list[QueryResultItem], trace: QueryTrace | None)`.
`target_kind="source_item"` (RAW) / `"memory_object"` (DERIVED) / `None` (HYBRID) filters
at the SQL/candidate level (`storage/sqlite_search.py`: two fixed statements before the
LIMIT), so arms are candidate-level, not post-filtered.

## Plan review

Clean-context reviewer (fresh subagent; verified every load-bearing claim against
source). Verdict: **APPROVE-WITH-CHANGES**. Headline: **offline-replay scoping is
SOUND; the live seam is genuinely NOT required** for this ticket's intent, so no
High-risk/human-approval stop condition triggers. Verified: `candidate_scores_json`
is memory-object-only (no `source_item_id`/`raw_rank`, `core/service.py:1207-1233`);
`source_only` writes no candidate snapshot (`core/query.py:126-162,226`); design 015
states the same gap (`:76-79`); offline retrieval construction + candidate-level
`target_kind` filtering all confirmed. Redline blue confirmed (reads guarded paths,
edits none). Seven required changes — all incorporated:

1. **Recovery label symmetry** — `memory_feedback` is DERIVED-only (no source column);
   mixing it with a RAW judge biases the metric. → Primary recovery metric is the
   objective, judge-free derivation EVIDENCE LINK (assumption 2, Plan step 1);
   `memory_feedback` demoted to a secondary DERIVED-side signal.
2. **Evidence-link co-recovery** — use `get_evidence_for_memory_object` to make
   RAW-only-vs-DERIVED-only an objective correspondence. → Plan step 1 + criterion 1.
3. **Decouple judge input from budget truncation** — judge sees FULL retrieved RAW
   turns, never the token-budget-truncated set (else false "unsupported"). → represent.py.
4. **Item-boundary truncation** — `equal_token_budget` drops whole items, never splits;
   asymmetry unit test added. → criterion 3 + Plan.
5. **Axis delineation vs fidelity eval** — this eval's axis is query-conditioned
   usability/misleadingness vs the RETRIEVED RAW arm (retrieval-conditioned), distinct
   from fidelity's query-agnostic source-fidelity; no re-publishing a source-fidelity
   rate. → represent.py + reciprocal seam_note.
6. **Done-When 3 variant-eval gap** — recording a version ≠ evaluating a re-derived
   variant. → Actual re-derivation scoped OUT with rationale + follow-up pointer
   (harness is variant-ready via version stamping); Done-When 3 not overclaimed.
7. **Current-index caveat** — report header states arms were replayed against the
   current index/config, not the point-in-time pool. → runner.py.

Nice-to-haves incorporated: agent-pull filter caveat (may include proactive MCP pulls)
in the report; "data-read-only, init ensures schema" wording softened; roadmap-ticket
Notes line reconciling the `retrieval_ablation`-extension deviation (new package
because that harness's data source is memory-only). "Curve" softened to equal-budget
point(s) with an optional multi-budget sweep.

## Result review

Independent clean-context reviewer (fresh subagent; verified every load-bearing claim
against source, re-ran the tests). Verdict: **PASS-WITH-NITS** — all 7 plan-review
changes verified correct, and every hard-correctness/safety check passed (pure modules
genuinely DB/LLM-free; N-independent-draw under a real `CachedLLMProvider`; read-only
with engine disposal; graceful judge-failure/empty degrade; scope clean; Done-When
covered, DW3 honestly deferred). No must-fix. Three non-blocking nits — all addressed
because two touch headline-metric fairness:

1. **Inconsistent RAW rendering in the equal-token-budget axis** — RAW fed *uncapped*
   turns to the cost axis while HYBRID capped source turns at 800, so a long source turn
   counted with different token weight in RAW vs HYBRID, skewing the "equal budget" the
   axis exists to guarantee. → Fixed: the cost axis now renders RAW through the SAME cap
   as HYBRID (`_render_arm_items`); the judge still receives the full uncapped turns.
2. **Recovery universe included soft-deleted/candidate objects** — a tombstoned object
   linked to a RAW source can never enter the DERIVED arm, so it was always labelled
   `raw_only`, inflating RAW's apparent recovery advantage. → Fixed:
   `build_recovery_universe` now restricts the RAW-linked object set to retrievable
   lifecycles (`include_candidates=False, include_soft_deleted=False`). New test
   `test_recovery_universe_excludes_tombstoned_objects` locks this in.
3. **`main()` didn't dispose the storage engine** — tidy-up only. → Fixed: best-effort
   `engine.dispose()` in a `finally`.

Post-fix: `tests/test_raw_derived_hybrid.py` = **19/19 pass** (added the tombstone test);
full suite green (1 pre-existing unrelated failure).
