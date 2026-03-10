Pallium now has a realistic agent-conversation test bed and a recurring-question value benchmark over a neutral public-safe sample domain.

Current focus:
- use the benchmark results to judge whether higher-level memory actually improves recurring-question answers before adding more capability
- keep semantic quality measurable against the committed regression batch while tiered memory is added
- preserve the current first-package boundary: memory over agent-mediated conversations, not ambient workplace chat
- keep the platform framing explicit: Pallium stays a generic memory engine even while the first package remains narrow
- treat hybrid retrieval as the target retrieval architecture, while slicing its delivery so it does not block the first tiered-memory value step

Concrete next steps:
- add the first bounded consolidation flow that produces a higher-level evidence-backed memory object such as `pattern_memory`
- after that, add hybrid-retrieval groundwork in slices:
  - retrieval trace and text-view modeling
  - vector retrieval provider support
  - RRF-based hybrid fusion
- rerun the recurring-question benchmark against both higher-level memory and later hybrid retrieval improvements

Still out of scope for this phase:
- turning Pallium into an agent runtime or workflow engine
- connector-framework-first scope
- broad ingestion of ambient team chat that never flowed through the downstream agent
- claiming whole-team knowledge coverage from an agent-mediated conversation subset
- full raw-content expansion endpoints as part of the default query path
- making embeddings the only retrieval foundation
- deep autonomous multi-level clustering
