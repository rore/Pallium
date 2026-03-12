Pallium now has a dedicated validation layer for tiered memory, a retrieval trace/debug path for lexical retrieval, package-owned internal routing over the current memory layers, and a bounded public-corpus evaluation path for messy real user-assistant interactions through WildChat as the primary realism corpus plus a complementary WildBench task slice.

Current focus:
- preserve the current product claim: Pallium improves cross-thread and cross-session recurring-question handling, not broad workspace search
- harden that claim against real interaction shape without depending on internal downstream traffic or private integration first
- keep `thread_summary_anchored` as the current package default because the validation benchmark shows it is conservative, interpretable, and broadly useful
- use the tiered-memory validation benchmark and routed retrieval benchmark as guardrails, but stop treating synthetic phrase coverage as sufficient proof of real interaction readiness
- keep tiered memory bounded, evidence-backed, and additive rather than operationalizing it as always-on behavior too early
- use the retrieval trace/debug path and the current routed package policy to inspect behavior as the eval corpus becomes more realistic

Concrete next steps:
- run the public-corpus benchmark against a real local WildChat export and use the results to determine whether the next limiting factor is retrieval recall, routed layer choice, or result packaging
- add a vector retrieval provider behind the existing retrieval boundary if that public-corpus eval shows paraphrase/concept recall is the next real bottleneck
- then add RRF-based hybrid retrieval fusion over lexical and vector candidates if dual-mode retrieval is justified by that eval evidence
- add a generic privacy-aware scope enforcement foundation before any later cross-container sharing work
- then add an explicit shared-memory derivation path so broader reuse happens through separate shared derived memory rather than in-place widening of local memory
- then treat cross-container memory as a later bounded shared-memory feature that builds on those privacy/scope foundations and still requires stronger guards and stronger false-merge evaluation than current within-container memory

What the current evaluation layer established:
- broad recurring why-questions benefit most from consolidated `pattern_memory`
- repeated-answer consistency benefits from bounded `continuity_memory` carry-forward
- same-thread and precise factual questions should not default to higher-level memory
- exact factual and evidence-heavy questions should still prefer lower-level `decision` or `investigation_outcome`
- the current routed policy can now distinguish broad recall, continuity, precise fact, and evidence-trace questions on the committed synthetic benchmark set
- the remaining unresolved risk is realism, not basic policy shape: even with the new WildBench complement, the committed reviewed slices are still bounded and should guide rather than replace larger local review runs

Still out of scope for this phase:
- private downstream-system coupling as a prerequisite for Pallium development
- global autonomous clustering over the full memory store
- vector-assisted consolidation selection
- public API expansion for consolidation control or query intent
- replacing lower-level memory with only higher-level summaries
- broad ambient-workspace knowledge coverage beyond agent-mediated conversation memory

