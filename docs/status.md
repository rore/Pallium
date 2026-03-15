# Status

This page is the external-facing status view for Pallium.

If you want maintainer detail, read `docs/context/state.md` and `roadmap/`.
If you want evaluator-friendly status, start here.

## Current Product Claim

The current shipped claim is narrow:

Pallium helps an agent remember prior conclusions and resumed-work state from
agent-mediated conversations strongly enough to answer repeated questions and
resume interrupted work more reliably.

## What Works Today

Current shipped surface:

- local-first FastAPI service
- SQLite-backed storage
- `POST /items`, `GET /items/{source_item_id}/processing`, `POST /query`,
  `POST /query/debug`, and `GET /debug/queue/health`
- selected ingest for user messages, assistant outputs, and bounded assistant
  work artifacts
- compact `memory_hit` and `source_hit` results
- scoped `visibility_context` enforcement with fail-closed behavior in the
  current conversation package
- a query path that can return derived memory, source evidence, or both
  depending on the question
- thread-level orientation and resumed-work checkpoints in the current product
  focus
- background processing for ingest and same-thread memory rebuilds

## What Is Validated Today

The current product focus is covered by:

- regression coverage for compact memory extraction
- benchmark coverage for repeated-question recall
- benchmark coverage for resumed-work continuity
- evaluation for choosing between memory and source evidence on query
- integration-readiness scenarios for the current package
- public-corpus evaluation workflows for reviewed WildChat and WildBench slices
- privacy-aware retrieval behavior with debug trace visibility exclusions

## What Is Still Experimental

The main open questions are:

- when broader carry-forward memory should win over lower-level evidence
- how well resumed-work packaging holds up on messier real-world traffic
- the current boundary between broad recall, precise fact lookup, and work
  resumption
- whether lexical retrieval is enough, or whether vector or hybrid retrieval is
  the next real bottleneck

## Best Fit Today

- agent-mediated conversations
- repeated follow-up questions
- interrupted investigations or implementation work
- scoped public/private continuity

## Poor Fit Today

- broad workspace search
- raw transcript storage
- fully shared memory across many contexts
- general workflow orchestration

## What Probably Comes Next

The next likely additions are:

- vector retrieval behind the current retrieval boundary
- hybrid lexical and vector fusion
- explicit shared-memory derivation
- cross-container bounded memory

## Where To Go Deeper

- product problem and approach: [problem-and-approach.md](problem-and-approach.md)
- 10-minute local walkthrough: [getting-started.md](getting-started.md)
- runtime integration: [agent-integration.md](agent-integration.md)
- HTTP API reference: [http-api.md](http-api.md)
- privacy model: [privacy-and-visibility.md](privacy-and-visibility.md)
- memory structure and lifecycle: [memory-model.md](memory-model.md)
- validation and evidence: [validation.md](validation.md)
- concepts and model: [overview.md](overview.md)
- stable architecture truth: [context/architecture.md](context/architecture.md)
