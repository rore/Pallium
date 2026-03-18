![Pallium Banner](assets/logo/pallium_header.png)

# Pallium

Agents are bad at continuity.

They forget why decisions were made, lose investigation outcomes, and struggle
to resume interrupted work without replaying transcripts or rediscovering
context.

Pallium is a local-first memory sidecar for agents. It helps them remember
prior decisions, findings, and work state so they can answer follow-up
questions and resume interrupted work without replaying full transcripts.

Under the hood, Pallium stores selected evidence, derives compact evidence-backed
memory, and returns small reusable memory and evidence cards. Pallium also
keeps public and private scoped memory separate by default in the current
conversation package.

The main thing Pallium tries to preserve is knowledge created during the
agent's own work: conclusions, findings, constraints, and resumed-work
checkpoints that may not exist cleanly in Slack, Jira, docs, or code comments
yet.

The current product focus is deliberately narrow: agent-mediated conversations,
repeated questions, resumed-work continuity, and safe scoped recall. In other
words, Pallium is optimized for conversation continuity, not general knowledge
memory.

A typical use case:

- yesterday the agent investigated an issue and chose an approach
- today you ask "why did we choose this?" or "where did we leave off?"
- Pallium returns a compact decision or task checkpoint plus the supporting
  evidence

## Why Not Just Transcript Search, Summaries, Or A Vector DB?

Common approaches each solve part of the problem and miss part of it:

- transcript replay is large, noisy, and expensive to keep re-feeding to a
  model
- prompt summaries are brittle and often lose the evidence behind conclusions
- vector search can find related text, but technical investigations produce
  structured outcomes such as decisions, findings, rejected paths, and compact
  work-state checkpoints that do not behave like isolated text fragments
- runtime-local state helps within a session, but usually does not give you
  reusable cross-thread memory with clear evidence and scoped visibility rules

Pallium's approach is to keep small reusable memory for agent-mediated
conversations, especially repeated questions and resumed work, while preserving
links back to supporting evidence.

## What You Get If You Add Pallium

Today Pallium's concrete value is:

- fewer repeated rediscovery cycles
- more consistent follow-up answers
- better resumed-work continuity
- safe scoped memory boundaries
- inspectable retrieval when results look wrong

## What Exists Today

Current behavior:

- selected ingest for conversation evidence and bounded work artifacts
- compact query results that can return derived memory, source evidence, or
  both
- repeated-question recall and resumed-work continuity
- fail-closed scoped visibility for public and private memory
- a debug path for retrieval and visibility behavior

Current implementation surface:

- one local-first FastAPI service
- SQLite-backed storage
- `POST /items`, `GET /items/{source_item_id}/processing`, `POST /query`,
  `POST /query/debug`, and `GET /debug/queue/health`
- lexical retrieval plus package-level query policy for the current
  conversation package, including a deterministic hot path and selective
  semantic ambiguity resolution for bounded unresolved cases
- a supported terminal harness at `python -m app.agent_simulation` for
  inspectable thin-agent memory loops against the real HTTP contract

## Validation

The repository includes validation for the current product focus:

- extraction regression coverage for compact memory derivation
- repeated-question benchmark coverage
- resumed-work benchmark coverage
- evaluation for choosing between memory and source evidence on query
- integration-readiness scenarios
- reviewed public-corpus slices from WildChat and WildBench
- scoped-visibility checks and debug trace coverage

See [docs/validation.md](docs/validation.md) for the validation summary.

## How Integration Works

The runtime model is simple:

1. send selected events to `POST /items`
2. call `POST /query` before answering a follow-up question or resuming work
3. use the returned compact memory and evidence cards in your runtime or prompt

Use `POST /query/debug` when you need to understand missing results, returned
result shape, or visibility exclusions.

For local exploratory validation, use `python -m app.agent_simulation`. The
harness exercises the same ingest and query endpoints, shows the debug decision
path before the assistant turn, and keeps the downstream side thin by only
passing Pallium-approved injected blocks into the draft prompt when
`should_inject=true`.

For the current product focus, the best inputs are:

- agent-mediated user messages
- final assistant outputs
- selected assistant work artifacts such as explicit blocker summaries or next
  steps

## Best Fit Today

- agent-mediated follow-up questions
- resumed investigations or implementation work
- scoped public/private continuity

## Poor Fit Today

- full transcript archive
- broad workspace knowledge search
- general-purpose org memory

## Evaluate It In 10 Minutes

If you want to try Pallium quickly:

- run the local service
- open `python -m app.agent_simulation`
- ask a repeated-question or resumed-work prompt
- inspect `should_inject`, `decision_reason`, injected blocks, and top results
- save the session and replay it after a code change

Follow [docs/getting-started.md](docs/getting-started.md).

## What Pallium Is Not

Pallium is not:

- a transcript archive
- a vector DB wrapper
- an agent runtime
- a workflow engine
- broad workspace search
- a system-of-record database

## What Is Not Shipped Yet

The current repo does not yet ship:

- vector retrieval behind the retrieval boundary
- hybrid lexical plus vector fusion
- explicit shared-memory derivation
- cross-container bounded memory
- broad ambient workspace ingestion

## Read Next

Choose the next doc by job:

- problem and value: [docs/problem-and-approach.md](docs/problem-and-approach.md)
- 10-minute tryout: [docs/getting-started.md](docs/getting-started.md)
- integration guide: [docs/agent-integration.md](docs/agent-integration.md)
- HTTP API reference: [docs/http-api.md](docs/http-api.md)
- privacy and scoped recall: [docs/privacy-and-visibility.md](docs/privacy-and-visibility.md)
- memory structure and lifecycle: [docs/memory-model.md](docs/memory-model.md)
- validation and evidence: [docs/validation.md](docs/validation.md)
- current maturity: [docs/status.md](docs/status.md)
- deeper concepts: [docs/overview.md](docs/overview.md)
- architecture: [docs/context/architecture.md](docs/context/architecture.md)
