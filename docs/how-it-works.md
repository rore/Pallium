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
| Expressed interest | `interest` | "Chroma sounds interesting, should check it some time" |
| Stated constraint | `constraint_memory` | "Must stay on Python 3.12 for compatibility" |
| Cross-thread carry-forward | `continuity_memory` | Same question answered consistently across threads |
| Recurring patterns | `pattern_memory` | Repeated architectural preference across conversations |

A fallback `discussion_summary` covers cases that don't match a specific type.

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

Personal memory types — `interest` and `constraint_memory` — are not created.
They fall through to `discussion_summary`, preserving the statement as shared
evidence rather than personal memory. All memories in shared containers have
`actor_ref = null`.

This means a user saying "Chroma sounds interesting" in a team channel produces
a shared `discussion_summary`, not a personal `interest` memory that could leak
into another user's recall.

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

## Internal Vocabulary

The generic core uses five primitives:

- **SourceItem** — one stored evidence unit from a producer
- **Annotation** — semantic annotations derived from a source item
- **MemoryObject** — reusable memory promoted from evidence
- **Relation** — explicit links between evidence and derived memory
- **IndexEntry** — retrieval materialization over source or memory text

These matter for contributors and deeper integrators. They are not needed to
use Pallium as a consumer.

## Semantic Packages

The repo includes three packages:

- `agent_conversation_memory` — the production package for repeated questions,
  resumed work, and scoped continuity
- `llm_agent_memory` — generic LLM-backed extraction over the semantic
  interface
- `demo_agent_memory` — deterministic skeleton for local testing without a
  live LLM provider
