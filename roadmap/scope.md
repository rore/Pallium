Pallium now has a dedicated validation layer for tiered memory, a retrieval trace/debug path for lexical retrieval, package-owned internal routing over the current memory layers, privacy-aware `visibility_context` enforcement, and a bounded public-corpus evaluation path for messy real user-assistant interactions through WildChat as the primary realism corpus plus a complementary WildBench task slice.

Current focus:
- keep `agent_conversation_memory` as the first product slice, but shift the hardening bar from "works on bounded scenarios" to "behaves safely and usefully on more realistic resumed-work interactions"
- the main brittle points are now narrower: routing still begins from query-text intent families, confidence still comes from reviewed open-data rather than downstream traffic, and retrieval is still lexical-first
- preserve the current product claim: Pallium should help an agent stay oriented across interrupted and resumed work without turning into the agent runtime, a workflow engine, or a transcript archive
- keep privacy as a permanent regression gate, not a one-time completed feature: every retrieval, routing, aggregation, and debug-path hardening slice must preserve fail-closed visibility behavior
- treat the canonical integration-readiness scenario as passed in-repo: Pallium now has a narrow self-contained proof of resumed-work value, no-value restraint, and fail-closed scope behavior before any thin downstream adapter exists
- use the work-resumption benchmark, the aggregate developer-work confidence harness, the reviewed WildChat/WildBench packs, and the canonical integration-readiness scenario as the standing tuning and regression loop before deeper retrieval sophistication
- keep memory bounded, evidence-backed, additive, and inspectable while increasing confidence in real-interaction behavior

Concrete next steps:
- use the canonical integration-readiness scenario plus the Bruno runner as a standing gate before any thin downstream adapter work is treated as meaningful validation
- validate the current build in a thin downstream integration outside the public repo while keeping privacy as a permanent regression gate inside Pallium
- use the expanded confidence harness to determine whether the next real bottleneck is still routing, result packaging, or lexical recall
- add a vector retrieval provider behind the existing retrieval boundary only if the expanded confidence harness shows paraphrase or concept recall remains the dominant bottleneck after routing and packaging hardening
- then add RRF-based hybrid retrieval fusion only if that evidence still supports a dual-mode retrieval path
- then add an explicit shared-memory derivation path so broader reuse happens through separate shared derived memory rather than in-place widening of local memory
- then treat cross-container memory as a later bounded shared-memory feature built on those privacy and sharing foundations

What the current evaluation layer established:
- broad recurring why-questions benefit most from consolidated `pattern_memory`
- repeated-answer consistency benefits from bounded `continuity_memory` carry-forward
- resumed-work continuity benefits from compact `task_checkpoint` memory and selected work artifacts
- same-thread and precise factual questions should not default to higher-level memory
- exact factual and evidence-heavy questions should still prefer lower-level `decision` or `investigation_outcome` or raw source evidence
- the current routed policy is now candidate-aware, explainable, and safer on weak support, but it still begins from explicit query-text intent families and is not yet a final answer for messy real interaction phrasing
- the current confidence harness is now strong enough to tune Pallium meaningfully, but still reflects reviewed authored and open-data cases rather than live downstream behavior
- privacy enforcement is now in place and fail-closed, but trust depends on keeping it permanently regressed as the retrieval and routing stack evolves

Still out of scope for this phase:
- private downstream-system coupling as a prerequisite for Pallium development
- global autonomous clustering over the full memory store
- vector-assisted consolidation selection
- public API expansion for consolidation control or query intent
- replacing lower-level memory with only higher-level summaries
- broad ambient-workspace knowledge coverage beyond agent-mediated memory
- turning Pallium into a workflow engine, transcript store, or raw tool-log archive
