# Pallium for Hermes

Install Pallium's native Hermes plugin, bundled `pallium-memory` skill and
plugin-owned MCP bridge into an explicit profile. Relay and Session History are
enabled by default; memory tools are optional. Setup preserves provider,
toolset, Tool Search, other plugin, credential and data settings and creates no
global `mcp_servers` entry.

See the [Hermes integration guide](../../docs/hermes-integration.md) for the
capability overview and supported behavior.

## Capabilities

The package supplies Relay, private Session History, a discoverable skill and
profile-scoped tools. Memory tools are optional, with no automatic injection.
Use the [integration guide](../../docs/hermes-integration.md) for the everyday
workflow and the shared [delivery table](../../docs/agent-relay.md#delivery-and-wake-behavior)
for a comparison with other hosts. This page is the package command reference.

## Prerequisites

<a id="prepare-an-isolated-profile"></a>
<a id="choose-a-profile-and-interpreters"></a>

- Use an existing Hermes profile and pass its exact `HERMES_HOME` directory.
  For a trial, choose a separate profile rather than replacing your everyday one.
- Select the Hermes virtual environment's Python with **MCP SDK2** and a Pallium
  Python environment with **MCP SDK1**. Setup validates both before mutation.
- Use a running local Pallium service and explicit container, actor and private
  visibility values. The package accepts private visibility only.
- Keep the Pallium checkout at a stable path; the bridge configuration contains
  absolute interpreter and checkout paths.

Stop the target Hermes host and other profile configuration writers before
install, update or removal. The installer uses Hermes's public config writer and
checks ownership fingerprints, but the native writer has no atomic compare-and-swap
against simultaneous external edits. After an uncertain config write, inspect
the preserved configuration and reported conflict before retrying.

## Setup

<a id="install-inspect-and-remove"></a>

From the Pallium checkout, replace the example paths and scope with your values:

```powershell
python -m app.run setup hermes `
  --home C:\path\to\hermes-profile `
  --hermes-python C:\path\to\hermes-venv\Scripts\python.exe `
  --service-url http://127.0.0.1:19836 `
  --container-ref git:example.test/team/project `
  --actor-ref developer `
  --visibility private `
  --mcp-python C:\path\to\pallium-venv\Scripts\python.exe `
  --mcp-repo C:\path\to\Pallium
```

`--mcp-python` defaults to the current Pallium interpreter; `--mcp-repo` defaults
to its checkout. Pass them explicitly when your environments differ.

Memory tools are disabled by default. Add `--memory-enabled` to opt in, including
on later setup/update calls that should preserve the opt-in. Omitting that flag
returns the catalog to disabled; `--no-memory-enabled` explicitly disables it.
The catalog adds eleven memory query/write tools, not automatic memory injection.

## Verify the connection

Inspect the configured installation:

```powershell
python -m app.run setup hermes --home C:\path\to\hermes-profile `
  --hermes-python C:\path\to\hermes-venv\Scripts\python.exe --status
```

Status checks configuration, not live readiness. Start the selected profile and
follow the [connection check](../../docs/hermes-integration.md#verify-the-connection)
to exchange a message/reply and verify captured History.

The skill is installed under `$HERMES_HOME/skills/pallium-memory/` for normal
Hermes discovery. The default catalog contains twelve Relay and three History
tools. The plugin supplies current host identity and private scope; callers must
not invent replacements.

## Delivery and recovery

<a id="relay-behavior"></a>

Incoming messages support 16,000 Unicode code points and host-bound replies
2,400. The plugin renews the exact Relay endpoint during trusted host activity;
background polling and MCP reads do not renew presence. Closed, replaced and
wrong-generation endpoints are refused.

The hook owns claim and ACK. It acknowledges delivery only when the complete
context is present in the assembled host request. ACK proves host-context receipt,
not provider completion or agent action. Never receive or ACK the same injected
delivery again; use its reply operation when a response is needed.

Pallium expands a bounded placeholder through public request middleware after
the host's hook-output size check. Middleware needing the payload must run after
that expansion. Removed or rewritten placeholders are not reconstructed, later
filters remain authoritative, and global spill settings are unchanged.
Admitted text remains available for later model calls in the same host turn,
including after reply, without retaining reply/ACK authority. Exact turn end or
plugin unload clears that view.

An admitted wake finishes locally when its exact host turn ends, even without a
reply. Missing or stale callbacks cannot release a newer wake; uncertain claim/ACK
state stays fenced. Serialization is local to one plugin process. Use status and
trace for uncertain outcomes rather than resending blindly.

## History and memory

<a id="session-history"></a>

The `post_llm_call` hook captures private, plain-text user/final-assistant snapshots
with stable host session, turn and message IDs. Duplicate callbacks do not create
duplicate sources or revive forgotten sources. Capture follows existing visibility,
redaction and forgetting rules. Hook observation is not proof of Hermes database
commit or delivery.

Each row supports up to 20,000 Unicode code points. Missing or ambiguous identity,
unsupported/multimodal/merged/hidden rows, mismatched callback text, oversized rows
and interrupted turns without the callback are skipped without truncation or
backfill. Synthetic wake user markers are excluded. Observed wake assistant
responses are labeled; provider context, tool output and Relay receipts are not
copied into the user row. Capture failure does not interrupt Hermes and has no
durable retry queue.

Use `pallium_search_history` for topic search or
`pallium_search_history_by_work_ref` with an exact known reference. Expand returned
sources with `pallium_expand_source`, passing the containing page's
`lookup_event_id` as `parent_lookup_id`. Follow returned offsets and revisions.
Work tags require a verified current-session association; failed reads omit them.
`actor_ref` and `source_thread_ref` are historical filters, not identity overrides.
Completion capture supplies no current `request_source_item_id`; do not invent it.

With memory enabled, source expansion can include supported memories and
`pallium_forget_source` is available. Its optional thread selector targets that
historical partition; omission keeps container-bounded behavior. Standard memory
query retains the configured actor filter; expansion follows canonical
same-container/matching-global visibility. Mutations use trusted profile and host
session provenance. See [Session History](../../docs/session-history.md).

## Update and removal

Repeat the setup command to update unchanged package-owned files, including
`--memory-enabled` if preserving that opt-in. Stop the target host and other
profile writers first. Remove unchanged package-owned artifacts:

```powershell
python -m app.run setup hermes --home C:\path\to\hermes-profile `
  --hermes-python C:\path\to\hermes-venv\Scripts\python.exe --uninstall
```

Repeating setup updates an unchanged owned installation. Edited owned files and
unowned collisions are refused. Removal restores the original `plugins.enabled`
state, removes this plugin's exact config entry and preserves unrelated nested
configuration, other plugins and data. A detected ownership conflict is not
permission to overwrite those files. Status checks fingerprints, not running-host
or live MCP readiness.

<a id="production-qualification-in-progress"></a>
<a id="native-qualification-limits"></a>
## Compatibility and troubleshooting

<a id="compatibility-and-limits"></a>

Hermes v0.22.0 and v0.22.2 have Linux TUI and Windows Desktop/TUI integration
coverage, with memory off and on. Admission uses public capabilities rather than
an exact-version lock. Other releases must retain compatible plugin identity,
hook, middleware and MCP interfaces.

Windows coverage uses Server 2025/unpacked builds, not Windows 11, MSIX, native
updater or native Quit qualification. Synthetic responses test integration
behavior, not paid-model quality or every provider/memory combination. Busy turns,
endpoint outages and controlled host/MCP relaunch are covered; automatic standalone
MCP reconnection, ordinary-turn fallback and uncertain claim recovery are not guaranteed. Shared Relay
availability can still return retryable busy errors.

Use Hermes's supported installation/update path. Dependency builds and Desktop
URL registration can escape a temporary profile: contributor qualification needs
a disposable OS environment, as described in
[native validation](../../docs/designs/hermes-native-qualification.md).

## Reference

- [Hermes integration workflow](../../docs/hermes-integration.md)
- [Session History search and expansion](../../docs/session-history.md)
- [Native validation and coverage boundaries](../../docs/designs/hermes-native-qualification.md)
