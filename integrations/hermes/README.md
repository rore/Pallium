# Pallium for Hermes

This experimental package installs a native Hermes plugin, the discoverable `pallium-memory` skill, and the plugin-owned Pallium MCP bridge. Earlier gateway RPC Relay/History checks passed on Hermes v0.22.0 and v0.22.2; the accepted native UI/MCP/package matrix below covers host/plugin behavior at `d5896a24`. Setup never creates a global `mcp_servers` connection and preserves provider, toolset, Tool Search, other plugin, credential, and data settings.

For the public capability overview and support boundaries, see the
[Hermes integration guide](../../docs/hermes-integration.md).

## Production qualification in progress

The corrected plugin renews the exact Relay endpoint during trusted ordinary
turns and matching wakes. Caller E2E covers the 24-hour boundary, and the current
native matrix passed complete 16,000-code-point Unicode deliveries with Hermes's
default enabled 10,000-character hook spill limit unchanged, followed by reply
wakes. Existing uncertain claim/admission fences remain intact.

The scoped Windows native matrix is accepted for both Desktop and **TUI**, with
memory off and on for Hermes v0.22.0 and v0.22.2. The package remains experimental
pending human release acceptance. The evidence covers the tested builds; later
releases need their own qualification. Runtime admission uses public API capabilities rather than an
exact Hermes version lock.

Relay context uses the public `llm_request` middleware after Hermes's hook-output
spill stage. Earlier request middleware sees a bounded placeholder; middleware
that must inspect the payload needs to run after expansion. Removed or rewritten
placeholders are not reconstructed, later filters remain authoritative, and the
raw execution gate still requires complete context before ACK. Setup preserves
the host's global spill settings.

| Gate | Required evidence | Current state |
|---|---|---|
| Released hosts | Actual Desktop and TUI journeys on the tested compatible releases | Windows Server 2025 unpacked-app matrix passed on v0.22.0 and v0.22.2: both surfaces, memory off/on; Linux TUI also passed on both pins |
| Runtime compatibility | Public plugin identity, injection, hook and middleware contracts; clear missing-capability errors | Gateway and scoped native checks passed on both pins. Admission uses public capabilities, not a version lock; later releases need their own evidence |
| Normal configuration | Default Tool Search and supported plugin coexistence | Native Windows tests used synthetic providers. Linux TUI covered built-in `openai-api` with memory off and custom synthetic provider with memory on; ordinary/paid-provider quality and all provider/memory combinations remain unqualified |
| Full package | Skill, Relay, History and opt-in memory lifecycle; memory off leaves Relay/History functional | All eight Windows UI cells passed complete 16,000-character delivery, subsequent reply and profile lifecycle with default hook spill enabled; Linux TUI default-off and opt-in lifecycles passed on both pins |
| Recovery | Busy/concurrent sessions, reset/close, host/service/MCP restart, stale routes and ambiguous outcomes | Busy turns, endpoint outage and controlled host/MCP relaunch passed in the scoped journeys. Automatic standalone MCP reconnection and untested failure modes remain unqualified |
| Lifecycle | Disposable install/update/remove/rollback, repeated use and owned-process cleanup | Native repeat setup, status and removal preserved profile data on both Windows pins and both surfaces; caller ownership/conflict coverage remains separate |
| Public documentation | Public entry points, setup/capability guides and bundled skill match final verified behavior; commands and links checked | Final alignment audit passed 11 documents, 93 local links/anchors and 3 setup commands; human release acceptance remains open |

The [v0.22.2 release notes](https://github.com/NousResearch/hermes-agent/releases/tag/v0.22.2)
identify v0.22.1 as an accidental build with a session-deletion issue; exclude it
from the initial matrix. A successful check on one release does not establish
compatibility with every future release. Record exact tested builds, then admit
other builds through the same public capability and behavioral checks without
forcing host downgrades or replacing the native updater.

Desktop qualification uses upstream's unpacked test build, not an everyday MSIX
installation. Windows Desktop requires Windows 11 22H2 or later. Isolate both
`HERMES_HOME` and `HERMES_DESKTOP_USER_DATA_DIR`, redirect process home/profile
discovery, scrub credentials, and provide the explicit source backend root and
`HERMES_DESKTOP_PYTHON`. Verify those paths before launch so unresolved backend
discovery cannot fall through to a first-run installer. An unpacked test proves
neither MSIX installation nor native update behavior. See upstream's
[Desktop build contract](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/apps/desktop/BUILDING.md).

Work and evidence are tracked in
`.agent-workflow/tasks/hermes-production-slice4.md`. Everyday installation remains
a separate rollout decision.

## Prepare an isolated profile

The setup command requires an existing explicit profile. It preserves provider, toolset, Tool Search and other plugin settings; it does not require a frozen local-provider profile. The built-in `openai-api` configuration has a synthetic-response Linux TUI qualification; other provider configurations remain unqualified. For isolated testing, use a disposable profile and loopback service. The following profile is an example of one possible test setup, not a package requirement:

```yaml
plugins:
  enabled: []
platform_toolsets:
  cli: [hermes-cli]
tools:
  tool_search:
    enabled: "off"
model:
  default: probe-model
  provider: custom
  base_url: http://127.0.0.1:57089/v1
  api_key: local-stub
  api_mode: chat_completions
fallback_providers: []
```

For qualification, use an isolated disposable profile and loopback service. The installer calls the public Hermes config writer in the selected `--hermes-python` interpreter and refuses incompatible or unreadable profile config before touching package files.

Run setup and removal only while the target Hermes host and other profile config
writers are stopped. The digest check detects edits before writing; the native
writer provides no atomic compare-and-swap against overlapping external writes.
Concurrent config writers and production installation remain unqualified. On an
uncertain write, current config bytes are retained for inspection rather than
overwritten from an older snapshot.

## Install, inspect, and remove

From the Pallium checkout, pass the exact profile and both Python environments:

```powershell
python -m app.run setup hermes `
  --home C:\path\to\disposable-hermes-home `
  --hermes-python C:\path\to\hermes-venv\Scripts\python.exe `
  --service-url http://127.0.0.1:29999 `
  --container-ref git:example.test/team/hermes-e2e `
  --actor-ref hermes-e2e `
  --visibility private `
  --mcp-python C:\path\to\pallium-venv\Scripts\python.exe `
  --mcp-repo C:\path\to\Pallium `
  --memory-enabled
```

Memory is disabled by default. Use `--memory-enabled` to opt in or
`--no-memory-enabled` to disable it. Repeating setup without `--memory-enabled`
resets a prior opt-in to disabled, so include the flag on repeat installs that
should keep memory tools enabled.

`--mcp-python` defaults to the current Pallium interpreter and `--mcp-repo` to this checkout. Setup validates Pallium MCP SDK v1 and Hermes MCP SDK v2 before mutation. The `service-url`, container, actor and visibility values are explicit package scope; this release accepts private visibility only.

Inspect configured files with the same explicit profile:

```powershell
python -m app.run setup hermes --home C:\path\to\disposable-hermes-home `
  --hermes-python C:\path\to\hermes-venv\Scripts\python.exe --status
```

Remove only unchanged package-owned files and configuration:

```powershell
python -m app.run setup hermes --home C:\path\to\disposable-hermes-home `
  --hermes-python C:\path\to\hermes-venv\Scripts\python.exe --uninstall
```

Setup is repeatable. The installer stores ownership fingerprints beside the plugin and skill. It refuses unowned collisions or edited owned artifacts rather than replacing them. Removal restores the original `plugins.enabled` state, deletes only this plugin's exact config entry, and preserves unrelated nested configuration and other enabled plugins. A conflict leaves the profile untouched. Status checks file/config fingerprints only; it does not qualify a running host or live MCP connection.

The profile skill is installed under `$HERMES_HOME/skills/pallium-memory/`, so Hermes includes it in normal skill discovery. The default MCP catalog includes Relay and three Session History tools. The explicit memory opt-in adds eleven existing memory query/write tools; this is an optional tool catalog and does not promise automatic memory injection. Relay ACK records host-context receipt before provider completion, not model/provider completion or action. Use the reply operation for an injected delivery and never receive or ACK it again.

An admitted wake also completes locally when its exact host turn ends without a
reply. Stale or incomplete callbacks cannot release a newer wake, and uncertain
claim/ACK state stays fenced. This serialization is local to one plugin process.
Caller tests cover successive wakes and explicit-memory recall, correction,
supersession and forgetting; these are separate from native UI qualification.

## Session History

The public `post_llm_call` hook captures the current plain-text user and final
assistant pair as private, hook-observed snapshots. Each source carries the exact
host session, turn and logical `message_uid`, with `capture_stage=post_llm_call`.
Stable source IDs prevent duplicate callback capture and do not revive forgotten
sources. Pallium applies its existing redaction, visibility and forgetting rules.
This is evidence of hook observation, not proof of Hermes database commit or
message delivery: Hermes can still invoke this hook after a transcript write fails.

Capture accepts nonempty simple text up to 20,000 Unicode code points per row.
Missing or ambiguous IDs, merged/hidden/scaffolding rows, mismatched callback text,
multimodal rows and longer content are skipped without truncation or backfill.
Interrupted turns without this callback are not captured. Synthetic Relay wake
user markers are excluded; an observed final assistant response is labeled
`capture_origin=relay_wake`. Provider context, tool output and private Relay
receipts are never copied into the captured user row. Capture failure does not
interrupt Hermes and has no durable retry queue.

Use `pallium_search_history` for broad earlier-session search, or
`pallium_search_history_by_work_ref` with an exact known reference. Capture copies
work references only from a verified current-session Relay association. Failed
association reads omit them, so exact-work search can miss otherwise searchable
turns. Use `pallium_expand_source` with a returned `source_item_id` and that search
page's `lookup_event_id` as `parent_lookup_id`. Keep returned offsets and revisions
for subsequent pages. The bridge binds the current container, session and private
visibility; standard memory query retains the configured actor filter, while
memory expansion uses canonical same-container and matching global visibility
rules. `actor_ref` and `source_thread_ref` remain optional History filters.
Completion-only capture supplies no current `request_source_item_id`; do not invent
one. With memory opt-in, `pallium_expand_source` can include supported memories.
Scoped mutations use trusted configured scope and host session provenance; the
current request source ID is unavailable. `pallium_forget_source` accepts an
optional target thread selector: supplying it targets that historical partition;
omitting it retains the bounded container partition.

## Native qualification limits

Earlier gateway wake qualification passed on v0.22.0 and v0.22.2 with
disposable local-provider profiles and loopback stubs. Those gateway checks do
not establish native UI interaction; accepted Windows UI evidence is summarized
below.
The accepted native run [39650756737](https://github.com/rore/Pallium/actions/runs/39650756737)
tested candidate `d5896a24ec3b72c1f23f5323e43ab8d2a06e60ca`. Independent review
accepted all eight Windows cells: v0.22.0 and v0.22.2, Desktop and TUI, memory
off and on. Each release job passed 83 checks with zero failures, errors or skips.
The complete journeys included the full Unicode payload at the provider under
default hook spill, subsequent reply, later-session History, busy-turn handling,
privacy/source checks, two normal process generations and profile update/status/removal.
All final audits recorded zero cancellations and zero fatal errors. The earlier
`b3601c79` matrix remains historical evidence for its shorter journeys.
Earlier failed and cancelled runs remain recorded as failures in the
[qualification history](../../docs/designs/hermes-native-qualification.md); this
accepted run does not reclassify them.

The scoped evidence does not qualify Windows 11, everyday MSIX/updater behavior,
native app Quit, automatic standalone MCP reconnection, paid-provider quality or
every provider/memory combination.

Native evidence used Windows Server 2025 with an unpacked app and synthetic
providers. The later service head `a48b0fef` fixes two logger references in
optional vector-failure paths. Its eight public HTTP fault regressions and
178-test affected memory subsystem passed. Vector import/build and remember
vector-persistence failures preserve lexical recall; lexical failures still
propagate with existing persistence timing. Native15 is reused for unchanged
host/plugin/MCP behavior and does not prove these injected service failures.
Current [CI 39667217842](https://github.com/rore/Pallium/actions/runs/39667217842)
remains failed in two Codex tests; Windows smoke and governance passed. These
and earlier generic registration and recovery CI failures remain failed in the
[qualification record](../../docs/designs/hermes-native-qualification.md#current-scoped-result).
Independent technical review accepted the corrected result. The package remains
experimental pending corrected-revision human release acceptance. A focused
gateway journey requires an isolated environment:

```powershell
$env:HERMES_E2E_SOURCE = 'C:\path\to\pinned\hermes-agent'
$env:HERMES_E2E_PYTHON = 'C:\path\to\hermes-venv\Scripts\python.exe'
python -m pytest -m slow -q -n 0 tests/test_hermes_relay_native_e2e.py
```

This does not qualify other Hermes releases, remote providers, competing middleware, multiple-profile routing, recovery after uncertain enqueue/claim, or production use. It does not install into or alter a user's everyday Hermes profile.
