Pallium currently has two primary capabilities:

1. **Session History** records governed agent work and makes earlier sessions
   searchable. Its vNext strategy is in `docs/context/strategy-vnext.md`.
2. **Agent Relay** moves bounded context between existing agent sessions. Its
   roadmap starts at `roadmap/ideas/idea-agent-relay.md`.

They share Pallium's local service and integration foundation. Each has its own
validation gates and can succeed or fail independently.
Everything below the current-focus sections records the shipped foundation these
tracks build on. It is context, **not** an invitation to reopen the prior
proactive-injection / routing-optimization program — that program is not the
current direction.

Foundation in place (shipped, stable): the `agent_conversation_memory` runtime with
multilingual support, multi-package parallel processing, hybrid retrieval
(lexical + vector + RRF fusion), cue-free structural routing, bounded consolidation,
thread continuity, resumed-work checkpoints, evidence-backed investigation
carry-forward, and package-owned injection decisions. Remaining limitations are
represented explicitly on the board as queued hardening, paused work, completed
investigations, or superseded directions rather than being implicitly active.

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

Current focus — Session History vNext (refined 2026-09-05):

The active milestone is **Session History vNext: historical agent work as a
first-class context layer** (strategy: `docs/context/strategy-vnext.md`; execution plan:
`docs/designs/015-vnext-historical-work-execution.md`). The prior Shaped Memory
Contract milestone is wound down (W2/W3/W4/W6 shipped; W1/W5/W7 parked as residuals
under Paused).

vNext is validation-first and experiment-gated: each phase must pass its live
experiment before the next earns significant investment. The product has two
primary capabilities: Agent Relay and **Session History**.
The Session History target is a package-independent raw record of governed agent
work. Generated memories become optional and disabled by default when the queued
decoupling slice ships.

The Session History slice is ordered. The first item is shipped; the next two are
vNext features, followed by a committed, time-boxed investigation:

1. `add-structural-session-work-references` — shipped: attach branch, exact Agent
   Workflow Work Record, and explicit issue/PR/ticket references without semantic
   inference.
2. `add-distinct-work-and-broad-history-search-tools` — provide exact work-scoped
   search and broad history search as separate agent operations over one retrieval
   and expansion implementation.
3. `decouple-session-history-from-derived-packages` — make start, ingest, raw
   indexing, governance, search, and expansion work with zero semantic packages;
   derived packages default off. There is no migration requirement for this
   single-operator deployment, but existing code and stored outputs remain usable.
4. `investigate-history-navigation-and-on-demand-compression` — compare flat,
   grouped, and index-first access plus raw, temporary on-demand compression, and
   persistent-derived representations before committing to another structure.

Primary KPI: fraction of
*eligible* sessions with ≥1 confirmed historical-reuse × 100 (session incidence,
capped at 100), reported as three rungs
(verified incorporation → judged influence → downstream benefit). Hard invariant
across all phases: visibility violations = 0, reported with attempted-disallowed-
access counts/types.

- **Phase 0 (Shipped foundation) — Measurement contract & raw-history governance**:
  shipped the linked event chain (`lookup_event_id`, exposed source
  ids/ranks, expansion parentage, session/agent identity), the eligible-session
  denominator and retrospective judge protocol, and raw-history governance (redaction
  on search+expansion, per-neighbor visibility, bounded windows, access audit,
  raw-turn forgetting, shared-raw revocation). These mechanics made Experiment 1
  valid and safe.
- **Phase 1 (Shipped foundation) — Historical Lookup**: shipped deliberate
  agent-pull raw-history search as one vertical slice (source-only retrieval target,
  `pallium_search_history` tool, source-context expansion). That slice reused the
  existing retrieval stack. Gate = Experiment 1 (reframed): the open question is NO
  LONGER "will agents
  pull unprompted?" — evidence shows they over-pull (≈0.75 on no-opportunity
  controls). The headline is now: **does agent-filtered historical pull improve the
  work enough to justify its token, latency, and contamination cost?** Measured on
  real corpus via the consolidated real-corpus decision experiment. If filtered pull
  is not net-positive, the core thesis is weak. The directional 12-case run was
  positive but exposed a concrete superseded-guidance risk. The outdated-history
  guard is shipped. A four-case exact-link pilot found encouraging value but also
  showed that exposure telemetry, expansion replay, temporal replacement handling,
  and result diversity are not yet faithful enough for a product verdict. The
  access-and-evaluation fix and its capped expansion are complete. The next step is
  the ordered Session History slice above. Broader post-change cases then feed the
  20-case `idea-pull-real-corpus-validation` gate before Phase 2 earns investment.
- **Continuous — Derived-memory evaluation (RAW/DERIVED/HYBRID + coverage/fidelity)**:
  not a sequential phase. Decompose why a DERIVED result loses into four seams
  (retrieval / extraction / derived-retrieval / representation). The shadow measures
  retrieval + representation (equal-token budgets; a shadow can't measure consumption)
  once raw search lands; the extraction-coverage/fidelity eval starts from source
  *episodes* (avoiding survivorship bias) and can start immediately. Gate = Experiment 3.
- **Phase 2 (Next) — Continuity across sessions/agents**: reduce the manual
  "summarize this for the other session" / "go read that transcript" handoff. Prove
  identified-source handoff value against manual baselines *before* building
  automatic session correlation or `agent_ref` routing. Gate = Experiment 2.
- **Phase 3 (Later) — Shared knowledge**: cross-user raw sharing is a *security
  mechanism*, not a substrate in hand — current enforcement has no per-user grant.
  First reconcile the authorization semantics and define an explicit raw-history
  sharing/grant + revocation contract; then test whether *granted* raw history from
  one user materially helps another (Experiment 4, needs a real multi-user
  deployment); build the shared-derivation mechanism (design-007 Phase 2/3, now
  uncommitted) only if the raw-first result requires it.

Rationale (from read-only corpus studies): useful cross-session history exists for
~38% of real prompts and is ~88% experiential; raw hybrid search already surfaces
it ~83% top-5; current derived memory did not beat raw on recall and is a lossy
consumption representation (~29% misleading); and cross-session transfer is common
but orchestrated manually today. This argues for changing the interaction model
(deliberate pull + continuity), not abandoning historical memory — with derivation
demoted to a continuously-evaluated optimization layer.

Agent Relay capability (2026-08):

Agent Relay tests a separate product hypothesis: Pallium's durable local service
and agent integration points may be valuable as a context-exchange layer, even
where semantic memory is not involved. An agent explicitly sends an attributed,
scoped message to another supported runtime. Shipped R1 persists it for the
recipient's next applicable natural turn. The committed wake-first extension will
attempt immediate activation by default and retain that R1 path as the fallback
when wake is unsupported, unsafe, or unavailable.

Pallium currently integrates with **Claude Code, Codex, and OpenCode**. R1 supports
runtime-wide fan-out plus exact-session and Relay-alias delivery within the same
repository/container. Extracted `work_refs` are retrieval hints, not reliable
delivery addresses, and must not be used to route Relay messages. Future-recipient
addressing remains an investigation until a reliable shared identity source exists.

Relay has two design invariants:

- routing and delivery do not depend on search, embeddings, ranking, or an LLM
- Pallium may trigger a delivery turn, but it does not spawn, assign, supervise,
  restart, or continuously coordinate agents

R1 explicit runtime/session Relay is shipped. The next committed steps are
wake-first delivery with deterministic next-turn fallback, followed by three
dependency-workflow E2E scenarios whose evidence drives public positioning and
usage guidance. Add only further extensions repeatedly demanded by real use. See
`roadmap/ideas/idea-agent-relay.md`.

Paused or parked work is listed explicitly in `roadmap/board.md`; completed
investigations and superseded directions are not active optimization targets.

Still out of scope:

- cold archive storage for expired raw evidence
- a general graph platform
- global contradiction resolution across all memory
- broad ontology management
- public API expansion for explicit retention administration
- replacing lower-level evidence-backed memory with only higher-level summaries
- turning Pallium into a workflow engine, exhaustive transcript archive, or raw
  tool-log store; bounded, governed agent/user turns needed for Session History
  remain in scope
