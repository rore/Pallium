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
session-bound tools. Memory tools are optional. Service-selected recall during
user capture runs independently of the tool catalog.
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
- Use a running local Pallium service. Normal setup requires session-owned cwd,
  surface and bound-route APIs and derives project/actor from the exact session's
  local cwd. The native injection route is separate from the Relay/History
  conversation ID. Private visibility is the default and only accepted value.
- The service must confirm guarded lifecycle enrollment and support conditional
  closure for automatic mode. An older service is refused before capture; the
  plugin never falls back to an unconditional close. Update the service using its
  normal installation procedure; profile setup does not upgrade it.
- Keep the Pallium checkout at a stable path; the bridge configuration contains
  absolute interpreter and checkout paths.

Stop the target Hermes host and other profile configuration writers before
install, update or removal. The installer uses Hermes's public config writer and
checks ownership fingerprints, but the native writer has no atomic compare-and-swap
against simultaneous external edits. After an uncertain config write, inspect
the preserved configuration and reported conflict before retrying.

## Setup

<a id="install-inspect-and-remove"></a>

From the Pallium checkout, replace the example paths with your values:

```powershell
python -m app.run setup hermes `
  --home C:\path\to\hermes-profile `
  --hermes-python C:\path\to\hermes-venv\Scripts\python.exe `
  --service-url http://127.0.0.1:19836 `
  --mcp-python C:\path\to\pallium-venv\Scripts\python.exe `
  --mcp-repo C:\path\to\Pallium
```

`--mcp-python` defaults to the current Pallium interpreter; `--mcp-repo` defaults
to its checkout. Pass them explicitly when your environments differ.

Normal setup records `scope_mode: cwd`; container and actor flags are unnecessary.
Git origin, root commit or local path supplies the initial project; actor identity
comes from project Git identity or `local`, subject to an explicit actor override.
Recognized Git project changes require exact Relay transition admission. Pending
deliveries stay bound to their recorded recipient project; a new project cannot
claim the old project's queue, while the old project can claim on return before
expiry. Authorized cross-project sends remain supported. A transient valid
non-Git cwd retains the prior project, while actor identity follows the current
cwd's Git identity or `local` unless an explicit profile or environment override
applies. Invalid or unavailable session cwd is refused, never replaced with a
process cwd or another session's directory.

For an intentional fixed-scope compatibility installation, add both
`--container-ref git:example.test/team/project` and `--actor-ref developer`.
This assigns that explicit project/actor to the whole profile. It is not normal
project resolution or a fallback when session APIs are missing. Configuration
without an explicit scope mode must be refreshed through setup. When updating an
intentional fixed-scope installation, repeat both flags to retain that choice;
omitting them selects normal cwd mode and its capability checks.

Memory tools are disabled on new installations. Add `--memory-enabled` to opt in;
ordinary updates without either memory flag preserve the existing selection.
`--no-memory-enabled` explicitly disables it. The catalog adds eleven memory
query/write tools. It is separate from service-selected recall and semantic
package configuration.

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

One plugin-owned SDK1 transport carries immutable session/turn/project/actor
metadata on each call. It does not bind concurrent sessions through a shared
mutable project. Background polling uses saved exact session records.

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

`on_session_end` completes a host turn; it does not mean conversation deletion.
Native finalize is advisory: it does not change Relay binding, wake or close the
endpoint. Only native delete with reason `delete`, explicit exact profile and
session IDs, and committed permanent lineage retirement may conditionally close
the saved endpoint and generation. Archive, prune, sweep, profile repair and
missing or unknown reasons do not authorize closure. Finalize, soft delete or
deletion without a matching notification can leave endpoint presence and pending
messages according to their existing expiry. Current lifecycle coverage is in
the native validation reference below.

## History and memory

<a id="session-history"></a>

In normal cwd mode, the plugin captures supported raw user text before inference through
`/item-and-query`. Its source identity uses the observed profile/project/session/
turn/role, independent of text or a later durable host message UID. Confirmed user
capture can survive an interrupted turn. The completion hook captures supported
final assistant text with its host message identity and reuses the observed-turn
identity for user text. Duplicate
callbacks do not revive forgotten sources. Capture follows existing visibility,
redaction and forgetting rules. Hook observation is not proof of Hermes database
commit, durable message identity or delivery.

Each row supports up to 20,000 Unicode code points. Missing or ambiguous identity,
unsupported/multimodal/merged/hidden content, mismatched callback text and oversized
rows cause capture to skip without truncation or backfill. Assistant capture requires a
completion callback. Synthetic wake user markers are excluded. Observed wake assistant
responses are labeled; provider context, tool output and Relay receipts are not
copied into the user row. Capture failure does not interrupt Hermes and has no
durable retry queue.

Use `pallium_search_history` for topic search or
`pallium_search_history_by_work_ref` with an exact known reference. Expand returned
sources with `pallium_expand_source`, passing the containing page's
`lookup_event_id` as `parent_lookup_id`. Follow returned offsets and revisions.
Eligible branch and Work Record origins are discovered from the session project
and admitted with Relay. Capture copies admitted current-session work references;
unavailable associations can leave exact-work coverage incomplete.
`actor_ref` and `source_thread_ref` are historical filters, not identity overrides.
Confirmed user capture supplies `request_source_item_id` automatically to History
search through trusted metadata. Do not supply or guess it.

With memory enabled, source expansion can include supported memories and
`pallium_forget_source` is available. Its optional thread selector targets that
historical partition; omission keeps container-bounded behavior. Standard memory
query retains the session actor filter; expansion follows canonical
same-container/matching-global visibility. Mutations use trusted project and host
session provenance. Service-selected `injectable_blocks` can also supply recall
during user capture, independently of the tool opt-in. Recall is bounded to 2,400
code points and marked as lower-authority reference data. Semantic packages are
disabled by default; provider-backed processing requires an explicit provider
and model. See [derived memory](../../docs/derived-memory.md) and
[Session History](../../docs/session-history.md).

## Update and removal

Repeat the setup command to update unchanged package-owned files; ordinary updates
preserve the memory-tool selection. Stop the target host and other
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

Automatic mode requires session-owned cwd, surface and bound-route capabilities.
Admission checks public capabilities rather than a release allowlist;
older hosts without automatic-scope APIs can use intentional fixed-scope
compatibility setup. Missing capabilities fail with actionable diagnostics;
Pallium does not force a host upgrade or silently choose fixed scope.

Fixed-context wake routing on the newer shared Gateway remains unqualified and
unresolved.

Windows coverage uses Server 2025/unpacked builds, not Windows 11, MSIX, native
updater or native Quit qualification. Synthetic responses test integration
behavior, not paid-model quality or every provider/memory combination. Automatic
standalone MCP reconnection, ordinary-turn fallback and uncertain claim recovery
are not guaranteed. Shared Relay availability can still return retryable busy errors.

Use Hermes's supported installation/update path. Dependency builds and Desktop
URL registration can escape a temporary profile: contributor qualification needs
a disposable OS environment, as described in
[native validation](../../docs/designs/hermes-native-qualification.md).

## Reference

- [Hermes integration workflow](../../docs/hermes-integration.md)
- [Session History search and expansion](../../docs/session-history.md)
- [Native validation and coverage boundaries](../../docs/designs/hermes-native-qualification.md)
