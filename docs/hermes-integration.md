# Hermes integration

Pallium's Hermes package remains **experimental** pending human release
acceptance. It bundles a native plugin, the `pallium-memory` skill and a
profile-scoped MCP bridge. Everyday installation remains a separate rollout
decision.

Independent review accepted all eight corrected-package Windows UI journeys in
[native run 39650756737](https://github.com/rore/Pallium/actions/runs/39650756737),
candidate `d5896a24ec3b72c1f23f5323e43ab8d2a06e60ca`. Each release job passed 83
checks with zero failures, errors or skips. The provider received the complete
16,000-code-point Unicode delivery with Hermes's default enabled
10,000-character hook spill limit unchanged, followed by a successful reply wake.
Separate caller E2E covers the 24-hour liveness boundary and uncertain outcomes.

The later service correction `a48b0fef` fixes two logger references in optional
vector-failure paths. Eight public HTTP regressions and the 178-test affected
memory subsystem passed, including lexical recall after vector failure. Native15
is reused for unchanged host/plugin/MCP behavior; it did not exercise those
injected service failures. Independent technical review accepted the corrected
result; required human release acceptance remains pending. Its
[CI run 39667217842](https://github.com/rore/Pallium/actions/runs/39667217842)
remains failed in two Codex tests; Windows smoke and governance passed. The
distinct failures and unreached assertions are retained in the qualification
record below.

The scoped native matrix passed on both Windows **Desktop and TUI**, with memory
off and on, for pinned Hermes **v0.22.0** and **v0.22.2** sources. It ran in an
isolated Windows Server 2025 VM with an unpacked app and synthetic providers.
Runtime checks use public plugin capabilities rather than an exact Hermes
version lock; a pass on these pins does not establish compatibility with every
later release. Earlier gateway RPC Relay/History checks also passed on both pins;
the accepted native UI/MCP/package matrix supplies the reused host evidence above.

Both pins passed the complete native Desktop/TUI memory-off and memory-on
journeys, including default Tool Search, Relay/wake, later-session History,
endpoint outage, controlled host/MCP relaunch and profile update/status/removal.
The memory-on journeys completed the optional-memory lifecycle. This evidence
does not qualify Windows 11, MSIX or native updater behavior, native app Quit,
automatic standalone MCP reconnection, paid-provider quality or every
provider/memory combination. Earlier failed runs remain documented as failed in
the package qualification record; the accepted matrix does not reclassify them.
Earlier CI retains distinct shared registration and recovery availability
failures; their scope and passing lanes are recorded in the
[qualification history](designs/hermes-native-qualification.md#current-scoped-result).

Additional isolated Linux TUI qualification passed on both releases at candidate
`b96a05e1`: the full default-off journey used Hermes's built-in `openai-api`
configuration, and the memory-on journey used a custom synthetic provider.
All four cases passed without skips: v0.22.0 took 115.475 seconds and v0.22.2
112.384 seconds. The journeys exercised the complete long payload, busy-turn
delivery, later-session History, host/MCP relaunch and profile update/removal.
Provider credentials stayed out of both MCP generations.
These offline checks use synthetic responses; they establish configuration and
integration behavior, not paid-model quality or every provider/memory combination.

## Available in the experimental package

| Capability | Current boundary |
|---|---|
| Relay | 12 MCP tools for discovery, identity, work associations, messaging, status and trace; native UI/MCP round trips passed in the current matrix on v0.22.0/v0.22.2 |
| Session History | Capture plus `pallium_search_history`, `pallium_search_history_by_work_ref` and `pallium_expand_source`; search and expansion passed in the current native UI/MCP matrix on v0.22.0/v0.22.2 |
| Skill and MCP | Bundled skill and plugin-owned stdio bridge; trusted conversation identity and private scope are supplied by the integration |
| Package lifecycle | Explicit-profile setup, status, repeat setup/update and removal with ownership checks; running-host readiness is a separate check |
| Derived memory | Eleven existing memory query/write tools are available through an explicit opt-in catalog; disabled by default. This adds tools, not automatic memory injection. The opt-in lifecycle passed on both pinned Windows Desktop/TUI releases and both tested Linux TUI releases |

Incoming Relay deliveries are admitted by the host integration and acknowledged
after the full delivery context is present in the assembled request for that
host session/turn. The ACK records host-context receipt before provider
completion; it does not prove model/provider completion or action. The package
does not expose receive/ACK tools. A saved send or wake attempt is not proof of
receipt.

Incoming payloads can contain up to 16,000 Unicode code points; host-bound
replies are limited to 2,400. Complete payload and attribution must fit the
bounded request before admission. Trusted ordinary turns and exact matching
wake callbacks renew the same Relay endpoint with an atomic endpoint/generation
check. Background polling and MCP reads do not renew presence, and closed or
replaced endpoints are refused. Existing uncertain claim/admission fences are
preserved across reload; the integration does not infer that an earlier action
was safe to retry.

Full context is inserted through Hermes's supported request middleware after its
hook-output size check. Request middleware registered before Pallium sees a
bounded placeholder; content inspection that needs the payload must run after
Pallium's expansion. Removing or rewriting the placeholder prevents expansion.
Later request filters remain authoritative, and missing complete context is
never acknowledged. No global hook-output limit is changed.

Already-admitted text remains in plugin memory for the same host turn's later
model calls, including its final response after an explicit reply. This retains
context without retaining reply or ACK permission. The view is discarded on the
exact turn-end callback or plugin unload and is not a persistent retry cache.

Busy-turn delivery, endpoint outage and controlled host/MCP relaunch
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
