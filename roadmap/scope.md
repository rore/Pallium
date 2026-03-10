Pallium now has a realistic agent-conversation test bed over a neutral public-safe sample domain, in addition to the stable lower-level typed-memory baseline and committed semantic regression set.

Current focus:
- use the new agent-conversation scenarios to measure whether recurring questions, cross-thread continuity, and assistant consistency improve with compact memory-backed context
- prove value before adding more memory capability by comparing current-thread context alone versus memory-backed context
- keep semantic quality measurable against the committed regression batch while the value benchmark and later tiered memory work are added

Concrete next steps:
- add a recurring-question benchmark that compares memory-backed context against the current lower-level retrieval shape
- add the first bounded consolidation flow that produces a higher-level evidence-backed memory object such as `pattern_memory`, but only after the benchmark makes the value target explicit
- keep consolidated memory queryable without weakening direct memory and evidence retrieval

Still out of scope for this phase:
- turning Pallium into an agent runtime or workflow engine
- connector-framework-first scope
- broad ingestion of ambient team chat that never flowed through the downstream agent
- claiming whole-team knowledge coverage from an agent-mediated conversation subset
- full raw-content expansion endpoints as part of the default query path
- making embeddings the only retrieval foundation
- deep autonomous multi-level clustering
