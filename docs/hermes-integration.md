# Hermes integration

Pallium connects Hermes **Desktop and TUI** to Relay, Session History and optional
memory tools. The package includes a native Hermes plugin, the discoverable
`pallium-memory` skill and a profile-scoped MCP bridge.

## Capabilities

| Capability | Behavior |
|---|---|
| Relay | Discover and address sessions, send messages, receive wake turns, reply, and inspect delivery status and trace |
| Session History | Capture supported completed turns, search earlier work by topic or exact work reference, and expand matching sources |
| Skill and MCP | Hermes discovers the bundled skill and plugin-owned tools; the integration supplies trusted session identity and private scope |
| Optional memory | Enable eleven memory query/write tools during setup; disabled by default, with no automatic memory injection |
| Package management | Install, inspect, update and remove Pallium's owned files and configuration while preserving unrelated profile data |

Relay and History work with memory disabled. History and memory access follow
Pallium's [privacy and visibility rules](privacy-and-visibility.md).

## Setup, update and removal

Follow the [Hermes package guide](../integrations/hermes/README.md#prepare-an-isolated-profile)
for prerequisites and complete install, status and removal commands.

`pallium setup hermes` requires an **existing explicit Hermes profile**, its Python
interpreter and a fixed private Pallium scope. Hermes uses MCP SDK2; the separate
Pallium bridge interpreter uses MCP SDK1. Setup checks both environments and
preserves the profile's provider, toolsets, Tool Search and other plugins. It does
not add a global `mcp_servers` connection.

Stop the target Hermes host and other profile writers before setup, update or
removal. Repeating setup updates an unchanged owned installation; conflicts with
edited or unowned files are refused. Status reports configuration and ownership,
not whether a running host is connected. Removal preserves unrelated settings
and data.

Use `--memory-enabled` to enable memory tools. Repeat that flag on updates that
should preserve the opt-in: setup without it disables the memory catalog.
`--no-memory-enabled` explicitly disables it. Enabling semantic packages in the
service does not enable this Hermes tool catalog.

## Delivery and history behavior

Incoming Relay payloads support up to 16,000 Unicode code points; host-bound
replies support 2,400. Acknowledgement means the complete delivery context reached
the host request, before provider completion. It does **not** prove that the agent
acted or replied. The hook owns claim and ACK; do not receive or acknowledge an
injected delivery again. Use status and trace when an outcome is uncertain.

Busy-turn delivery, endpoint outages and controlled host/MCP relaunch are covered
by the integration checks. Automatic standalone MCP reconnection, ordinary-turn
fallback and recovery after uncertain claim/ACK outcomes are not guaranteed. Uncertain delivery state
stays fenced rather than being silently replayed. Wake serialization is local to
one plugin process, not shared across independent processes using one profile.

History captures private, hook-observed plain-text user/final-assistant snapshots,
not a complete mirror of the Hermes database. Unsupported, oversized or ambiguous
rows and turns without a completion callback can be absent. Capture has no durable
retry queue. Exact-work search can miss captures whose work association was not
available; broaden the search within the same trusted scope when needed.
See [Session History](session-history.md) for search and expansion.

## Compatibility and limits

- Integration checks cover Hermes v0.22.0 and v0.22.2 on Linux TUI and Windows
  Desktop/TUI. Runtime admission checks public plugin capabilities instead of
  enforcing an exact-version allowlist; other releases need compatible APIs.
- Windows checks used Windows Server 2025 and an unpacked app. They do not cover
  Windows 11, MSIX installation, the native updater or native app Quit. Keep
  Hermes installation and updates on its supported upstream path.
- Provider configuration is preserved. Synthetic-provider checks establish
  integration behavior, not model quality or every provider/memory combination.
- Relay can report retryable busy errors. Shared service availability remains a
  limitation; inspect delivery state before retrying an operation with an
  uncertain outcome.
- Request middleware before Pallium sees a bounded placeholder. Middleware that
  needs the delivery text must run after Pallium's expansion; removing or rewriting
  the placeholder prevents admission. Host spill settings are unchanged.

For setup errors, check the selected interpreters, service URL and profile scope.
A missing public capability or trusted identity fails closed; do not patch host
registries or upgrade shared environments to bypass it. The
[package reference](../integrations/hermes/README.md) has ownership and capture
details; [contributor validation](designs/hermes-native-qualification.md) describes
the test surfaces and coverage boundaries.
