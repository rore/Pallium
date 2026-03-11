Pallium now has its first higher-level memory layer for the `agent_conversation_memory` package: bounded, evidence-backed `pattern_memory` built over `thread_summary`, `decision`, and `investigation_outcome`.

Current focus:
- prove that tiered memory improves answers in the right cases and stays out of the way in the wrong ones
- keep the first-package value claim explicit: Pallium improves cross-thread and cross-session recurring-question handling, not broad workspace search
- treat tiered memory as a reusable capability between the generic core and semantic packages, with package-owned strategy policy
- use the recorded strategy comparison to keep consolidation conservative and interpretable
- preserve the current default package strategy: `thread_summary_anchored`
- keep semantic quality measurable against the committed regression batch while higher-level memory grows
- validate tiered-memory usefulness and safety before changing the default consolidation posture
- then move the next retrieval work into explainability and text-view modeling before vector and fusion slices

Concrete next steps:
- add a tiered-memory validation benchmark that compares strategies, lower-level memory, and non-value cases
- then add retrieval trace and text-view modeling so Pallium can explain why a hit appeared and prepare cleanly for hybrid retrieval
- then add a vector retrieval provider behind the existing retrieval boundary
- then add RRF-based hybrid retrieval fusion over lexical and vector candidates
- keep reranking as a later optional extension after hybrid retrieval is measurable

What tiered memory now provides:
- a reusable consolidation capability with explicit strategy hooks
- three bounded selection/grouping strategies for comparison:
  - `thread_local_carry_forward`
  - `container_topic_window`
  - `thread_summary_anchored`
- evidence-backed `pattern_memory` as a normal retrievable memory type
- lifecycle-managed higher-level memory built over meaningful conversation units rather than raw atomic events

Still out of scope for this phase:
- global autonomous clustering over the full memory store
- vector-assisted consolidation selection
- public API expansion for consolidation control
- replacing lower-level memory with only higher-level summaries
- broad ambient-workspace knowledge coverage beyond agent-mediated conversation memory
