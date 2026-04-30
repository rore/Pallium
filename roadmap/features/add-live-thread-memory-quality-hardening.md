---
id: add-live-thread-memory-quality-hardening
title: Live thread memory quality hardening
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Fix the memory-quality issues surfaced by live downstream-agent integration runs: low-value conversational turns are still being promoted too often, thread summaries are rebuilt too eagerly, and investigative verdict prompts still let generic summaries beat sharper lower-level memory.

This slice should make Pallium create less noise, rebuild less often, surface the right memory kind for investigative and resumed-work queries, keep semantic policy inside Pallium rather than pushing more shaping logic into downstream agents, and return integration-ready carry-forward output and injection decisions that downstream agents can use directly.

## Why

The live integration run showed that Pallium is already producing useful memory, including `task_checkpoint`, but real usefulness is being dragged down by three concrete issues:

- greetings, acknowledgments, and meta chatter still become `turn_summary` memory
- nearly every substantive or non-substantive turn still schedules a thread rebuild
- investigative prompts can still return generic `thread_summary` / `turn_summary` when a sharper `investigation_outcome`, `decision`, or stronger evidence-backed candidate exists

Those problems increase DB noise, weaken retrieval quality, make later retention harder, and create pressure to move ranking, memory-worthiness, and injectability policy into the downstream agent when Pallium should own that logic.

## In Scope

- suppress durable memory promotion for low-value meta turns when item-level semantic signals mark `is_low_value_meta=true`
- keep raw `SourceItem` evidence for those turns, but do not create `turn_summary` memory by default
- add an explicit internal processing signal so semantic packages can decide whether a source item should schedule thread rebuild work
- make `agent_conversation_memory` schedule rebuild only when the item contributes durable value such as:
  - typed conclusion
  - substantive non-low-value summary
  - constraint / blocker / progress / next-step / key-finding signal
  - selected assistant work artifact
- add a dedicated investigative-conclusion routing family for prompts like:
  - what had we concluded
  - which repo changed more and why
  - what did the investigation find
- extend the non-debug query input so downstream agents can send a small amount of explicit runtime context such as:
  - `turn_kind`
  - whether the active session already has sufficient local context
  while keeping that context mechanical rather than semantic
- for that routing family, prefer in order:
  - `investigation_outcome`
  - `decision`
  - source evidence
  - `thread_summary`
  - `turn_summary`
- keep current `work_resumption` behavior for blocker/progress/next-step prompts, with `task_checkpoint` still first there
- strengthen lexical/index views for `investigation_outcome`, `decision`, and `task_checkpoint` using their conclusion, rationale, blocker, progress, next-step, and freshness text
- add explicit freshness metadata for memory objects so routing can rank newer competing same-kind conclusions above older ones
- allow same-thread same-kind lower-level conclusions to supersede older ones when the newer item is clearly a replacement for the same conclusion family
- make the non-debug query contract return dedicated integration-ready `injectable_blocks` or `injectable_results` rather than forcing downstream agents to infer injectability from generic ranked results
- make the non-debug query contract also return Pallium-owned injection judgment such as:
  - `should_inject`
  - `decision_reason`
  so the downstream agent does not need to guess whether same-thread context is already sufficient or whether only low-value candidates were found
- make those integration-ready blocks/results already be:
  - filtered
  - ranked
  - capped
  - compact enough for direct prompt injection
- ensure downstream agents do not need local semantic policy for:
  - memory-kind preference
  - inject-worthiness
  - weak-candidate dropping beyond a final hard cap
- keep downstream-agent responsibility mechanical:
  - refs
  - visibility
  - runtime seam timing
  - empty or duplicate payload protection
- improve `/query/debug` so it shows for sharp candidates such as `task_checkpoint`, `investigation_outcome`, and `decision`:
  - candidate kind
  - candidate score
  - injection eligibility
  - whether the candidate was not retrieved, retrieved but demoted, excluded later in routing or packaging, or dropped by the final injection cap
  - the stage where that loss happened

## Out of Scope

- hot-store retention and deletion policy
- dedicated cleaner runtime
- cold/archive storage
- global contradiction resolution across all threads and containers
- changing public query API shapes beyond debug trace detail
- making `task_checkpoint` the winner for non-resumption investigative questions

## Done When

1. Low-value greetings, acknowledgments, and obvious meta chatter no longer create durable `turn_summary` memory.
2. Low-value-only items no longer trigger thread rebuild scheduling.
3. Investigative verdict and continuation-style prompts surface `investigation_outcome` / `decision` or stronger evidence ahead of generic summaries and return fewer, sharper candidates.
4. The normal query contract accepts explicit runtime context and returns integration-ready injectable output plus Pallium-owned injection decisions that downstream agents can use without local semantic reranking.
5. Current resumed-work prompts still surface `task_checkpoint` first.
6. Competing same-kind conclusions use explicit freshness during ranking, and same-thread explicit replacements can supersede older lower-level conclusions.
7. `/query/debug` can show each sharp candidate's type, score, injection eligibility, and stage-of-loss when it was missing, demoted, excluded, or dropped by the final injection cap.
8. Live downstream-agent regression coverage proves reduced greeting/meta noise, better investigative retrieval, and downstream-ready injection output.

## Notes

Implementation defaults:

- keep summary annotations if needed for debugging/eval, but do not automatically create a durable memory object for low-value-meta items
- introduce package-driven rebuild gating through the process-result path rather than hard-coding rebuild rules in the generic service
- store memory freshness explicitly rather than inferring everything at query time from `created_at`
- treat cross-thread conflicting conclusions as competing candidates ranked by freshness and evidence; do not try to auto-resolve global truth in this slice
- add focused tests for:
  - low-value turn suppression
  - rebuild gating
  - investigative-conclusion routing
  - runtime-context-aware injection decisions
  - freshness-based same-kind ranking
  - integration-ready injectable output for new-thread continuation queries
  - debug trace explanations for sharp-candidate loss and final injection packaging


