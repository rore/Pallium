# Cross-project Relay discovery

`pallium_relay_recipients` and ordinary MCP recipient lookup are limited to the sender's injected `container_ref`. An empty result does not establish that a recipient in another project is absent.

On the same trusted local Pallium service, use the read-only `GET /dashboard/api/relay/sessions` endpoint or Dashboard Relay Sessions view with no `container_ref` filter. The endpoint has no `session_ref` filter. Page with `limit` (maximum 200) and `offset` until the listing is complete.

Start with the target's exact runtime, session_ref, and container_ref from independent trusted context. Do not derive scope from cwd, task title, or a dashboard row. Require exactly one matching nonclosed session. Treat an incomplete or unstable listing, unknown target container, no match, or multiple plausible endpoints as uncertainty—not proof of absence.

Inspect that row's destination health. For an exact task, use its `id` as the canonical `relay-session-...` selector. For a role, verify its current `@name` before using it. Keep the sender's injected `container_ref` on the send and inspect returned admission destination session/container. If any check cannot complete, ask the target for `pallium_relay_address` or use an app task-message fallback. A saved or uncertain send is not permission to resend.
