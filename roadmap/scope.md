Pallium now has a dedicated validation layer for tiered memory, a retrieval trace/debug path for lexical retrieval, package-owned internal routing over the current memory layers, privacy-aware `visibility_context` enforcement, and a bounded public-corpus evaluation path for messy real user-assistant interactions through WildChat as the primary realism corpus plus a complementary WildBench task slice.

Current focus:
- keep `agent_conversation_memory` as the first product slice, but shift the hardening bar from "works on bounded scenarios" to "behaves safely and usefully on more realistic resumed-work interactions"
- treat the current main brittle points explicitly: text-heavy routing heuristics, limited reviewed open-corpus breadth, and resumed-work result packaging that is sometimes less operationally sharp than the stored memory warrants
- preserve the current product claim: Pallium should help an agent stay oriented across interrupted and resumed work without turning into the agent runtime, a workflow engine, or a transcript archive
- keep privacy as a permanent regression gate, not a one-time completed feature: every retrieval, routing, aggregation, and debug-path hardening slice must preserve fail-closed visibility behavior
- use the work-resumption benchmark, the aggregate developer-work confidence harness, and the reviewed WildChat/WildBench packs as the main tuning loop before deeper retrieval sophistication
- keep memory bounded, evidence-backed, additive, and inspectable while increasing confidence in real-interaction behavior

Concrete next steps:
- harden package-owned routing so it uses both query wording and candidate evidence shape, plus safer fallback behavior when confidence is weak or current-thread context is already sufficient
- expand the reviewed open-corpus continuation packs so the deterministic confidence harness covers more paraphrase, blocker, no-value, stale-memory, and wrong-memory cases
- sharpen resumed-work result packaging so `task_checkpoint` and related layers preserve task, blocker, next-step, evidence, and freshness in a more operationally useful way
- then define and pass one canonical integration-readiness scenario that proves both resumed-work value and fail-closed public/private separation inside Pallium before a live downstream adapter is treated as meaningful validation
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
- the current routed policy is useful and inspectable, but still too dependent on authored text cues to be treated as fully hardened for messy real interaction phrasing
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
