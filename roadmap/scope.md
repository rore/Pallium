Pallium now has its first realistic runtime shape for `agent_conversation_memory`: async ingest and background processors are shipped, thread rebuild work is serialized safely, queue/debug observability exists, the item-level semantic path now extracts richer internal signals in the same LLM call rather than leaning mainly on caller-perfect artifact shaping, and the cleaner-driven retention/runtime logging slice is shipped.

The next architectural correction is to make the agent boundary explicit: downstream agents should send runtime facts and raw events, while Pallium owns memory judgment, ranking, injectability, and final carry-forward packaging. Live downstream-agent integration work showed that if Pallium returns only low-level ranked candidates, semantic policy leaks back into the agent and the integration stops being thin.

Current focus:
- keep `agent_conversation_memory` as the first product slice, but move the next bar from proving the runtime shape to fixing the concrete quality issues from live downstream-agent runs
- stop low-value turns from becoming durable memory and from triggering thread-summary churn so downstream agents can stay thin and Pallium owns more of the semantic policy itself, including inject-worthiness, final carry-forward packaging, and explicit injection decisions
- make investigative conclusion prompts surface `investigation_outcome` / `decision` / sharper evidence ahead of generic `thread_summary` and `discussion_summary`
- make the canonical agent integration contract part of the live memory-quality slice so Pallium accepts runtime context like turn kind and returns `should_inject`, `decision_reason`, and integration-ready `injectable_blocks` rather than leaving those decisions to the caller
- use freshness as an explicit signal for competing conclusions and working-state relevance rather than relying only on raw creation time
- keep privacy as a permanent regression gate while these ranking and lifecycle changes land
- keep vector retrieval and hybrid fusion behind these fixes; only move there if live downstream-agent evidence still shows recall rather than memory quality or retention as the next bottleneck
- once the current memory-quality contract lands, expand the benchmark program so Pallium is scored as a memory-decision sidecar:
  - not only "was the right memory retrievable?"
  - but also "did Pallium inject the right thing, stay quiet when it should, and keep the downstream agent thin without local semantic compensation?"
- after that internal benchmark layer lands, add a targeted external memory pressure pack to expose generic core-engine blind spots our product-shaped evals may still miss, with priorities in this order:
  - LongMemEval for update, freshness, and cross-session change over time
  - LoCoMo for long noisy conversational recall and multi-hop memory pressure
  - MemoryAgentBench later for bounded incremental multi-turn agent-memory pressure

Concrete next steps:
- ship low-value promotion suppression plus thread-rebuild gating so greetings, acknowledgments, and obvious meta chatter stay as raw evidence without creating `discussion_summary` memory or needless rebuilds
- add a dedicated investigative-conclusion routing path and sharper lexical/index views for `investigation_outcome`, `decision`, and `task_checkpoint`, plus an integration-ready query contract so Pallium returns filtered injectable blocks/results, explicit injection decisions, and `/query/debug` shows candidate type, score, and whether sharp memory was missing, demoted, excluded, or dropped during final injection packaging
- add bounded freshness-aware handling for competing same-kind conclusions so newer or more recently supported conclusions rank ahead of older ones without pretending global contradiction resolution is solved
- after that contract lands, promote the agent memory-decision benchmark program so Pallium is scored on injection decisions, low-value/noise suppression, rebuild churn, and thin-agent boundary correctness rather than only retrieval usefulness
- then adopt a targeted external memory benchmark pressure pack so Pallium gets public pressure on update handling, stale-memory behavior, long noisy recall, and incremental memory drift without confusing those checks with the thin-agent product acceptance gate
- after the internal and external benchmark layers exist, add a live miss-capture loop so suspicious real cases become bounded miss bundles, reviewable promotions into replay fixtures, and safer shadow comparisons instead of staying anecdotal

What the current evaluation and live integration evidence established:
- broad recurring why-questions benefit most from consolidated `pattern_memory`, but live downstream-agent investigative prompts can still over-surface generic summaries when sharper lower-level memory exists
- resumed-work continuity benefits from `task_checkpoint`, but low-value turn promotion and generic summary competition still weaken live retrieval quality
- same-thread and precise factual questions should not default to higher-level memory, and investigative verdict questions now need a sharper dedicated routing family rather than being treated as broad generic recall
- live downstream-agent runs exposed that promotion noise, rebuild churn, injectability policy, and the lack of a canonical integration contract are now product issues, not just optional polish
- those same runs also showed a benchmark gap: current suites are stronger on retrieval and continuity usefulness than on injection decisions, low-value promotion, rebuild churn, and thin-agent boundary correctness
- privacy enforcement, query-debug traceability, opt-in live semantic smoke tests, and timestamped runtime logs are already in place and should stay the validation loop while the current memory-quality slice lands

Still out of scope for this phase:
- cold archive storage for expired raw evidence
- global contradiction resolution across all memory
- vector-assisted consolidation selection
- public API expansion for explicit retention administration
- replacing lower-level evidence-backed memory with only higher-level summaries
- turning Pallium into a workflow engine, transcript archive, or raw tool-log store




