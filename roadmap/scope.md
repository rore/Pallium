Pallium now has a stable lower-level memory baseline: typed `decision` and `investigation_outcome` memory, compact event-oriented ingest/query contracts, and a committed semantic regression set with a clean current OpenAI baseline.

Current focus:
- prove clear user-facing value beyond raw retrieval-and-synthesis by adding the first higher-level memory layer
- measure whether recurring questions become easier for a downstream agent to answer from compact memory than from many low-level items
- keep semantic quality measurable against the committed regression batch while higher-level memory is added

Concrete next steps:
- add the first bounded consolidation flow that produces a higher-level evidence-backed memory object such as `pattern_memory`
- add a recurring-question benchmark that compares high-signal Pallium answers against the current lower-level retrieval shape
- keep consolidated memory queryable without weakening direct memory and evidence retrieval

Still out of scope for this phase:
- turning Pallium into an agent runtime or workflow engine
- connector-framework-first scope
- full raw-content expansion endpoints as part of the default query path
- making embeddings the only retrieval foundation
- deep autonomous multi-level clustering
