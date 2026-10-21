# Hermes integration

Pallium's Hermes package remains **experimental** pending human release
acceptance. It bundles a native plugin, the `pallium-memory` skill and a
profile-scoped MCP bridge. Everyday installation remains a separate rollout
decision.

The scoped native matrix passed on both Windows **Desktop and TUI**, with memory
off and on, for pinned Hermes **v0.22.0** and **v0.22.2** sources. It ran in an
isolated Windows Server 2025 VM with an unpacked app and synthetic providers.
Runtime checks use public plugin capabilities rather than an exact Hermes
version lock; a pass on these pins does not establish compatibility with every
later release. Current-source gateway RPC Relay/History proof also passed on both
pins.

Both pins passed the complete native Desktop/TUI memory-off and memory-on
journeys, including default Tool Search, Relay/wake, later-session History,
endpoint outage, controlled host/MCP relaunch and profile update/status/removal.
The memory-on journeys completed the optional-memory lifecycle. This evidence
does not qualify Windows 11, MSIX or native updater behavior, native app Quit,
automatic standalone MCP reconnection, paid-provider quality or every
provider/memory combination. Earlier failed runs remain documented as failed in
the package qualification record; the accepted matrix does not reclassify them.

Additional isolated Linux TUI qualification passed on both releases at candidate
`13029e38`: the full default-off journey used Hermes's built-in `openai-api`
configuration, and the memory-on journey used a custom synthetic provider.
Both exercised busy-turn delivery, later-session History, host/MCP relaunch and
profile update/removal. Provider credentials stayed out of both MCP generations.
These offline checks use synthetic responses; they establish configuration and
integration behavior, not paid-model quality or every provider/memory combination.

## Available in the experimental package

| Capability | Current boundary |
|---|---|
| Relay | 12 MCP tools for discovery, identity, work associations, messaging, status and trace; current gateway round trips passed on v0.22.0/v0.22.2 |
| Session History | Capture plus `pallium_search_history`, `pallium_search_history_by_work_ref` and `pallium_expand_source`; current search and expansion passed through v0.22.0/v0.22.2 gateway RPC |
| Skill and MCP | Bundled skill and plugin-owned stdio bridge; trusted conversation identity and private scope are supplied by the integration |
| Package lifecycle | Explicit-profile setup, status, repeat setup/update and removal with ownership checks; running-host readiness is a separate check |
| Derived memory | Eleven existing memory query/write tools are available through an explicit opt-in catalog; disabled by default. This adds tools, not automatic memory injection. The opt-in lifecycle passed on both pinned Windows Desktop/TUI releases and both tested Linux TUI releases |

Incoming Relay deliveries are admitted by the host integration and acknowledged
after the full delivery context is present in the assembled request for that
host session/turn. The ACK records host-context receipt before provider
completion; it does not prove model/provider completion or action. The package
does not expose receive/ACK tools. A saved send or wake attempt is not proof of
receipt. Busy-turn delivery, endpoint outage and controlled host/MCP relaunch
passed across the scoped native matrix. A separate caller E2E proves queued
delivery persistence across an owned Pallium process restart. Automatic
standalone MCP reconnection, ordinary-turn fallback and other untested reset or
close failure modes remain unqualified; do not apply another integration's wake
guarantees to Hermes.

After an admitted delivery's exact host turn ends, the integration releases its
local wake fence even if the agent did not reply. Missing or stale turn-end
callbacks and uncertain claim/ACK state remain fenced. Serialization applies
within one plugin process; it does not coordinate independent processes sharing
a profile.

History capture stores private, hook-observed plain-text user/final-assistant
snapshots with stable host session, turn and message IDs. It accepts up to
20,000 Unicode code points per row and skips unsupported, oversized or ambiguous
rows and synthetic wake user markers. It is not proof of Hermes database commit
or message delivery, and capture has no durable retry queue. Current completion
capture supplies no `request_source_item_id`; never invent one. Work references
are copied only from verified current-session associations, so exact-work search
may miss a capture when that lookup fails.

History search and expansion reuse Pallium's visibility, redaction, forgetting,
paging and lookup-lineage rules. The default catalog has three History tools;
History diagnostics remain unavailable. With memory enabled, source-forget and
the optional memory tools are added. Standard memory query retains its
configured actor filter; expansion follows canonical same-container and matching
global visibility rules. Scoped mutation provenance comes from trusted profile
and host session context. Source-forget's optional thread selector identifies
the target source partition; omission preserves the bounded container partition.
Historical `actor_ref` and `source_thread_ref` filters do not change integration
identity. The package supplies a fixed private container configuration and
host-issued current session.
Explicit memories can be queried across sessions within that scope. Correction
updates the payload and stored search entries atomically; vector embedding is
best-effort, with reconciliation for missing vectors. Evidence-specific filters
cannot match an explicit memory without evidence, and forgotten memories remain
excluded. Caller tests cover these contracts; native opt-in UI lifecycle passed
on both pinned Windows Desktop/TUI releases and both Linux TUI releases.
See [Session History](session-history.md) and
[Privacy and Visibility](privacy-and-visibility.md).

## Setup, update and removal

Use the complete commands and prerequisites in the
[Hermes package guide](../integrations/hermes/README.md#prepare-an-isolated-profile).
The setup target is `pallium setup hermes`; it requires an existing explicit
profile, the Hermes interpreter and fixed Pallium scope. It is not interchangeable
with the quickstart's default-profile setup commands.

Setup preserves the profile's provider, toolsets, Tool Search and other plugins;
those are not intrinsic package requirements. It validates Hermes MCP SDK2 and
a separate Pallium MCP SDK1 interpreter. It does not create a global
`mcp_servers` entry. Windows native tests used synthetic providers. Linux TUI
checks covered the built-in `openai-api` configuration with memory off and a
custom synthetic provider with memory on. Other provider configurations, paid
model quality and every provider/memory combination remain unqualified.

Memory tools are disabled by default. Pass `--memory-enabled` to opt in; pass
`--no-memory-enabled` to disable them. Repeating setup without the opt-in flag
sets the catalog back to disabled, so repeat the flag when preserving an opt-in.
The optional catalog does not promise automatic memory injection.

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
- Upstream Desktop requires Windows 11 22H2 or later. Qualification must isolate
  backend, Electron and process-home data paths inside a disposable OS/account,
  or use a supported registration opt-out. Profile directories alone do not isolate
  native URL-handler registration. The accepted v0.22.0/v0.22.2 Desktop and TUI
  journeys ran on Windows Server 2025 with an unpacked app. Windows 11, MSIX and
  native updater behavior remain unqualified.
- Caller tests cover explicit-memory recall/correction and successive wakes
  after admitted no-reply turns. Native opt-in UI lifecycle passed on both pinned
  Windows Desktop/TUI releases and both Linux TUI releases. A successful write or tool call alone
  is insufficient evidence.

The [qualification record](../integrations/hermes/README.md#production-qualification-in-progress)
tracks the accepted scoped matrix and remaining provider, reconnect and platform
limits. Public docs, commands and support claims still require human release
acceptance before broader rollout.
Current work remains on the [Hermes roadmap item](../roadmap/features/add-hermes-agent-integration.md).
