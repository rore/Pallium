Pallium now has a dedicated validation layer for tiered memory, and the current `agent_conversation_memory` package has a recorded safety/value baseline for higher-level `pattern_memory`.

Current focus:
- preserve the current product claim: Pallium improves cross-thread and cross-session recurring-question handling, not broad workspace search
- keep `thread_summary_anchored` as the current package default because the validation benchmark shows it is conservative, interpretable, and broadly useful
- use the tiered-memory validation benchmark to judge when higher-level memory should help and when lower-level memory should still win
- keep tiered memory bounded, evidence-backed, and additive rather than operationalizing it as always-on behavior too early
- move the next retrieval work into explainability and text-view modeling before broader retrieval or routing slices

Concrete next steps:
- add retrieval trace and text-view modeling so Pallium can explain why a hit appeared and prepare later retrieval-policy work cleanly
- then add `continuity_memory` as a second bounded higher-level memory kind and validate it separately from the current broad `pattern_memory` path
- after multiple higher-level kinds exist, add internal intent-aware retrieval policy so the package can route broad recall, continuity, precise-fact, and evidence-trace questions without expanding the public API too early
- then add a vector retrieval provider behind the existing retrieval boundary
- then add RRF-based hybrid retrieval fusion over lexical and vector candidates
- add a generic privacy-aware scope enforcement foundation before any later cross-container sharing work
- then add an explicit shared-memory derivation path so broader reuse happens through separate shared derived memory rather than in-place widening of local memory
- then treat cross-container memory as a later bounded shared-memory feature that builds on those privacy/scope foundations and still requires stronger guards and stronger false-merge evaluation than current within-container memory

What the tiered-memory validation benchmark established:
- broad recurring why-questions benefit most from consolidated `pattern_memory`
- repeated-answer consistency also benefits from bounded higher-level memory, and this should be proved as its own memory kind before adding routed retrieval policy
- same-thread and precise factual questions should not default to higher-level memory
- exact factual and evidence-heavy questions should still prefer lower-level `decision` or `investigation_outcome`
- the benchmark now records per-strategy trace data including merge rationale

Still out of scope for this phase:
- global autonomous clustering over the full memory store
- vector-assisted consolidation selection
- public API expansion for consolidation control or query intent
- replacing lower-level memory with only higher-level summaries
- broad ambient-workspace knowledge coverage beyond agent-mediated conversation memory
