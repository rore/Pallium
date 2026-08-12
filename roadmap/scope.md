Pallium now has a stable runtime shape for `agent_conversation_memory` with shipped multilingual support, multi-package parallel processing, hybrid retrieval, cue-free routing, and bounded consolidation.

The north star remains making Pallium reliably solve a bounded set of agent-memory jobs without repeated heuristic chasing:

- answer requirement and architecture questions from prior decisions and evidence
- resume long investigations with findings, blockers, and prior reasoning intact
- resume interrupted work from explicit checkpoints instead of transcript replay
- reuse prior answers safely across later conversations when the same conclusion should help again
- preserve findings discovered while exploring external systems without turning Pallium into the system of record
- keep long-lived conversation continuity compact and selective rather than defaulting to transcript growth
- let downstream agents stay thin by relying on Pallium's memory decisions instead of local heuristics

Current gap assessment against that north star:
- strongest today:
  - thread continuity and multilingual content handling
  - resumed-work checkpoints
  - bounded investigation carry-forward
  - package-owned injection decisions and compact carry-forward output
  - cue-free routing with structural lane narrowing (no English phrase dependence)
  - hybrid retrieval (lexical + vector + RRF fusion) with cross-script support
- partial today:
  - requirement and architecture recall when the decision or conclusion already exists in the current scope
  - repeated-question reuse within bounded local scope
  - evidence-backed reuse of findings that were surfaced clearly enough during the original interaction
  - routing calibration across paraphrase variants (3 regressions from routing simplification still open)
- still weak or unstable:
  - thread-level interest extraction (per-item extraction loses subject context when interest spans multiple messages)
  - lexical retrieval scaling beyond small-to-medium corpora
  - systematic handling of stale, superseded, or contradictory structured memory
  - confidence that Pallium stays quiet when it should and does not force downstream semantic compensation

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
- **Phase 2 (Next) — Derived-memory continuous evaluation**: shadow
  RAW/DERIVED/HYBRID on real lookups; derivation earns more responsibility only if
  it repeatedly beats raw on a measured dimension. Gate = Experiment 3.
- **Phase 3 (Later) — Continuity across sessions/agents**: reduce the manual
  "summarize this for the other session" / "go read that transcript" handoff.
  Gate = Experiment 2.
- **Phase 4 (Later) — Shared knowledge**: design-007 Phase 2/3, gated by a real
  multi-user deployment (Experiment 4); reconcile visibility vocabulary first.

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
