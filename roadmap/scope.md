Pallium now has its first realistic runtime shape for `agent_conversation_memory`: async ingest and background processors are shipped, thread rebuild work is serialized safely, queue/debug observability exists, the item-level semantic path extracts richer internal signals in the same LLM call, the cleaner-driven retention/runtime logging slice is shipped, and the live thread memory-quality plus thin-agent contract correction is shipped.

The north star for the next phase is not "add more memory features." It is to make Pallium reliably solve a bounded set of downstream-agent use cases:

- answer requirement and architecture questions from prior decisions and evidence
- resume long investigations with findings, blockers, and prior reasoning intact
- resume interrupted work from explicit checkpoints instead of transcript replay
- reuse prior answers safely across later conversations when the same conclusion should help again
- preserve findings discovered while exploring external systems without turning Pallium into the system of record
- keep long-lived conversation continuity compact and selective rather than defaulting to transcript growth
- let downstream agents stay thin by relying on Pallium's memory decisions instead of local heuristics

Current gap assessment against that north star:
- strongest today:
  - thread continuity
  - resumed-work checkpoints
  - bounded investigation carry-forward
  - package-owned injection decisions and compact carry-forward output
- partial today:
  - requirement / architecture recall when the decision or conclusion already exists in the current scope
  - repeated-question reuse within bounded local scope
  - evidence-backed reuse of findings that were surfaced clearly enough during the original interaction
- still weak or incomplete:
  - safe reuse beyond one thread or container
  - richer preserved reasoning structure such as rejected alternatives and changed decisions over time
  - robust stale-memory and update handling across longer gaps and changing truth
  - confidence that Pallium stays quiet when it should and does not force downstream semantic compensation
  - a systematic loop that turns real misses into permanent regressions and safer tuning decisions

Current focus:
- make the agent memory-decision benchmark program the active `Next` feature so Pallium is judged against the north-star use cases as a memory-decision system, not only as a retrieval stack
- use that benchmark layer to score the product risks surfaced by live integration work:
  - low-value promotion
  - rebuild churn
  - sharp-vs-generic competition
  - injection decisions
  - thin-agent boundary correctness
  - same-thread no-value behavior
- keep privacy, query-debug traceability, retention safety, and timestamped runtime logs as permanent regression gates while the benchmark program expands
- treat vector retrieval and hybrid fusion as lower-priority retrieval enhancements, not as the current product driver; only move them forward if the benchmark stack and live evidence show recall/paraphrase bottlenecks are now more important than memory-quality, injection, freshness, or scope reuse gaps

Plan from the current gaps:
- first, land the agent memory-decision benchmark program so authored scenarios, public-corpus slices, and downstream-style simulations score `should_inject`, `decision_reason`, injected block quality, low-value/noise suppression, rebuild churn, and thin-agent boundary correctness
- second, adopt the targeted external memory pressure pack so Pallium gets public pressure on stale-memory handling, update correctness, long noisy recall, and incremental memory drift without confusing those checks with the product acceptance gate
- third, add the live miss-capture and replay-promotion loop so suspicious real cases become bounded miss bundles, reviewable promotions into replay fixtures, and safer shadow comparisons instead of staying anecdotal
- fourth, move to explicit shared-memory derivation and then bounded cross-container memory so repeated-question reuse across later conversations becomes a stronger first-class capability rather than a byproduct of local scope only
- only after those layers are clearer should vector retrieval, hybrid fusion, and broader retrieval expansion move up, and only if the evidence shows recall rather than memory decision quality is the real bottleneck

What the current evaluation and live integration evidence established:
- broad recurring why-questions benefit most from consolidated `pattern_memory`, but live downstream-agent investigative prompts previously over-surfaced generic summaries when sharper lower-level memory existed; the shipped hardening slice corrected that and restored the broader recall guardrails
- resumed-work continuity benefits from `task_checkpoint`, but the stronger product question is now whether Pallium makes the right injection decision and stays quiet when local context is sufficient
- same-thread and precise factual questions should not default to higher-level memory, and investigative verdict questions need to remain sharply separated from broad recurring recall
- live downstream-agent runs showed that promotion noise, rebuild churn, injectability policy, and the lack of a canonical integration contract were product issues, not optional polish; those contract and routing corrections are now shipped
- the remaining benchmark gap is that current suites are still stronger on retrieval and continuity usefulness than on injection decisions, low-value promotion, rebuild churn, freshness/update handling, and safe reuse beyond local scope

Still out of scope for this phase:
- cold archive storage for expired raw evidence
- global contradiction resolution across all memory
- vector-assisted consolidation selection
- public API expansion for explicit retention administration
- replacing lower-level evidence-backed memory with only higher-level summaries
- turning Pallium into a workflow engine, transcript archive, or raw tool-log store
