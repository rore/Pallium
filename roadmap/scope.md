Pallium now has a stable lower-level memory baseline: typed `decision` and `investigation_outcome` memory, compact event-oriented ingest/query contracts, and a committed semantic regression set with a clean current OpenAI baseline.

Current focus:
- turn the current event contract into a concrete agent-conversation-memory package with a clear downstream value proposition
- build a realistic test bed from agent-mediated conversation events and assistant artifacts so value can be judged from believable scenarios, not only synthetic low-level samples
- measure whether recurring questions, cross-thread continuity, and assistant consistency become better with compact memory than with lower-level retrieval alone
- keep semantic quality measurable against the committed regression batch while higher-level memory and value tests are added

Concrete next steps:
- add the first agent-conversation-memory semantic package over user messages and assistant outputs
- add a realistic test bed that simulates how an interactive downstream agent actually uses Pallium across threads and sessions
- add a recurring-question benchmark that compares high-signal Pallium answers against the current lower-level retrieval shape
- add the first bounded consolidation flow that produces a higher-level evidence-backed memory object such as `pattern_memory`, but only after the lower-level agent-memory package and test bed show clear value
- keep consolidated memory queryable without weakening direct memory and evidence retrieval

Still out of scope for this phase:
- turning Pallium into an agent runtime or workflow engine
- connector-framework-first scope
- broad ingestion of ambient team chat that never flowed through the downstream agent
- claiming whole-team knowledge coverage from an agent-mediated conversation subset
- full raw-content expansion endpoints as part of the default query path
- making embeddings the only retrieval foundation
- deep autonomous multi-level clustering
