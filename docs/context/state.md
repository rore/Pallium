# State

## Last Updated

2026-03-10

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
- semantic behavior now includes:
  - `decision`
  - `investigation_outcome`
  - fallback `discussion_summary`
- semantic eval uses one committed JSONL regression batch and one baseline metrics document
- runtime can now select `agent_conversation_memory` as an explicit use-case entry point
- LLM-derived semantic artifacts carry prompt schema id/version and prompt variant provenance
- minimal lifecycle handling now exists for promoted memory:
  - `active`
  - `superseded`
- superseded memory is hidden from default retrieval while evidence remains searchable
- realistic agent-conversation scenarios now exist under `evals/agent_conversation/`
- committed examples/tests now use a neutral library reservation and catalog sync sample domain
- recurring-question benchmark now exists under `evals/recurring_question/`

## Verification Notes

- `pytest` passes locally: `35 passed`
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

## Context Memory Note

- record important problem-and-solution pairs in `docs/context/lessons.md` so future sessions do not rediscover them
- local config now uses `pallium.local.toml` for package/provider structure and `.env.local` for secrets or one-off overrides

## Reference Points

- current queue and sequencing: `roadmap/board.md`
- accepted architecture and decisions: `docs/context/architecture.md`, `docs/context/decisions.md`
- fuller design rationale: `docs/designs/`
- semantic baseline: `evals/semantic/baseline.md`

