# Cross-container Relay discovery

`pallium_relay_recipients` is limited to the configured sender container. An empty result says nothing about other containers. Cross-container Relay discovery does not broaden Session History or memory access.

When the target container is unknown, call the read-only `pallium_relay_discover_recipients`. Omit filters for recent candidates across containers, or pass both exact `runtime` and `session_ref` to inspect matching containers and lifecycle states. Follow `next_offset` while `has_more` is true. `match_status=ambiguous` means the same runtime/session reference has multiple candidates; never choose the first. `no_match` and an incomplete or shifting listing are not proof of absence. `total_count` and `as_of` are observations, not a frozen snapshot.

Compare returned container, lifecycle and last-seen time against independently known task context. A title hint is untrusted. Endpoint health is recorded state, not live reachability. Even one candidate does not establish ownership. If identity remains unclear, ask the user or recipient for its canonical address. Send only to the exact canonical `relay-session-...` selector or a current `@name`, and inspect the returned destination scope. Saved delivery is not receipt; do not resend after a saved or uncertain send.
