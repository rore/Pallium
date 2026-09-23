<!-- pallium:start -->
## Pallium

Pallium provides:

- **Relay:** coordinate independent agent sessions.
- **Session History:** resume earlier work.
- **Derived memory:** optional compact context.

Load the `pallium-memory` skill when any applies. When no capability applies, answer normally without loading the skill.

### Always-safe rules

- Copy injected `container_ref`, `thread_ref`, `actor_ref`, `agent_ref`, `request_source_item_id`, and `work_ref` exactly when required. Never derive identity or scope from cwd, recipients, or history. If required scope is missing, skip that scoped call; never call it with guessed or absent values.
- For hook-injected Relay payloads: The hook owns claim and ACK, so never call receive for it. Act or report a blocker; ignore ACK-only deliveries. Never ACK through raw HTTP; use Relay tools. A trace state of `delivered` does not make its payload stale. Only an explicit `already_delivered` or conflict from a claim/ACK/reply operation marks that copy stale; do not reuse it.
- Relay sends only to canonical `relay-session-...` or global `@name`; no broadcast/bare runtime. Ask before takeover. Cross-container routing never changes History or memory scope. Queued or wake evidence is not receipt. For an exact empty-wake instruction, pass its supplied `relay-delivery-*` identifier as Relay trace's `message_id`; do not receive or resend.
- Picking up prior work? Search the injected exact `work_ref` when present; otherwise search broadly. Never guess a History search filter. Work associations use only exact provider-returned references.
- For History searches, pass injected `request_source_item_id` only there, expand a returned `source_item_id` with its `lookup_event_id` as `parent_lookup_id`, and omit `actor_ref` unless an exact metadata filter is requested.
- History retry: keep a delivered-page ledger across query repair; retry the same failed page at most twice, continue unread pages, and keep page-specific lookup lineage. Revalidate completed sources by content revision; use bounded retries. A historical recap is not live state; verify current state live. See [procedure](skills/pallium-memory/references/history-replay.md).
- Retrieval alone never changes accessibility or ranking. Derived memory is optional and private by default; global writes require intent. New memory writes copy exact injected provenance; correction and forget retain existing provenance. Work associations are optional, grant no access or ownership, and are skipped without exact identity/tools. Do not ingest routine turns or re-query content already injected.

Use skill/tool descriptions for procedures.
<!-- pallium:end -->