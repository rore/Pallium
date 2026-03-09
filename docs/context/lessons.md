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

## 2026-03-09 - GPT-5 mini rejects forced temperature 0 on chat completions

Problem:
The OpenAI-compatible provider failed completely after switching to `gpt-5-mini`.

Why:
The provider hardcoded `temperature: 0`, and this model only accepts its default temperature on the chat completions endpoint.

Solution:
Do not force `temperature` in the OpenAI-compatible provider unless the target model explicitly supports it.

## 2026-03-09 - Prompt provenance must be stored with LLM-derived memory

Problem:
Prompt changes alter semantic behavior, but without recorded prompt provenance it becomes difficult to tell which stored memory objects were created under which prompt contract.

Why:
LLM prompt logic is part of the semantic package, not just ephemeral runtime configuration.

Solution:
Store prompt schema id, prompt schema version, and prompt variant in LLM-derived artifacts and eval traces.

## 2026-03-09 - Semantic eval speed is dominated by remote LLM latency

Problem:
Prompt bakeoffs and larger semantic eval batches became too slow for fast iteration when every LLM call ran sequentially.

Why:
The runtime cost is mostly network and provider latency.

Solution:
Run semantic eval with bounded concurrency and keep the output order stable.

## 2026-03-09 - Agent runtimes produce atomic events, not thread-native documents

Problem:
It is easy to design ingestion around whole threads or whole conversations, but real agent runtimes often emit one message or one assistant artifact at a time.

Why:
Upstream systems already own thread hydration, session tracking, and transcript collection.

Solution:
Treat message events and assistant artifacts as atomic `SourceItem`s. Keep thread, session, container, actor, and source references explicit on the item.

## 2026-03-09 - Investigation memory needs its own typed path

Problem:
Important findings and root-cause conclusions were collapsing into `discussion_summary` because only `decision` had a first-class typed memory path.

Why:
Many high-value agent events are explicit findings or diagnostic outcomes rather than committed choices.

Solution:
Promote a second typed memory class, `investigation_outcome`, in both deterministic and LLM-backed extraction.

## 2026-03-09 - A committed semantic regression set is necessary product infrastructure

Problem:
Ad hoc eval batches made it too easy to change prompts and extraction behavior without a stable quality reference.

Why:
Semantic quality is one of Pallium's main product risks, and it changes independently of API or storage behavior.

Solution:
Keep one committed labeled JSONL regression batch and record baseline metrics for the chosen model and prompt path.

## 2026-03-09 - Current typed-memory baseline is good but still over-promotes a few cases

Problem:
The real `gpt-5-mini` regression run on the 30-item committed batch did not collapse everything into one type, but it still produced three false positives.

Why:
The current prompt remains slightly too eager on:
- agreed need statements
- operational status statements
- detected backlog/symptom notifications

Solution:
Keep `strict_decision_v2_source_aware` as the current default because it is materially better than the looser prompt, but use the committed regression set to keep tightening abstention on non-decision, non-investigation events.

## 2026-03-09 - Lifecycle filtering should hide stale promoted memory without deleting evidence

Problem:
As repeated agent events accumulate, old promoted memory can become stale or superseded.

Why:
Deleting stale memory would lose provenance, but surfacing it as current would reduce trust.

Solution:
Keep raw evidence intact, add minimal `active` vs `superseded` lifecycle on promoted memory, and filter superseded memory from default retrieval.
