# Pallium — OpenCode integration

This plugin connects OpenCode sessions to the local Pallium service. It records
selected turns for Session History, delivers Relay messages on normal turns, and
supports optional derived-memory processing.

## Capabilities

<a id="what-you-get"></a>

### Relay

- send messages to another connected Pallium session through the MCP tools;
- receive attributed messages on the next normal OpenCode turn;
- reply to the sender and inspect delivery status.

The stable V1 plugin is passive: messages remain stored until the recipient's
next normal turn. An opt-in V2 adapter adds native queued wake delivery; its
qualification limits are listed below. It is a separate plugin entry and does
not replace an existing global V1 loader automatically.

> List Pallium Relay recipients, then send `@review`: "The API response
> still needs the legacy field."

### Session History

- record OpenCode user and assistant messages;
- search earlier sessions broadly with `pallium_search_history`;
- search one known exact work reference with `pallium_search_history_by_work_ref`;
- open nearby messages with `pallium_expand_source`.

> Search Pallium Session History for why we kept the legacy response field.

### Optional derived memory

The plugin can ingest turns, request compact memory, and inject selected results.
Failure and retry triggers remain opt-in. None of this is required for Relay
routing or deliberate Session History search.

## Prerequisites

- A running local Pallium service with the MCP endpoint enabled; see [Getting Started](../../docs/getting-started.md).
- OpenCode and a stable checkout containing the complete plugin directory.
- Choose V1 for passive normal-turn delivery or deliberately opt in to V2. This V2 native-wake path requires the context-message metadata API introduced in OpenCode 2.3.0. Compatible later releases must retain that contract; they are not automatically runtime-qualified.
- Historical combined V2 coverage is isolated Windows OpenCode 2.0.24. Earlier 2.2.7 evidence covers discovery only, not the recovery candidate below. Those scoped results and V1 passive delivery do not establish the current native-wake path on older hosts. Other platforms and global installation remain unqualified.
- Provider credentials are needed by Pallium only for optional derived memory, not Relay or raw History.

## Setup

<a id="install"></a>

### 1. Run Pallium

The plugin and MCP client use the local Pallium service on port `19836` by
default:

```bash
python -m app.run all --port 19836
curl http://localhost:19836/status
```

### 2. Add the plugin and MCP server

OpenCode needs both pieces:

- the plugin for automatic session registration, history capture, incoming Relay
  delivery, and optional derived-memory behavior;
- the Pallium MCP endpoint for Relay send/reply tools and deliberate Session
  History search.

Use exactly one Pallium adapter across all effective OpenCode configuration roots, including the default user, custom `OPENCODE_CONFIG_DIR`, and project roots; inspect each root for entries pointing to different physical copies. The upstream [V1 duplicate-loading report](https://github.com/Tencent/teamai-cli/pull/1405) has not been reproduced with Pallium, and V2 loading from multiple roots is unverified; when moving configuration, remove only an identified obsolete copy you control, with appropriate approval.

The stable V1 local loader uses the explicit plugin file:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["./integrations/opencode/.opencode/plugins/pallium.mjs"],
  "mcp": {
    "pallium": {
      "type": "remote",
      "url": "http://localhost:19836/mcp",
      "enabled": true
    }
  }
}
```

To opt in to V2 from a local checkout, use OpenCode's plural `plugins` directory
loader in a project configuration. This loads the package server entry exported
by `integrations/opencode/server.js`; keep the existing global V1 `plugin` entry
unchanged until you deliberately switch configurations. Do not load both adapters
in one OpenCode configuration.

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": ["./integrations/opencode"],
  "mcp": {
    "servers": {
      "pallium": {
        "type": "remote",
        "url": "http://localhost:19836/mcp"
      }
    }
  }
}
```

A relative plugin path is resolved from the configuration file. For a global
install, put the entry in `~/.config/opencode/opencode.json` and use a path that
reaches the checked-out plugin file.

The explicit `"plugin"` file entry is the stable V1 loading method. V2 uses the
plural `"plugins"` directory entry shown above. Keep the plugin files together
because each adapter imports its shared helper by relative path.

The `mcp` block follows OpenCode's
[remote MCP configuration](https://opencode.ai/docs/mcp-servers/). If Pallium
uses another port, change both the service command and MCP URL.

### Current-session MCP identity

OpenCode sends the invoking session ID in each MCP tool request's
`_meta["ai.opencode/sessionID"]`. Pallium uses that request-local value for
the current Relay address, work-reference list/attach/detach, and recovery
receive. Direct and Code Mode tools use the same identity path. No shared-server
`PALLIUM_AGENT_REF` or per-session `PALLIUM_THREAD_REF` is needed for this path.

The ID is correlation, not authentication or authorization. Keep the injected
container scope and existing permissions; Pallium does not derive scope from the
ID. Present malformed metadata or a conflicting configured runtime fails closed.
When this metadata is absent, existing intentional launcher configuration still
works; an unconfigured client fails rather than guessing a session.

Do not set one global session ID to repair a shared MCP connection. It would
identify the wrong conversation when several sessions use that connection.

### 3. Add the Pallium guidance

OpenCode reads `AGENTS.md`. Append this directory's
`<!-- pallium:start -->...<!-- pallium:end -->` block to a project or global
`AGENTS.md`. It explains when to use Relay, Session History, and optional
derived memory.

The plugin automatically registers the bundled `pallium-memory` skill and
`/pallium-memory` command. Their compatibility names remain memory-oriented, but
their guidance covers all three Pallium uses.

## Verify the connection

1. Check the configured service with `curl http://localhost:19836/status` (use your configured port).
2. Start OpenCode with exactly one Pallium adapter and confirm its MCP tools are available.
3. Ask for this session's Relay address. Exchange a short message and reply with another connected session; V1 needs a normal recipient turn.
4. Record a distinctive finding, then search and expand it in a later session in the same History container. Confirm returned text, not just successful registration.

## Delivery and recovery

<a id="v1-and-v2-relay-behavior"></a>

V1 uses the normal-turn `/relay/turn` path. Relay messages are included on a
natural OpenCode turn. V2 polls its native queue in process and asks OpenCode to
queue a native user input; the context hook adds the Relay content to the model
request. The receipt ACK only confirms attachment to model-bound context. It
does not mean the model completed the requested work.

Git discovery uses asynchronous native subprocesses with a 3-second per-command
timeout and a 1 MiB stdout byte limit. It shares Git facts within a callback, not
across sessions. Cancellation does not publish fallback identity or late pins.
This removes synchronous Git from the server event loop; it does not set an
aggregate hook-latency budget or guarantee descendant-process drain.
[Qualification run44046705214](https://github.com/rore/Pallium/actions/runs/44046705214)
at `29f9a602d687a76be779f69d6e76eb96c9ae8d86` passed strict4 baseline RED/candidate GREEN
and the full package: 241 cases, 234 passed, zero failures and seven existing
Windows skips. All45 required cases and the separate22 async cases passed unskipped.
The whole released OpenCode 2.3.0 journey passed all13 native checks and HTTP25,
including original payload non-replay before fresh input and four distinct NEW
automatic wakes.
Source11/binary bookends and normal/final owned drain passed. Real-child caller
tests establish Git responsiveness separately; they do not inject delayed Git
inside the released host. This is hosted qualification, not installed/loaded-host
recovery or downstream-task completion.

V1 deletion clears pending payloads and invalidates its original callback
lifetime before close. It retains one empty closed Map per deleted session ID
until explicit create/chat reactivation or plugin unload. This is O(distinct
deleted IDs), not globally bounded memory. Passive late callbacks cannot
reactivate a deleted ID or clean up its same-ID successor.

V2 can attach up to three deliveries in a wake, with the reserved trigger first
and a separate ACK for each attached message. If the claim response is lost,
continuation restores only the trigger. Unobserved siblings keep their original
leases and can be collected by an existing turn or wake once eligible.

### Coalesced wake settlement and recovery (hosted qualification)

V2 preserves its ordinary same-input terminal correlation. The native wake path
requires OpenCode 2.3.0 metadata APIs or compatible later releases. Exact CI
archive/version pins make evidence reproducible; they are not an exact user-version
lock or certification of every later release. Native idle covers the whole busy period,
including ordinary inputs steered in before idle. After the native wait, fresh
context must still contain the exact wake user ID, text, marker, generation and
delivery. The first later idle must have a distinct valid ID and outcome exactly
`succeeded`, `failed` or `interrupted`. The plugin rechecks its current session,
location, endpoint, container and generations before the existing terminal
request. The backend still checks the current owner and exact wake binding.
If the validated current snapshot already says `admitted: true`, the plugin
skips the redundant admission write but still waits and proves terminal state.
A sent or lost response never sets that flag locally. An unresolved false
snapshot keeps the existing admission path; this is not global one-shot deduplication.

This settles activation, not the requested business task. Failed or interrupted
work is not reported as successful. ACK, wait alone, elapsed time, an unknown or
outcomeless idle, and a missing wake input do not authorize this extra path.
No transcript or proof is stored. The plugin never prompts again merely to
reconstruct missing proof. A separate fresh-witness path can settle an absent
admitted anchor after compaction/reload, but only prospectively:

- The certified producer must have observed the exact native wake promoted
  before setting `admitted`. Queue acceptance alone is not admission proof.
- That admitted generation must already be known when a genuinely new ordinary
  prompt is first observed. The plugin freezes one session-lifetime relationship
  before awaits; delayed enrollment or an old manual/context row cannot create it.
- Until that SAME ordinary input is observed promoted, its absence means not
  ready. The existing poll rechecks the same candidate, without another prompt.
  After promotion, missing, changed or nonlatest input invalidates it.
- Outside hooks, native wait must finish through successors. Fresh raw context
  must show the same latest ordinary input and a later valid outcome-idle.
  After a fresh exact-generation backend poll and final native ownership read,
  a final raw read must confirm that SAME input and SAME selected idle before
  the existing fenced terminal request. It cannot select replacement evidence.

This witness is ephemeral. Compaction, reload, shutdown, move, revert, disposal,
duplicate input, binding changes or verification errors discard it. Loss of the
event subscription disables this path for that plugin lifetime. Old completed
manual turns cannot be blessed retrospectively. With no eligible fresh witness,
the anchor stays held even if a normal turn collects backlog. A lost terminal
reply is reconciled by normal polling, never by replaying the old payload.
Backend transactions fence backend changes; they do not create an atomic native
snapshot or undo an already committed request. Claim/ACK, expiry, original
delivery priority and continuation rules stay unchanged.

The bounded disposable Windows OpenCode 2.3.0 recovery witness passed at
[`d9ca9db8`](https://github.com/rore/Pallium/commit/d9ca9db82c1662ba25d33d4141c3ae4489a14354)
in [run43929918263](https://github.com/rore/Pallium/actions/runs/43929918263).
It was independently reviewed, accepted and merged in
[PR410](https://github.com/rore/Pallium/pull/410) as
[`9a885914`](https://github.com/rore/Pallium/commit/9a8859149581822354178f22f0836814aa1c14d1):

- Strict baseline 3 expected RED and candidate 3 GREEN were observed.
- Package 218: 211 passed, zero failed, seven existing skips; all 44 required cases passed.
- The native witness ran unskipped with all 13 checks true, including admission
  counts, ACK/payload checks, reload/compaction holds, fresh recovery, the original
  pre-U payload non-replay oracle and four distinct NEW sequential automatic wakes.
- Required HTTP 25/25 passed. Source/binary bookends and normal/final owned drain passed.
- Ordinary Python 3.13 completed 9,190 passed/106 skipped/2 xfailed. Python 3.12
  stopped early at 7,252 passed/1 failed/37 skipped/2 xfailed: initial registration
  returned 503 `relay_busy` instead of 200 before the association discovery/send/reply
  journey. Its immediate cause remains unknown; its later 3.12 assertions were not
  reached. The same test passed on 3.13. Relevant controls passed in both lanes,
  Windows smoke and governance passed, and the retained failure was accepted as
  nonblocking for this scope. Overall ordinary CI was not green.

All eight earlier qualification campaigns remain failed. The first two skipped native; the third failed
native with its predicate/cause still unknown. The fourth and fifth failed the
package and skipped native. The sixth passed the full package and ordinary CI
but failed the original-delivery prerequisite before its required native journey.
Its source follow-up found an uncorrelated provider-entry barrier and a 2.2.7
context projection that omits stored wake metadata. These are distinct source
concerns, not proof of the sixth run's exclusive cause. The seventh passed the
full package and ordinary controls but failed a session-list precondition before
Relay registration or the first send. Its exact failing conjunct/cursor value
remains unknown. Official 2.3.0 source shows that a next cursor is a resume token,
even on the final singleton page. The corrected fixture uses an unfiltered,
bounded short page instead. The eighth passed both full Linux lanes, Windows
smoke, controls and package, then failed the unchanged native admission-count
assertion: two successful admitted requests versus one terminal for the original
delivery. That does not prove duplicate native prompts or payload replay.
Later ACK/payload, reload/compaction, pre-U non-replay and four NEW wake checks
were not reached. The shared caller now guards known admission; the ninth
campaign's exact new regression RED/GREEN and full native journey passed as above.
Historical failures and
partial passes remain in the [result receipt](https://github.com/rore/Pallium/pull/410#issuecomment-6886277488).
Earlier 2.2.7 discovery-only evidence does not qualify settlement or recovery
after compaction. The later 2.3.0 witness does not certify other platforms, every
future release, installed recovery or downstream task success. Its four NEW
sequential wakes are not an earlier cumulative backlog latch or batched payload count.
Installed recovery and other findings remain open in the
[reliability feature](../../roadmap/features/fix-opencode-plugin-reliability.md).

V2 owns a short server lease and renews it while polling. Disposal retires local
hooks and the event stream, cancels ordinary integration requests, and fences
late native callbacks. Best-effort owner detach uses one 500 ms remote cleanup
window with at most four requests in flight; a later owner can enroll after the
lease expires if detach fails. Repeated disposal shares one result. Cleanup
attempts every hook and reports disposal failures rather than claiming success.
Client cancellation cannot undo a request the service already committed.
A closed session or changed container scope invalidates the old binding. If compaction removes a
queued native input before V2 can verify it, V2 does not guess that delivery was
admitted or queue it again. Relay keeps the item available for a later normal
turn after its claim lease expires. V1 remains the passive fallback when V2 is
not configured or its native wake cannot be verified.

## History and memory

Session History records selected user and assistant turns for scoped search and
expansion; it is not a complete OpenCode transcript mirror.

V2 assistant capture keeps the existing aggregate after the latest native user.
Every selected assistant must have a valid native message ID and a finite
`time.completed` marker. Empty text (including tool-only turns) and text over
20,000 UTF-16 units are skipped; a later completed tool-plus-text aggregate can
be captured. This is best-effort latest-user capture, without historical backfill.
Overlapping callbacks reserve the same scoped capture identity. Retries and
plugin reload reuse a full SHA-256 source key derived from agent, actor,
container, native session and the final selected assistant ID. Pallium's existing
source uniqueness resolves a committed write whose response was lost. Only a
valid single receipt under current native ownership marks the capture successful;
failed writes remain retryable.

Use `pallium_search_history` or an exact known work reference with
`pallium_search_history_by_work_ref`, then `pallium_expand_source` with the returned
page lookup lineage. Relay routes across containers on the same service; History
and optional memory still follow [visibility rules](../../docs/privacy-and-visibility.md).
Derived memory is optional and needs separate service configuration; the plugin
can query and inject selected results.

## Update and removal

Keep the checkout and its shared helper files at the configured path. For an
update, review the chosen adapter and reload the host after updating its files.
Switch V1/V2 deliberately; do not load both or silently replace a global loader.

To remove the integration, back up your configuration, close the affected host,
remove only the configured Pallium plugin entry, its `mcp.pallium` entry and the
Pallium guidance block you added. Preserve other plugins and guidance. Reload
OpenCode and verify Pallium is no longer loaded. This does not uninstall the
shared Pallium service or delete its History/memory data.

## Compatibility and troubleshooting

Use the V2 batching adapter and the Pallium service from the same approved
revision. Verify both revisions before loading the complete adapter directory
and enabling its wake callbacks. An older service rejects the new batch count.
Older adapters can still request one exact delivery from the updated service.

Existing combined ownership and capture qualification covers isolated Windows
OpenCode 2.0.24. This does not imply compatibility with every V2 release.
The isolated Windows E2E uses
`PALLIUM_OPENCODE_V2_BINARY` and a local mock provider. It verifies idle and busy
wakes, tool continuation across a Pallium restart after ACK, pre-claim retry,
OpenCode hard restart, service startup recovery, history capture and deletion.
It also reloads the production plugin while a claimed Relay response body is
withheld, verifies the retired callback sends no ACK or payload to the provider,
and verifies successor delivery after claim-lease recovery.

<a id="known-gaps"></a>

- V1 remains passive. The ownership/capture witness covers isolated Windows
  OpenCode 2.0.24; coalesced wake/recovery has the separate isolated Windows 2.3.0
  qualification above. Neither certifies all other releases/platforms or the
  global installation. Native admission and ACK do not guarantee interrupted task completion.
- Usage-audit population is server-owned after durable assistant ingestion.
- Compaction records the latest assistant turn but does not run a pre-compaction
  query.
- Session orientation runs on `session.created`, not on every resumed session.
- Git timeout and output bounds are per command, not an aggregate hook budget.
  The hosted qualification above adds no aggregate-latency or descendant-drain guarantee.
- There is no `pallium setup opencode` command. Plugin, MCP, and guidance setup
  remain manual.

For missing tools, check both the plugin path and MCP URL. For a pending
delivery, confirm which adapter is loaded and inspect Relay status/trace before
retrying an operation whose outcome is uncertain. A recorded send or native
queue acceptance is not proof that the payload reached context.

## Reference

### How the hooks map

| Pallium behavior | Claude hook | OpenCode adapter |
|---|---|---|
| Register and orient a session | SessionStart | `event` → `session.created` → optional orientation query |
| Record a user message | UserPromptSubmit | `chat.message` → `POST /item-and-query` |
| Deliver incoming Relay (V1) | UserPromptSubmit | `chat.message` claims deliveries → `experimental.chat.messages.transform` appends an attributed reminder → receipt ACK |
| Deliver incoming Relay (V2) | UserPromptSubmit | native queue poll → queued OpenCode input → model context injection → receipt ACK |
| Record an assistant turn | Stop | `event` → `session.idle` → read the last assistant message → `POST /items` |
| Optional failure/retry memory | PostToolUse | `tool.execute.after`, off unless `PALLIUM_POSTTOOL_TRIGGERS=1` |
| Preserve before compaction | PreCompact | `experimental.session.compacting` → `POST /items`, best effort |

Ordinary hooks fail open. A current, verified internal wake without Relay context
fails visibly before provider dispatch. An unproven or stale marker cannot claim
or register a session; it may leave an empty provider turn rather than abort
ordinary user work.
HTTP calls use a short timeout. Incoming Relay uses the message transform
because resumed sessions can discard system-transform additions.

Injection formatting and trigger behavior follow the same contracts as the
Python integrations. See
[the injection policy specification](../../docs/specs/2026-06-27-injection-policy-abstention.md)
for the optional derived-memory details.

### Files

```text
integrations/opencode/
|-- package.json
|-- opencode.json
|-- AGENTS.md
|-- README.md
|-- skills/
|   +-- pallium-memory/
|       |-- SKILL.md
|       +-- references/field-feedback.md
|-- .opencode/
|   |-- command/pallium-memory.md
|   +-- plugins/
|       |-- pallium.mjs
|       +-- pallium-common.mjs
+-- tests/
    |-- common.test.mjs
    +-- plugin.test.mjs
```

`pallium-common.mjs` is the OpenCode JavaScript copy of the shared integration
helpers. Each runtime keeps a self-contained adapter; parity tests compare their
observable behavior.

### Configuration

| Environment variable | Default | Meaning |
|---|---|---|
| `PALLIUM_PORT` | `19836` | Port used by the plugin's HTTP calls. Keep the MCP URL on the same port. |
| `PALLIUM_POSTTOOL_TRIGGERS` | unset | Set to `1` to enable optional failure/retry derived-memory triggers. |

Per-session deduplication and container-pinning state uses
`~/.pallium/hooks/state/`, the same format as the Python integrations.

### Tests

```bash
cd integrations/opencode
npm test
```

The suite covers container derivation, redaction parity, deduplication, session
pinning, injection budgets, turn extraction, hook behavior, and fail-safe
operation when Pallium is unavailable.
