# Hermes integration

Pallium's Hermes package is **experimental**. It bundles a native plugin, the
`pallium-memory` skill and a profile-scoped MCP bridge. It is not ready for an
everyday installation.

Production support must cover both Windows **Desktop and TUI** across compatible
Hermes releases. Runtime checks use public plugin capabilities rather than an
exact Hermes version check. The current proof uses gateway RPC on clean
**v0.22.0 and v0.22.2** sources with disposable profiles and a local provider.
It does not establish actual Desktop or TUI interaction, ordinary-provider
support, or compatibility with every later release.

## Available in the experimental package

| Capability | Current boundary |
|---|---|
| Relay | 12 MCP tools for discovery, identity, work associations, messaging, status and trace; gateway round trips passed on both tested releases |
| Session History | Capture plus `pallium_search_history`, `pallium_search_history_by_work_ref` and `pallium_expand_source`; later-session search and expansion passed through gateway RPC |
| Skill and MCP | Bundled skill and plugin-owned stdio bridge; trusted conversation identity and private scope are supplied by the integration |
| Package lifecycle | Explicit-profile setup, status, repeat setup/update and removal with ownership checks; running-host readiness is a separate check |
| Derived memory | Memory query/write tools and automatic memory injection are not exposed or qualified |

Incoming Relay deliveries are handled by hooks, which own claim and ACK. The
package does not expose receive/ACK tools. A saved send or wake attempt is not
proof of receipt. Automatic recovery, busy/reset/close/restart behavior and
ordinary-turn fallback are still unqualified; do not apply another integration's
wake guarantees to Hermes.

History capture stores private, hook-observed plain-text user/final-assistant
snapshots with stable host session, turn and message IDs. It accepts up to
20,000 Unicode code points per row and skips unsupported, oversized or ambiguous
rows and synthetic wake user markers. It is not proof of Hermes database commit
or message delivery, and capture has no durable retry queue. Current completion
capture supplies no `request_source_item_id`; never invent one. Work references
are copied only from verified current-session associations, so exact-work search
may miss a capture when that lookup fails.

History search and expansion reuse Pallium's visibility, redaction, forgetting,
paging and lookup-lineage rules. History diagnostics, source-forget and memory
tools described elsewhere are not in this Hermes catalog. The package supplies
a fixed private container/actor configuration and host-issued current session;
historical `actor_ref` and `source_thread_ref` filters do not change that identity.
See [Session History](session-history.md) and
[Privacy and Visibility](privacy-and-visibility.md).

## Setup, update and removal

Use the complete commands and prerequisites in the
[Hermes package guide](../integrations/hermes/README.md#prepare-an-isolated-profile).
The setup target is `pallium setup hermes`; it requires an existing explicit
profile, the Hermes interpreter and fixed Pallium scope. It is not interchangeable
with the quickstart's default-profile setup commands.

Current setup requires the frozen custom loopback provider, no fallback, only
Pallium enabled, the `hermes-cli` toolset and Tool Search set to the string
`"off"`. It validates Hermes MCP SDK2 and a separate Pallium MCP SDK1 interpreter.
It does not repair these settings or create a global `mcp_servers` entry.

With the target host and other profile writers stopped, use the same
[install/status/removal procedure](../integrations/hermes/README.md#install-inspect-and-remove).
Repeat setup updates an unchanged owned installation. Edited or unowned files
and conflicting configuration are refused. Status checks configured fingerprints,
not live MCP or host readiness. Removal preserves unrelated configuration/data.
On an uncertain config write, inspect the preserved config and reported conflict
before retrying; the native writer has no atomic compare-and-swap for overlapping
writers. No everyday profile or host updater should be replaced for qualification.

## Compatibility and troubleshooting

- Use explicit interpreter and checkout paths. An MCP startup refusal requires
  checking the selected environments and service configuration, not upgrading
  Hermes's dependencies in place.
- A missing public plugin capability or trusted session/turn identity fails
  closed. Do not substitute a guessed identity or patch a private host registry.
- Empty exact-work History results can reflect omitted association tags. Try
  broad History search within the same trusted scope; retrieval is not proof of
  current live state.
- Desktop qualification needs Windows 11 22H2 or later and separate backend,
  Electron and process-home data paths. Existing isolated UI automation has not
  completed a Desktop/TUI journey; gateway success does not resolve that gate.

The [qualification matrix](../integrations/hermes/README.md#production-qualification-in-progress)
tracks the remaining normal-provider, default Tool Search, plugin coexistence,
memory, recovery and lifecycle gates. Public docs, commands and support claims
must be reviewed against the final verified behavior before a production release.
Current work remains on the [Hermes roadmap item](../roadmap/features/add-hermes-agent-integration.md).
