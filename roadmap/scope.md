This minimap workspace tracks Pallium after typed investigation memory, a committed semantic regression set, and minimal lifecycle handling.

Current focus:
- improve semantic precision using the committed regression set and baseline metrics
- keep the generic event contract and compact query shape stable while semantic quality improves
- defer higher-level memory work until typed-memory quality is strong enough to support consolidation safely

Concrete next steps:
- reduce the remaining false positives in typed-memory extraction
- decide when the current semantic baseline is strong enough for tiered memory work
- keep prompt and model changes measurable against the committed regression batch

Still out of scope for this phase:
- turning Pallium into an agent runtime or workflow engine
- connector-framework-first scope
- full raw-content expansion endpoints as part of the default query path
- making embeddings the only retrieval foundation
