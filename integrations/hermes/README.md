# Pallium for Hermes

This experimental package installs a native Hermes plugin, the discoverable `pallium-memory` skill, and the plugin-owned Pallium MCP bridge. Current source passed gateway RPC Relay/History on Hermes v0.22.0 and v0.22.2. Setup never creates a global `mcp_servers` connection and preserves provider, toolset, Tool Search, other plugin, credential, and data settings.

For the public capability overview and support boundaries, see the
[Hermes integration guide](../../docs/hermes-integration.md).

## Production qualification in progress

The release target covers both Windows **Desktop and TUI**, with public API
capability checks rather than an exact Hermes version lock. The current package
remains experimental until the following gates pass; these are targets, not a
supported-version claim.

| Gate | Required evidence | Current state |
|---|---|---|
| Released hosts | Actual Desktop and TUI journeys on current compatible releases | Linux TUI memory-off/on passed on both pins; Windows Desktop and TUI memory-off/on passed on v0.22.0; the v0.22.2 Windows matrix remains incomplete and under review |
| Runtime compatibility | Public plugin identity, injection, hook and middleware contracts; clear missing-capability errors | Current v0.22.0/v0.22.2 gateway checks passed; full native release coverage pending |
| Normal configuration | Ordinary providers, default Tool Search, supported plugin coexistence | Built-in openai-api configuration, default Tool Search and a harmless peer hook passed in isolated Linux TUI checks on both releases; current Windows matrix and other providers remain unqualified |
| Full package | Skill, Relay, History and opt-in memory lifecycle; memory off leaves Relay/History functional | Complete Linux TUI default-off and opt-in memory lifecycles passed on both pins; Windows Desktop and TUI default-off and opt-in lifecycles passed on v0.22.0; v0.22.2 Windows remains incomplete and under review |
| Recovery | Busy/concurrent sessions, reset/close, host/service/MCP restart, stale routes and ambiguous outcomes | Endpoint outage and controlled host/MCP relaunch passed in Desktop memory-off; a separate caller E2E proves queued delivery persistence across an owned Pallium process restart. Native service/MCP reconnection and the remaining matrix are unqualified |
| Lifecycle | Disposable install/update/remove/rollback, repeated use and owned-process cleanup | Native repeat setup, status and removal preserved profile data in v0.22.0 Desktop and TUI cases; caller ownership/conflict coverage remains separate |
| Public documentation | Public entry points, setup/capability guides and bundled skill match final verified behavior; commands and links checked | Initial alignment audit updated the guides; final production review still required |

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

Current native gateway wake qualification passed on v0.22.0 and v0.22.2 with
disposable local-provider profiles and loopback stubs. Those gateway checks do
not establish native UI interaction; accepted Windows UI evidence is summarized
below.
Earlier hosted native runs [39483789032](https://github.com/rore/Pallium/actions/runs/39483789032)
and [39490754190](https://github.com/rore/Pallium/actions/runs/39490754190)
passed the complete Desktop memory-off journey on v0.22.0, including default Tool
Search, Relay/wake, later-session History, a harmless peer hook, endpoint outage,
controlled host/MCP relaunch and profile update/status/removal. The TUI off/on and
Desktop memory-on cases failed; fail-fast cancelled v0.22.2. Run2 exposed cursor
redraw and mixed memory/History fixture errors. Run3 used the corrected fixtures,
then failed on an orphan wide-character cell in the terminal observer and a valid
nullable expansion field in the memory script. Reviewed test-only corrections at
`31f1b240` passed parser and memory-script regressions in the Python 3.13 full
suite; they have not passed a complete native matrix. The separate service-process
E2E passed on Python 3.12 and 3.13, preserving exact queued endpoint/message/delivery
IDs through public claim, ACK, reply and final-state reads. That is queue
persistence proof, not native automatic MCP reconnection.

The earlier retained run [39557493207](https://github.com/rore/Pallium/actions/runs/39557493207)
tested exact candidate `f348f00f9b4ef0b6fbf63d0e87df245102318498`. Both Desktop and
TUI memory-off journeys passed on v0.22.0. Both memory-on cases reached their
memory lifecycle, then failed a fixture assertion using a History attribution
field for an ordinary memory query. All four cleanup/source postconditions passed;
v0.22.2 was cancelled by fail-fast. The corrected query assertion and later
busy-turn/source-composition changes remain unqualified by that run.

Native run [39586401041](https://github.com/rore/Pallium/actions/runs/39586401041)
used candidate `7df9975dd6e6176e5c0a8b5b046e173179f62e97`. Independent review
accepted its four actual v0.22.0 Desktop/TUI memory-off/on cells; the aggregate
run failed a pure-helper cleanup mock, so it is not an all-green run.
Follow-up run [39588545910](https://github.com/rore/Pallium/actions/runs/39588545910)
used candidate `b13a3dd29eefc243ef0b10920fdd6b2d33aefbde`. Its v0.22.0 job passed
61 checks in 360.95 seconds. The v0.22.2 job passed 60 checks and failed one in
417.18 seconds: the actual TUI memory-off cell reported a fatal HTTP API response
write error, `ConnectionAbortedError(10053)`. The artifact remains under review;
the failed cell and v0.22.2 matrix are unqualified, and its cause is not classified.
Required-CI shared-test availability failures affected Python 3.12 and 3.13 on
different candidate heads; the Hermes changes did not repair them.
These results do not qualify Windows 11, everyday MSIX/updater behavior, native
app-quit behavior, automatic standalone MCP reconnection, paid-provider quality
or every provider/memory combination.

Native evidence uses Windows Server 2025 with an unpacked app and synthetic
provider: run2 image `win25-vs2026`/`20261018.275.1`; run3 image
`win25-vs2026`/`20261007.264.1`. Earlier required CI on `31f1b240` failed on Python
3.12 Relay acquisition in unchanged tests. Both failed attempts are retained in
[CI 39493899447](https://github.com/rore/Pallium/actions/runs/39493899447).
[CI 39550292689](https://github.com/rore/Pallium/actions/runs/39550292689) passed
all required lanes on the documentation-only successor `f348f00f`, including the
parser, memory-script and service-process persistence checks. That green result
is non-reproduction of the earlier failures, not a causal reliability fix. The complete
v0.22.2 Windows matrix remains pending, and the package stays experimental. A focused
gateway journey requires an isolated environment:

```powershell
$env:HERMES_E2E_SOURCE = 'C:\path\to\pinned\hermes-agent'
$env:HERMES_E2E_PYTHON = 'C:\path\to\hermes-venv\Scripts\python.exe'
python -m pytest -m slow -q -n 0 tests/test_hermes_relay_native_e2e.py
```

This does not qualify other Hermes releases, remote providers, competing middleware, multiple-profile routing, recovery after uncertain enqueue/claim, or production use. It does not install into or alter a user's everyday Hermes profile.
