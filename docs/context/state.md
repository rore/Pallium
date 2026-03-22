# State

## Last Updated

2026-03-22

## Repo Snapshot

- repository initialized locally and linked to GitHub
- roadmap/ is the canonical planning workspace for queue and status
- docs/context/ holds stable project truth
- docs/designs/ holds deeper design threads and analyses
- Pallium is still optimized for a narrow conversation-continuity slice, not broad workspace memory

## Current Baseline

- first implementation language: Python
- architecture direction: single local-first service with clear module boundaries
- first concrete product package: `agent_conversation_memory`
- current LLM provider: Anthropic Claude (Sonnet + Haiku via per-role model config)
  - Sonnet: write_extraction (quality-critical, 14-field schema)
  - Haiku: thread_aggregation, consolidation, query_ambiguity_resolution (simpler schemas, benchmarked equal or better)
- current extraction prompt: `strict_typed_memory_v7_claude_structured` (560 tokens, 55/55 on expanded fixture set, perfect signal extraction)
- normal local runtime goes through `python -m app.run ... --processors N`
- debug queue health exists at `GET /debug/queue/health`
- query/debug exposes retrieval trace plus package-owned routing and injection trace
- generic `visibility_context` exists on ingest, storage, query, evidence, and debug trace for privacy-aware scope enforcement
- promoted memory currently includes:
  - `decision`
  - `investigation_outcome`
  - `thread_summary`
  - `task_checkpoint`
  - `pattern_memory`
  - `continuity_memory`
  - fallback `discussion_summary`
- reusable thread aggregation and bounded consolidation capabilities are shipped for the current package
- item-level LLM extraction persists internal semantic signals under `SourceItem.metadata["pallium_semantic_signals"]`
- `agent_conversation_memory` now applies a cue-free control plane above routing:
  - routing uses typed structure and retrieval evidence, not English phrase matching
  - `QuerySignalEnvelope` is the canonical routing authority (Tier 1 structural, Tier 2 candidate evidence, no English cue fallback)
  - structural lane narrowing with 3 lanes: `work_resumption`, `evidence_trace`, `residual_recall`
  - `constraint_policy` lane removed — Pallium remembers and returns constraints but does not enforce them; enforcement is the consuming agent's job
  - recall modes derive weight-only preferences from candidate evidence
  - scoring formula simplified from 7 to 5 components
  - constraint compatibility engine removed (~1000 lines) — constraint memories route through `residual_recall`
  - ~40 English cue constants eliminated from the control plane
  - ordinary queries stay on the deterministic hot path with selective `query_ambiguity_resolution` only for bounded unresolved ambiguity
- role-specific prompt governance is live for:
  - `write_extraction`
  - `write_enrichment`
  - `query_ambiguity_resolution`
- role-specific prompt config is now part of the shipped runtime surface:
  - package `prompt_variant`
  - role-scoped `prompt_variants`
  - package `resolver_enabled`
  - package `resolver_timeout_ms`
- write-time retrieval enrichment is shipped for higher-level memory and stays off the query hot path
- grounded evidence checks now enforce source-backed investigation evidence and stricter normalized evidence handling for decision/investigation paths
- the initial live-improvement loop is now shipped:
  - drift metrics in the exploratory runner
  - shadow routing comparison via injectable routing overrides
  - replay-promotion tooling from exploratory captures into replay scenario skeletons
- committed examples and tests use a neutral library reservation and catalog sync sample domain
- hybrid retrieval is now the shipped production retrieval path:
  - `CompositeRetrievalProvider` fuses lexical and vector results via Reciprocal Rank Fusion (RRF, k=60, scale=600)
  - `OnnxEmbeddingProvider` and `FastEmbedProvider` available; fastembed requires Python 3.12/3.13
  - all 6 promoted memory types are embedded at background processing time, not at ingest
  - `SourceItem` embedding is plugin-owned via a package method on the semantic plugin boundary
  - production `/query` path activates hybrid retrieval by default
  - retrieval trace continues to show per-result origin (lexical, vector, or fused)

## Verification Notes

- the repo now has a stronger validation architecture than earlier phases, but hard-gate status still matters more than raw scenario totals
- current validation surface includes:
  - semantic extraction regressions
  - routing and injection tests
  - resumed-work and repeated-question benchmarks
  - public-corpus reviewed slices
  - low-value churn coverage
  - integration-readiness scenarios
  - live exploratory drift and replay-promotion tooling
- the developer-work confidence harness should be read by hard-gate fields first, not by aggregate scenario-success counts alone
- replay is now a real tooling surface, but replay coverage is still materially smaller than the authored confidence packs
- test suite: 631 passed, 5 skipped
- semantic extraction fixture set: 58 items (12 decisions, 14 investigations, 20 boundary-null, 13 signal cases)

## Configuration Note

- local config now uses `pallium.local.toml` for package/provider structure and `.env.local` for secrets or one-off overrides
- current config supports:
  - named provider blocks
  - named semantic package blocks
  - package prompt defaults
  - role-specific prompt overrides
  - role-specific model overrides (`model_roles`)
  - provider auth style (`auth_style` for proxy-compatible headers)
  - resolver toggles and timeout
  - observability and retention
- the reference for the shipped config surface is now `docs/configuration.md`

## Reference Points

- current queue and sequencing: `roadmap/board.md`
- accepted architecture and decisions: `docs/context/architecture.md`, `docs/context/decisions.md`
- fuller design rationale: `docs/designs/`
- semantic baseline: `evals/semantic/baseline.md`

## Next Hardening Direction

- the next hardening work should build on the shipped live-improvement loop rather than still describing it as future work
- roadmap ideas board was cleaned up (2026-03-21):
  - `idea-optional-embedding-provider-support` retired — realized by vector+fusion features
  - `idea-evidence-backed-agent-memory` retired — realized by the full agent_conversation_memory product slice
  - `idea-optional-llm-assisted-routing` retired — realized by query_ambiguity_resolution (bounded LLM tiebreaker)
  - `add-live-integration-improvement-loop-and-replay-pipeline` moved to Done — drift metrics, shadow comparison, and replay promotion all shipped
  - remaining ideas: lifecycle signals, scale hardening, multi-package processing, reranker support
- likely next architectural pressure remains:
  - explicit shared-memory derivation
- follow-on work around the live improvement loop should stay bounded to:
  - replay promotion quality
  - shadow tuning workflow
  - drift visibility
  - turning real misses into reusable generic failure classes rather than anecdotal fixes

## LLM Resilience Notes

- provider calls retry only transient failures with bounded conservative backoff
- OpenAI-compatible and Anthropic providers capture request ids when available
- `Retry-After` is honored when present
- invalid successful responses remain fail-fast and are not retried
- live eval and benchmark paths use the same provider resilience path as normal semantic extraction
- thread rebuild and consolidation use combined LLM calls (1 call per operation instead of 2-4)
