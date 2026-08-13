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
Offline + read-only: never affects live injection/output (satisfies "shadow-only"
without a live seam). RAW arm is candidate-level source-only (`target_kind=
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
   lookup + aggregate: the three arms' candidate ids/ranks/fusion scores, a
   candidate-recovery comparison (RAW-only vs DERIVED-only recovery of a
   relevance-labelled target), representation-quality aggregates on the DERIVED arm
   (misleading/unsupported rate, judged relevance) vs RAW, and context cost at equal
   token budget. → runner test against a synthetic DB with a stub judge.
2. Arms are built at CANDIDATE level via `target_kind` (RAW=source_item,
   DERIVED=memory_object, HYBRID=mixed); the RAW arm contains NO memory objects. →
   unit + runner test asserting arm purity.
3. Equal-token-budget comparison is pure and deterministic: given per-arm rendered
   items + a token budget, it truncates by the `ceil(len/4)` estimate to the same
   budget and reports each arm's retained item count + a quality-vs-token point. →
   unit test.
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
2. Assumption: a usable relevance signal for candidate-recovery exists offline
   (per-query: the source/derived item(s) judged relevant to the lookup). Options: reuse
   `memory_feedback` where present, else an offline relevance judge over the query +
   candidate. Disproof: neither yields a defensible label. Action: report
   candidate-recovery as RAW-only-vs-DERIVED-only OVERLAP/diff (descriptive) rather than
   recall-vs-gold, and mark relevance advisory.
3. Assumption: equal-token-budget truncation on the `ceil(len/4)` estimate is a fair
   context-cost control. Disproof: reviewer wants real tokenizer counts. Action: note
   the estimate; the comparison is relative, not absolute.
4. Assumption: replaying against the CURRENT index/config (not query-time state) is
   correct for a derivation A/B. Disproof: user wants point-in-time replay. Action:
   document; point-in-time needs the live-seam item.

**Plan:**
Sequence (all under `evals/raw_derived_hybrid/` unless noted):
1. `arms.py` — pure: `Arm`/`Candidate` structs; `partition_candidates` guarding RAW
   purity (no memory objects); `candidate_recovery(raw, derived, relevant_ids)` →
   RAW-only vs DERIVED-only vs both recovery of the relevance target;
   `equal_token_budget(items, budget)` → deterministic `ceil(len/4)` truncation +
   retained-count + total-token point (quality-vs-token).
2. `represent.py` — `REPRESENTATION_SCHEMA` + `build_representation_prompt(query,
   raw_turns, derived_text, *, sample_ordinal)` (judge: is the DERIVED text
   misleading/unsupported vs the RAW turns, and relevant to the query?);
   `aggregate_representation(samples)` (majority/median, agreement); reuse
   `extract_derivation_version` from the fidelity eval. Pure.
3. `runner.py` — offline: `build_service`/retrieval construction from `--db`+config
   (vector optional); load historical queries from `query_audit_log`
   (`--trigger-origin`, `--limit`, seeded sample); for each: call
   `retrieval.query(target_kind=...)` three times → arms with ids/ranks/fusion scores;
   candidate-recovery (assumption 2); render each arm, equal-token-budget compare;
   representation judge on DERIVED vs RAW (judge built directly via `build_llm_provider`
   + optional `CachedLLMProvider`; degrade to no-judge); stamp derivation version +
   report-time model; write JSON to `--out`. `main`/`build_parser` + `__main__.py`.
4. `docs/context/validation.md` — one Eval Toolbox row.
5. `tests/test_raw_derived_hybrid.py` — pure units (arm purity, candidate-recovery,
   equal-token-budget truncation, representation aggregation incl. N-independent-draw,
   provenance) + a runner test on a synthetic DB (real storage + lexical-only retrieval,
   vector disabled) with a stub judge: ingest source turns + create linked memory
   objects, replay a query, assert RAW arm has no memory objects, three arms produced,
   seam-labelled report, no blended/downstream number, version stamped.

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
Pending — Elevated requires a clean-context agent review before implementation
(must specifically pressure-test the offline-replay-vs-live-seam scoping decision and
the candidate-recovery relevance signal). Verdict + reference recorded under
`## Plan review`.

**Approvals:**
Not required at this risk level (Elevated). Proceeding under the standing overnight
mandate to drive the next board item to completion. NOTE: if the clean-context review
or CI redline determines the live-seam mechanic is required (making this a
guarded/High change), that needs human approval — STOP and surface, do not self-approve.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

(pending plan review, then implementation)
