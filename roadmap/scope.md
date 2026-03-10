Pallium now has a stable lower-level memory baseline: typed `decision` and `investigation_outcome` memory, compact event-oriented ingest/query contracts, and a committed semantic regression set with a clean current OpenAI baseline.

Current focus:
- begin the first bounded tiered-memory extension on top of the stable typed-memory layer
- keep semantic quality measurable against the committed regression batch while higher-level memory is added
- preserve the generic event contract and compact query shape while consolidation capabilities grow

Concrete next steps:
- add the first bounded consolidation flow that produces a higher-level evidence-backed memory object
- keep consolidated memory queryable without weakening direct memory and evidence retrieval
- use the existing regression and context lessons to avoid semantic drift while tiered memory is introduced

Still out of scope for this phase:
- turning Pallium into an agent runtime or workflow engine
- connector-framework-first scope
- full raw-content expansion endpoints as part of the default query path
- making embeddings the only retrieval foundation
- deep autonomous multi-level clustering
