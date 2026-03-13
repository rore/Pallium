# State

## Last Updated

2026-03-13

## Repo Snapshot

- repository initialized locally and linked to GitHub
- first Python application scaffold exists and is runnable locally
- roadmap/ is the canonical planning workspace for queue and status
- docs/context/ holds stable project truth
- docs/designs/ holds deeper design threads and analyses

## Current Baseline

- first implementation language: Python
- architecture direction: single local-first service with clear module boundaries
- development style: walking skeleton before deeper hardening
- first concrete product package: `agent_conversation_memory`
- ingest supports explicit event refs for messages and assistant artifacts
- query returns compact source-hit cards with structured refs
- debug query now exposes retrieval trace plus package-owned routing trace over the same compact result set
- generic `visibility_context` now exists on ingest, storage, query, evidence, and debug trace for privacy-aware scope enforcement
- semantic behavior now includes:
  - `decision`
  - `investigation_outcome`
  - `thread_summary`
  - `task_checkpoint`
  - `pattern_memory`
  - `continuity_memory`
  - fallback `discussion_summary`
- reusable thread aggregation capability now exists for `agent_conversation_memory`
- `agent_conversation_memory` now accepts a bounded evidence set beyond user messages and final assistant outputs:
  - selected assistant-originated `tool_use_summary` artifacts for explicit progress or blocker state
  - selected assistant-originated `todo_snapshot` artifacts for explicit next-step state
  - those bounded artifacts can now be promoted into a compact `task_checkpoint` for resumed-work continuity
  - raw tool logs, raw MCP events, and exhaustive runtime notifications remain out of scope
- reusable bounded consolidation capability now exists for higher-level `pattern_memory` and `continuity_memory`
- semantic eval uses one committed JSONL regression batch and one baseline metrics document
- runtime can now select `agent_conversation_memory` as an explicit use-case entry point
- LLM-derived semantic artifacts carry prompt schema id/version and prompt variant provenance
- provider-level LLM resilience now includes conservative retries, backoff, request-id metadata, and bounded concurrency
- thread summaries now use an explicit-only, token-bounded prompt contract
- minimal lifecycle handling now exists for promoted memory:
  - `active`
  - `superseded`
- superseded memory is hidden from default retrieval while evidence remains searchable
- named text-view metadata now exists on `IndexEntry`
- current lexical trace records matched tokens and selected text views across `SourceItem` and `MemoryObject` retrieval
- `agent_conversation_memory` now applies internal routed retrieval policy across higher-level memory, lower-level memory, and source evidence
- `agent_conversation_memory` is now scope-aware and fail-closed: query visibility is required, missing-visibility ingest stays non-promotable and non-retrievable in normal scoped queries, and public/private memory stays separated through exact-match-only derivation
- a bounded offline public-corpus eval path now exists for WildChat reviewed-manifest selection plus a complementary WildBench reviewed task slice, with local helper workflows for both
- realistic agent-conversation scenarios now exist under `evals/agent_conversation/`
- recurring-question benchmark now exists under `evals/recurring_question/`
- authored developer-work continuity suite now exists under `evals/work_resumption/`
- memory-routing benchmark now exists under `evals/memory_routing/`
- aggregate developer-work confidence harness now exists under `evals/developer_work_confidence/`
- consolidation strategy comparison harness now exists under `evals/consolidation/`
- tiered-memory validation benchmark now exists under `evals/tiered_memory_validation/`
- committed examples/tests use a neutral library reservation and catalog sync sample domain

## Verification Notes

- last recorded benchmark/privacy/routing regression slice passes locally: `71 passed`
- focused retrieval-trace slice tests pass locally:
  - `tests/test_storage_sqlite.py`
  - `tests/test_api.py`
  - `tests/test_e2e.py`
- thread aggregation tests pass locally
- focused privacy and scope-enforcement slices pass locally:
  - `tests/test_visibility_scope.py`
  - `tests/test_storage_sqlite.py`
- focused routing and resumed-work slices pass locally:
  - `tests/test_thread_aggregation.py`
  - `tests/test_agent_conversation_memory_routing.py`
  - `tests/test_work_resumption_benchmark.py`
  - `tests/test_tiered_memory.py`
- focused public-corpus slice tests pass locally, including the small WildBench developer-continuation pack assets:
  - `tests/test_public_corpus_builder.py`
  - `tests/test_public_corpus_benchmark.py`
  - `tests/test_public_corpus_wildchat_local.py`
- live scenario harness run succeeded locally:
  - `evals/agent_conversation/output/local-agent-conversation-smoke`
  - `2` value scenarios found expected memory
  - `1` low-value scenario correctly added no memory signal
- live recurring-question benchmark run succeeded locally:
  - `evals/recurring_question/output/local-recurring-question-smoke`
  - `2` value scenarios where memory-backed won
  - `1` non-value scenario where memory-backed correctly did not win
- deterministic developer-work continuity benchmark now exists as the committed continuity guardrail:
  - `evals/work_resumption/`
  - scenario families now cover resumed investigation, blocker recovery, implementation continuity, review continuity, wrong-memory or stale-memory guards, and stronger no-value continuation guards
  - the gap rollup is partly hypothesis-driven because scenario-authored `dimension_gap_targets` contribute to it, so benchmark results should be read as guidance rather than neutral proof
  - the benchmark now exercises package-owned `task_checkpoint` memory for compact resumed-work continuity and separates failures into retrieval recall, routing/layer choice, result packaging/evidence, compact task-state packaging, no-value overreach, and stale/wrong-memory guard misses
- deterministic aggregate developer-work confidence run succeeded locally:
  - `evals/developer_work_confidence/output/local-developer-work-confidence-stub`
  - `24 / 24` policy-success scenarios across the authored work suite plus reviewed WildChat and WildBench packs
  - `0` privacy leaks, `0` wrong-memory failures, `0` stale-memory failures, and `0` no-value overreach failures in the committed stub confidence gate
- deterministic memory-routing benchmark run succeeded locally:
  - `evals/memory_routing/output/local-memory-routing-stub`
  - `10 / 10` policy-success scenarios
  - `0` false-merge failures
  - broad recall, continuity, precise fact, and evidence-trace scenarios all matched the current routed-policy expectations
- semantic regression baseline remains the committed real OpenAI run on the current batch
- current recorded semantic baseline on `gpt-5-mini` with `strict_typed_memory_v4_evidence_guarded` is:
  - `30 / 30` overall correct
  - `0` decision false positives
  - `0` investigation false positives
  - `0` false negatives
- unresolved thread summary overreach was observed in a live thread-evolution run and tightened with a stricter `thread_summary_extraction` v2 prompt before rerunning
- live OpenAI provider smoke call succeeded through the framework resilience layer and returned request-id metadata

## Context Memory Note

- record important problem-and-solution pairs in `docs/context/lessons.md` so future sessions do not rediscover them
- local config now uses `pallium.local.toml` for package/provider structure and `.env.local` for secrets or one-off overrides

## Reference Points

- current queue and sequencing: `roadmap/board.md`
- accepted architecture and decisions: `docs/context/architecture.md`, `docs/context/decisions.md`
- fuller design rationale: `docs/designs/`
- semantic baseline: `evals/semantic/baseline.md`

## Tiered Memory Notes

- bounded tiered memory now produces higher-level memory over `thread_summary`, `decision`, and `investigation_outcome`
  - `pattern_memory` for broad recurring recall
  - `continuity_memory` for repeated-answer carry-forward
  - `task_checkpoint` for compact resumed-work continuity when selected work artifacts provide explicit progress, blocker, or next-step state
- current package default strategy: `thread_summary_anchored`
- deterministic tiered-memory validation benchmark recorded:
  - `evals/tiered_memory_validation/output/local-tiered-memory-validation-stub`
  - all three strategies stayed false-merge-safe on the current scenario set
  - `container_topic_window` won the broad cross-thread prior-conclusion scenario with `pattern_memory`
  - `thread_local_carry_forward` and bounded single-thread `thread_summary_anchored` won the repeated-answer continuity scenario with `continuity_memory`
  - lower-level memory correctly beat higher-level memory on precise factual and evidence-heavy questions
- deterministic strategy-comparison run recorded:
  - `thread_local_carry_forward`: broad same-thread pattern coverage, no false merges
  - `container_topic_window`: most selective cross-thread grouping, no false merges after stopword filtering
  - `thread_summary_anchored`: broad useful pattern coverage with bounded cross-thread carry-forward and no false merges
- a live OpenAI-backed consolidation comparison can still fail transiently on provider `503`; the deterministic stub harness is the current reproducible comparison baseline
- external tiered-memory research broadly validates the current Pallium direction:
  - consolidate from trusted lower-level semantic units
  - keep higher-level memory additive and evidence-backed
  - keep tiered memory in a reusable capability layer with package-owned policy
- the main unresolved tiered-memory risk is still principled candidate selection and grouping
- `pattern_memory` should be treated as the first higher-level type, not the final higher-level ontology
- likely follow-up hardening after the current internal-routing slice:
  - richer per-result retrieval provenance so later vector and hybrid retrieval can flow through the same routed trace path
  - consolidation trace and merge rationale

## Next Hardening Direction

- the first bounded public real-interaction evaluation path now includes a local full-corpus WildChat workflow under `evals.public_corpus_wildchat_local` plus reviewed manifest selection
- the next hardening question is whether running that path on real local WildChat data shows the true bottleneck is:
  - paraphrase and concept recall
  - routed layer choice
  - result packaging and evidence presentation
- vector retrieval should follow only if the public-corpus eval shows lexical recall is the next real limitation

## LLM Resilience Notes

- provider calls now retry only transient failures with bounded conservative backoff
- OpenAI-compatible and Anthropic providers now capture request ids when available
- `Retry-After` is honored when present
- invalid successful responses remain fail-fast and are not retried
- live eval/benchmark paths now use the same provider resilience path as normal semantic extraction



