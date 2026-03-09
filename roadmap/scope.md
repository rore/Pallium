This minimap workspace tracks Pallium after the agent-event contract milestone.

Current focus:
- improve semantic quality over the new message-event and assistant-artifact inputs
- add richer typed memory so important non-decision knowledge does not collapse into `discussion_summary`
- keep the generic event contract and compact query shape stable while the semantic layer grows

Concrete next steps:
- add a second typed memory class, likely `investigation_outcome`
- establish a committed semantic regression set over message and assistant-artifact inputs
- add minimal memory lifecycle handling so stale or superseded knowledge can be managed safely

Still out of scope for this phase:
- turning Pallium into an agent runtime or workflow engine
- connector-framework-first scope
- full raw-content expansion endpoints as part of the default query path
- making embeddings the only retrieval foundation
