# Lessons

## 2026-03-09 - Idempotent ingest can hide semantic-path changes

Problem:
Re-running the same semantic scenario against an existing SQLite database can make it look like a new plugin path is not working.

Why:
Ingest is idempotent on `source_type + source_id`, so Pallium returns existing artifacts instead of reprocessing the source item.

Solution:
When validating semantic behavior changes, use a fresh database or new source IDs.

## 2026-03-09 - LLM path should fail explicitly, not silently downgrade

Problem:
Silent fallback from the LLM-backed plugin to deterministic extraction hides real provider and parsing failures.

Why:
That makes it hard to tell whether Pallium actually used the LLM path, and it can mask real integration problems.

Solution:
The LLM-backed plugin should not fall back to deterministic extraction. If the LLM path fails, treat it as an LLM-backed processing failure and surface it clearly.
