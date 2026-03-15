Pallium now has its first realistic runtime shape for `agent_conversation_memory`: async ingest and background processors are shipped, thread rebuild work is serialized safely, queue/debug observability exists, and the item-level semantic path now extracts richer internal signals in the same LLM call rather than leaning mainly on caller-perfect artifact shaping.

Current focus:
- keep `agent_conversation_memory` as the first product slice, but move the next bar from "ship async infrastructure" to "prove that the current memory stack is actually useful under live Pelican-style interaction on top of Claude?"
- use the new observability surfaces as the default integration-debug path: queue health, per-item provenance, failure categories, thread rebuild outcomes, and `/query/debug` should explain why Pallium behaved the way it did without direct SQLite spelunking
- keep the richer item-level semantic extraction as a product hardening direction: Pallium should infer durable constraints, work-state, and analytical findings from ordinary conversation text without depending on perfect upstream artifact shaping
- treat live provider-backed semantic smoke tests as a practical quality loop for prompt changes, not just rely on stubbed normalization tests
- preserve the current product claim: Pallium should help an agent stay oriented across interrupted and resumed work without turning into the agent runtime, a workflow engine, or a transcript archive
- keep privacy as a permanent regression gate, not a one-time completed feature: every retrieval, routing, aggregation, debug-path, and live-semantic hardening slice must preserve fail-closed visibility behavior
- treat the canonical integration-readiness scenario as passed in-repo and use the aggregate developer-work confidence harness, reviewed WildChat/WildBench packs, and opt-in live semantic checks as the standing validation loop before deeper retrieval work
- keep memory bounded, evidence-backed, additive, inspectable, and more robust to realistic noisy agent output

Concrete next steps:
- use live Pelican threads plus the new debug/queue health surfaces to measure where Pallium still underperforms relative to Claude's built-in memory and where external typed/evidence-backed memory clearly helps
- keep the opt-in live semantic smoke suite as the default prompt-quality loop whenever item-level extraction changes, especially around low-value meta suppression, verdict extraction, and ordinary-text work-state inference
- use the expanded confidence harness and live integration observation to determine whether the next real bottleneck is lexical recall, routing/layer choice, result packaging, or the current single-package processing model
- add a vector retrieval provider behind the existing retrieval boundary only if the evaluation stack still shows paraphrase or concept recall as the main bottleneck after the current semantic/runtime hardening
- then add RRF-based hybrid retrieval fusion only if that evidence still supports a dual-mode retrieval path
- then add an explicit shared-memory derivation path so broader reuse happens through separate shared derived memory rather than in-place widening of local memory
- then treat multi-package source-item processing and cross-container/shared memory as later bounded architecture slices built on those foundations

What the current evaluation layer established:
- broad recurring why-questions benefit most from consolidated `pattern_memory`
- repeated-answer consistency benefits from bounded `continuity_memory` carry-forward
- resumed-work continuity benefits from compact `task_checkpoint` memory and selected work artifacts
- same-thread and precise factual questions should not default to higher-level memory
- exact factual and evidence-heavy questions should still prefer lower-level `decision` or `investigation_outcome` or raw source evidence
- the current routed policy is now candidate-aware, explainable, and safer on weak support, but it still begins from explicit query-text intent families and is not yet a final answer for messy real interaction phrasing
- the current confidence harness is now strong enough to tune Pallium meaningfully, but still reflects reviewed/authored and open-data cases rather than broad downstream production behavior
- the newer item-level semantic path is materially better than before, but live provider-backed checks remain necessary because prompt/schema additions can drift in ways stub tests do not reveal
- privacy enforcement and runtime observability are now in place, but trust depends on keeping both permanently regressed as the retrieval and semantic stack evolves

Still out of scope for this phase:
- private downstream-system coupling as a prerequisite for Pallium development
- global autonomous clustering over the full memory store
- vector-assisted consolidation selection
- public API expansion for consolidation control or query intent
- replacing lower-level memory with only higher-level summaries
- broad ambient-workspace knowledge coverage beyond agent-mediated memory
- turning Pallium into a workflow engine, transcript store, or raw tool-log archive
