Pallium now has a dedicated validation layer for tiered memory, a retrieval trace/debug path for lexical retrieval, package-owned internal routing over the current memory layers, and a bounded public-corpus evaluation path for messy real user-assistant interactions through WildChat as the primary realism corpus plus a complementary WildBench task slice.

Current focus:
- preserve the current product claim, but sharpen it: Pallium should help an agent stay oriented across interrupted and resumed work, not only answer recurring questions
- keep `agent_conversation_memory` as the first package, but treat the next value slice as work continuity within agent-mediated, tool-mediated workflows rather than broad workspace search
- keep `thread_summary_anchored` as the current package default because the validation benchmark shows it is conservative, interpretable, and broadly useful
- use the public-corpus layer, routed retrieval benchmark, and tiered-memory validation benchmark as guardrails, but stop treating conversation realism alone as sufficient proof of workflow continuity
- keep memory bounded, evidence-backed, and additive: Pallium should preserve learned state from work, not replace transcript persistence, live tool retrieval, or the agent runtime itself
- extend the current slice through selected work-state signals and compact task checkpoints before expanding retrieval sophistication again

Concrete next steps:
- add an explicit work-resumption benchmark so Pallium is tested on interruption, resumed investigation, partial progress, blocker recovery, and no-value continuation cases
- add selected agent work-artifact semantic support beyond final assistant outputs so partial findings, blockers, and next-step state can contribute to memory without ingesting raw runtime logs
- add one compact `task_checkpoint`-style memory kind for resuming work with current state, key findings, blockers, next step, evidence, and freshness
- add a vector retrieval provider behind the existing retrieval boundary only if the work-resumption and public-corpus evals show paraphrase or concept recall is the next real bottleneck after the task-continuity slices land
- then add RRF-based hybrid retrieval fusion over lexical and vector candidates if dual-mode retrieval is justified by that evaluation evidence
- add a generic privacy-aware scope enforcement foundation before any later cross-container sharing work
- then add an explicit shared-memory derivation path so broader reuse happens through separate shared derived memory rather than in-place widening of local memory
- then treat cross-container memory as a later bounded shared-memory feature that builds on those privacy/scope foundations and still requires stronger guards and stronger false-merge evaluation than current within-container memory

What the current evaluation layer established:
- broad recurring why-questions benefit most from consolidated `pattern_memory`
- repeated-answer consistency benefits from bounded `continuity_memory` carry-forward
- same-thread and precise factual questions should not default to higher-level memory
- exact factual and evidence-heavy questions should still prefer lower-level `decision` or `investigation_outcome`
- the current routed policy can now distinguish broad recall, continuity, precise fact, and evidence-trace questions on the committed synthetic benchmark set
- the remaining unresolved risk is realism and workflow continuity, not only basic policy shape: even with the new WildBench complement, the committed reviewed slices are still bounded and conversation-oriented compared with resumed developer work

Still out of scope for this phase:
- private downstream-system coupling as a prerequisite for Pallium development
- global autonomous clustering over the full memory store
- vector-assisted consolidation selection
- public API expansion for consolidation control or query intent
- replacing lower-level memory with only higher-level summaries
- broad ambient-workspace knowledge coverage beyond agent-mediated memory
- turning Pallium into a workflow engine, transcript store, or raw tool-log archive
