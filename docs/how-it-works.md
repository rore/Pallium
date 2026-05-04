# How Pallium Works

This document covers Pallium's design rationale, memory model, and retrieval
architecture. Read the [README](../README.md) first for the quick version.

## Why Pallium Exists

Most agents can see the current thread. Many still fail at continuity:

- they forget why a decision was made
- they lose investigation outcomes across later follow-ups
- they resume interrupted work without the right context
- they blur public and private memory boundaries

Common approaches each cover part of this gap:

- **Transcript replay** — too much text, too much noise, repeated prompt cost
- **Prompt summaries** — lossy, hard to audit, disconnected from evidence
- **Vector search** — finds related text but doesn't give you structured
  conclusions, rejected hypotheses, or evidence-backed checkpoints
- **Runtime-local state** — helps within one session but doesn't survive across
  threads or conversations

Pallium's approach is to keep small, reusable, evidence-backed memory for
agent-mediated conversations — especially repeated questions and resumed work.

## What Goes In

Pallium stores selected evidence, not everything. For the current conversation
package, the high-value inputs are:

- user messages that define a question or task
- final assistant outputs containing reusable conclusions
- selected work artifacts: compact findings, blocker summaries, next-step
  snapshots

Selective ingest is part of the design. The goal is to preserve the few pieces
of context worth carrying forward, not to warehouse everything the runtime
sees.

## What Gets Derived

From stored evidence, Pallium derives compact reusable memory for concrete
jobs:

| Job | Memory type | Example |
|-----|-------------|---------|
| Prior conclusions | `decision` | "Use event time for ordering — avoids timezone drift" |
| Investigation findings | `investigation_outcome` | "Root cause: stale cache after deploy" |
| Thread orientation | `thread_summary` | "Discussed migration strategy, agreed on staged rollout" |
| Resumed-work state | `task_checkpoint` | "Blocked on API rate limit, next: implement backoff" |
| Explicit notes | `note` | "API key rotation: generate → vault → restart → verify → revoke" |
| Factual knowledge | `atomic_fact` | "Jordan completed a half-marathon in Denver in March 2024" |
| Consolidated facts | `fact_summary` | Cross-thread factual summary grouped by subject and topic |
| Stated constraint | `constraint_memory` | "Must stay on Python 3.12 for compatibility" |
| Cross-thread carry-forward | `continuity_memory` | Same question answered consistently across threads |
| Recurring patterns | `pattern_memory` | Repeated architectural preference across conversations |

`continuity_memory` and `pattern_memory` are functional but not yet fully
product-proven — grouping and candidate selection need further hardening.

`note` is different from other types: it bypasses standard type-classification
extraction entirely. When a user explicitly asks to "remember something," the
integrating agent passes `artifact_kind="note"` on ingest. Pallium uses a
dedicated title-extraction prompt (not the standard extraction) to generate a
short heading for retrieval, and preserves the original content verbatim. Notes
are durable (never garbage-collected) and excluded from consolidation. At
injection time, long notes are truncated with a `[+source]` pointer so agents
can expand them on demand.

Items that don't match any specific type produce no memory object — only
items with clear typed signals (decisions, investigation outcomes, interests,
constraints) create persistent memory.

Every memory object stays linked to its supporting source evidence. Query
results can include both `memory_hit` (derived context) and `source_hit`
(supporting evidence), so the agent can orient quickly and still ground its
answers.

## Memory Scoping

Not all memory types are created in all contexts. Container visibility drives
which memory types are promoted and whether memories carry actor attribution.

**Private containers** (`visibility = "private"`):

All memory types are available. Memories carry `actor_ref` set to the speaker
from the source item. Everything in a private container is personal to the
container owner.

**Shared containers** (`visibility = "container"` or `"public"`):

Personal memory types — `constraint_memory` — are not created.
The statement remains available as source evidence but does not produce a
personal memory object. All memories in shared containers have
`actor_ref = null`.

This means a user stating a personal constraint in a team channel does not
produce a personal `constraint_memory` that could leak into another user's recall.
The source item is still available as evidence if queried directly.

**Thread aggregation** always produces shared memories (`actor_ref = null`)
regardless of container type. Thread summaries and task checkpoints describe the
conversation, not an individual. In private containers, container-level
visibility still restricts access.

The `actor_ref` field on memory objects tracks who the memory is about, not who
created it. Query-time actor filtering uses this field to prevent personal
memories from being injected into other users' contexts.

## How Memory Changes Over Time

- New memory starts as `active`
- Newer or better-supported memory can supersede older memory
- Superseded memory remains stored but hidden from default retrieval
- Source evidence remains available regardless of memory state

The lifecycle is intentionally minimal — enough to keep recall useful without
pretending memory never changes.

## Multilingual Support

Pallium is designed to be multilingual. Memory is preserved in the original
language and cross-language recall works natively — a query in one language can
retrieve memory stored in another. This is an intentional architectural
property, not an undocumented side effect.

Supported scripts:

- **Latin** (English, Spanish, French, German, etc.)
- **Hebrew** and **Arabic** (right-to-left, with combining mark stripping)
- **CJK** (Chinese, Japanese, Korean — character-per-token tokenization)
- **Cyrillic** (Russian, Ukrainian, etc.)

Key behaviors:

- Combining marks (Hebrew niqud, Arabic vowels, Latin diacritics) are stripped
  before tokenization so variant spellings match
- When query and candidate use entirely different Unicode scripts, the lexical
  content-overlap gate defers to vector similarity instead of blocking
- Embedding providers support query/passage prefix modes for multilingual
  models (e.g. E5 family). Pallium auto-detects prefixes for known model
  families.

For configuration, see [configuration.md](configuration.md#embedding-providers).

## How Retrieval Works

The query path follows a staged pipeline:

1. **Structured filters** — container, thread, artifact kind, role
2. **Visibility enforcement** — scoped access checked before ranking
3. **Hybrid retrieval** — lexical search + vector similarity, fused via
   Reciprocal Rank Fusion (RRF)
4. **Package routing** — `agent_conversation_memory` reranks based on query
   shape, memory type, and structural signals
5. **Injection decision** — Pallium decides whether to inject and returns
   `should_inject`, `decision_reason`, and `injectable_blocks`

Most integrations use `POST /item-and-query` to combine evidence storage and
memory retrieval in a single call. The separate `POST /items` and `POST /query`
endpoints are also available when you need them independently.

The query path is deterministic by default. A selective LLM-assisted
disambiguation step (using a fast model with conservative fallback) runs only
for a small set of genuinely ambiguous cases.

`POST /query/debug` exposes the full trace: retrieval matches, routing
decisions, visibility exclusions, and injection reasoning.

## When Pallium Returns Nothing

Pallium is designed to abstain rather than inject noise. These are the cases
where it returns `should_inject: false`:

| Reason | `decision_reason` | What happened |
|--------|-------------------|---------------|
| Low-value query | `low_value_query` | Greetings, acknowledgements, or meta-conversation that won't benefit from memory |
| Same-thread context | `same_thread_context_sufficient` | The agent already has the relevant context in its current conversation — injection would be redundant |
| No relevant memory | `no_relevant_memory` | Retrieval ran but nothing matched well enough to surface |
| Only low-value candidates | `only_low_value_candidates` | Matches found but all are too low-value to inject |
| Low injection confidence | `low_injection_confidence` | Candidates exist but confidence is too low to recommend injection |
| No candidates above floor | `no_candidates_above_floor` | Candidates exist but none scored above the minimum routing floor |
| Lane ambiguity | `lane_ambiguity` | The query didn't clearly map to a retrieval strategy and Pallium chose silence over a guess |
| No lane eligible | `no_lane_eligible` | No structural lane (work resumption, evidence trace, residual recall) matched the query shape |

This matters because memory systems fail more by false positives than by
missing features. Injecting stale, irrelevant, or redundant context is worse
than returning nothing — it wastes tokens and can mislead the agent.

Use `POST /query/debug` to see exactly why Pallium abstained. The trace shows
which candidates were retrieved, which were excluded by visibility or routing,
and which decision path was taken.

## Privacy Model

Locality is not privacy. `container_ref` identifies where an item belongs, and
`visibility` controls who can see it across containers.

- `public` — shared memories (`actor_ref = null`) visible from any container;
  personal memories (`actor_ref` set) visible only from their own container
- `container` — visible only within the same container (e.g. a private channel)
- `private` — visible only within the same container (e.g. a DM)

Visibility is enforced before ranking. Derivation preserves scope by exact
match — thread aggregation and consolidation never cross visibility
boundaries. Missing visibility on query returns nothing (fail-closed).

See [privacy-and-visibility.md](privacy-and-visibility.md) for the full
contract.

## Known Limitations

Current areas under active hardening:

- **Extraction confidence** — promoted memory objects carry a type-based
  confidence label but no instance-level support signal. Grounding checks
  exist for decision and investigation evidence fields (substring containment
  against source), but synthesized fields (constraint, summaries)
  have no post-extraction quality signal.
- **Contradiction supersession** — when a newer fact contradicts an older one,
  the atomic facts are correctly superseded but thread summaries containing the
  old fact persist. This can cause stale information to outnumber corrections
  in retrieval results.

## Internal Vocabulary

The generic core uses four primitives:

- **SourceItem** — one stored evidence unit from a producer
- **MemoryObject** — reusable memory promoted from evidence
- **Relation** — explicit links between evidence and derived memory
- **IndexEntry** — retrieval materialization over source or memory text

These matter for contributors and deeper integrators. They are not needed to
use Pallium as a consumer.

## Semantic Packages

Pallium processes stored evidence through semantic packages — each package
extracts different kinds of reusable memory from the same upstream events.
Packages run in parallel: the same ingested item can be processed by multiple
packages independently.

The two production packages serve complementary recall jobs:

- `agent_conversation_memory` — **work continuity**: prior decisions,
  investigation findings, resumed-work checkpoints, thread orientation, and
  scoped constraints. This is the package that answers "why did we choose
  this?", "what did the investigation find?", and "where did we leave off?"

- `conversational_knowledge` — **factual recall**: atomic facts extracted from
  conversation threads — names, dates, preferences, events, relationships.
  This is the package that answers "when did Jordan go camping?", "what's
  Maria's phone number?", and "which restaurant did they recommend?" Memory
  from both packages is preserved in the original language.

These packages cover different failure modes. Work continuity catches
structured conclusions that vector search misses. Factual recall catches
concrete details that continuity-focused extraction skips because they don't
fit decision/finding/checkpoint types.

Additional packages:

- `llm_agent_memory` — generic LLM-backed extraction over the semantic
  interface
- `demo_agent_memory` — deterministic skeleton for local testing without a
  live LLM provider
