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
Important findings and root-cause conclusions were collapsing into `turn_summary` because only `decision` had a first-class typed memory path.

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
The committed regression set showed that prompt-only conservatism was not enough; the current best path is stricter evidence-grounded prompting plus code-side evidence gating. Make `strict_typed_memory_v4_evidence_guarded` the default typed-memory prompt and require typed-memory promotion evidence to contain a strong explicit cue.

## 2026-03-09 - Local config can silently override code defaults during semantic evaluation

Problem:
A real regression run used the old prompt behavior even after the code default changed.

Why:
`.env.local` can pin `PALLIUM_LLM_PROMPT_VARIANT`, which overrides the new code default.

Solution:
When validating a prompt change, either update `.env.local` or pass `--prompt-variants` explicitly to the eval harness so the run is unambiguous.

## 2026-03-09 - Lifecycle filtering should hide stale promoted memory without deleting evidence

Problem:
As repeated agent events accumulate, old promoted memory can become stale or superseded.

Why:
Deleting stale memory would lose provenance, but surfacing it as current would reduce trust.

Solution:
Keep raw evidence intact, add minimal `active` vs `superseded` lifecycle on promoted memory, and filter superseded memory from default retrieval.

## 2026-03-10 - Committed sample domains must stay neutral and public-safe

Problem:
Examples, tests, eval fixtures, and manual request collections started drifting into workplace-adjacent terminology.

Why:
Even when the product is shaped by an internal downstream use case, committed sample content is part of the public artifact surface and can leak internal context or make the project look narrower than it is.

Solution:
Keep committed examples and fixtures on a neutral public-safe sample domain. The current repo baseline uses library reservation and catalog sync examples, and new fixtures should follow that pattern unless there is an explicit decision to change the public sample domain.

## 2026-03-10 - Package-scoped config should live in TOML, not flat env vars

Problem:
A single global env-based LLM configuration does not scale once multiple semantic packages need different models and prompt variants.

Why:
Each semantic package is effectively its own runtime product surface and needs package-specific model and prompt settings.

Solution:
Use pallium.local.toml for named provider blocks and per-package semantic config, and reserve .env.local for secrets and temporary overrides.


## 2026-03-10 - Thread summaries must be explicit-only and token-bounded

Problem:
The first `thread_summary` prompt overreached on unresolved threads and generated recommendations and likely causes that were not actually stated in the thread.

Why:
The prompt asked for a concise future-recall summary but did not explicitly forbid inference, and it left the model too much room to turn an open question into a diagnosis or next-step plan. It also had no explicit budget guard for long thread material.

Solution:
Use a stricter thread-summary prompt that allows only explicit facts from thread items and carried conclusions, says unresolved threads must stay unresolved, caps the summary to about two sentences / 60 words, and bounds the thread material included in the prompt to protect token budget.

## 2026-03-10 - Container-level lexical overlap can false-merge unrelated memories

Problem:
A broad same-container consolidation strategy initially merged unrelated conversation memory because generic discussion words created accidental lexical overlap.

Why:
Container-scoped grouping is useful for cross-thread carry-forward, but low-signal tokens like generic conversation words can make unrelated threads appear connected.

Solution:
Keep the first tiered-memory strategies conservative, add consolidation-specific stopword filtering and minimum token length rules, and require stronger overlap before broad same-container grouping is allowed.

## 2026-03-10 - Live consolidation comparisons need defensive cleanup

Problem:
A live OpenAI-backed consolidation comparison failed on provider `503` and left the temporary SQLite file locked during teardown.

Why:
The comparison harness was disposing the storage engine only on the success path.

Solution:
Always dispose the temporary storage engine in a `finally` block so failed live comparison runs still clean up correctly.

## 2026-03-11 - LLM access needs resilience at the provider layer, not ad hoc in callers

Problem:
Live semantic evaluation and benchmark runs can fail on transient provider errors such as `429` or `503`, and package code should not need to reimplement retries or rate-limit handling.

Why:
Retries, backoff, and request-id capture are framework concerns shared by semantic extraction, thread summary synthesis, pattern synthesis, and answer-generation benchmarks.

Solution:
Keep resilience in the provider layer with conservative retries, bounded backoff, `Retry-After` support, request-id capture, and bounded in-process concurrency. Package code should continue to call the same `generate_json(...)` contract.
## 2026-03-11 - Tiered memory should consolidate from trusted intermediate units with symbolic guards first

Problem:
It is tempting to treat higher-level memory as broad semantic clustering over all stored events, but that creates the highest risk of false merges and misleading patterns.

Why:
Recent memory-system research and current Pallium experiments both point to the same weakness: principled grouping is the hardest part of consolidation, and broad semantic grouping alone is too fragile.

Solution:
Consolidate from trusted lower-level semantic units such as `thread_summary`, `decision`, and `investigation_outcome`, and keep grouping bounded by hard guards first:
- same package
- eligible memory types only
- container and time constraints
- minimum overlap requirements
Only then synthesize higher-level memory inside that bounded set.


## 2026-03-11 - Tiered-memory validation must separate broad recurring questions from precise factual ones

Problem:
A consolidation strategy can look helpful if it compresses lower-level memory, even when a precise factual or evidence-heavy question should still be answered from lower-level `decision` or `investigation_outcome`.

Why:
Context reduction alone is not the same as better retrieval policy. Broad recurring why-questions and repeated-answer continuity benefit from `pattern_memory`, but precise factual and evidence-heavy questions can lose useful precision if higher-level memory is allowed to dominate.

Solution:
Benchmark tiered memory in multiple modes: baseline, lower-level memory, and per-strategy higher-level memory. Score broad recurring questions separately from precise factual/evidence-heavy questions, and only count tiered memory as a win when it improves the intended question class without violating expected grouping shape.

## 2026-03-21 - Claude Sonnet needs explicit evidence cue lists for typed-memory classification

Problem:
When switching from GPT-5-mini to Claude Sonnet, compact prompts (v5, v6) that omit explicit evidence cue phrases ("Decision:", "Root cause:", "Investigation found", etc.) suffer severe under-promotion — investigation_outcome FN rates of 4-5 out of 11. Zero false positives; the failure is purely conservative.

Why:
Claude follows "only promote when explicit proof exists" instructions more literally than GPT. Without the explicit cue list, Claude cannot determine what counts as "proof" and defaults to null. GPT inferred acceptable evidence phrases from context; Claude does not.

Solution:
Always include the explicit evidence cue lists (decision cues: "Decision:", "we decided", "we chose"; investigation cues: "Root cause:", "Investigation found", "Verdict:", etc.) in extraction prompts for Claude. The v7_claude_structured variant achieves v4's accuracy (36/37) at 57% fewer tokens (560 vs 1318) by combining cue lists with structured sections. Instruction density helps Claude more than minimalism.
