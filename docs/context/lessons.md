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


## 2026-03-09 - LLM decision extraction is still too permissive

Problem:
A 10-item semantic eval batch against a real OpenAI model promoted almost every item to `decision`, including discussion and investigation-style inputs.

Why:
The current prompt and validation contract make it too easy for the model to classify general conclusions or observations as formal decisions.

Solution:
Tighten the decision prompt and add stricter promotion validation before relying on LLM-produced `decision` memory at scale.

## 2026-03-09 - GPT-5 mini rejects forced temperature 0 on chat completions

Problem:
The OpenAI-compatible provider failed completely after switching to `gpt-5-mini`.

Why:
The provider hardcoded `temperature: 0`, and this model only accepts its default temperature on the chat completions endpoint.

Solution:
Do not force `temperature` in the OpenAI-compatible provider unless the target model explicitly supports it.


## 2026-03-09 - Stricter decision prompt reduces false positives substantially

Problem:
The baseline LLM prompt promoted too many discussions and findings into `decision` memory objects.

Why:
The prompt did not clearly distinguish committed choices from preferences, findings, or agreed needs.

Solution:
Add a stricter decision-only prompt variant with explicit non-decision cases. In the 40-item GPT-5 mini comparison run, this reduced false positives from 8 to 2 while keeping false negatives at 0.

## 2026-03-09 - Prompt provenance must be stored with LLM-derived memory

Problem:
Prompt changes can alter semantic behavior, but without recorded prompt provenance it becomes difficult to tell which stored memory objects were created under which prompt contract.

Why:
LLM prompt logic is part of the semantic package, not just ephemeral runtime configuration. Maintenance, cleanup, and reprocessing become much harder if prompt variants and schema versions are invisible in stored artifacts.

Solution:
Store prompt schema id, prompt schema version, and prompt variant in LLM-derived artifacts and eval traces.

## 2026-03-09 - Semantic eval speed is dominated by remote LLM latency

Problem:
Prompt bakeoffs and larger semantic eval batches became too slow for fast iteration when every LLM call ran sequentially.

Why:
The runtime cost is mostly network and provider latency, not local Python execution. Running prompt variants over tens of items multiplies the total wall-clock time quickly.

Solution:
Run semantic eval with bounded concurrency and keep the output order stable. Use `--max-concurrency` for faster bakeoffs while still writing `results.jsonl` in deterministic input/prompt order.
