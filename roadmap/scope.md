Pallium now has a dedicated validation layer for tiered memory, a retrieval trace/debug path for lexical retrieval, and the current `agent_conversation_memory` package has recorded value for two bounded higher-level memory kinds: `pattern_memory` and `continuity_memory`. It also now applies package-owned internal routing over those layers without expanding the public query contract.

Current focus:
- preserve the current product claim: Pallium improves cross-thread and cross-session recurring-question handling, not broad workspace search
- keep `thread_summary_anchored` as the current package default because the validation benchmark shows it is conservative, interpretable, and broadly useful
- use the tiered-memory validation benchmark to judge when higher-level memory should help and when lower-level memory should still win
- keep tiered memory bounded, evidence-backed, and additive rather than operationalizing it as always-on behavior too early
- use the retrieval trace/debug path and the current routed package policy to guide broader retrieval expansion without hiding behavior

Concrete next steps:
- add a vector retrieval provider behind the existing retrieval boundary
- then add RRF-based hybrid retrieval fusion over lexical and vector candidates
- add a generic privacy-aware scope enforcement foundation before any later cross-container sharing work
- then add an explicit shared-memory derivation path so broader reuse happens through separate shared derived memory rather than in-place widening of local memory
- then treat cross-container memory as a later bounded shared-memory feature that builds on those privacy/scope foundations and still requires stronger guards and stronger false-merge evaluation than current within-container memory

What the tiered-memory validation benchmark established:
- broad recurring why-questions benefit most from consolidated `pattern_memory`
- repeated-answer consistency benefits from bounded `continuity_memory` carry-forward
- same-thread and precise factual questions should not default to higher-level memory
- exact factual and evidence-heavy questions should still prefer lower-level `decision` or `investigation_outcome`
- the benchmark now records per-strategy trace data including merge rationale and routed retrieval intent/layer choices

Still out of scope for this phase:
- global autonomous clustering over the full memory store
- vector-assisted consolidation selection
- public API expansion for consolidation control or query intent
- replacing lower-level memory with only higher-level summaries
- broad ambient-workspace knowledge coverage beyond agent-mediated conversation memory
