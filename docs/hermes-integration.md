# Hermes integration

Pallium's Hermes package remains **experimental** while the current Windows
matrix completes. It bundles a native plugin, the `pallium-memory` skill and a
profile-scoped MCP bridge. Everyday installation remains a separate rollout
decision.

Production support must cover both Windows **Desktop and TUI** across compatible
Hermes releases. Runtime checks use public plugin capabilities rather than an
exact Hermes version check. Current-source gateway RPC Relay/History proof passed
on clean **v0.22.0** and **v0.22.2** with disposable profiles and a local provider.
These checks do not establish actual Desktop or TUI
interaction, normal provider/default Tool Search behavior, memory parity or later
release compatibility.

On v0.22.0, complete native Desktop and TUI memory-off and memory-on journeys
passed in an isolated Windows Server 2025 VM with an unpacked app and synthetic
provider. The memory-off cases covered default Tool Search, Relay/wake,
later-session History, a harmless peer hook, endpoint outage, controlled
host/MCP relaunch and profile update/status/removal; memory-on completed the
optional-memory lifecycle. These checks do not qualify Windows 11, MSIX or native
updater behavior, paid-provider quality, or automatic standalone MCP reconnection.
The v0.22.2 Windows matrix remains incomplete and under review. Earlier failed-run
details are retained in the package qualification record as history.

Additional isolated Linux TUI qualification passed on both releases at candidate
`13029e38`: the full default-off journey used Hermes's built-in `openai-api`
configuration, and the memory-on journey used a custom synthetic provider.
Both exercised busy-turn delivery, later-session History, host/MCP relaunch and
profile update/removal. Provider credentials stayed out of both MCP generations.
These offline checks use synthetic responses; they establish configuration and
integration behavior, not model quality or the remaining Windows matrix.

## Available in the experimental package

| Capability | Current boundary |
|---|---|
| Relay | 12 MCP tools for discovery, identity, work associations, messaging, status and trace; current gateway round trips passed on v0.22.0/v0.22.2 |
| Session History | Capture plus `pallium_search_history`, `pallium_search_history_by_work_ref` and `pallium_expand_source`; current search and expansion passed through v0.22.0/v0.22.2 gateway RPC |
| Skill and MCP | Bundled skill and plugin-owned stdio bridge; trusted conversation identity and private scope are supplied by the integration |
| Package lifecycle | Explicit-profile setup, status, repeat setup/update and removal with ownership checks; running-host readiness is a separate check |
| Derived memory | Eleven existing memory query/write tools are available through an explicit opt-in catalog; disabled by default. This adds tools, not automatic memory injection. The opt-in lifecycle passed on v0.22.0 Windows Desktop/TUI and both tested Linux TUI releases; v0.22.2 Windows remains unqualified |

Incoming Relay deliveries are admitted by the host integration and acknowledged
after the full delivery context is present in the assembled request for that
host session/turn. The ACK records host-context receipt before provider
completion; it does not prove model/provider completion or action. The package
does not expose receive/ACK tools. A saved send or wake attempt is not proof of
receipt. Endpoint outage and controlled host/MCP relaunch passed in the Desktop
memory-off journey. A separate caller E2E proves queued delivery persistence
across an owned Pallium process restart. Automatic native reconnection,
busy/reset/close behavior across the full matrix and ordinary-turn fallback remain
unqualified; do not apply another integration's wake guarantees to Hermes.

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
on v0.22.0 Desktop/TUI and both Linux TUI releases. The v0.22.2 Windows matrix
remains incomplete and under review.
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
`mcp_servers` entry. The current Linux TUI checks cover one built-in provider
configuration, default Tool Search and a harmless peer hook. The complete current
Windows matrix and other provider configurations remain unqualified.

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
- Desktop qualification needs Windows 11 22H2 or later and separate backend,
  Electron and process-home data paths inside a disposable OS/account, or a
  supported registration opt-out. Profile directories alone do not isolate
  native URL-handler registration. Hosted v0.22.0 Desktop and TUI memory-off/on
  journeys passed on Windows Server 2025 with an unpacked app; v0.22.2 and Windows
  11/MSIX qualification remain open.
- Caller tests cover explicit-memory recall/correction and successive wakes
  after admitted no-reply turns. Native opt-in UI lifecycle passed on v0.22.0
  Desktop/TUI and both Linux TUI releases; the v0.22.2 Windows matrix remains a
  release gate. A successful write or tool call alone is insufficient evidence.

The [qualification matrix](../integrations/hermes/README.md#production-qualification-in-progress)
tracks the incomplete v0.22.2 Windows run and remaining provider, reconnect and
platform gates. Public docs, commands
and support claims must be reviewed against the final verified behavior before a
production release.
Current work remains on the [Hermes roadmap item](../roadmap/features/add-hermes-agent-integration.md).
