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

## Implemented Core and Retrieval Slice

Implemented HTTP endpoints:

- POST /items
- POST /query
- POST /query/debug
- GET /items/{source_item_id}/processing
- GET /debug/queue/health

Implemented abstractions:

- storage provider boundary
- retrieval provider boundary
- semantic plugin boundary
- LLM provider boundary with shared retry, backoff, and call metadata

Implemented storage and retrieval behavior:

- SQLite-backed storage provider
- synchronous raw source ingest plus queue state on `source_items` for async semantic processing
- compact per-item debug state embedded in `SourceItem.metadata` for integration explainability
- lexical retrieval over indexed text views
- named text-view metadata on `IndexEntry`
- indexing for both `SourceItem` and `MemoryObject`
- mixed retrieval over memory hits and compact source hits
- compact source-hit cards with explicit event refs instead of raw full content
- lifecycle-aware retrieval that excludes superseded memory by default
- optional lexical retrieval trace on the debug query path, including matched tokens, candidate-flow counts, selected text views, routed exclusion reasons, and result-origin summaries
- package-owned candidate-aware routed reranking on top of retrieval results for `agent_conversation_memory`, with explicit safer-layer fallback exposed through the existing debug trace path
- evidence resolution from memory objects back to source items
- generic `visibility_context` plumbing on `SourceItem`, `MemoryObject`, and query requests, with fail-closed retrieval enforcement for scope-aware packages before ranking and visibility exclusion trace on the debug path
- explicit local integration-debug logging for processing outcomes, failures, memory provenance, and thread rebuild results, gated behind config rather than always-on logging

## Target Retrieval Architecture

The current executable slice is structured-plus-lexical retrieval. The target retrieval architecture is hybrid retrieval.

Target query flow:

1. structured narrowing
2. lexical retrieval over named text views
3. vector retrieval over selected text views
4. explicit fusion
5. optional reranking
6. compact, evidence-backed result packaging

Design implications:

- lexical retrieval remains mandatory because technical memory includes exact names, IDs, acronyms, and rare terms
- vector retrieval is additive, not a replacement for lexical retrieval
- fusion should be explicit rather than implicit score blending
- retrieval should stay debuggable so Pallium can explain whether a hit came from lexical retrieval, vector retrieval, or fusion
- both `SourceItem` and `MemoryObject` remain first-class retrieval targets
- later vector and fusion slices should extend the current trace and text-view model rather than redesigning `IndexEntry`

Current intended fusion baseline:

- Reciprocal Rank Fusion (RRF) first
- weighted blending only later if labeled evaluation justifies it

## Implemented Semantic Behavior

Implemented semantic behavior now includes:

- an explicit `agent_conversation_memory` runtime package over the current LLM-backed semantic path
- deterministic and LLM-backed semantic plugins
- one summary annotation per ingested source item
- one typed candidate annotation when extraction matches a typed memory path
- promoted typed memory for:
  - `decision`
  - `investigation_outcome`
- thread-level memory for:
  - `thread_summary`
- higher-level memory for:
  - `pattern_memory`
  - `continuity_memory`
  - `task_checkpoint`
- fallback `discussion_summary` for non-typed extraction results
- prompt provenance attached to LLM-derived annotations and memory objects
- internal-only item semantic signals now extracted in the same item-level LLM call and persisted under `SourceItem.metadata["pallium_semantic_signals"]` for later higher-level synthesis

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

The shared prompt-role governance layer now owns the canonical role/schema contract for semantic prompt-backed work. In the first shipped slice, only the live `write_extraction` runtime path is migrated onto that shared contract; thread and consolidation prompts remain on their local runtime pattern until the later enrichment work consumes the shared contract directly.

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
- `Annotation`
- `Relation`
- `IndexEntry`
- `MemoryObject`

Important model properties:

- a source item does not always become memory
- a source item may produce zero, one, or multiple memory objects over time
- current async processing assigns exactly one semantic package (`use_case`) per source item; this is a deliberate current limitation, not the intended final multi-package architecture
- future multi-package support should keep raw source items package-neutral and move queue/processing ownership to per-package records keyed by `(source_item_id, use_case)` through an additive migration: add the new per-package table, backfill current single-package rows, switch worker claims, then retire source-item-level queue ownership later
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

The package now also owns the query-routing policy that reranks retrieved candidates across `pattern_memory`, `continuity_memory`, sharp lower-level conclusions, and source evidence using both question shape and retrieved candidate evidence shape. The generic core only carries optional mechanical `runtime_context` into that package hook and returns the package-owned outcome; memory-kind preference, injectability, and sharper investigative routing stay inside `agent_conversation_memory`.

The public `/query` contract now reflects that package-owned decision point. Callers can send optional runtime context such as `turn_kind` and `session_has_sufficient_local_context`, and Pallium returns explicit `should_inject`, `decision_reason`, and `injectable_blocks` alongside the generic ranked `results`. `/query/debug` keeps the richer trace and now also exposes package-owned injection decisions plus sharp-candidate diagnostics so routing, packaging, and cap drops are explainable.

For resumed-work queries, that same package-owned path adds explicit usefulness and freshness shaping for `task_checkpoint` plus adjacent evidence. Sharp checkpoints that preserve blocker, next step, evidence, and freshness can win cleanly, while thin or stale checkpoints can be demoted beneath fresher explicit source state without moving policy back into downstream agents.

`agent_conversation_memory` is now the first scope-aware package. It requires consumer-supplied `visibility_context` on ingest and query, preserves visibility on direct and higher-level memory, excludes missing-visibility evidence from promotion and normal retrieval, and relies on the core/capability layer for exact-match-only aggregation and consolidation.

## Future Operational Scale

The current architecture intentionally accepts some write amplification in
exchange for explicit evidence, thread-level state, and compact derived memory.
One meaningful ingest can create:

- one raw source item
- one or more annotations
- one or more direct memory objects
- rebuilt thread-level memory such as `thread_summary` or `task_checkpoint`
- explicit evidence relations
- lexical index entries

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

Promoted memory now has a minimal lifecycle model:

- `active`
- `superseded`

Current behavior:

- newly promoted memory defaults to `active`
- superseded memory remains stored and evidence-backed
- default retrieval does not surface superseded memory as current
- raw source evidence remains searchable even when a promoted memory object is superseded

Future lifecycle direction should stay generic rather than package-specific:

- lineage should explain how memory was formed and superseded
- confidence should weight how strongly memory is trusted
- decay should reduce stale-memory influence at retrieval time without deleting history

These are intended as future engine-level lifecycle signals, not semantic memory kinds.

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

- provider: OpenAI-compatible
- model: `gpt-5-mini`
- prompt variant: `strict_typed_memory_v4_evidence_guarded`
- prompt schema: `typed_memory_extraction`
- prompt schema version: `v5`

The item-level prompt now carries field-specific internal-signal rules and examples so a single extraction call can also emit low-value-meta, constraint, blocker, progress, next-step, and key-finding state. Prompt changes should be validated both with stub tests and with the opt-in real-provider smoke suite at `tests/test_semantic_llm_live.py`.

## Tiered Memory

Tiered memory is now implemented as a reusable consolidation capability between the core and semantic packages.

Current behavior:

- first higher-level memory kinds:
  - `pattern_memory`
  - `continuity_memory`
- first eligible lower-level inputs:
  - `thread_summary`
  - `decision`
  - `investigation_outcome`
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
- richer per-result retrieval provenance so later vector and fusion retrieval can plug into the same routed trace path


