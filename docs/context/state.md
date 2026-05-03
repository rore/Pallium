# State

## Last Updated

2026-04-16

## Repo Snapshot

- repository initialized locally and linked to GitHub
- roadmap/ is the canonical planning workspace for queue and status
- docs/context/ holds stable project truth
- docs/designs/ holds deeper design threads and analyses
- Pallium is still optimized for a narrow conversation-continuity slice, not broad workspace memory

## Current Baseline

- first implementation language: Python
- architecture direction: single local-first service with clear module boundaries
- first concrete product package: `agent_conversation_memory`
- current LLM provider: Anthropic Claude (Sonnet + Haiku via per-role model config)
  - Sonnet: write_extraction (quality-critical, 14-field schema)
  - Haiku: thread_aggregation, consolidation, query_ambiguity_resolution (simpler schemas, benchmarked equal or better)
- current extraction prompt: `strict_typed_memory_v8b_work_refs_separate` (867 tokens, work_ref extraction for cross-surface work continuity, prompt schema v8)
- normal local runtime goes through `python -m app.run ... --processors N`
- debug queue health exists at `GET /debug/queue/health`
- query/debug exposes retrieval trace plus package-owned routing and injection trace
- generic `visibility` field exists on ingest, storage, query, evidence, and debug trace for privacy-aware scope enforcement
- promoted memory currently includes:
  - `decision`
  - `investigation_outcome`
  - `thread_summary`
  - `task_checkpoint`
  - `interest`
  - `pattern_memory`
  - `continuity_memory`
  - `constraint_memory`
  - `atomic_fact` (from `conversational_knowledge`)
  - `fact_summary` (from `conversational_knowledge` consolidation, `high_value=True`)
- visibility terminology: `"limited"` renamed to `"container"` (visible within this single container); `container_visibility` field renamed to `visibility`; breaking change — requires fresh DB after applying
- actor-scoped memory and container-driven visibility rules are shipped:
  - `actor_ref` field on MemoryObject tracks who a memory is personal to
  - personal memory types (interest, constraint_memory) are suppressed in shared containers (container/public) with no fallback extraction
  - constraint_memory has a role guard — assistant messages cannot create it
  - constraint_memory is now created directly from `constraint_text` — the structured `constraint_candidates` extraction path has been fully removed (ConstraintCandidate dataclass, prompts, output schema, parser, and downstream constants all deleted); natural-language constraints are reliably promoted
  - shared memory is visible to other users via evidence-path actor filter; multi-user test coverage added across all test layers
  - query-time actor filtering via optional `actor_ref` on QueryFilters and query API
  - thread-level memories (thread_summary, task_checkpoint) always have actor_ref=null (shared)
  - backward compatible — queries without actor_ref work as before
- reusable thread aggregation and bounded consolidation capabilities are shipped for the current package
- item-level LLM extraction persists internal semantic signals under `SourceItem.metadata["pallium_semantic_signals"]`
- work reference (work_ref) support is shipped for cross-surface work continuity:
  - external work identifiers (ticket IDs, PR numbers, incident keys) extracted from content via LLM prompt
  - optional runtime hints via `pallium_work_refs` metadata key on source items
  - normalized identifiers (casefold + separator canonicalization) stored on `MemoryEnvelopeScope.work_refs`
  - scoring affinity: +40 for continuity_memory with shared work_ref
  - packaging gate relaxation: cross-thread bundling when work_refs match
  - query-time detection: candidate work_refs matched as substrings of normalized query text (data-driven, no regex)
  - `work_refs` field on QueryFilters for agent-provided high-confidence hints
  - prompt schema version bumped from v7 to v8
- `agent_conversation_memory` now applies a cue-free control plane above routing:
  - routing uses typed structure and retrieval evidence, not English phrase matching
  - `QuerySignalEnvelope` is the canonical routing authority (Tier 1 structural, Tier 2 candidate evidence, no English cue fallback)
  - structural lane narrowing with 3 lanes: `work_resumption`, `evidence_trace`, `residual_recall`
  - `constraint_policy` lane removed — Pallium remembers and returns constraints but does not enforce them; enforcement is the consuming agent's job
  - recall modes derive weight-only preferences from candidate evidence
  - scoring formula simplified from 7 to 5 components
  - constraint compatibility engine removed (~1000 lines) — constraint memories route through `residual_recall`
  - ~40 English cue constants eliminated from the control plane
- thread summary `content_quality` is now LLM self-classified via a schema field (v4/v2) rather than post-hoc English substring matching against marker lists; `QUERY_ONLY_SUMMARY_MARKERS` and `UNRESOLVED_SUMMARY_MARKERS` removed from production; schema versions: `thread_summary_extraction` v3→v4, `thread_summary_with_checkpoint_extraction` v1→v2
  - ordinary queries stay on the deterministic hot path with selective `query_ambiguity_resolution` only for bounded unresolved ambiguity
- role-specific prompt governance is live for:
  - `write_extraction`
  - `write_enrichment`
  - `query_ambiguity_resolution`
- role-specific prompt config is now part of the shipped runtime surface:
  - package `prompt_variant`
  - role-scoped `prompt_variants`
  - package `resolver_enabled`
  - package `resolver_timeout_ms`
- write-time retrieval enrichment is shipped for higher-level memory and stays off the query hot path
- grounded evidence checks now enforce source-backed investigation evidence and stricter normalized evidence handling for decision/investigation paths
- the initial live-improvement loop is now shipped:
  - drift metrics in the exploratory runner
  - shadow routing comparison via injectable routing overrides
  - replay-promotion tooling from exploratory captures into replay scenario skeletons
- committed examples and tests use a neutral library reservation and catalog sync sample domain
- hybrid retrieval is now the shipped production retrieval path:
  - `CompositeRetrievalProvider` fuses lexical and vector results via Reciprocal Rank Fusion (RRF, k=60, scale=600)
  - `OnnxEmbeddingProvider` and `FastEmbedProvider` available; fastembed requires Python 3.12/3.13
  - embedding model configured via `pallium.local.toml`; default fallback is bge-small-en-v1.5; multilingual-e5-small is supported with query/passage prefixes
  - all 6 promoted memory types are embedded at background processing time, not at ingest
  - `SourceItem` embedding is plugin-owned via a package method on the semantic plugin boundary
  - production `/query` path activates hybrid retrieval by default
  - retrieval trace continues to show per-result origin (lexical, vector, or fused)
- FTS5 lexical retrieval is shipped (addresses lexical retrieval scaling concern):
  - O(N) full-table-scan replaced by SQLite FTS5 inverted-index lookup with native BM25 scoring
  - standalone `lexical_fts` FTS5 virtual table maintained transactionally alongside `index_entries`
  - BM25 scores (float) replace IDF integers; `normalize_lexical_score()` provides 0-1 normalization for all routing consumers
  - language-agnostic IDF weighting supplemented by explicit multilingual stopword sets (English + Hebrew) for edge cases IDF misses
  - prevents off-topic injection (e.g., weather query matching vector DB memories on shared function words)
- `interest` memory kind is shipped:
  - captures specific-but-uncommitted user interest (dedicated type, weaker than task_checkpoint)
  - user-only role guard — assistant messages cannot create interest
  - suppressed in shared containers (container/public) with no fallback
  - per-item extraction with `interest_text` signal, also detected at thread aggregation level
- processing pipeline latency optimizations are shipped:
  - worker poll interval reduced from 1.0s to 0.2s
  - thread rebuild decoupled from item processing with max-wait timer (2s default)
  - thread summary + task checkpoint combined into single LLM call
  - vector index batch saves — one save per processing cycle instead of per-item
  - thread rebuild storage queries batched from O(N) to O(1)
- operational scale-hardening slice is shipped for the current SQLite-backed runtime:
  - hot-path secondary indexes added for source item claims, thread lookups, relation traversals, index-entry scans, thread rebuild leases, and package-claim ordering
  - vector retrieval now batch-hydrates index entries through storage instead of per-hit lookup loops
  - worker logging uses a summary-only processing result path; full item-processing hydration remains available for API/tests/debug inspection
  - package claim ordering now uses denormalized `source_item_created_at` on `package_processing_status`, avoiding a join on every claim and backfilling legacy rows at startup
  - vector reconciliation is now bounded in both directions: SQLite paging for forward fill and batched stale-usearch cleanup for reverse repair
- routing module structural refactoring is shipped:
  - `agent_conversation_memory_routing.py` (~168KB) decomposed into 6 focused modules
  - extracted: routing_constants, routing_signals, routing_trace, routing_policy, routing_scoring, routing_selection
  - orchestrator remains as thin coordination layer with re-exports for backward compatibility
- anchor prefilter layered defense is shipped:
  - three-tier behavior replaces the original binary exclusion gate: aligned primary / secondary tier / no-anchor legacy fallback
  - `anchored_conflicting` candidates are demoted to the insufficient fallback bucket (`insufficient_retained_demoted`) instead of being hard-excluded; when aligned candidates exist they are retained as secondary tier, when no aligned candidates exist they surface via the existing insufficient fallback path
  - `ANCHOR_SECONDARY_TIER_PENALTY = 120` (== `ROUTING_FOCUS_BOOST`) deducted from `base_routing_score` for all secondary-tier candidates, guaranteeing aligned always outranks secondary even at max focus boost
  - when aligned candidates exist, insufficient and legacy candidates enter `retained_memory_ids` as `secondary_tier` and fill remaining result slots not consumed by aligned
  - `fallback_mode = "aligned_with_secondary"` and `secondary_tier_count` exposed in anchor_prefilter trace; `anchor_tier_penalty` exposed per-candidate in routing trace
- query tokenization is now unified: `tokenize_query` from `retrieval/lexical.py` is the single implementation; duplicate `_query_tokens` in `core/query.py` removed; debug query filter matching unified on canonical `matches_filters` (corrects lifecycle, thread_ref relaxation, and actor_ref handling on the debug path)
- multilingual tokenization is shipped:
  - Unicode-aware TOKEN_PATTERN centralized in `core/text.py`, handles Latin, Hebrew, Arabic, CJK, Cyrillic
  - combining marks (Hebrew niqud, Arabic vowels, Latin diacritics) stripped before tokenization
  - cross-language content-overlap bypass: when query and candidate use entirely different Unicode scripts, the gate defers to vector similarity instead of blocking
  - embedding provider supports query/passage prefix modes (`EmbedMode`) for multilingual models
- embedding provider auto-detects query/passage prefixes for known model families (E5 family)
- vector index self-healing is shipped:
  - source item vector embedding runs regardless of LLM outcome (survives extraction failures)
  - startup count mismatch logs a warning and continues with reduced recall instead of disabling vector
  - server-owned reconciliation: a daemon thread in the API server process embeds SQLite entries missing from usearch (batch-bounded) and removes stale usearch entries missing from SQLite
  - processor subprocesses run with `enable_vector=False` — they write IndexEntry records to SQLite only; the server reconciliation thread picks them up
  - `rebuild-vector-index` CLI command remains available for manual recovery
- persisted annotation layer removed:
  - `Annotation` model, `AnnotationRecord` ORM, `annotations` DB table, and all storage methods deleted
  - `annotation_ids` and `annotation_count` removed from API responses and contracts
  - annotation data was 100% duplicated in MemoryObjects; no query-time code read annotations
  - core data model reduced to four primitives: SourceItem, MemoryObject, Relation, IndexEntry

## Verification Notes

- the repo now has a stronger validation architecture than earlier phases, but hard-gate status still matters more than raw scenario totals
- current validation surface includes:
  - semantic extraction regressions
  - routing and injection tests
  - resumed-work and repeated-question benchmarks
  - public-corpus reviewed slices
  - low-value churn coverage
  - integration-readiness scenarios
  - live exploratory drift and replay-promotion tooling
- the developer-work confidence harness should be read by hard-gate fields first, not by aggregate scenario-success counts alone
- replay is now a real tooling surface, but replay coverage is still materially smaller than the authored confidence packs
- test suite: 965 passed, 147 skipped
- semantic extraction fixture set: 58 items (12 decisions, 14 investigations, 20 boundary-null, 13 signal cases)
- subject_hints eval surface is shipped:
  - ground-truth fixture: 33 items across 7 pattern classes (harder modifiers, gerunds, hard negatives)
  - `strict_typed_memory_v7_claude_structured_v2` registered alongside base variant for comparative runs
  - runner with scoring logic and unit tests in `evals/subject_hints/`

## Configuration Note

- local config now uses `pallium.local.toml` for package/provider structure and `.env.local` for secrets or one-off overrides
- current config supports:
  - named provider blocks
  - named semantic package blocks
  - package prompt defaults
  - role-specific prompt overrides
  - role-specific model overrides (`model_roles`)
  - provider auth style (`auth_style` for proxy-compatible headers)
  - `api_key_file` for loading API keys from a file path instead of inline value
  - resolver toggles and timeout
  - observability and retention
- the reference for the shipped config surface is now `docs/configuration.md`

## Reference Points

- current queue and sequencing: `roadmap/board.md`
- accepted architecture and decisions: `docs/context/architecture.md`, `docs/context/decisions.md`
- fuller design rationale: `docs/designs/`
- semantic baseline: `evals/semantic/baseline.md`

## Next Hardening Direction

- the next hardening work should build on the shipped live-improvement loop rather than still describing it as future work
- roadmap ideas board was cleaned up (2026-03-21):
  - `idea-optional-embedding-provider-support` retired — realized by vector+fusion features
  - `idea-evidence-backed-agent-memory` retired — realized by the full agent_conversation_memory product slice
  - `idea-optional-llm-assisted-routing` retired — realized by query_ambiguity_resolution (bounded LLM tiebreaker)
  - `add-live-integration-improvement-loop-and-replay-pipeline` moved to Done — drift metrics, shadow comparison, and replay promotion all shipped
  - remaining ideas: lifecycle signals, scale hardening, multi-package processing, reranker support
- likely next architectural pressure remains:
  - explicit shared-memory derivation
- follow-on work around the live improvement loop should stay bounded to:
  - replay promotion quality
  - shadow tuning workflow
  - drift visibility
  - turning real misses into reusable generic failure classes rather than anecdotal fixes

## LLM Resilience Notes

- provider calls retry only transient failures with bounded conservative backoff
- OpenAI-compatible and Anthropic providers capture request ids when available
- `Retry-After` is honored when present
- invalid successful responses remain fail-fast and are not retried
- live eval and benchmark paths use the same provider resilience path as normal semantic extraction
- thread rebuild and consolidation use combined LLM calls (1 call per operation instead of 2-4)
