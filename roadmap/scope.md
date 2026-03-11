Pallium now has a dedicated validation layer for tiered memory, and the current `agent_conversation_memory` package has a recorded safety/value baseline for higher-level `pattern_memory`.

Current focus:
- preserve the current product claim: Pallium improves cross-thread and cross-session recurring-question handling, not broad workspace search
- keep `thread_summary_anchored` as the current package default because the validation benchmark shows it is conservative, interpretable, and broadly useful
- use the new tiered-memory validation benchmark to judge when higher-level memory should help and when lower-level memory should still win
- keep tiered memory bounded, evidence-backed, and additive rather than operationalizing it as always-on behavior too early
- move the next retrieval work into explainability and text-view modeling before vector and fusion slices

Concrete next steps:
- add retrieval trace and text-view modeling so Pallium can explain why a hit appeared and prepare cleanly for hybrid retrieval
- then add a vector retrieval provider behind the existing retrieval boundary
- then add RRF-based hybrid retrieval fusion over lexical and vector candidates
- keep reranking as a later optional extension after hybrid retrieval is measurable

What the tiered-memory validation benchmark established:
- broad recurring why-questions benefit most from consolidated `pattern_memory`
- repeated-answer consistency also benefits from bounded higher-level memory
- same-thread and precise factual questions should not default to higher-level memory
- exact factual and evidence-heavy questions should still prefer lower-level `decision` or `investigation_outcome`
- the benchmark now records per-strategy trace data including merge rationale

Still out of scope for this phase:
- global autonomous clustering over the full memory store
- vector-assisted consolidation selection
- public API expansion for consolidation control
- replacing lower-level memory with only higher-level summaries
- broad ambient-workspace knowledge coverage beyond agent-mediated conversation memory
