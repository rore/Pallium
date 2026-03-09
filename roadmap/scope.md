This minimap workspace tracks Pallium after the agent-event contract milestone.

Current focus:
- keep the agent-facing ingest and compact query contracts stable as the system grows
- improve semantic quality over the new message-event and assistant-artifact inputs
- preserve the generic-core and replaceable-provider boundaries while adding more memory types

Concrete next steps:
- decide whether the next increment is tiered memory or lifecycle hardening
- add richer typed memory beyond `decision`, likely around investigation or findings
- keep retrieval structured-first as the model grows

Still out of scope for this phase:
- turning Pallium into an agent runtime or workflow engine
- connector-framework-first scope
- making embeddings the only retrieval foundation
