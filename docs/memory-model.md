# Memory Structure And Lifecycle

This page explains the memory structure Pallium uses today.

Read this after the README or getting-started guide if you want to understand
what gets stored, what gets derived, and how memory changes over time.

## Plain-Language Model

Pallium keeps two kinds of information:

- selected source evidence from agent-mediated conversations
- derived memory built from that evidence

Those layers are separate on purpose.

Source evidence is the basis. Derived memory is the reusable interpretation that
helps later recall and resumed work.

## What Goes In Today

For the current conversation package, the main evidence inputs are:

- user messages
- final assistant outputs
- selected assistant work artifacts such as compact findings, blocker summaries,
  and next-step snapshots

Pallium does not treat every event as memory material. Selective ingest is part
of the model.

## What Pallium Derives From That Evidence

Today the current package derives memory for a few concrete jobs:

- prior conclusions
- investigation findings
- thread orientation
- resumed-work checkpoints
- bounded carry-forward across related earlier work

The current internal labels for those jobs include:

- `decision`
- `investigation_outcome`
- `thread_summary`
- `task_checkpoint`
- `continuity_memory`
- `pattern_memory`
- fallback `discussion_summary`

You do not need to think in those labels first to use Pallium, but they are the
current memory objects exposed by the implementation.

## How Evidence Links Work

Every memory object remains linked to supporting source evidence.

That means Pallium can return:

- a compact memory card for orientation
- source evidence for grounding, debugging, or later inspection

This is why query results can include both `memory_hit` and `source_hit` items.

## How Memory Changes Over Time

The current lifecycle model is minimal:

- new memory starts as `active`
- newer or better-supported memory can supersede older memory
- superseded memory remains stored
- default retrieval hides superseded memory as current
- source evidence remains available even when memory is superseded

The lifecycle model is intentionally small today. It is there to keep recall
useful without pretending that memory never changes.

## How Thread And Resumed-Work Memory Are Managed

The current package does more than store single conclusions.

It also manages:

- thread-level orientation through `thread_summary`
- resumed-work state through `task_checkpoint`
- bounded carry-forward memory when earlier work is useful to later work

This is part of why Pallium is more useful for continuity than transcript search
alone.

## How Scope Is Preserved

The current package preserves scope while managing memory.

That means:

- `visibility_context` is attached to evidence and memory
- derivation preserves scope by exact match in the current package
- thread-level rebuilds do not cross scope boundaries
- higher-level memory does not silently widen into broader shared memory

See [privacy-and-visibility.md](privacy-and-visibility.md) for the full privacy
rules.

## What Query Returns

`POST /query` and `POST /query/debug` return compact result cards.

In practice that means:

- `memory_hit` gives you reusable derived context
- `source_hit` gives you supporting evidence with refs and excerpt

The debug path adds retrieval and visibility trace information so you can see
why the result set looks the way it does.

## Why This Model Exists

The point of the model is practical:

- keep reusable continuity context compact
- keep evidence available
- avoid replaying full transcripts by default
- support repeated questions and resumed work in a bounded way

## Read Next

- evaluator path: [problem-and-approach.md](problem-and-approach.md)
- local walkthrough: [getting-started.md](getting-started.md)
- runtime usage: [agent-integration.md](agent-integration.md)
- API reference: [http-api.md](http-api.md)
- deeper architecture: [context/architecture.md](context/architecture.md)
