Pallium now has its first realistic runtime shape for `agent_conversation_memory`: async ingest and background processors are shipped, thread rebuild work is serialized safely, queue/debug observability exists, the item-level semantic path extracts richer internal signals in the same LLM call, the cleaner-driven retention/runtime logging slice is shipped, and the live thread memory-quality plus thin-agent contract correction is shipped.

The current focus is no longer proving the runtime shape or fixing the first live integration breakages. Those slices are done. The next bar is to turn Pallium into a benchmarked memory-decision system with stronger evidence about where its next real bottlenecks are.

Current focus:
- keep `agent_conversation_memory` as the first product slice, but shift the next acceptance bar from feature completion to benchmarked confidence in Pallium's memory decisions
- make the agent memory-decision benchmark program the active `Next` feature so Pallium is scored as a thin-agent memory sidecar:
  - not only "was the right memory retrievable?"
  - but also "did Pallium inject the right thing, stay quiet when it should, and keep the downstream agent thin without local semantic compensation?"
- use that benchmark layer to measure the concrete product risks surfaced by live integration work:
  - low-value promotion
  - rebuild churn
  - sharp-vs-generic competition
  - injection decisions
  - thin-agent boundary correctness
- keep privacy, query-debug traceability, retention safety, and timestamped runtime logs as permanent regression gates while the benchmark program expands
- keep vector retrieval and hybrid fusion behind the benchmark work; only move them forward if the benchmark stack and live evidence show recall/paraphrase bottlenecks are now more important than memory-quality, injection, or lifecycle failures
- after the internal benchmark layer lands, add a targeted external memory pressure pack to expose core-engine blind spots our product-shaped evals may still miss, in this order:
  - LongMemEval for update, freshness, and cross-session change over time
  - LoCoMo for long noisy conversational recall and multi-hop memory pressure
  - MemoryAgentBench later for bounded incremental multi-turn agent-memory pressure

Concrete next steps:
- land the agent memory-decision benchmark program so authored scenarios, public-corpus slices, and downstream-style simulations all score `should_inject`, `decision_reason`, injected block quality, low-value/noise suppression, rebuild churn, and thin-agent boundary correctness
- then adopt the targeted external memory benchmark pressure pack so Pallium gets public pressure on stale-memory handling, update correctness, long noisy recall, and incremental memory drift without confusing those checks with the product acceptance gate
- after the internal and external benchmark layers exist, add the live miss-capture and replay-promotion loop so suspicious real cases become bounded miss bundles, reviewable promotions into replay fixtures, and safer shadow comparisons instead of staying anecdotal
- keep vector retrieval, hybrid fusion, shared-memory derivation, and cross-container memory behind this evidence loop rather than promoting them simply because they are architecturally available

What the current evaluation and live integration evidence established:
- broad recurring why-questions benefit most from consolidated `pattern_memory`, but live downstream-agent investigative prompts previously over-surfaced generic summaries when sharper lower-level memory existed; the shipped hardening slice corrected that and restored the broader recall guardrails
- resumed-work continuity benefits from `task_checkpoint`, but the stronger product question is now whether Pallium makes the right injection decision and stays quiet when local context is sufficient
- same-thread and precise factual questions should not default to higher-level memory, and investigative verdict questions need to remain sharply separated from broad recurring recall
- live downstream-agent runs showed that promotion noise, rebuild churn, injectability policy, and the lack of a canonical integration contract were product issues, not optional polish; those contract and routing corrections are now shipped
- the remaining benchmark gap is that current suites are still stronger on retrieval and continuity usefulness than on injection decisions, low-value promotion, rebuild churn, and thin-agent boundary correctness

Still out of scope for this phase:
- cold archive storage for expired raw evidence
- global contradiction resolution across all memory
- vector-assisted consolidation selection
- public API expansion for explicit retention administration
- replacing lower-level evidence-backed memory with only higher-level summaries
- turning Pallium into a workflow engine, transcript archive, or raw tool-log store
