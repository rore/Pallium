# Hermes integration

Pallium connects Hermes **Desktop and TUI** to Relay, Session History and optional
memory tools. The package includes a native Hermes plugin, the discoverable
`pallium-memory` skill and a plugin-owned MCP bridge with session-bound scope.

## Capabilities

| Capability | Behavior |
|---|---|
| Relay | Discover and address sessions, send messages, receive wake turns, reply, and inspect delivery status and trace |
| Session History | Capture supported user turns before inference and final assistant responses at completion, search earlier work, and expand matching sources |
| Skill and MCP | Hermes discovers the bundled skill and plugin-owned tools; the integration supplies trusted session identity and private scope |
| Optional memory | Enable eleven memory query/write tools during setup; service-selected recall runs independently of that tool opt-in |
| Package management | Install, inspect, update and remove Pallium's owned files and configuration while preserving unrelated profile data |

Relay and History work with memory disabled. History and memory access follow
Pallium's [privacy and visibility rules](privacy-and-visibility.md).

## Prerequisites

`pallium setup hermes` requires an **existing explicit Hermes profile**, its Python
interpreter and public session-cwd and session-surface APIs. Hermes uses MCP SDK2; the separate
Pallium bridge interpreter uses MCP SDK1. Setup checks both environments and
preserves the profile's provider, toolsets, Tool Search and other plugins. It does
not add a global `mcp_servers` connection.

## Setup

Stop the target Hermes host and other profile writers. Follow the
[package setup commands](../integrations/hermes/README.md#setup), supplying the
profile, interpreters and local service URL explicitly. Keep the
Pallium checkout at a stable path because the bridge uses absolute paths.

Normal setup derives each session's private project and actor from that session's
local working directory. Independent sessions in one profile can use different
projects. A recognized Git project change moves the session only after exact
Relay admission; temporary non-Git directory changes retain the previous project.
Missing, stale, remote or ambiguous cwd fails closed. The plugin never substitutes
its background process's directory. An intentional fixed-scope compatibility
override is available in the package guide; it is never an automatic fallback.

Use `--memory-enabled` to enable memory tools. New installations default to tools
disabled; ordinary updates preserve the existing selection. `--no-memory-enabled`
explicitly disables them. Service semantic packages and the tool catalog are
separate settings.

## Verify the connection

1. Run the package guide's [status command](../integrations/hermes/README.md#verify-the-connection)
   to inspect ownership and configuration. Status alone does not establish live readiness.
2. Start the selected Hermes profile in Desktop or TUI. Ask Pallium for this
   session's Relay address and list recipients; check the intended session and project.
3. Exchange a short message and reply with another connected session. Confirm
   the attributed payload appears in the intended host, not just that send saved it.
4. Record a distinctive finding, then search and expand it from a later session
   using the same trusted History scope.

## Delivery and recovery

<a id="delivery-and-history-behavior"></a>

Incoming Relay payloads support up to 16,000 Unicode code points; host-bound
replies support 2,400. Acknowledgement means the complete delivery context reached
the host request, before provider completion. It does **not** prove that the agent
acted or replied. The hook owns claim and ACK; do not receive or acknowledge an
injected delivery again. Use status and trace when an outcome is uncertain.

Automatic standalone MCP reconnection, ordinary-turn fallback and recovery after
uncertain claim/ACK outcomes are not guaranteed. Uncertain delivery state stays
fenced rather than being silently replayed. Wake serialization is local to
one plugin process, not shared across independent processes using one profile.

Turn completion releases only that turn's admitted wake. Native session finalize
and delete callbacks close the saved exact endpoint and generation; an uncertain
close remains fenced. These lifecycle paths still require current native
Desktop/TUI qualification.

Changing project or actor retires earlier turn authority, including after a
plugin reload. Invalid saved authority is refused without clearing pending
delivery or operation fences.

## History and memory

History captures private, hook-observed plain-text snapshots, not a complete
mirror of the Hermes database. In normal cwd mode, supported user text is captured before inference,
so an interrupted turn can retain its confirmed user capture. Assistant text is
captured at completion. Unsupported, oversized or ambiguous rows can be absent;
assistant capture requires the completion callback. Capture has no durable retry
queue. Eligible branch and Work Record references are discovered from the session
project and admitted through Relay. Exact-work search can still miss captures
whose association was unavailable; broaden within the same trusted scope.
See [Session History](session-history.md) for search and expansion.

Confirmed user capture supplies current request provenance automatically to
History search. Callers must not invent or supply that identity. Captures identify
an observed host turn; they do not prove a durable Hermes message ID or database
commit.

The service can return selected recall during user capture. Pallium adds it as
bounded, lower-authority reference context independently of the memory-tool flag.
Semantic packages are disabled by default and provider-backed processing requires
an explicitly configured provider and model. Enabling memory tools alone does
not enable semantic processing. See [derived memory](derived-memory.md).

## Update and removal

<a id="setup-update-and-removal"></a>

Stop the target Hermes host and other profile writers before repeating setup or
using the [removal command](../integrations/hermes/README.md#update-and-removal).
Repeating setup updates an unchanged owned installation; conflicts with edited or
unowned files are refused. Ordinary updates preserve the memory-tool opt-in.
Removal preserves unrelated settings and data. Inspect conflicts before retrying;
they do not authorize overwriting an unowned file.

## Compatibility and troubleshooting

<a id="compatibility-and-limits"></a>

- Automatic project scope also requires a Pallium service that confirms guarded
  session enrollment and supports conditional session closure. If that capability
  is missing, admission is refused before History capture; there is no fallback to
  fixed scope or unconditional closure. Update the service through its normal
  installation procedure before using automatic mode.
- Automatic project scope requires session-owned cwd, surface and bound-route
  capabilities. Pallium keeps the native injection route separate from the
  conversation ID used by Relay and History. Missing capabilities or an unbound
  route fail closed. Accepted v0.22.4 CWD qualification covers Linux TUI with
  memory off and on. Windows Desktop/TUI CWD and the complete automatic-mode
  matrix remain pending. Admission uses capability checks rather than a release
  allowlist.
- Existing v0.22.0/v0.22.2 Linux TUI and Windows Desktop/TUI receipts qualify fixed
  scope only. Those releases lack the required automatic-scope APIs; their results
  do not establish automatic-mode project isolation or lifecycle behavior.
- Fixed-context wake routing on the newer shared Gateway remains unqualified and
  unresolved; older fixed-scope results do not establish that compatibility.
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

For setup errors, check the selected interpreters, service URL and session APIs.
A missing public capability or trusted identity fails closed; do not patch host
registries or upgrade shared environments to bypass it. The
[package guide](../integrations/hermes/README.md) describes ownership checks.

## Reference

- [Package commands, ownership and capture details](../integrations/hermes/README.md)
- [Shared delivery table and recovery tools](agent-relay.md#delivery-and-wake-behavior)
- [Contributor validation and coverage boundaries](designs/hermes-native-qualification.md)
