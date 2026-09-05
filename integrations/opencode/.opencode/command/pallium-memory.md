---
description: Use Pallium Relay, Session History, or optional derived memory
---

Use the relevant Pallium capability for: $ARGUMENTS

- **Relay:** discover recipients with `pallium_relay_recipients`, then send useful context with `pallium_relay_send` when another session's work should change.
- **Session History:** call `pallium_search_history` for earlier work, then `pallium_expand_source` with the hit's `source_item_id` and the search result's `lookup_event_id` as `parent_lookup_id`.
- **Derived memory:** use `pallium_query` for compact stored context, or the explicit remember/correct/supersede/forget tools when the user asks.

Use the injected `container_ref` and current scope values exactly. Default to `visibility: "private"`; global visibility requires explicit user intent.
