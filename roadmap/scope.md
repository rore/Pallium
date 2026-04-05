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

- **Multilingual tokenization and embedding**: Unicode-aware tokenization for Hebrew, Arabic, CJK, Cyrillic; combining mark stripping; cross-script content-overlap bypass; embedding prefix modes with auto-detection for known model families (E5)
- **Multi-package parallel processing**: `PackageProcessingRecord` per `(source_item_id, use_case)` enables items to be processed by multiple packages independently; `parallel_processing = True` packages process every item; `TypeRegistry` for package-owned memory type metadata
- **Conversational knowledge fact extraction**: second production package (`conversational_knowledge`) extracts atomic facts via thread rebuild, runs alongside `agent_conversation_memory`
- **Cue-free routing control plane**: `QuerySignalEnvelope` as canonical routing authority; 3 structural lanes (work_resumption, evidence_trace, residual_recall); ~40 English cue constants removed; scoring simplified from 7 to 5 components; constraint_policy lane and compatibility engine removed (~1000 lines)
- **Hybrid retrieval**: `CompositeRetrievalProvider` fusing lexical + vector via RRF (k=60, scale=600); IDF-weighted lexical scoring with multilingual stopword sets
- **Vector index self-healing**: daemon reconcile thread in API server; processor subprocesses write IndexEntry only; startup mismatch warning instead of disabling vector
- **Annotation layer removal**: core data model reduced to four primitives (SourceItem, MemoryObject, Relation, IndexEntry)
- **Shared prompt-role governance**: contract ownership for `write_extraction`, `write_enrichment`, `query_ambiguity_resolution`
- **Live improvement loop**: drift metrics, shadow routing comparison, replay-promotion tooling

Current focus:

- **Routing calibration**: 3 regressions from routing simplification still open; fixing injection confidence thresholds
- **LoCoMo benchmark**: baseline at 61.2% on conv-26; confirms need for fact extraction package alongside agent continuity
- **Lifecycle hardening**: stale/superseded/contradictory memory handling before broader reuse and sharing work

Next (from board.md):

- investigate thread-level interest and threadless aggregation
- investigate lexical retrieval scaling

Later:

- bounded memory lifecycle hardening
- explicit shared-memory derivation
- cross-container bounded memory

Still out of scope:

- cold archive storage for expired raw evidence
- a general graph platform
- global contradiction resolution across all memory
- broad ontology management
- public API expansion for explicit retention administration
- replacing lower-level evidence-backed memory with only higher-level summaries
- turning Pallium into a workflow engine, transcript archive, or raw tool-log store
