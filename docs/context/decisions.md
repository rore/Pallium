# Decisions

## Accepted

### 2026-03-07 - Generic core with semantic layer

Pallium will be built as a generic memory core with an extensible semantic
use-case layer on top.

Why:

- keeps the project reusable beyond a single internal consumer
- avoids baking domain objects into the core
- supports OSS positioning as a memory tool for agents

### 2026-03-07 - Source systems remain systems of record

Pallium should not mirror external systems wholesale.

Why:

- avoids duplication of authoritative stores
- keeps memory focused on derived knowledge
- reduces noise and storage bloat

### 2026-03-07 - Tiered memory is an extension, not v1 core

Tiered consolidation is important and should be designed for, but not required
for the first implementation.

Why:

- keeps v1 manageable
- preserves a differentiated long-term direction
- allows consolidation to be added without distorting the core model

### 2026-03-08 - Build a walking skeleton before deep model hardening

The project should start with a minimal end-to-end skeleton that includes all
major system elements, then evolve iteratively.

Why:

- reduces the risk of locking in the wrong abstractions too early
- keeps the system mentally graspable while the design is still evolving
- gives continuous end-to-end proof as capabilities expand

### 2026-03-08 - Use Python for the main Pallium service

The first implementation should use Python.

Why:

- best fit for rapid iteration on semantic processing and consolidation logic
- strong ecosystem for retrieval and text-heavy workflows
- good enough performance for a local-first, non-multi-tenant internal service
- aligns with the walking-skeleton approach better than a heavier runtime

### 2026-03-08 - Use a single-service architecture first

Pallium should start as a single local-first service with clear internal module
boundaries instead of multiple services.

Why:

- keeps the first implementation small and understandable
- preserves end-to-end flow without distributed-system overhead
- still allows later extraction of boundaries if needed

### 2026-03-08 - Start with a simulated agent-memory consumer

The first end-to-end usage should include a simulated generic agent that uses
Pallium as its unstructured memory layer.

Why:

- keeps the project grounded in a real consumer workflow
- exercises both write and read paths from the start
- avoids building storage and retrieval without proving actual use

### 2026-03-09 - Keep external dependencies behind replaceable abstractions

The first slice should isolate external dependencies behind thin interfaces.

Why:

- keeps the core and API independent of SQLite-specific logic
- preserves the ability to add Postgres later without changing core flow
- applies the same design posture to retrieval and semantic processing

### 2026-03-09 - Memory objects are explicitly evidence-backed

The intended model is that memory objects always point to one or more
supporting source items.

Why:

- keeps durable memory grounded in evidence
- supports later many-to-many evidence relationships without changing the core shape
- prepares the model for later synthesis and consolidation

### 2026-03-09 - Promotion is plugin-driven and selective

A source item does not automatically become a memory object.

Why:

- preserves the distinction between evidence, interpretation, and durable memory
- keeps the generic core disciplined
- avoids turning the system into a store of low-value promoted summaries

### 2026-03-09 - Mixed retrieval over memory and source evidence

The next retrieval layer should return both promoted memory and raw evidence in one explicit response contract.

Why:

- moves Pallium closer to its real value than memory-only lexical search
- keeps answers grounded in raw evidence
- reduces the risk that retrieval overfits to promoted summaries only

### 2026-03-09 - Validate typed memory before LLM extraction

The next semantic milestone should introduce deterministic typed memory for `decision` before adding an LLM-backed semantic plugin.

Why:

- separates architecture risk from LLM-quality risk
- proves that typed promotion works before semantic quality becomes the main variable
- keeps the next LLM milestone focused on extraction quality against a stable contract

### 2026-03-09 - Use provider-neutral prompts for structured semantic extraction

The first LLM-backed semantic milestone should work across both OpenAI-compatible and Claude-style APIs through a shared Pallium-side extraction contract.

Why:

- avoids provider lock-in through JSON mode or tool-calling features
- keeps the semantic plugin unaware of provider wire formats
- makes semantic quality comparable across providers under one extraction contract

### 2026-03-09 - Treat token budget as a first-class semantic design constraint

Prompt and response size should be managed deliberately as the semantic layer evolves.

Why:

- source item content is often the dominant token cost in extraction runs
- prompt growth can quietly make evals and production ingestion expensive
- explicit token-budget awareness helps balance precision against operating cost

### 2026-03-09 - Store prompt provenance with LLM-derived semantic artifacts

LLM-derived annotations, memory objects, and eval traces should record the prompt schema id, prompt schema version, and prompt variant that produced them.

Why:

- makes later maintenance and cleanup possible when prompts change
- supports comparing semantic behavior across prompt revisions
- keeps stored derived memory auditable instead of treating prompts as invisible runtime state

### 2026-03-12 - Position Pallium as derived knowledge memory for agents

Pallium should be positioned as a generic memory engine whose differentiated direction is derived knowledge memory, not only fact storage or episodic transcript recall.

Why:

- matches the implemented memory objects such as `decision`, `investigation_outcome`, `thread_summary`, `pattern_memory`, and `continuity_memory`
- better explains why evidence links, lifecycle, consolidation, and routed retrieval matter
- keeps the public claim narrow while still describing the real architectural direction

### 2026-03-20 - RRF as fusion baseline

Reciprocal Rank Fusion with k=60 and score scale=600. Chosen because it avoids
raw score blending between incompatible score scales (lexical token count vs
cosine similarity). Validated with real BGE-small embeddings.

### 2026-03-20 - Plugin-owned SourceItem embedding

SourceItem vector embedding is decided by the semantic plugin, not hard-coded in
core. Decoupled from semantic processing success (persisted before processing,
survives extraction failures). Policy: messages + assistant outputs >= 40 chars.

### 2026-03-20 - Local-first embedding via ONNX

OnnxEmbeddingProvider wraps onnxruntime + tokenizers directly, bypassing
fastembed's dependency chain. Same model, same output. fastembed works on
Python 3.12/3.13; onnx works on all supported versions.

### 2026-03-20 - Minimum similarity threshold 0.55

Validated that 0.3 provides zero noise filtering. 0.55 cuts false positives from
11 to 5 per query with zero recall loss. Provider-specific (BGE-small), not
architecture-level.

### 2026-03-20 - Minimum embedding content guard 40 chars

Texts shorter than 40 characters are too generic for meaningful vector
discrimination. Applied as a length check in build_embedding_text() and
source_item_embedding_text().

### 2026-03-21 - Bearer auth style for proxy-compatible providers

LLM provider config supports `auth_style` ("native" or "bearer") to switch
between `x-api-key` (direct Anthropic) and `Authorization: Bearer` (proxy
endpoints). Default is "native" for backward compatibility.

### 2026-03-21 - Per-role model configuration

Semantic packages support `model_roles` mapping (role -> model name) alongside
the package-wide `model` default. Mirrors the existing `prompt_variants`
pattern. Enables cost/quality optimization per LLM call type (e.g., Sonnet for
extraction, Haiku for summaries and resolver).

### 2026-03-21 - Combined LLM calls for thread and consolidation

Thread rebuild and consolidation each use a single combined LLM call instead of
separate extraction + enrichment calls. Reduces thread rebuild from 4 calls to
1 and consolidation from 2 to 1. Motivated by proxy rate limits and general
efficiency. Enrichment context is folded into the parent prompt schema.

### 2026-03-21 - Haiku for thread aggregation and consolidation roles

Thread aggregation (summary + checkpoint) and consolidation (pattern + continuity
memory) use Haiku instead of Sonnet. Benchmarked: identical routing accuracy
(11/11), improved work resumption contract (100% vs 92.3%), no wrong memory.
These roles have simpler schemas and code-level fallback defaults that compensate
for weaker LLM output. Write extraction stays on Sonnet (quality-critical,
14-field schema with strict evidence rules).

### 2026-03-22 - Constraint boundary correction

Pallium remembers and returns constraints; it does not enforce them. The
consuming agent handles enforcement. The constraint compatibility engine was
removed (~1000 lines), including the `constraint_policy` routing lane and
structured constraint profiles. Constraint memories now route through
`residual_recall` like other memory types. Rationale: Pallium is a memory
sidecar — enforcement is the consumer's job, not the recall layer's.

### 2026-03-22 - Cue-free control plane

English cue tables removed from the `agent_conversation_memory` control plane.
Routing uses typed structure (`QuerySignalEnvelope`) and retrieval evidence, not
English phrase matching. ~40 English constants eliminated. Scoring formula
simplified from 7 to 5 components. Three routing lanes remain:
`work_resumption`, `evidence_trace`, `residual_recall`.

### 2026-03-23 - Three-tier exploratory QA with invariant-driven evaluation

Automated exploratory QA uses taxonomy-driven scenario generation evaluated by
universal invariants (not hand-authored expected outcomes). Three tiers control
when scenarios run:

- **P0** (correctness gate, ~15-25 scenarios): scope violations, actor leaks,
  visibility bugs, role attribution. Run on demand before merging. Must pass.
- **P1** (quality gate, ~50-100 scenarios): off-topic injection, routing errors,
  greeting suppression, IDF discrimination. Run nightly or pre-release.
- **P2** (coverage expansion, hundreds+): LLM-generated scenarios from taxonomy
  dimension pairs. Run on-demand for exploration. Never in a build pipeline.

Confirmed bug from any tier gets promoted into the P0/P1 regression set with
authored expectations. The corpus grows at the regression layer, not the build
layer. Generated scenarios are gitignored; seed and promoted scenarios are
committed.

Infrastructure: `evals/generated_exploratory/` (invariants, runner, taxonomy,
seed scenarios). 13 invariants (INV-01 through INV-13). Runner supports
multi-step scenarios (ingest → drain → query → check invariants per step).

Why:

- manual exploratory testing found 12 bugs in 3 sessions but doesn't scale
- invariants catch bugs without per-scenario expected outcomes
- tier separation keeps fast tests fast and exploration unbounded
- promotion pipeline converts discovery into durable regression protection

### 2026-03-23 - Container-driven actor scoping

Container type drives memory scoping, not memory type detection or content
analysis. Personal memory types (`interest`, `constraint_memory`) are suppressed
in shared containers (`container`, `public`) and fall through to
`discussion_summary`. `actor_ref` is propagated from source item only in private
containers; shared containers always produce `actor_ref = null`.

Personal memories (`actor_ref` set) do not cross container boundaries even when
public. Only shared memories (`actor_ref = null`) are visible cross-container.
This prevents a user's interest from one session bleeding into another session's
context while still allowing shared decisions and thread summaries to flow.

Why:

- detecting "I" vs "we" in content is unreliable — container type is a stable signal
- personal statements in shared channels should become shared evidence, not personal memories for other users
- personal memories from one container should not appear in a different container's context
- keeps the model simple: one nullable field plus container-driven rules, no taxonomy matrices or scope enums
- `constraint_memory` gets the same role guard as `interest` — only user messages can create it

### 2026-03-23 - IDF-weighted lexical scoring

Lexical search uses inverse document frequency (IDF) weighting instead of raw
token overlap count. Common words that appear in most documents score near zero;
rare domain-specific words score high. Language-agnostic — no stopword lists,
corpus statistics determine what's common.

Why:

- raw token count gave equal weight to "the" and "weather", causing off-topic
  injection (weather query matching vector DB memories on shared function words)
- IDF is the established solution — used in BM25, TF-IDF, and all major search engines
- language-agnostic approach avoids maintaining stopword lists per language
- zero additional I/O — IDF computed inline during the existing full-scan
- when retrieval moves to SQLite FTS5 or PostgreSQL, native BM25/ranking replaces this

### 2026-03-23 - Interest memory kind

`interest` captures specific-but-uncommitted user interest — stronger than
`discussion_summary`, weaker than `task_checkpoint`. Created when the LLM judges
that a specific subject is present and the speaker expressed meaningful
future-oriented interest without a concrete commitment.

Why:

- user-stated interest ("Chroma sounds interesting, I should check it sometime")
  was falling through to generic `discussion_summary` with no special weight
- cross-thread recall queries ("what was the db I wanted to check?") couldn't
  surface the interest because it was buried among other summaries
- user-only role guard prevents assistant responses from creating interest
- suppressed in shared containers (container/public) per container-driven scoping

## Open

### Ingestion policy

Need explicit rules for when a producer should submit a source item.

### Memory lifecycle

Need a clearer generic lifecycle model that eventually covers:

- richer lineage across derivation, consolidation, and supersession
- confidence as a generic trust signal
- decay as retrieval-time freshness weighting
- any later expansion beyond the current `active` and `superseded` states

### Query contract beyond mixed hits

Need to define how far the query API should evolve toward structured filters,
retrieval intent, and result-type-specific controls.

### 2026-04-03 - LLM self-classification for thread summary content_quality

Thread summary `content_quality` (substantive / query_only / unresolved / weak) is
now classified by the LLM via a schema field in the same JSON call that produces
the summary, rather than by post-hoc English substring matching against marker
lists. The structural shortcut (conclusions or work artifacts present → substantive)
and the `WEAK_THREAD_SUMMARY_TEXT` guard remain as deterministic checks that run
before the LLM classification.

Schema versions bumped: `thread_summary_extraction` v3 → v4,
`thread_summary_with_checkpoint_extraction` v1 → v2.

Why:

- the marker-based approach required a code patch each time the LLM generated a
  new phrasing for "this thread has no resolved information"
- this is the same brittleness the cue-free control plane (2026-03-22) eliminated
  from the routing layer, now extended to write time
- LLM self-classification of its own output in the same call is reliable with
  explicit enum descriptions (unlike cross-call inference)
- backward compatible: old memories without the field → None → not rejected by
  routing; falls through to support grade qualification
