Pallium now has a dedicated validation layer for tiered memory, a retrieval trace/debug path for lexical retrieval, package-owned internal routing over the current memory layers, privacy-aware `visibility_context` enforcement, and a bounded public-corpus evaluation path for messy real user-assistant interactions through WildChat as the primary realism corpus plus a complementary WildBench task slice.

Current focus:
- keep `agent_conversation_memory` as the first product slice, but shift the next hardening bar from "works on bounded scenarios" to "holds up under realistic ingest latency and background semantic processing"
- make `POST /items` cheap and predictable by persisting raw evidence synchronously, then moving semantic extraction, direct promotion, and thread rebuild work onto an explicit SQLite-backed async queue and worker path
- make that eventual-consistency path explainable during integration work: queue health, per-item provenance, failure categories, thread rebuild outcomes, and richer `/query/debug` should answer why Pallium did what it did without direct SQLite spelunking
- treat eventual consistency as an explicit product/runtime property rather than an accidental side effect: raw source evidence should stay queryable immediately, while derived memory appears once worker processing completes
- use this slice to strengthen the current product claim before deeper retrieval upgrades: if ingest remains slow or fragile under realistic write amplification, vector and fusion work would optimize the wrong bottleneck
- preserve the current product claim: Pallium should help an agent stay oriented across interrupted and resumed work without turning into the agent runtime, a workflow engine, or a transcript archive
- keep privacy as a permanent regression gate, not a one-time completed feature: every retrieval, routing, aggregation, and debug-path hardening slice must preserve fail-closed visibility behavior
- treat the canonical integration-readiness scenario as passed in-repo: Pallium now has a narrow self-contained proof of resumed-work value, no-value restraint, and fail-closed scope behavior before any thin downstream adapter exists
- use the work-resumption benchmark, the aggregate developer-work confidence harness, the reviewed WildChat/WildBench packs, and the canonical integration-readiness scenario as the standing tuning and regression loop before deeper retrieval sophistication
- keep memory bounded, evidence-backed, additive, and inspectable while increasing confidence in real-interaction behavior

Concrete next steps:
- add an explicit async ingest queue on `source_items`, plus standalone worker processing and an opt-in local supervisor mode, so the write path no longer blocks on semantic extraction or thread rebuild work
- keep the canonical integration-readiness scenario plus the Bruno runner as a standing gate, but run it only after queue drain or worker completion so the benchmark reflects the new eventual-consistency contract explicitly
- preserve privacy as a regression gate across both sync raw indexing and async derived-memory creation, especially for skipped items that lack required `visibility_context`
- use the new queue-health and query-debug surfaces as the default integration-debug path before deeper retrieval work
- use the expanded confidence harness to determine whether the next real bottleneck after async ingest is routing, result packaging, or lexical recall
- add a vector retrieval provider behind the existing retrieval boundary only if the expanded confidence harness still shows paraphrase or concept recall as the main bottleneck after the ingest/runtime hardening work lands
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


