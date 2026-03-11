# State

## Last Updated

2026-03-11

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
- debug query now exposes retrieval trace over the same compact result set
- semantic behavior now includes:
  - `decision`
  - `investigation_outcome`
  - `thread_summary`
  - `pattern_memory`
  - `continuity_memory`
  - fallback `discussion_summary`
- reusable thread aggregation capability now exists for `agent_conversation_memory`
- reusable bounded consolidation capability now exists for higher-level `pattern_memory`
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
- realistic agent-conversation scenarios now exist under `evals/agent_conversation/`
- recurring-question benchmark now exists under `evals/recurring_question/`
- consolidation strategy comparison harness now exists under `evals/consolidation/`
- tiered-memory validation benchmark now exists under `evals/tiered_memory_validation/`
- committed examples/tests use a neutral library reservation and catalog sync sample domain

## Verification Notes

- `pytest` passes locally: `65 passed`
- focused retrieval-trace slice tests pass locally:
  - `tests/test_storage_sqlite.py`
  - `tests/test_api.py`
  - `tests/test_e2e.py`
- thread aggregation tests pass locally
- live scenario harness run succeeded locally:
  - `evals/agent_conversation/output/local-agent-conversation-smoke`
  - `2` value scenarios found expected memory
  - `1` low-value scenario correctly added no memory signal
- live recurring-question benchmark run succeeded locally:
  - `evals/recurring_question/output/local-recurring-question-smoke`
  - `2` value scenarios where memory-backed won
  - `1` non-value scenario where memory-backed correctly did not win
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
- likely follow-up hardening after the current continuity-memory slice:
  - retrieval-policy evaluation for when `pattern_memory`, `continuity_memory`, lower-level memory, or source evidence should win
  - consolidation trace and merge rationale

## LLM Resilience Notes

- provider calls now retry only transient failures with bounded conservative backoff
- OpenAI-compatible and Anthropic providers now capture request ids when available
- `Retry-After` is honored when present
- invalid successful responses remain fail-fast and are not retried
- live eval/benchmark paths now use the same provider resilience path as normal semantic extraction
