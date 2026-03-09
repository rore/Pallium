# State

## Last Updated

2026-03-09

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
- first consumer proof: simulated generic agent-memory workflow
- current slice includes API, core service, semantic plugins, LLM provider adapters, retrieval provider, SQLite storage provider, simulation script, Bruno collection, and pytest coverage
- ingest now supports explicit event refs for messages and assistant artifacts, and query returns compact source-hit cards with structured refs
- current semantic behavior includes deterministic and LLM-backed `decision` promotion, with `discussion_summary` used only for non-decision extraction results
- semantic eval uses a single JSONL input file and now defaults to `results.jsonl` plus `summary.json`, with split per-input artifacts only when explicitly requested
- semantic eval now supports bounded concurrency for faster prompt bakeoffs while preserving deterministic result order
- LLM-derived semantic artifacts now carry prompt schema id/version and prompt variant provenance for later maintenance
- token budget is now treated as an explicit semantic design concern alongside prompt quality
- the LLM-backed path no longer falls back to deterministic extraction on provider or parsing failure

## Verification Notes

- pytest passes locally in the repo venv
- semantic eval runner is verified with bounded concurrency and still writes results in deterministic input/prompt order
- the live HTTP flow succeeds against a fresh temporary database with the deterministic plugin
- the live HTTP flow also succeeds with the LLM-backed plugin against a local fake OpenAI-compatible provider
- a real OpenAI-backed run also succeeded against a fresh temporary database
- the current query contract returns decision memory hits, discussion-summary hits, and source hits

## Context Memory Note

- record important problem-and-solution pairs in `docs/context/lessons.md` so future sessions do not rediscover them

## Reference Points

- current queue and sequencing: roadmap/board.md
- accepted architecture and decisions: docs/context/architecture.md, docs/context/decisions.md
- fuller design rationale: docs/designs/

