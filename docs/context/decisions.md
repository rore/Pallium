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

LLM-derived memory objects and eval traces should record the prompt schema id, prompt schema version, and prompt variant that produced them.

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
survives extraction failures). The usearch embedding also runs regardless of LLM
outcome — the source item is vector-searchable even during sustained LLM outages.
Policy: messages + assistant outputs >= 40 chars.

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

### 2026-04-05 - Unicode-aware tokenization and multilingual embedding support

Lexical tokenization replaced from ASCII-only `[a-z0-9]+` to Unicode-aware
pattern centralized in `core/text.py`. Handles Latin, Hebrew, Arabic, CJK
(character-per-token), Cyrillic, and Korean. Combining marks (Hebrew niqud,
Arabic vowels, Latin diacritics) stripped before tokenization. Four duplicate
TOKEN_PATTERN definitions consolidated into one canonical source.

Embedding provider interface extended with `EmbedMode` (query/passage) to
support models requiring asymmetric prefixes (e.g., multilingual-e5-small).
Prefix strings configured in TOML, injected by the provider. Default fallback
model remains bge-small-en-v1.5 for backward compatibility.

Content-overlap injection gate extended with cross-script bypass: when query
and candidate use entirely different Unicode scripts (e.g., Hebrew query,
English memory), the gate defers to vector similarity instead of blocking.

Stopword sets expanded from English-only to English + Hebrew. Explicit
stopwords supplement IDF weighting for edge cases IDF alone misses.

Why:

- non-Latin scripts produced zero tokens from `[a-z0-9]+`, making lexical
  retrieval and content-overlap routing non-functional for non-English content
- the content-overlap injection gate silently bypassed for non-Latin queries
  (empty token set), then after tokenizer fix would block valid cross-language
  candidates without the script-aware bypass
- embedding model swap requires prefix differentiation; the provider interface
  had no mechanism for query vs passage mode
- four duplicated TOKEN_PATTERN definitions were a maintenance hazard

### 2026-04-27 - Container as virtual thread with intentional scope overlap

Container-level extraction treats the container as a virtual thread: all
top-level messages (first item per thread_ref + threadless items) form a
coherent main-channel conversation. A thread parent appearing in both thread
and container extraction is intentional — the two scopes represent different
conversational contexts that may yield different facts. Thread scope extracts
within the sub-conversation context; container scope extracts within the
main-channel conversation context.

This means the first message of a multi-item thread is collected by both
scopes. Dedup via existing-facts context in the LLM prompt prevents redundant
extraction in the common case, and fact consolidation merges any remaining
overlap. Omitting multi-item thread parents from container scope would leave
gaps in the main-channel conversation.

Why:

- the container IS the main conversation — removing messages that happen to
  have replies would break the conversational flow at the container level
- different extraction contexts (sub-thread vs main-channel) can yield
  different facts from the same message
- dedup and consolidation handle overlap without special-case filtering
- the alternative (filtering out messages with replies) introduces fragile
  coupling between scope collection and thread item counts

## Open

### Ingestion policy

Need explicit rules for when a producer should submit a source item.

### Memory lifecycle

Need a clearer generic lifecycle model that eventually covers:

- richer lineage across derivation, consolidation, and supersession
- confidence as a generic trust signal
- decay as retrieval-time freshness weighting

The `suppressed` lifecycle state has been added (2026-04-17), partially addressing
expansion beyond `active` and `superseded`. Suppression is driven by external
feedback from integrating agents via a flag endpoint. Confidence and decay remain
open for future work.

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

### 2026-03-24 - Visibility value renamed from "limited" to "container"

The visibility enum value `"limited"` was renamed to `"container"` and the field
`container_visibility` was renamed to `visibility`. The `Visibility` type alias is
now unified in `core/visibility.py`. The legacy `visibility_context` field was
removed from API schemas.

Why:

- `"limited"` was ambiguous — it described a restriction, not a scope; `"container"`
  explains what it means (visible within this single container only)
- `container_visibility` was tautological; `visibility` is the correct generic name
- breaking change — existing DBs must be rebuilt after applying

### 2026-03-24 - Constraint memory unified on constraint_text; structured path removed

The `constraint_candidates` structured extraction path (ConstraintCandidate dataclass,
output schema field, parser, downstream constants) was fully removed.
`constraint_memory` is now created directly from the `constraint_text` signal,
mirroring the `interest_text` path. Dead constraint constants and functions in
`agent_conversation_memory_constraints` were also deleted.

Why:

- the structured candidates path added complexity without improving recall quality
- `constraint_text` natural-language extraction proved reliable enough that the
  structured intermediate step was wasted work
- keeps constraint memory creation symmetric with interest memory creation

### 2026-04-04 - Anchor prefilter layered defense over binary exclusion

The anchor prefilter's single binary gate (conflicting → hard-excluded) is replaced
with a three-tier defense:

1. **Demotion** — `anchored_conflicting` candidates enter the `insufficient` fallback
   bucket (`insufficient_retained_demoted`) instead of being hard-excluded. They
   survive via the fallback path when no aligned candidates exist.
2. **Tier penalty** — `ANCHOR_SECONDARY_TIER_PENALTY = 120` (== `ROUTING_FOCUS_BOOST`)
   is deducted from `base_routing_score` for all secondary-tier candidates after
   anchor_prefilter_states are merged. This guarantees aligned always outranks
   secondary even when secondary receives maximum focus boost.
3. **Secondary retention** — when aligned candidates exist, insufficient and legacy
   candidates enter `retained_memory_ids` as `secondary_tier` and fill result slots
   not consumed by aligned. `fallback_mode = "aligned_with_secondary"` is set when
   secondary candidates are present.

Why:

- the binary gate caused hard-miss results when the LLM made an extraction error and
  classified a relevant memory as conflicting instead of aligned
- secondary-tier retention lets correctly-relevant but under-extracted memories
  surface in remaining result slots without displacing aligned winners
- the penalty invariant (`penalty >= focus_boost`) is tested explicitly so the
  ranking guarantee is verifiable, not just assumed

### 2026-04-05 - Remove persisted annotation layer

The `Annotation` model, `AnnotationRecord` ORM, `annotations` DB table, storage
methods, and all `annotation_ids` / `annotation_count` API fields were removed.
The core data model is now four primitives: SourceItem, MemoryObject, Relation,
IndexEntry.

Why:

- annotations were a dead abstraction — their data was 100% duplicated in
  MemoryObjects; no query-time code ever read them
- the one functional dependency (provenance relay in
  `_semantic_provenance_from_process_result`) was validated to always succeed
  through the memory_object fallback path
- removing them simplifies the data model, reduces storage writes per ingest,
  and eliminates a concept that overlapped confusingly with the unrelated routing
  "annotations" (transient scoring dict keys on candidates)
- the transient `SemanticExtraction` (intermediate LLM extraction artifact) is
  preserved — the claim is that *persisted* annotations are unnecessary, not that
  intermediate extraction is unnecessary

### 2026-04-05 - Injection precision principle: wrong memory is worse than no memory

For fact recall, injecting a wrong memory is usually worse than injecting nothing.
For continuity/work resumption, an incomplete but directionally right memory can
still be useful, if it is clearly labeled as tentative and backed by evidence.
Unverified or low-confidence memory must not be injected as authoritative. When
uncertain, abstain or inject only as tentative evidence.

Why:

- a wrong injected memory can mislead the consuming agent into acting on stale or
  unrelated context — the agent has no way to know the memory is wrong
- no memory simply means the agent proceeds without context, which is the baseline
  — it loses nothing and can still ask the user
- this asymmetry means injection gates should err on the side of not injecting when
  the system cannot verify topical relevance
- for work resumption, directional context (e.g., "you were working on X") has
  value even if incomplete, but must be clearly scoped and evidence-backed
- this principle governs trade-offs in injection gate thresholds: when a candidate
  has retrieval signal (lexical/vector) but no verifiable content-word grounding
  with the query, the system should abstain rather than inject

### 2026-04-05 - Multi-package source item processing

Source items can now be processed by multiple semantic packages independently.
A per-package tracking table (`PackageProcessingRecord`) keyed by
`(source_item_id, use_case)` owns queue state. Packages with
`parallel_processing = True` process every incoming item; others are assigned
via `use_case` matching.

Why:

- the single-package limitation blocked running fact extraction alongside
  conversation memory on the same source items
- per-package tracking keeps raw source items package-neutral
- `parallel_processing` opt-in avoids forcing all packages to process all items

### 2026-04-05 - Routing as core service with TypeRegistry

Routing is now a core service called directly by `QueryExecutor`, not a
package-internal module. `TypeRegistry` lets packages register memory types
(display names, descriptions, categories) at startup. Routing reads type
metadata from the registry rather than hardcoding type knowledge.

Why:

- multi-package processing means multiple packages produce memory types that
  must be routed together at query time
- hardcoded type knowledge in routing would not scale across packages
- registry-driven metadata keeps routing package-agnostic while letting each
  package describe its own types

### 2026-04-05 - Fact extraction package: conversational_knowledge

The `conversational_knowledge` package extracts atomic facts from conversation
threads. It uses the existing thread rebuild capability, runs as a
`parallel_processing` package alongside `agent_conversation_memory`, and
produces `atomic_fact` memory objects.

Why:

- LoCoMo benchmark baseline (61.2% on conv-26) confirmed that
  `agent_conversation_memory` alone misses factual detail recall
- thread-level extraction captures facts that span multiple messages
- running in parallel keeps the existing conversation memory path unchanged

### 2026-04-06 - Fact consolidation via FactConsolidationStrategy

`FactConsolidationStrategy` groups `atomic_fact` objects by
`(container_ref, subject, category)` into `fact_summary` memory objects
via LLM synthesis. `fact_summary` is registered as `high_value=True`
in the type registry.

Why:

- LoCoMo multi_hop failures (11 of 15) were caused by cross-session
  fact scattering — facts about one person's activities were spread
  across many threads, and top-10 retrieval couldn't aggregate them
- grouping by subject + category produces one retrieval hit that
  answers aggregate questions ("What activities does Melanie partake in?")
- minimum thresholds (3+ facts, 2+ threads) avoid wasting LLM calls
  on small groups that retrieval already handles
- consolidation uses the existing ConsolidationRunner framework with
  no changes to the runner itself

### 2026-04-07 — FTS5 lexical retrieval

Replaced the O(N) full-table-scan lexical search with SQLite FTS5 inverted-index lookup + BM25 scoring. A standalone `lexical_fts` FTS5 virtual table lives alongside `index_entries`. Write and delete paths maintain both tables transactionally. BM25 scores (float) replace IDF integers; all routing consumers use `normalize_lexical_score()` for 0-1 normalization. See spec: `docs/specs/2026-04-07-fts5-lexical-retrieval-design.md`.

### 2026-04-09 - WAL journal mode for multi-process SQLite

WAL (Write-Ahead Logging) is enabled during schema initialization. WAL allows concurrent readers
during writes and reduces write contention between the API server, processors, and cleaners.

Why:

- DELETE journal mode (SQLite default) acquires an exclusive lock for the full transaction duration
- with sustained write pressure from multiple processes, this creates visible contention
- WAL allows readers to proceed during writes and narrows the write-contention window to commit time
- WAL is the recommended journal mode for multi-process SQLite on local disk
- also required for non-blocking snapshot persistence via the SQLite backup API

### 2026-04-09 - SQLite backup API for snapshot persistence

Periodic snapshots use Python's `sqlite3.backup()` with page-level yielding (`pages=256,
sleep=0.01`) instead of `VACUUM INTO`. Shutdown snapshots use `pages=-1` (all-at-once) since no
writers are active.

Why:

- `VACUUM INTO` holds a shared lock for the entire copy duration, blocking all writers
- at expected scale (hundreds of MB), this means seconds of write stall
- `sqlite3.backup()` copies pages in batches, yielding to writers between batches
- individual lock holds are microseconds per batch; writers see negligible contention
- the backup API produces a raw page copy (no defragmentation), which is acceptable — the goal is
  consistent snapshot, not compaction

### 2026-04-14 - Work reference (work_ref) for cross-surface work continuity

External work identifiers (ticket IDs, PR numbers, incident keys) extracted
from content via LLM and stored on `MemoryEnvelopeScope.work_refs` as
normalized structural scoping alongside `container_ref` and `thread_ref`.

Work_refs stored on MemoryEnvelopeScope, not envelope subjects — subject
anchors use token-overlap matching unsuitable for structural identifiers.
Query-time detection is data-driven (candidate work_refs matched as
substrings of normalized query text), not regex — consistent with the
cue-free control plane. Prompt places work_refs in a separate "External
References" section to avoid interference with decision classification.

Why:

- real agent work spans multiple threads and containers; structural
  identifiers provide precise cross-thread retrieval without depending on
  lexical/semantic similarity alone
- extracted from content primarily (LLM path), supplemented by optional
  runtime hints via `pallium_work_refs` metadata key
- scoring affinity (+40 for continuity_memory) and packaging gate relaxation
  enable cross-thread bundling when work_refs match
- does not override visibility rules — private memories stay private
- prompt schema bumped v7 → v8; default variant: `strict_typed_memory_v8b_work_refs_separate`
