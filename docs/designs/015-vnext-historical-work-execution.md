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

- **Raw turns are already a searchable substrate.** Every ingested source turn is
  lexically + vector indexed (`core/service.py`, `core/vector_embed.py`);
  `source_hit` is a real result kind with excerpt + provenance
  (`retrieval/lexical.py`); container/thread/actor/visibility scoping and
  `source_type`/`role`/`artifact_kind`/`work_refs` filters are plumbed
  end-to-end (`core/query.py`, `core/filters.py`, `api/`). **Gap:** the default
  query path routes everything through the memory-centric pipeline
  (`semantic/agent_conversation_memory_routing*.py`), which never ranks or
  selects `source_hit`s. There is no raw-ranked retrieval mode and no
  agent-facing tool to invoke one.
- **Shadow-experiment harness pattern exists and is removable.** The
  `subtask_selector_shadow` runner attaches at a single seam in
  `core/query.py`, gated by an `ObservabilityConfig` flag, dispatches off the hot
  path, and writes a side table — never touching `should_inject`. This is the
  template for the RAW/DERIVED/HYBRID shadow. `evals/retrieval_ablation/` is an
  existing offline replay A/B harness to extend.
- **Reuse-funnel telemetry is partial.** `query_audit_log` (with `trigger_origin`),
  `memory_usage_audit` (`referenced_in_next_turn`, populated by the claude/codex
  stop-hook matcher), `memory_feedback`, and `metrics` exist. **Gaps:** MCP tools
  don't pass `trigger_origin` (agent-initiated lookups are invisible); there is no
  "opportunity" denominator; `referenced_in_next_turn` captures *citation*, not
  *material use*; no raw fusion score is stored (a RAW arm can't be reconstructed
  from history); no cross-agent/cross-user or continuation-success dimension.
- **Continuity primitives are strong within a thread, weaker across sessions.**
  `work_refs` cross-surface continuity is shipped (cross-thread affinity +
  packaging); `task_checkpoint`/`thread_summary`/`continuity_memory` ship. **Gap:**
  each new session mints a fresh `thread_ref`, so the `resumed_session` fast-path
  does not fire for genuinely new sessions; cross-session relies on
  container-scoped retrieval + work_ref affinity. Cross-*agent* (Claude↔Codex)
  continuity is *emergent* from shared `container_ref`/`actor_ref` — `agent_ref`
  is stored but is not a routing/handoff dimension, and there is no explicit
  handoff packaging.
- **Sharing foundation Phase 1 shipped.** `visibility_context` + enforce-before-
  ranking are in (`core/visibility.py`, design 007). **Gap:** explicit
  shared-derived-memory objects (design 007 Phase 2) and bounded cross-container
  reuse (Phase 3) are unbuilt; and there is an impl/spec vocabulary drift
  (`public|container|private|global` implemented vs `public|limited|user`
  specified) to reconcile before sharing work.

## Guarded-path note

Phase 1+ touch guarded paths — `core/service.py` (red), `core/query.py` (watch),
plus `api/` and `storage/`. Per repo rule, **each implementation slice starts by
invoking `/agent-workflow`** (writes the Work Record, classifies risk) before any
code edit. This plan is documentation and needs no Work Record; the *items* do.

---

## Phase 1 — Historical Lookup (agent pull)

**Gate: Experiment 1 (agent pull behavior) — the most important near-term
validation.**

**Goal.** An agent can *deliberately* search prior agent work when it judges
history may matter, get relevant prior turns back, and expand to source — and we
can measure whether agents actually do this unprompted.

**What we build** (committed items, detailed in `roadmap/features/`):
- `add-raw-historical-search-mode` — a raw-ranked retrieval mode that ranks
  `source_hit`s (reusing `CompositeRetrievalProvider`) under existing
  scope/visibility/filters, bypassing the memory-only routing/abstention gate.
- `add-agent-historical-lookup-tool` — an agent-facing MCP tool
  (`pallium_search_history`) + client method + `trigger_origin="user_explicit"`,
  with skill/CLAUDE.md guidance on *when* to look up.
- `add-source-context-expansion` — source-centric expand
  (`GET /source/{id}/context`: neighbor turns by `thread_ref` + reverse
  `supported_by` memories) for follow-through.
- `add-historical-lookup-funnel-telemetry` — tag agent lookups distinctly and
  record the pull funnel: opportunity → agent query → useful result → material
  use; seed the reuse-events KPI and a missed-opportunity signal.

**Success gate.** Over a live window: agents invoke lookup at appropriate moments
without explicit user prompting at a non-trivial rate; the funnel yields a first
**reuse-events-per-100-sessions** number and a lookup→useful→material-use
breakdown. **Decision:** if agents don't pull despite strong retrieval, the core
thesis is weak (strategy decision-point 1) — stop and reassess before Phase 2/3.

**Dependencies.** None (substrate exists). Enables Phase 2 (RAW arm) and the KPI.

## Phase 2 — Derived-memory continuous evaluation (RAW/DERIVED/HYBRID)

**Gate: Experiment 3.** Outlined as `idea-raw-derived-hybrid-shadow-eval`.

**Goal.** Turn "is derivation worth it?" into a standing measurement instead of a
one-off study.

**What we build.** A shadow runner (reusing the `subtask_selector_shadow` seam +
a new side table) that, on real lookups, constructs RAW / DERIVED / HYBRID
candidate sets and records recovered info, RAW-only vs DERIVED-only wins,
completeness, misleading/unsupported rate, context size, derivation-failure vs
retrieval-failure, and downstream material use; store the raw fusion score so the
RAW arm is reconstructable; extend `evals/retrieval_ablation/` for periodic A/B.

**Success gate.** Derived memory earns more responsibility **only if** it
repeatedly beats RAW/HYBRID on precision, misleading rate, context-for-equivalent-
quality, normalization recall, or downstream performance. Otherwise simplify
around raw history (strategy decision-point 3).

**Dependencies.** Phase 1 raw search (no RAW arm without it).

## Phase 3 — Work continuity across contexts

**Gate: Experiment 2.** Outlined as `idea-cross-context-work-continuity`.

**Goal.** Make continuing work from another context easy enough to reduce the
manual "summarize this for the other session" / "go read that transcript" ritual,
while preserving correct understanding.

**What we build.** Stable work/session correlation across `session_id`s so
resumption ranking spans sessions (not just one long thread); explicit
continuation/handoff packaging; make `agent_ref` a first-class handoff dimension
(Claude↔Codex). Builds on shipped `work_refs`, `task_checkpoint`, `resumed_session`.

**Success gate.** Pallium-supported continuation beats the manual baselines
(summary / pointer / raw-transcript inspection) on user-orchestration cost while
preserving correct prior-work understanding (strategy decision-point 2).

**Dependencies.** Phase 1 (lookup/expand). Independent of Phase 2.

## Phase 4 — Shared agent knowledge

**Gate: Experiment 4 (requires a real multi-user deployment).**

**Goal.** Let knowledge produced by one user/agent/context benefit another where
visibility permits — measured, not assumed.

**What we build.** Reuse existing committed items
`add-explicit-shared-memory-derivation` (design 007 Phase 2) and
`add-cross-container-bounded-memory` (Phase 3); add
`idea-visibility-vocab-reconciliation` to close the `global` vs `limited|user`
drift *before* shared-derivation work.

**Success gate.** Cross-user work materially benefits another user;
**visibility violations = 0.** Until a genuine multi-user environment exists, this
phase stays validation-blocked by design.

**Dependencies.** Sharing foundation Phase 1 (shipped); vocab reconciliation;
lifecycle hardening (`add-bounded-memory-lifecycle-hardening`).

---

## Measurement model

**Primary KPI:** confirmed historical-reuse events per 100 substantive sessions.

**Supporting metrics** (built incrementally, mostly in Phases 1–2):
historical-opportunity → lookup rate; lookup → useful-result rate; lookup →
material-use rate; missed lookup opportunities; continuation/handoff success;
RAW vs DERIVED vs HYBRID performance; cross-agent reuse; cross-user reuse;
proactive-resume precision; **visibility violations = 0**.

Instrumentation reuses `query_audit_log` / `memory_usage_audit` / `metrics` and
the `phase6_measurement.py` rollup template; the material-use signal must go
beyond the current citation-level matcher.

## Non-goals for this phase

No new broad proactive-injection mechanisms; no retrieval/ranking mechanism
proliferation; no workflow mining; no automatic skill generation; no agent
analytics/coaching; no synthetic benchmark built to prove derived memory superior.
Proactive delivery is kept only for high-confidence continuation/resumption and
must justify itself on live precision.

## Decision points (mapped to gates)

1. **Do agents reuse historical work often enough to matter?** → Phase 1 gate. If
   no despite good retrieval, the thesis is weak.
2. **Does Pallium make cross-context continuity materially easier?** → Phase 3 gate.
3. **Does derived memory beat raw enough to justify its complexity?** → Phase 2
   gate. If never, simplify around raw history.

## Strategy → phase → roadmap mapping

| Strategy element | Phase | Roadmap item(s) |
|---|---|---|
| Bet 1: historical lookup | P1 | add-raw-historical-search-mode, add-agent-historical-lookup-tool, add-source-context-expansion |
| KPI + funnel telemetry | P1→P2 | add-historical-lookup-funnel-telemetry |
| Derived-memory as evaluated layer / Exp 3 | P2 | idea-raw-derived-hybrid-shadow-eval |
| Bet 2: continuity / Exp 2 | P3 | idea-cross-context-work-continuity |
| Bet 3: shared knowledge / Exp 4 | P4 | add-explicit-shared-memory-derivation, add-cross-container-bounded-memory, idea-visibility-vocab-reconciliation |

## Risks / open questions

- **Pull adoption is the make-or-break unknown** and cannot be de-risked by more
  corpus analysis — hence Phase 1 is a live behavioral test, not a build-and-hope.
- **Material-use measurement** is currently citation-level; the KPI needs a
  stronger signal without over-claiming.
- **Cross-agent frequency** is unknown outside this corpus; Phase 3 must not
  over-invest in cross-agent before evidence.
- **Visibility drift** must be reconciled before any sharing work to avoid
  building Phase 4 on an ambiguous contract.
