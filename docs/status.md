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
- `POST /items`, `POST /query`, `POST /query/debug`
- selected ingest for user messages, assistant outputs, and bounded assistant
  work artifacts
- compact `memory_hit` and `source_hit` results
- scoped `visibility_context` enforcement with fail-closed behavior in the
  current package
- routed retrieval over memory and source evidence
- thread-level carry-forward and resumed-work checkpoints in the current slice

## What Is Validated Today

The repo already contains meaningful proof layers:

- semantic regression coverage for the typed extraction path
- recurring-question benchmark coverage
- developer-work resumption benchmark coverage
- routed retrieval benchmark coverage
- public-corpus evaluation workflows for reviewed WildChat and WildBench slices
- privacy-aware retrieval behavior with debug trace visibility exclusions

This is stronger than a typical concept repo. The project includes both product
claims and ways to test those claims.

## Still Being Tuned Or Proven

The main open questions are easier to understand in plain language:

- when higher-level carry-forward memory should win over lower-level evidence
- how well resumed-work packaging holds up on messier real-world traffic
- the current routing boundary between broad recall, precise fact lookup, and
  work resumption
- whether lexical retrieval is enough, or whether vector or hybrid retrieval is
  the next real bottleneck

## Best Fit Today

- agent-mediated conversations
- repeated follow-up questions
- interrupted investigations or implementation work
- scoped public/private continuity

## Not The Best Fit Today

- broad workspace search
- raw transcript storage
- fully shared memory across many contexts
- general workflow orchestration

## Likely Next Bets

The next likely additions are:

- vector retrieval behind the current retrieval boundary
- hybrid lexical and vector fusion
- explicit shared-memory derivation
- cross-container bounded memory

## Where To Go Deeper

- product problem and approach: [problem-and-approach.md](problem-and-approach.md)
- 10-minute local walkthrough: [getting-started.md](getting-started.md)
- runtime integration: [agent-integration.md](agent-integration.md)
- privacy model: [privacy-and-visibility.md](privacy-and-visibility.md)
- concepts and model: [overview.md](overview.md)
- stable architecture truth: [context/architecture.md](context/architecture.md)