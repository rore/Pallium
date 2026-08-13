# Pallium vNext — Historical Agent Work: Execution Plan

Date: 2026-08-12
Status: Accepted direction (execution plan for [strategy-vnext](../context/strategy-vnext.md))

## Purpose

Translate the vNext strategy — *"Pallium makes prior agent work usable across
agent contexts, sessions, agents, and users"* — into an executable, phased plan
grounded in the current architecture. This doc owns the **phasing, dependencies,
success gates, and architecture rationale**. Item-level scope lives in the
`roadmap/` items this doc references; the near-term narrative lives in
`roadmap/scope.md`.

## Operating principles

1. **Experiment-gated phases.** Each phase is gated by one of the strategy's four
   live experiments. A phase must pass its gate before the next earns
   significant investment. We are validating a thesis, not shipping a backlog.
2. **Raw history is the baseline; derived memory is an evaluated optimization
   layer.** We do not remove derivation and we do not assume it. It earns
   responsibility only where it beats RAW/HYBRID on a measured dimension.
3. **Primary KPI: confirmed historical-reuse events per 100 substantive
   sessions** (history retrieved *and* materially used). Retrieval Recall@K is an
   offline capability metric, not the product-success metric.
4. **Hard invariant across every phase: visibility violations = 0.**
5. **Corpus analysis is exhausted for these questions; the open questions are
   behavioral and require live usage.** (See the empirical basis below.)

## Empirical basis (why this plan)

Established by read-only studies over the real local corpus:

- Useful cross-session history exists for **~38% of real prompts**, and **~88% of
  that useful history is experiential**, not reconstructable from code.
- **Raw hybrid history search is already strong**: ~83% top-5, ~97% top-10 on
  clear historical opportunities — and current derived memory did **not** beat it
  on recall.
- As a consumption representation, current derivation gives only ~2.8×
  compression at ~29% fully-complete and ~29% misleading.
- Cross-session transfer is common but **orchestrated manually today** (the user
  asks the agent to summarize, or points it at another session/file); Pallium is
  not the channel. Cross-*agent* transfer is real but rare in this corpus and is
  workflow-dependent — not a frequency we can assume.

## Current architecture grounding

What already exists that this plan builds on (with the gaps each phase closes):

- **Raw turns are already a searchable substrate that routing already touches.**
  Every ingested source turn is lexically + vector indexed (`core/service.py`,
  `core/vector_embed.py`); `source_hit` is a real result kind with excerpt +
  provenance (`retrieval/lexical.py`); container/thread/actor/visibility scoping and
  `source_type`/`role`/`artifact_kind`/`work_refs` filters are plumbed end-to-end
  (`core/query.py`, `core/filters.py`, `api/`). Routing already **scores and selects
  source hits**, not just memory objects: `_specificity_bonus_source_hit`
  (`semantic/agent_conversation_memory_routing_scoring.py`), a reserved
  `MIN_SOURCE_HIT_SLOTS` in recall selection, and work-resumption source companions
  (`semantic/agent_conversation_memory_routing_selection.py`). **Gap:** raw turns
  compete in a *mixed* candidate pool and are then subject to memory-oriented
  routing/injection policy, where memory objects can starve raw candidates; there is
  no source-only retrieval target that ranks raw turns on their own before
  top-K/fusion, and no agent-facing tool to invoke one. The fix is a source-only
  target that **reuses** the existing lexical/vector fusion, visibility, filtering,
  redaction, and trace infrastructure — not a second retrieval stack.
- **Shadow-experiment harness pattern exists and is removable.** The
  `subtask_selector_shadow` runner attaches at a single seam in
  `core/query.py`, gated by an `ObservabilityConfig` flag, dispatches off the hot
  path, and writes a side table — never touching `should_inject`. This is the
  template for the RAW/DERIVED/HYBRID shadow. `evals/retrieval_ablation/` is an
  existing offline replay A/B harness to extend.
- **Reuse-funnel telemetry is partial.** `query_audit_log` (with `trigger_origin`),
  `memory_usage_audit` (`referenced_in_next_turn`, populated by the claude/codex
  stop-hook matcher), `memory_feedback`, and `metrics` exist; fusion scores already
  ride result objects and the audit serializes score/lexical/vector fields.
  **Gaps:** MCP tools don't distinguish an agent-initiated pull from proactive
  injection; there is no stable `lookup_event_id`, and the audit snapshot lacks
  reconstructable *source identity + raw rank* (so a RAW arm can't be rebuilt from
  history); expansion has no parent-lookup link; there is no "eligible session"
  denominator or tool-exposure population; `referenced_in_next_turn` captures
  *citation*, not *material use*; and there is no cross-agent/cross-user or
  continuation-success dimension. Whether the *user directed* a lookup vs the agent
  *decided* on its own is not a deterministic tool property — it must be judged
  retrospectively from the preceding conversation.
- **Continuity primitives are strong within a thread, weaker across sessions.**
  `work_refs` cross-surface continuity is shipped (cross-thread affinity +
  packaging); `task_checkpoint`/`thread_summary`/`continuity_memory` ship. **Gap:**
  each new session mints a fresh `thread_ref`, so the `resumed_session` fast-path
  does not fire for genuinely new sessions; cross-session relies on
  container-scoped retrieval + work_ref affinity. Cross-*agent* (Claude↔Codex)
  continuity is *emergent* from shared `container_ref`/`actor_ref` — `agent_ref`
  is stored but is not a routing/handoff dimension, and there is no explicit
  handoff packaging.
- **Sharing foundation Phase 1 shipped, but is not a cross-user sharing contract.**
  `visibility_context` + enforce-before-ranking are in (`core/visibility.py`,
  design 007). **Gap:** current enforcement has no per-user grant — a public
  candidate requires `actor_ref is None` (`core/visibility.py`), which raw source
  items (they keep their producer actor) do not satisfy; a private/unspecified query
  sees *everything in the same container regardless of actor* (container-wide, not
  consented per user); and actor filters exclude another user's raw sources
  (`core/filters.py`). So cross-user raw sharing needs an explicit
  authorization/grant contract (consent, target audience, revocation, provenance,
  access audit, fail-closed) — **not** merely a vocabulary reconciliation, and not a
  derived shared object. Explicit shared-derived-memory objects (design 007 Phase 2)
  and bounded cross-container reuse (Phase 3) remain unbuilt and are now downstream
  of a demonstrated raw cross-user value result.

## Guarded-path note

Phase 0+ touch guarded paths — `core/service.py` (red), `core/query.py` (watch),
plus `core/visibility.py`, `core/filters.py`, `api/` and `storage/`. Per repo rule,
**each implementation slice starts by invoking `/agent-workflow`** (writes the Work
Record, classifies risk) before any code edit. This plan is documentation and needs
no Work Record; the *items* do.

---

## Phase 0 — Measurement contract & raw-history governance

**Not experiment-gated; it is the prerequisite that makes Phase 1's experiment valid
and safe.** Must land before the lookup/expansion tools are broadly exposed.

**Goal.** Fix the measurement and safety contract *before* observing behavior, so
Experiment 1 measures the real question and raw exposure is governed.

**What we build** (committed items):
- `add-historical-lookup-funnel-telemetry` — the measurement contract: a linked
  event chain (`lookup_event_id`, exposed source ids + ranks, `parent_lookup_id` on
  expansion, session/agent identity, subsequent-turn links, a real tool-exposure
  population); denominators ("substantive"/"eligible" session), sampling, judge
  rubric + calibration, uncertainty; a three-rung reuse ladder (verified
  incorporation → judged influence → downstream benefit, the last needing controlled
  exposure); user-directed-vs-agent-decided judged **retrospectively**, not recorded
  as a tool property.
- `add-raw-history-governance` — exposure safety for the new first-class asset:
  redaction on search + expansion, per-neighbor visibility on expansion, bounded
  expansion windows/token limits, access audit, raw-turn forgetting, and revocation
  of shared raw work. (`add-bounded-memory-lifecycle-hardening` covers *structured
  memory* only.)

**Success gate.** The event chain, denominators, judge protocol, and governance
mechanics exist and are documented before tool exposure. Visibility violations are
reported *with* attempted-disallowed-access counts/types (zero without adversarial
opportunity is not evidence).

**Dependencies.** None. Blocks broad Phase 1 exposure.

## Phase 1 — Historical Lookup (agent pull)

**Gate: Experiment 1 (agent pull behavior) — the most important near-term
validation.** Ship the three items below as **one vertical experimental release**
(partial delivery can't answer the product question); the P0 event schema precedes
tool exposure.

**Goal.** An agent can *deliberately* search prior agent work when it judges
history may matter, get relevant prior turns back, and expand to source — and we
can measure whether agents actually do this unprompted.

**What we build** (committed items, detailed in `roadmap/features/`):
- `add-raw-historical-search-mode` — a source-only retrieval target that ranks
  `source_hit`s on their own (reusing `CompositeRetrievalProvider`, visibility,
  filters, redaction, trace) so memory objects can't starve raw candidates. Routing
  already scores/selects source hits today; the gap is a clean source-only target,
  not a second retrieval stack.
- `add-agent-historical-lookup-tool` — an agent-facing MCP tool
  (`pallium_search_history`) whose default is just "search prior work for X" (full
  filters optional), tagged with a distinct agent-pull origin (marks *that an agent
  issued a lookup*, **not** that it decided independently — that is judged
  retrospectively), returning the `lookup_event_id`. Experiment 1 varies
  tool-description-only vs stronger skill guidance.
- `add-source-context-expansion` — source-centric expand
  (`GET /source/{id}/context`: neighbor raw turns by `thread_ref`, per-neighbor
  visibility, bounded window, `parent_lookup_id`; supported memories opt-in and
  separate so the RAW baseline stays uncontaminated).

**Success gate.** Over a live window: agents invoke lookup at appropriate moments
without explicit user prompting at a non-trivial rate; the funnel yields a first
**reuse-events-per-100-eligible-sessions** number and the three-rung breakdown.
**Decision:** if agents don't pull despite strong retrieval, the core thesis is weak
(strategy decision-point 1) — stop and reassess before Phase 2/3.

**Dependencies.** P0 contract (event schema + governance) precedes exposure. Enables
the continuous evaluation track (RAW arm) and Phases 2–3, and the KPI.

## Continuous evaluation track — is derivation worth it? (RAW/DERIVED/HYBRID + fidelity)

**Gate: Experiment 3. This is a continuous track, not a sequential phase.** It
cannot start before Phase 1 (there is no RAW arm without raw search), but once raw
search lands it runs *continuously alongside* Phases 2–3 rather than blocking them.
Outlined as `idea-raw-derived-hybrid-shadow-eval` and `idea-derivation-fidelity-eval`.

**Goal.** Turn "is derivation worth it?" into a standing measurement instead of a
one-off study, and decompose *why* a DERIVED result loses into four seams:
(1) retrieval — was the relevant raw source in RAW candidates? (2) extraction —
did the relevant source episode produce a faithful derived object at all?
(3) derived-retrieval — did that object enter DERIVED candidates? (4) representation
— holding information and retrieval constant, is the rendered DERIVED text usable and
non-misleading? A shadow can address seams 1, 3, 4 and fidelity; **consumption /
downstream benefit cannot be measured by a shadow the agent never sees** and needs a
separate controlled-exposure step.

**What we build.**
- *Retrieval + representation* (`idea-raw-derived-hybrid-shadow-eval`): a shadow
  runner (reusing the `subtask_selector_shadow` seam + a new side table) that, on
  real lookups, constructs RAW / DERIVED / HYBRID candidate sets and records
  recovered info, RAW-only vs DERIVED-only wins, judged relevance, misleading/
  unsupported rate, and **context cost at equal token budget or as a quality-vs-token
  Pareto curve** (HYBRID must not win by receiving more context); store the raw
  fusion score + source ids/ranks so the RAW arm is reconstructable; record the
  derivation schema/prompt/model version and allow evaluating *new* derivation
  variants; extend `evals/retrieval_ablation/`. Downstream/consumption is explicitly
  out of the shadow.
- *Extraction coverage + fidelity* (`idea-derivation-fidelity-eval`): start from
  source *episodes* (not existing derived objects — that has survivorship bias) and
  score whether a faithful derived object was produced at all, and where it exists,
  completeness / unsupported claims / drift / compression. This isolates the
  derivation-side seams (extraction + fidelity) from the retrieval-side seams.

**Success gate.** Derived memory earns more responsibility **only if** it repeatedly
beats RAW/HYBRID on precision, misleading rate, context-for-equivalent-quality (at
equal budget), or — under controlled exposure — downstream performance. Otherwise
simplify around raw history (strategy decision-point 3).

**Dependencies.** The shadow needs Phase 1 raw search (no RAW arm without it); the
extraction-coverage/fidelity eval is **independent of Phase 1** and can start
immediately. Runs continuously; does not gate Phases 2–3.

## Phase 2 — Work continuity across contexts

**Gate: Experiment 2.** Outlined as `idea-cross-context-work-continuity`.

**Goal.** Make continuing work from another context easy enough to reduce the
manual "summarize this for the other session" / "go read that transcript" ritual,
while preserving correct understanding.

**What we build — simplest form first.**
- *First, validate the value:* a source session is *identified* by the user or agent
  (no automatic session-identity solving); Pallium retrieves and packages that
  session's relevant work; the receiving session continues. Compare against the
  manual baselines (paste-a-summary / read-the-transcript).
- *Only if that beats manual, invest in mechanism:* stable work/session correlation
  across `session_id`s so resumption ranking spans sessions; `agent_ref` as a
  first-class handoff dimension (Claude↔Codex); richer continuation packaging. Builds
  on shipped `work_refs`, `task_checkpoint`, `resumed_session`.

**Success gate.** Pallium-supported continuation beats the manual baselines
(summary / pointer / raw-transcript inspection) on user-orchestration cost while
preserving correct prior-work understanding (strategy decision-point 2).

**Dependencies.** Phase 1 (lookup/expand). Independent of the continuous eval track.

## Phase 3 — Shared agent knowledge

**Gate: Experiment 4 (requires a real multi-user deployment).**

**Goal.** Let knowledge produced by one user/agent/context benefit another where
visibility permits — measured, not assumed.

**What we build — raw value first, mechanism only if needed.**
- *First, the authorization contract:* `idea-visibility-vocab-reconciliation` — turn
  the visibility drift into an **authorization-semantics** task and define an explicit
  raw-history sharing/grant contract (consent, target audience, revocation,
  provenance, access audit, fail-closed). Current enforcement has no per-user grant
  (public requires `actor_ref is None`; a private query is container-wide regardless
  of actor), so cross-user raw sharing is a security mechanism to build, not a
  substrate in hand.
- *Then the value experiment:* `idea-cross-user-raw-history-value` — test whether
  scoped raw history *granted* by user A materially helps user B in a real multi-user
  deployment.
- *Only if raw cross-user sharing proves insufficient:* the design-007 mechanism
  items `add-explicit-shared-memory-derivation` and `add-cross-container-bounded-memory`
  (now `uncommitted`), with `add-bounded-memory-lifecycle-hardening` as their safety
  prerequisite. These are no longer the *entry point* to shared knowledge — they are
  downstream of a demonstrated value result.

**Success gate.** Cross-user *granted* work materially benefits another user;
**visibility violations = 0**, reported with attempted-disallowed-access counts/types.
Until a genuine multi-user environment exists, this phase stays validation-blocked by
design.

**Dependencies.** Sharing foundation Phase 1 (shipped); the authorization/grant
contract before any cross-user work; lifecycle hardening before shared-derivation
mechanism.

---

## Measurement model

**Primary KPI:** confirmed historical-reuse events per 100 *eligible* sessions
(with "substantive" and "eligible" session defined in the P0 measurement contract).

**Reuse is reported as three distinct rungs, not one blurred number:**
1. verified incorporation — history appears in the agent's reasoning, action, or answer;
2. judged influence/necessity — a retrospective judge assesses whether it shaped the work;
3. downstream benefit — requires controlled exposure, user confirmation, or outcome
   comparison (not claimable from passive logs).

**Supporting metrics** (built incrementally, starting in P0/P1):
historical-opportunity → lookup rate; lookup → useful-result rate; the three reuse
rungs; missed lookup opportunities (sampled diagnostic, non-thesis-gating unless judge
reliability is shown); continuation/handoff success; RAW vs DERIVED vs HYBRID
performance across the four seams; derivation coverage + fidelity; cross-agent reuse;
cross-user reuse; proactive-resume precision; **visibility violations = 0, reported
with attempted-disallowed-access counts/types**.

Instrumentation reuses `query_audit_log` / `memory_usage_audit` / `metrics` and the
`phase6_measurement.py` rollup template, on top of the P0 event chain
(`lookup_event_id`, exposed source ids/ranks, `parent_lookup_id`, session/agent
identity, subsequent-turn links). Cheap deterministic facts are logged online; the
ambiguous stages — historical opportunity, influence, and material use — are evaluated
**retrospectively
by a sampled judge**, not by a new online router or matcher.

## Non-goals for this phase

No new broad proactive-injection mechanisms; no retrieval/ranking mechanism
proliferation; no workflow mining; no automatic skill generation; no agent
analytics/coaching; no synthetic benchmark built to prove derived memory superior.
Proactive delivery is kept only for high-confidence continuation/resumption and
must justify itself on live precision.

## Decision points (mapped to gates)

1. **Do agents reuse historical work often enough to matter?** → Phase 1 gate. If
   no despite good retrieval, the thesis is weak.
2. **Does Pallium make cross-context continuity materially easier?** → Phase 2 gate.
3. **Does derived memory beat raw enough to justify its complexity?** → continuous
   evaluation track. If never, simplify around raw history.

## Strategy → phase → roadmap mapping

| Strategy element | Phase | Roadmap item(s) |
|---|---|---|
| Measurement contract + KPI | P0 | add-historical-lookup-funnel-telemetry |
| Raw-history governance | P0 | add-raw-history-governance |
| Bet 1: historical lookup (vertical slice) | P1 | add-raw-historical-search-mode, add-agent-historical-lookup-tool, add-source-context-expansion |
| Derived-memory as evaluated layer / Exp 3 | Continuous | idea-raw-derived-hybrid-shadow-eval, idea-derivation-fidelity-eval |
| Bet 2: continuity / Exp 2 | P2 | idea-cross-context-work-continuity |
| Bet 3: shared knowledge / Exp 4 | P3 | idea-visibility-vocab-reconciliation (first), idea-cross-user-raw-history-value, add-bounded-memory-lifecycle-hardening, add-explicit-shared-memory-derivation (uncommitted), add-cross-container-bounded-memory (uncommitted) |

## Risks / open questions

- **Pull adoption is the make-or-break unknown** and cannot be de-risked by more
  corpus analysis — hence Phase 1 is a live behavioral test, not a build-and-hope.
- **Material-use measurement** is currently citation-level; the KPI needs a
  stronger signal without over-claiming.
- **Cross-agent frequency** is unknown outside this corpus; Phase 2 continuity must
  not over-invest in cross-agent before evidence, and should prove identified-source
  handoff value before building automatic session correlation.
- **Visibility drift** must be reconciled before any sharing work to avoid
  building Phase 4 on an ambiguous contract.
