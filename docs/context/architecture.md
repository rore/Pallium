# Architecture

## Top-Level Shape

Pallium runs as a single local-first service with clear internal module boundaries.

Main layers:

1. API layer
2. Generic core
3. Reusable capability layer
4. Semantic use-case layer
5. Provider layer
6. Storage layer
7. Retrieval layer
8. Background processor and supervisor runtime

## MCP Endpoint

`app/mcp/` provides an MCP server mounted on the FastAPI app at `/mcp` via
streamable-http transport. Agent runtimes connect to `http://<host>:<port>/mcp`
to access `pallium_query`, `pallium_query_debug`, `pallium_ingest`,
`pallium_get_evidence`, and `pallium_flag_memory` tools.
The MCP module depends only on `mcp[cli]` and `httpx` — no core Pallium imports.
It proxies tool calls to the HTTP API on the same server. Also available as a
standalone entry point (`python -m app.run mcp`) for stdio transport.

## Implemented Core and Retrieval Slice

Implemented HTTP endpoints:

- POST /items
- POST /query
- POST /query/debug
- POST /memory/{memory_object_id}/flag
- GET /items/{source_item_id}/processing
- GET /memory/{memory_object_id}/evidence
- GET /debug/queue/health

Implemented abstractions:

- storage provider boundary
- retrieval provider boundary
- semantic plugin boundary
- LLM provider boundary with shared retry, backoff, call metadata, and configurable auth style
- embedding provider boundary (`EmbeddingProvider` ABC with fastembed and ONNX Runtime implementations)
- vector index adapter (usearch)

Implemented storage and retrieval behavior:

- SQLite-backed storage provider
- synchronous raw source ingest plus queue state on `source_items` for async semantic processing
- compact per-item debug state embedded in `SourceItem.metadata` for integration explainability
- lexical retrieval over indexed text views
- vector retrieval over embedded text views via usearch index
- hybrid retrieval via `CompositeRetrievalProvider` fusing lexical and vector results with Reciprocal Rank Fusion (RRF, k=60, scale=600)
- named text-view metadata on `IndexEntry`
- indexing for both `SourceItem` and `MemoryObject`
- mixed retrieval over memory hits and compact source hits
- compact source-hit cards with explicit event refs instead of raw full content
- lifecycle-aware retrieval that excludes superseded memory by default
- optional retrieval trace on the debug query path, including matched tokens, candidate-flow counts, selected text views, routed exclusion reasons, result-origin summaries, and per-result retrieval origin (lexical, vector, or fused)
- package-owned candidate-aware routed reranking on top of retrieval results for `agent_conversation_memory`, with explicit safer-layer fallback exposed through the existing debug trace path
- evidence resolution from memory objects back to source items
- generic `visibility` plumbing on `SourceItem`, `MemoryObject`, and query requests, with fail-closed retrieval enforcement for scope-aware packages before ranking and visibility exclusion trace on the debug path
- explicit local integration-debug logging for processing outcomes, failures, memory provenance, and thread rebuild results, gated behind config rather than always-on logging

## Hybrid Retrieval Architecture

The production retrieval path is hybrid retrieval, fusing lexical and vector results.

Production query flow:

1. structured narrowing
2. lexical retrieval over named text views
3. vector retrieval over embedded text views
4. Reciprocal Rank Fusion (RRF, k=60, scale=600)
5. optional reranking
6. compact, evidence-backed result packaging

Design properties:

- lexical retrieval remains mandatory because technical memory includes exact names, IDs, acronyms, and rare terms
- vector retrieval is additive, not a replacement for lexical retrieval
- fusion is explicit via RRF rather than implicit score blending
- retrieval stays debuggable: Pallium can explain whether a hit came from lexical retrieval, vector retrieval, or fusion
- both `SourceItem` and `MemoryObject` remain first-class retrieval targets
- the trace and text-view model extend to vector hits without redesigning `IndexEntry`

Multilingual retrieval properties:

- lexical tokenization is Unicode-aware via centralized `core/text.py`
- non-Latin scripts (Hebrew, Arabic, CJK, Cyrillic) produce real tokens
- CJK scripts use character-per-token tokenization (no word segmentation dependency)
- combining marks (Hebrew niqud, Arabic vowels, Latin diacritics) stripped before tokenization
- content-overlap injection gate includes cross-script bypass for cross-language containers
- embedding provider supports query/passage prefix modes for multilingual models

Embedding write path:

- embedding happens at background processing time, not at ingest
- `SourceItem` embedding is plugin-owned: the semantic plugin boundary exposes a package method that controls which text views are embedded for source items
- all 6 promoted memory types are embedded
- `OnnxEmbeddingProvider` and `FastEmbedProvider` are both available; fastembed requires Python 3.12/3.13

## Implemented Semantic Behavior

Implemented semantic behavior now includes:

- an explicit `agent_conversation_memory` runtime package over the current LLM-backed semantic path
- a `conversational_knowledge` fact extraction package that extracts atomic facts from threads using the thread rebuild mechanism, runs as a `parallel_processing` package alongside `agent_conversation_memory`, and consolidates cross-thread facts into `fact_summary` objects via `FactConsolidationStrategy`
- deterministic and LLM-backed semantic plugins
- promoted typed memory for:
  - `decision`
  - `investigation_outcome`
- thread-level memory for:
  - `thread_summary`
- higher-level memory for:
  - `pattern_memory`
  - `continuity_memory`
  - `task_checkpoint`
- item-level typed memory for:
  - `constraint_memory`
- fallback: items that don't match any typed extraction produce no memory object (turn_summary fallback removed)
- prompt provenance attached to LLM-derived memory objects
- internal-only item semantic signals now extracted in the same item-level LLM call and persisted under `SourceItem.metadata["pallium_semantic_signals"]` for later higher-level synthesis
- work reference extraction for cross-surface work continuity:
  - external work identifiers (ticket IDs, PR numbers, incident keys) extracted from content via a dedicated "External References" prompt section
  - optional runtime hints via `pallium_work_refs` on source item metadata, merged with LLM extraction
  - normalized identifiers stored on `MemoryEnvelopeScope.work_refs` alongside `container_ref` and `thread_ref`
  - scoring affinity for continuity_memory with shared work_ref
  - packaging gate relaxation allows cross-thread bundling when work_refs match
  - query-time detection matches candidate work_refs as substrings of normalized query text

Current `agent_conversation_memory` evidence now includes selected assistant-originated work artifacts in addition to user messages and final assistant outputs:

- `artifact_kind="tool_use_summary"` with `role="assistant"` for explicit progress or blocker state
- `artifact_kind="todo_snapshot"` with `role="assistant"` for explicit next-step state

Prompt provenance fields currently tracked:

- `prompt_role`
- `prompt_schema_id`
- `prompt_schema_version`
- `prompt_variant`
- `model_role`
- `provider_name`
- `provider_kind`
- `model`

The shared prompt-role governance layer now owns the canonical role/schema contract for semantic prompt-backed work. The live `write_extraction`, `write_enrichment`, and selective query-time `query_ambiguity_resolution` runtime paths now run on that shared contract and normalized provenance, while `write_reconciliation` remains a contract-only later role.

## Provider Resilience

The provider layer now includes a shared resilience policy for live LLM access.

Current behavior:

- conservative retries for transient failures only
- bounded exponential backoff with jitter
- `Retry-After` honored when present
- request-id capture where vendors expose it
- bounded in-process concurrency per provider
- invalid successful responses remain fail-fast and are not retried

Current retryable classes:

- timeouts
- transport / connection failures
- `429`
- `500`, `502`, `503`, `504`
- Anthropic-style overload `529` treated as transient provider error

Current non-retryable classes:

- auth / request-shape failures such as `400`, `401`, `403`, `404`, `422`
- invalid response bodies after a successful provider response

Resilience is configured at the provider block level in `pallium.local.toml`, not per semantic package.

## Generic Core

The core remains domain-agnostic.

Core entities:

- `SourceItem`
- `MemoryObject`
- `Relation`
- `IndexEntry`
- `TypeRegistry` — packages register their memory types at startup; routing reads type metadata (display names, descriptions, categories) from the registry rather than hardcoding type knowledge

Important model properties:

- a source item does not always become memory
- a source item may produce zero, one, or multiple memory objects over time
- async processing uses a per-package tracking table (`PackageProcessingRecord`) keyed by `(source_item_id, use_case)`, enabling items to be processed by multiple packages independently
- packages with `parallel_processing = True` process every incoming item; packages without it are assigned via `use_case` matching as before
- raw source items remain package-neutral; queue/processing ownership lives in the per-package tracking records
- memory objects are evidence-backed and may point to one or more supporting source items
- generic visibility is separate from locality metadata; `container_ref`, `thread_ref`, and `session_ref` remain descriptive unless a package explicitly maps them into policy
- relations stay explicit and boring early on
- `IndexEntry` now models index type separately from named text view and provider/version metadata so later retrieval stages can reuse the same record shape

## Reusable Capabilities

Pallium now has its first reusable capability between the generic core and semantic packages: thread aggregation.

Current thread-capability behavior:

- atomic ingest remains the source-item unit
- items can be grouped by `container_ref + thread_ref`
- the capability rebuilds a deterministic thread aggregate as new items arrive
- when a package is visibility-aware, aggregation only combines exact same-visibility items
- semantic packages can consume that aggregate without making thread a universal core entity

The first package using this capability is `agent_conversation_memory`, which produces a queryable `thread_summary` memory object.

## Agent Conversation Memory Package

The first concrete product package is now agent conversation memory.

That package reuses the generic core and existing typed-memory path. It should be treated as the first semantic package proving value on top of Pallium, not as the definition of the platform itself.

Current package boundary:

- primary evidence units:
  - `artifact_kind="message"` with `role="user"`
  - `artifact_kind="assistant_output"` with `role="assistant"`
- selected assistant-originated work artifacts:
  - `artifact_kind="tool_use_summary"` with `role="assistant"`
  - `artifact_kind="todo_snapshot"` with `role="assistant"`
- primary value targets:
  - recurring-question recall
  - cross-thread continuity
  - assistant consistency
  - resumed-work continuity
- explicit non-goals for the package:
  - all workplace chat
  - arbitrary ambient messages that never flowed through the agent
  - full transcript replay as the default retrieval shape

The package reuses the current typed-memory extraction path rather than introducing a separate semantic engine.

It now also uses the shared thread aggregation capability to build one active `thread_summary` memory object per `container_ref + thread_ref`. Each thread summary is evidence-backed, lifecycle-managed through supersession, and can carry forward active `decision` and `investigation_outcome` conclusions from that conversation thread.

The package now also owns the query-routing policy that reranks retrieved candidates using both question shape and retrieved candidate evidence shape. Routing is cue-free: `QuerySignalEnvelope` is the canonical routing authority, consuming typed structure and retrieval evidence rather than English phrase matching. Three structural lanes — `work_resumption`, `evidence_trace`, `residual_recall` — narrow candidates before scoring. Recall modes derive weight-only preferences from candidate evidence. The generic core only carries mechanical `runtime_context` into that package hook and returns the package-owned outcome; memory-kind preference, injectability, and sharper investigative routing stay inside `agent_conversation_memory`. Pallium remembers and returns constraints but does not enforce them — enforcement is the consuming agent's job.

That package-owned query path now also has an explicit bounded query-policy layer ahead of final intent restriction and ranking. The default hot path stays deterministic: low-value queries can fail closed early, structural lane narrowing drives coarse policy-family selection, and package-owned ranking and packaging remain deterministic after policy narrowing. A selective `query_ambiguity_resolution` prompt role may run only for the small bounded ambiguity pairs that survive deterministic narrowing, and it may choose only among precomputed policy options with deterministic fallback.

The public `/query` contract now reflects that package-owned decision point. Pallium infers session lifecycle state (`turn_kind`, `session_has_sufficient_local_context`) from its own thread data — callers do not need to classify turns. Pallium returns explicit `should_inject`, `decision_reason`, and `injectable_blocks` alongside the generic ranked `results`. `/query/debug` keeps the richer trace and now also exposes package-owned injection decisions plus sharp-candidate diagnostics so routing, packaging, and cap drops are explainable.

For resumed-work queries, that same package-owned path adds explicit usefulness and freshness shaping for `task_checkpoint` plus adjacent evidence. Sharp checkpoints that preserve blocker, next step, evidence, and freshness can win cleanly, while thin or stale checkpoints can be demoted beneath fresher explicit source state without moving policy back into downstream agents.

`agent_conversation_memory` is now the first scope-aware package. It requires consumer-supplied `visibility` on ingest and query, preserves visibility on direct and higher-level memory, excludes missing-visibility evidence from promotion and normal retrieval, and relies on the core/capability layer for exact-match-only aggregation and consolidation.

Actor scoping extends the visibility model with per-memory attribution:

- personal memory types (`constraint_memory`) are only created in private containers; in shared containers they are suppressed with no fallback
- `constraint_memory` has a role guard — only user messages can create it
- `note` type is created via explicit ingest with `artifact_kind="note"` — bypasses standard type-classification extraction and uses a dedicated title-extraction prompt; content is preserved verbatim in payload, title provides retrieval metadata; durable (never garbage-collected), excluded from consolidation, injection truncates at 500 chars with `[+source]` pointer for expansion
- `actor_ref` on `MemoryObject` tracks who the memory is about, not who created it; set from source item in private containers, null in shared containers
- thread-level memories (`thread_summary`, `task_checkpoint`) always have `actor_ref = null` regardless of container type
- query-time actor filtering prevents personal memories from being injected into other users' contexts; shared memories (`actor_ref = null`) always pass the filter

Global visibility extends the model with cross-container actor-scoped memory:

- `visibility = "global"` is a special fourth value orthogonal to the `public/container/private` containment hierarchy
- semantics: personal memory that follows a specific actor across all containers
- always has `actor_ref` (the owner); visible in any container where `query_actor_ref == candidate_actor_ref`
- fail-closed: if either `candidate_actor_ref` or `query_actor_ref` is None, global memories are invisible
- `container_ref` on global items records provenance (where it originated) but does not bound retrieval
- only created by explicit user request (MCP `pallium_ingest` with `visibility: "global"`); automatic extraction never produces global memories
- `query_actor_ref` is threaded through the entire retrieval pipeline (lexical, vector, composite, query executor) to `is_visible()`
- `core/filters.py` exempts global from container_ref filtering (same as public) so global items reach the visibility check from any container
- does not participate in thread aggregation or cross-container consolidation

## Future Operational Scale

The current architecture intentionally accepts some write amplification in
exchange for explicit evidence, thread-level state, and compact derived memory.
One meaningful ingest can create:

- one raw source item
- one or more direct memory objects
- rebuilt thread-level memory such as `thread_summary` or `task_checkpoint`
- explicit evidence relations
- lexical index entries
- vector embeddings for promoted memory and plugin-selected source items

That is acceptable for the current selected-artifact, local-first product
assumptions, but it creates predictable future operational pressure in ingest
latency, LLM cost, thread rebuild amplification, index growth, and SQLite write
concurrency.

If later downstream usage justifies it, the preferred scale levers are:

- selective or debounced thread rebuilds
- broader background consolidation and scale work beyond the now-async ingest path
- bounded or incremental thread recomputation
- stricter artifact gating
- background consolidation scheduling
- backend upgrades only after the current product slice proves the need

## Lifecycle

Promoted memory now has a lifecycle model:

- `active`
- `superseded`
- `suppressed`

Current behavior:

- newly promoted memory defaults to `active`
- superseded memory remains stored and evidence-backed
- suppressed memory is flagged as bad by external feedback (integrating agents)
- default retrieval does not surface superseded or suppressed memory as current
- raw source evidence remains searchable even when a promoted memory object is superseded or suppressed
- suppression is driven by a flag endpoint: integrating agents report bad memories, and after a configurable threshold of independent flags (default: 2 unique sources within 30 days), the memory lifecycle transitions to `suppressed`
- immediate suppression is available for human-reviewed triage (bypasses threshold)
- flags are stored for audit in a `memory_flags` table and cascade-deleted when the memory is cleaned by retention

Future lifecycle direction should stay generic rather than package-specific:

- lineage should explain how memory was formed and superseded
- confidence should weight how strongly memory is trusted
- decay should reduce stale-memory influence at retrieval time without deleting history

These are intended as future engine-level lifecycle signals, not semantic memory kinds.

## Snapshot Persistence

Pallium supports periodic SQLite snapshot persistence for ephemeral storage deployments
(containers, VMs, cloud compute). The live database runs on fast local/ephemeral disk while
consistent snapshots are written to a configurable durable path.

Current behavior:

- startup: restore newest valid snapshot to live DB path (before any child process spawns)
- runtime: periodic snapshots via SQLite backup API with page-level yielding to writers
- shutdown: best-effort snapshot after all children exit
- dirty tracking: snapshot only when DB modified since last snapshot (mtime-based)
- pruning: retains configurable number of most recent snapshots
- validation: `PRAGMA quick_check` on restore candidates, falling back to older snapshots
- vector index is not snapshotted — reconciliation rebuilds it from DB after restore

The snapshot worker runs as a restartable supervised child process alongside processors and
cleaners. WAL mode is enabled on the live database for concurrent read/write access.

Configuration: `[snapshot]` section in `pallium.local.toml` or `PALLIUM_SNAPSHOT_*` env vars.

## Semantic Regression

The repo now treats semantic evaluation as a first-class product asset.

Implemented pieces:

- one committed JSONL regression batch
- one eval harness that records:
  - raw LLM output
  - parsed JSON
  - normalized extraction
  - final promoted artifacts
- one baseline metrics document for the chosen model and prompt path

Current chosen path:

- provider: Anthropic Claude
- model: `claude-sonnet-4-6` (write_extraction), `claude-haiku-4-5` (background roles)
- extraction prompt variant: `strict_typed_memory_v8b_work_refs_separate`
- enrichment prompt variant: `search_context_v2_compact`
- prompt schema: `typed_memory_extraction`
- prompt schema version: `v8`
- OpenAI-compatible fallback: `gpt-5-mini` with `strict_typed_memory_v6_work_state_examples`

The item-level prompt now carries field-specific internal-signal rules and examples so a single extraction call can also emit low-value-meta, constraint, blocker, progress, next-step, and key-finding state. Higher-level memory objects can also carry write-time `retrieval_enrichment` produced by the separate `write_enrichment` role. Prompt changes should be validated both with stub tests and with comparative eval runners before defaults change; see [prompt-improvement.md](prompt-improvement.md).

## Tiered Memory

Tiered memory is now implemented as a reusable consolidation capability between the core and semantic packages.

Current behavior:

- first higher-level memory kinds:
  - `pattern_memory`
  - `continuity_memory`
  - `fact_summary` (from `conversational_knowledge` via `FactConsolidationStrategy`)
- first eligible lower-level inputs:
  - `thread_summary`
  - `decision`
  - `investigation_outcome`
  - `atomic_fact` (for `conversational_knowledge` consolidation only)
- consolidation remains bounded and additive
- exact-match visibility compatibility is a hard precondition for consolidation groups in the scope-aware package
- higher-level memory is evidence-backed and lifecycle-managed
- retrieval can return higher-level memory as a normal `memory_hit`

Current strategy hooks:

- `select_candidates`
- `group_candidates`
- `synthesize_group`
- `promote_group`

Implemented strategies for `agent_conversation_memory`:

- `thread_local_carry_forward`
- `container_topic_window`
- `thread_summary_anchored`

Implemented strategies for `conversational_knowledge`:

- `fact_consolidation` — groups `atomic_fact` by `(container_ref, subject, category)` into `fact_summary` objects; skips groups with fewer than 3 facts or fewer than 2 distinct threads

Current package default:

- `thread_summary_anchored`

The current default was chosen because it keeps thread summaries as the main interpretable unit, allows bounded cross-thread carry-forward, and stayed conservative on the current false-merge guard scenario. Current package policy now lets broader/cross-thread groups continue to produce `pattern_memory`, while bounded single-thread carry-forward groups can produce `continuity_memory`.

Current architectural stance on tiered memory:

- higher-level memory remains **promising but not yet fully product-proven**
- consolidation should remain bounded and policy-controlled, not broad global clustering
- grouping should stay symbolic-first:
  - package boundary
  - eligible lower-level types
  - container and time constraints
  - minimum overlap guards
  - synthesis only inside that bounded set
- `pattern_memory` is the first higher-level type, not the final higher-level ontology

Current main unresolved risk:

- principled candidate selection and grouping for consolidation

Current expected follow-up hardening:

- richer consolidation trace and merge rationale
- richer per-result retrieval provenance so later retrieval improvements can plug into the same routed trace path


