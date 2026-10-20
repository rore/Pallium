# Session History replay

Session History search and expansion tools are not exposed by the current Hermes Pallium package. Do not claim to search History or call tools from another integration.

When using an integration that does expose these tools, keep a delivered-page ledger across query repair: record exact offsets, revisions, each page's `lookup_event_id`, source length and completion state. Advance only after successful caller delivery. Retry a failed page with identical arguments at most twice; do not skip unread pages or re-expand delivered pages. Keep the ledger through at most two query repairs, expand with the page-specific `parent_lookup_id`, and revalidate completed sources by revision. A historical recap is evidence about the past, not live state.
