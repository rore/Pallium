Pallium's current direction is **Pallium vNext: historical agent work as a
first-class context layer** (see "Current focus" below; strategy
`docs/context/strategy-vnext.md`, execution
`docs/designs/015-vnext-historical-work-execution.md`). That is the active thesis
and the lens for prioritization.

Everything below the current-focus section records the shipped foundation vNext
builds on. It is context, **not** an invitation to reopen the prior
proactive-injection / routing-optimization program — that program is not the
current direction.

Foundation in place (shipped, stable): the `agent_conversation_memory` runtime with
multilingual support, multi-package parallel processing, hybrid retrieval
(lexical + vector + RRF fusion), cue-free structural routing, bounded consolidation,
thread continuity, resumed-work checkpoints, evidence-backed investigation
carry-forward, and package-owned injection decisions. Known residual limitations
(thread-level interest extraction, lexical scaling beyond medium corpora, systematic
stale/superseded/contradictory-memory handling) are **parked deliberately** under
vNext (see Parked below) — they are not active optimization targets.

Shipped since last major scope update:

- **Injection policy abstention (2026-06-27)**: per-type injection policy
  (`[injection.policy.types.*]` config) with proactive/event/on_demand/
  suspended modes; deterministic Phase 4 triggers
  (PostToolUse failure + retry, SessionStart, pre-compact, user_prompt_submit,
  user_explicit) in claude-code and codex integrations; `memory_usage_audit`
  table + populator hook for measuring whether injected memories were
  actually used (`referenced_in_next_turn`). Phase 6 measurement window
  pending live-data accumulation.
- **Thread + per-item near-duplicate supersession (2026-06-28)**:
  `SequenceMatcher.ratio >= 0.85` similarity gate on top of T2's
  exact-equality supersession. Closes the byte-equality blind spot
  for LLM paraphrases across thread rebuilds (writer-side, in
  `build_thread_summary`) AND per-item extractions on adjacent turns
  (resolver-side, in `_resolve_supersession_pairs_in_session`). 296
  active near-dup memories collapsed on the live corpus.
- **Multilingual tokenization and embedding**: Unicode-aware tokenization for Hebrew, Arabic, CJK, Cyrillic; combining mark stripping; cross-script content-overlap bypass; embedding prefix modes with auto-detection for known model families (E5)
- **Multi-package parallel processing**: `PackageProcessingRecord` per `(source_item_id, use_case)` enables items to be processed by multiple packages independently; `parallel_processing = True` packages process every item; `TypeRegistry` for package-owned memory type metadata
- **Conversational knowledge fact extraction**: second production package (`conversational_knowledge`) extracts atomic facts via thread rebuild, runs alongside `agent_conversation_memory`
- **Cue-free routing control plane**: `QuerySignalEnvelope` as canonical routing authority; 3 structural lanes (work_resumption, evidence_trace, residual_recall); ~40 English cue constants removed; scoring simplified from 7 to 5 components; constraint_policy lane and compatibility engine removed (~1000 lines)
- **Hybrid retrieval**: `CompositeRetrievalProvider` fusing lexical + vector via RRF (k=60, scale=600); IDF-weighted lexical scoring with multilingual stopword sets
- **Vector index self-healing**: daemon reconcile thread in API server; processor subprocesses write IndexEntry only; startup mismatch warning instead of disabling vector
- **Annotation layer removal**: core data model reduced to four primitives (SourceItem, MemoryObject, Relation, IndexEntry)
- **Shared prompt-role governance**: contract ownership for `write_extraction`, `write_enrichment`, `query_ambiguity_resolution`
- **Live improvement loop**: drift metrics, shadow routing comparison, replay-promotion tooling

Current focus — Pallium vNext (2026-08):

The active milestone is **Pallium vNext: historical agent work as a first-class
context layer** (strategy: `docs/context/strategy-vnext.md`; execution plan:
`docs/designs/015-vnext-historical-work-execution.md`). The prior Shaped Memory
Contract milestone is wound down (W2/W3/W4/W6 shipped; W1/W5/W7 parked as residuals
under Paused).

vNext is validation-first and experiment-gated: each phase must pass its live
experiment before the next earns significant investment. Primary KPI: confirmed
historical-reuse events per 100 substantive sessions. Hard invariant across all
phases: visibility violations = 0.

- **Phase 1 (Now) — Historical Lookup**: expose raw-history search as a deliberate
  agent pull (raw-ranked retrieval mode, `pallium_search_history` tool,
  source-context expansion) plus funnel telemetry. Gate = Experiment 1: do agents
  invoke lookup unprompted, and is retrieved history materially used? If not
  despite strong retrieval, the core thesis is weak.
- **Continuous — Derived-memory evaluation (RAW/DERIVED/HYBRID + fidelity)**: not a
  sequential phase. Once raw search lands, continuously shadow RAW/DERIVED/HYBRID on
  real lookups and separately sample source→derived fidelity (to tell a derivation
  failure from a retrieval failure); derivation earns more responsibility only if it
  repeatedly beats raw on a measured dimension. Gate = Experiment 3.
- **Phase 2 (Next) — Continuity across sessions/agents**: reduce the manual
  "summarize this for the other session" / "go read that transcript" handoff. Prove
  identified-source handoff value against manual baselines *before* building
  automatic session correlation or `agent_ref` routing. Gate = Experiment 2.
- **Phase 3 (Later) — Shared knowledge**: first test whether scoped *raw* history
  from one user materially helps another (Experiment 4, needs a real multi-user
  deployment); reconcile visibility vocabulary first; build the shared-derivation
  mechanism (design-007 Phase 2/3) only if the raw-first result requires it.

Rationale (from read-only corpus studies): useful cross-session history exists for
~38% of real prompts and is ~88% experiential; raw hybrid search already surfaces
it ~83% top-5; current derived memory did not beat raw on recall and is a lossy
consumption representation (~29% misleading); and cross-session transfer is common
but orchestrated manually today. This argues for changing the interaction model
(deliberate pull + continuity), not abandoning historical memory — with derivation
demoted to a continuously-evaluated optimization layer.

Still parked (pre-vNext investigations):

- investigate thread-level interest and threadless aggregation
- investigate lexical retrieval scaling
- bounded memory lifecycle hardening (prerequisite for Phase 4 sharing)

Still out of scope:

- cold archive storage for expired raw evidence
- a general graph platform
- global contradiction resolution across all memory
- broad ontology management
- public API expansion for explicit retention administration
- replacing lower-level evidence-backed memory with only higher-level summaries
- turning Pallium into a workflow engine, transcript archive, or raw tool-log store
