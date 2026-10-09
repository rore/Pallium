# Operations

How the Pallium service runs and how to read its health. Machine-specific launch
details (paths, keys, restart commands) live in operator notes, not here.

## Service model

Pallium runs as a long-lived local service, independent of any one repo or agent
session. A supervisor process starts the HTTP **api**, the async **processor**
(ingest → memory), the **cleaner** (retention), and the **MCP** endpoint. State is
a main SQLite DB, an isolated Relay SQLite DB, plus an on-disk vector index.

The service is **trusted-local**: no auth layer. Identity fields (`container_ref`,
`actor_ref`, `session_id`) are for attribution and visibility scoping, not
authorization.

Codex and Claude hooks expose the host's active task as a compact injected
`thread_ref`; deliberate historical search and expansion must pass it so lookup
events can be joined to later work. It always names the requester, never the
historical source, and grants no access. If the host supplies no task identity,
Pallium leaves attribution absent rather than guessing or writing `unknown`. The
marker uses the existing injection character budget.

## Linux user service

The Linux implementation uses one `systemd --user` unit,
`~/.config/systemd/user/pallium.service`. The public
`pallium service install|status|start|stop|restart|uninstall` commands are the
lifecycle authority; the shipped `.sh` wrappers delegate to those commands
instead of generating a second unit form. Manager failures are errors, and
install, start, and restart return success only after `/health`, `/status`,
and `/debug/queue/health` are ready.

There is one Pallium unit per Linux user. Every lifecycle command must use the
same `--home`; installing a different home fails rather than silently
retargeting the unit. Uninstall preserves data by default. `--remove-data` accepts only the default home with its exact managed-home marker
written by install. Custom homes are always preserved and must be removed manually
after inspection; filesystem root and the user home are always refused.

Live qualification covers Ubuntu 24.04 under WSL2 with systemd enabled:
install, idempotent install, status, stop/start, restart, crash recovery,
occupied-port failure, missing unit, custom port, spaces/Unicode home, wrapper
delegation, uninstall, safe data removal, and named-distro restart. Linger is
not changed. When WSL stops the distro, the Linux service is also stopped; the
enabled unit starts and becomes ready when the Ubuntu user session starts
again. This is WSL qualification, not a live claim for every Linux distribution
or for macOS.

## Startup diagnostics

API startup has a bounded 120-second allowance per supervisor attempt. This is
an availability safeguard, not a startup performance target. Logs identify each
attempt and time storage setup, embedding initialization, vector loading, the raw
backfill check and lifespan initialization. A completed stage only means that
call returned; verify health and `embedding_provider_ok` separately. Delays before
these markers are not attributed by them.

## SQLite database operations

Both SQLite files use the same lifecycle: WAL, auto_vacuum=INCREMENTAL, and a bounded connection busy timeout. Relay writes use only the Relay file, so a long ingestion transaction in the main file does not hold the Relay writer lock. Each file must still be backed up, checked, and restored as a pair; never mix files from different snapshot generations.

Persistent `auto_vacuum` and WAL modes are initialized once under the schema lock on an autocommit connection. Pooled connections set only their bounded busy timeout before ordinary work. Incremental-vacuum/checkpoint maintenance temporarily fails fast and restores the connection's prior timeout, so a live reader defers truncation instead of holding a worker for the full busy window.

Only the current Relay schema is supported. Keep the main and Relay SQLite files together, back up and restore them as a paired snapshot generation, and verify /health, /status, and /debug/queue/health after service restart. A partial live pair or a database missing required current Relay columns fails closed without being rewritten.

### Main database work-reference projection

The main database owns `PRAGMA user_version`: legacy/fresh version 0 migrates to 1
with one atomic rebuild of `source_item_work_refs` from authoritative metadata.
The projection table/index, rows and completion mark commit together. Failure
rolls back that step; other schema initialization steps are not globally atomic.
Unknown versions and incompatible source/projection schemas fail closed.
Supported version 0 snapshots with the baseline source columns but no
`metadata_json` first add that nullable column through the existing structural
upgrade. Those column upgrades remain outside the atomic projection step.
Version 1 missing metadata, missing source IDs and legacy tables missing metadata
without the complete baseline still fail admission. Projection and repair require
both authoritative columns before deleting rows or marking completion.

Completed version 1 startup skips the metadata scan and projection rewrite.
A missing projection table is rebuilt atomically without resetting the version;
a missing lookup index alone is restored without rebuilding rows. Supported
metadata updates and retention still maintain the projection incrementally.
Out-of-band metadata/row edits no longer receive automatic repair on reopen.
The existing private `_backfill_source_item_work_refs()` repair remains explicit,
unconditional and version-preserving; this introduces no public repair command.

Separate Relay database versions/rows are not migrated by this main step.
Ordinary Relay startup maintenance can independently change its schema identity
(for example, by initializing planner statistics) and invalidate a repair manifest.
A same-file deployment shares the changed header: prior offline repair manifests
become stale and must be regenerated through the existing stopped procedure.
Do not bypass their identity fence. Earlier binaries retain schema compatibility
but resume their old unconditional rebuild; they do not reset version 1. This
release rejects unknown future versions rather than promising arbitrary downgrade.
Installed rollout separately requires approved paired backup, version provenance
and compatibility checks, qualified restart, and an exact rollback path. A repo
merge or passing private test does not authorize an installed database migration.

## Relay control-plane resilience

An enrolled Codex Desktop MCP child may reconnect automatically after the service
restarts while that same child and Desktop identity remain alive. Recovery repeats
the native identity/catalog checks and keeps every durable delivery fence; it does
not replay tool calls or messages. Startup-only retries stop after 12 attempts or
five minutes. Changed capability/identity, unsafe bootstrap, unresolved I/O and
explicit shutdown stop automatic reconnection. A new child still needs an actual
authenticated request to enroll. Existing MCP children do not reload Python code
on service restart: qualify an updated worker using a normally reloaded dedicated
child, never by interrupting active user chats or treating service health as
delivery evidence.

`/status` and the Relay summary expose `relay_wake.native_enrollment` as cached
lifecycle evidence from this service instance. `never_registered` means no
registration was accepted in this instance; `registered`, `retained_disconnected`,
`authority_cleared`, `unresolved_handles`, and `released` describe the last
observed lifecycle state. `unavailable` means the service snapshot is missing,
malformed, or its cached evidence was lost while an outcome remained unresolved;
it does not imply that registration was never accepted. These fields do not probe native handles, prove reachability, identify
the live owner, or establish the loaded worker version. Continuity opt-in records
the registration protocol used. The last failure stage and reason are fixed
categories and may describe an older event after cleanup.

A slow native delivery may cause another registration to return authenticated
`busy`. An already admitted, unchanged live source keeps its checked connection
and previous caller, without retrying the registration. Busy does not enroll a
new source or qualify restart recovery; other failures still fail closed.

Cancellation during initial readiness, before any registration is attempted,
does not reserve the native admission slot indefinitely. A live request already queued may use the
existing ready channel; otherwise an idle, never-used resolved channel closes
without stopping its worker. A fresh request arriving during cleanup may use
constructor-only retries within a one-second window under the same trusted service
bootstrap and runtime capability. Readiness, registration and tool calls are
not replayed; ordinary first acquisition still has no retry, and uncertainty or
identity changes fail closed. This lifecycle repair is not evidence of installed
delivery or a historical outage's cause.

For operator-owned native qualification only, the installed
`scripts/qualify_codex_relay_faults.py` supports `install`/`restore` with explicit
`--hooks-dir` and `--control-dir`. Provision a fresh case directory outside the
checkout and verify user/SYSTEM/admin-only ACLs before install; the helper does
not set ACLs. Record configured hook/helper paths, original/config hashes and
existing hook ACLs. Installation wraps only the two named hook files, keeps the
configuration unchanged, matches the exact recipient session and preselected
message ID from real claim responses, and expires its one-shot fault. Restore
both original hashes and unchanged configuration before teardown; retain each
case's private backups/evidence and never reuse its control directory. The modes
are `claim-response-loss`, `ack-precommit` and `ack-response-loss`; the last drops
only a confirmed delivered ACK response. None proves a notification lost before
the hook runs, and no manual recipient turn/receive qualifies as automatic recovery.

The opt-in `observe` mode uses the same private case and restoration controls,
but injects no fault. It reserves the first eligible exact-session turn before
claiming, then records whether the preselected message was actually observed.
Only stage outcomes/timing and a validated matching delivery ID are captured;
no payloads, tokens, arguments or exception text enter its ledger. Capture is
capped at 64 events/16 KiB; after restoring references it waits at most 50 ms for
a best-effort daemon append. A `captured` terminal marker describes the bounded
sequence and restoration, not file durability, host receipt or model consumption.
Missing/truncated evidence or `incomplete` is not success; target absence does
not prove the target was claimed. Use a fresh case and retain its evidence.

Relay storage calls use a four-operation AnyIO capacity limiter independent of the
default synchronous route pool, and `/health` stays on the event loop. Client
cancellation does not cancel an already-running SQLite operation; service shutdown
waits for active Relay operations before closing either database. Slow and busy
server operations log only the static operation name, outcome, and duration. Hook
client failures log method, fixed path, duration, and exception type; no payload or
scope identifiers are logged.

Relay MCP clients retry connection establishment failures and structured `relay_busy` responses within one bounded attempt/time budget for reads and explicitly idempotent send, reply, and acknowledgement operations. Read, write, protocol, cancellation, and ambiguous post-acceptance failures are not retried. Exhausted transport and HTTP failures are returned as bounded, redacted MCP tool errors (`isError=true`), not successful string payloads.

Claude Code and Codex hooks persist each exact Relay scope-transition intent before HTTP and serialize registration under the existing per-session lock. `/relay/turn` moves only the supplied endpoint from the supplied source generation; retries recognize exactly one committed generation step. No global session inference or destination takeover occurs. Endpoint aliases, work references, pending/claimed deliveries, and delivery audit snapshots survive a confirmed move. ACK wake rearm resolves the endpoint's live scope rather than the delivery's historical scope snapshot.

The service reconciliation loop scans eligible never-claimed pending deliveries and
expired claims at startup and every 30 seconds, then dispatches through the existing
runtime adapter without claiming early. Codex confirmed or ambiguous native wake
submission keeps the oldest per-session trigger behind a durable fence; native
queue writes are never retried blindly. Retained Codex recovery may issue a new
notification for a never-claimed pending delivery or an expired unacknowledged
claim after its persisted
60-second cooldown when a fresh authenticated Desktop read reports the current
exact target idle or notLoaded and the database generation check still sees no
active claim. Uncorrelated SessionStart claims qualify only after lease expiry;
committed ACKs remain terminal even when their response is lost. Busy or unavailable targets stay pending for a later sweep. A
large backward wall-clock correction clamps the deadline once to one cooldown.
Exact ACK, MCP ACK, or atomic reply releases that delivery's durable ownership. Startup
and send-time reconciliation remove only missing deliveries or exact
endpoint-matching terminal reservations; pending, active claims, endpoint
mismatches, and uncertain reads keep their fences. Service restart reloads those
durable reservations before reconstructing pending work, preventing blind
resubmission of accepted or uncertain prompts. Current Codex fences and their
generation high-water are stored in the resolved Relay SQLite database. The
old `reservations.json` is read only during one offline import: a conventional
`data/pallium-relay.db` uses its parent home's `codex-wake` directory, while
other files use a sibling `<full-database-filename>-codex-wake` directory.
`PALLIUM_CODEX_WAKE_DIR` overrides only that legacy import source. Completed
migration ignores the leftover file, which remains unchanged. In-memory apps
keep their fences in their app-owned ephemeral Relay database. Never copy
reservations between instances. Claude wake capabilities and intents follow
the same Relay-database ownership pattern: conventional `data/pallium-relay.db`
uses the home `claude-wake`, other files use
`<full-database-filename>-claude-wake`, and in-memory apps are nonpersistent.
Claude setup pins its hook port, Relay identity, and wake path. Re-run setup after
changing the target; a mismatched service marker fails closed before credential
write-ahead, while an outage keeps the pinned path. Never share
`PALLIUM_CLAUDE_WAKE_DIR` across different Relay databases. An exact
internal Codex wake is excluded from deduplication and memory ingestion. If its hook
cannot recognize or complete the wake, including when the host skips or terminates
the hook, the native prompt can remain model-visible without a delivery block.
Only a delivery-specific wake with a successfully parsed delivery ID supplies
that ID for nonmutating trace inspection. Ordinary user
prompts remain fail-open. Once an exact wake is recognized, any exception or failed
payload/block write before successful emission exits with Codex's blocking signal
(exit 2), without ACK or memory ingestion. The stderr reason is best effort;
stderr write/flush errors do not change exit 2, but a blocked pipe or host
termination can prevent completion. A claimed delivery remains lease-recoverable.
Successful emission still precedes ACK.

This protects concurrent users inside the supported single-owner, single-Uvicorn-process
service. SQLite serializes current-fence transitions; the native initiation guard
remains process-local. Horizontal native wake ownership is not qualified.

### One-time Codex wake store upgrade

Fresh `service run`, `serve`, and `all` launches initialize an empty SQLite authority
automatically under the existing owner lock, before starting children. Both database
files and the legacy source must be conclusively absent. Ordinary app startup never
imports an existing store. Reinstall refuses an unmarked store before replacing its
old launcher/unit metadata.

On Windows, `scripts/restart-service.ps1` drains and verifies the installed old tree,
imports and verifies wake state using the installed interpreter/home, then starts
the service. `-StopOnly` only stops and verifies. Failed drain/import/verification
leaves the service stopped. On Linux, use the same installed home for the one-time
offline sequence:

```sh
pallium service stop --home /path/to/pallium-home
pallium service initialize-wakes --home /path/to/pallium-home
pallium service start --home /path/to/pallium-home
```

For a foreground deployment without an installed service, stop all API/supervisor
owners and native wake workers first, then run `pallium service initialize-wakes
--home /path/to/pallium-home --foreground-quiescent`. That option is an explicit
operator declaration of quiescence, not process detection. The supported owner lock
does not exclude another home pointing at the same database or an unsupported old
binary started concurrently. Do not mix old file owners and new SQLite owners.

The atomic import preserves reserved, accepted, uncertain, generation and exact-claim
correlation fences. Corrupt/unreadable/conflicting legacy state refuses migration;
repair the source while stopped before retrying. Back up the paired databases and
legacy source before upgrade. After SQLite-owned attempts exist, prefer a forward
fix. Downgrade requires quiescence and reconciled state export; never launch an old
file-only binary against the stale leftover JSON. Verify `/health`, `/status`, and
`/debug/queue/health` after the supported service start/restart.

## Developing integrations without leaving stale local installs

Claude Code and Codex setup commands write absolute checkout and Python paths into the
host's MCP and hook configuration. The stable OpenCode global loader likewise points
at the explicit V1 plugin file. Treat a temporary worktree as a build/test location,
not as the long-lived installation source.

OpenCode V1 remains passive and receives Relay on a natural turn. V2 is a separate,
opt-in adapter for OpenCode 2.0.22, loaded through the plural `plugins` directory
entry in a project config. It queues native input in process, adds Relay context to
the model request, and ACKs with the receipt when that context is attached; the ACK
does not report task completion. Keep the existing global V1 loader as-is unless
you intentionally switch the installation. Never load V1 and V2 together.

V2 renews a short owner lease while polling and detaches when its plugin is disposed.
After owner expiry, a later V2 instance can enroll again. A closed session or moved
container scope makes the old binding stale. If native compaction leaves admission
uncertain, V2 does not re-insert an input it cannot verify; a later normal turn
can receive the delivery after its claim lease expires. Unproven stale marker
inputs cannot register or claim; they may leave an empty provider turn. A live
owner lease proves registration, not native idle/busy status, so availability
remains unknown. Isolated Windows native V2 E2E passed with released 2.0.22 through
`PALLIUM_OPENCODE_V2_BINARY`, including Pallium restart after ACK before tool
continuation, native hard restart and service startup recovery. This does not
qualify the current global V1 installation or interrupted task completion.

When moving an installation from a worktree back to the primary checkout:

1. Preserve dirty work in a named stash or branch, restore the primary checkout
   to clean, current `main`, and keep the old worktree until migration finishes.
2. For Claude Code, run the uninstaller **from the old checkout's working
   directory**, then run setup from the primary checkout; its hook removal is
   path-specific. Current Codex setup repairs missing old sources automatically
   but refuses to replace hooks from another live checkout without explicit
   intent. For a deliberate Codex move, run setup from the destination checkout
   with `--replace-existing-checkout`; this reconciles stale registrations and
   repoints its MCP server. With older Pallium versions, uninstall Codex from
   the old checkout first.
3. Confirm Claude's MCP plus hooks and Codex's MCP, hooks, and
   `pallium-relay.config.toml` contain only primary-checkout paths. Confirm the
   OpenCode config still registers its loader, the loader points to the primary
   plugin, and its MCP URL uses the installed service port.
4. Restart already-open agent hosts when their MCP or hook configuration must be
   reloaded. New sessions use the new installation; existing MCP subprocesses
   can keep the old executable until their host restarts.

Changing integration or service code normally requires updating the stable
checkout and restarting the installed service, not reinstalling its scheduled
task. On Windows, always use `scripts/restart-service.ps1`. It validates the
registered VBS, interpreter, optional working directory, configured port, and
`app.run` imports before stopping a healthy process tree. After launch it reports
success only when `/health`, `/status`, and `/debug/queue/health` satisfy their
documented readiness contracts; failures name the last check and Pallium log.
Queue health is a live database query and may use up to ten seconds; health and
status remain capped at two seconds, and every request is clipped to the one
overall readiness deadline. The default readiness budget is three minutes; an explicit
`-ReadinessTimeoutSeconds` value keeps its exact finite deadline.

Generated Windows VBS launchers keep the service hidden, wait for its termination,
and return its exit status to the script host. Fatal supervisor recovery exhaustion
is a failure; requested shutdown is successful. Existing launchers are not rewritten
by source updates or restarts. A launcher-generation change therefore needs a
separately approved regeneration of the installed launcher/task, with its metadata
backed up and rollback available. Verify the actual installed task's lifetime and
failure status before claiming Task Scheduler recovery; private script-host tests
and successful service health checks do not establish that result.

For offline Relay endpoint repair, first start the upgraded service once so it creates the repair ledger, then run `scripts/restart-service.ps1 -StopOnly`. The wrapper stops the installed task without starting it again and fails if the task, listener, or managed process tree cannot be conclusively drained.

Create a disposition file that classifies every live repairable delivery on the source endpoints: pending deliveries plus claimed deliveries whose finite lease has expired. An expired claim may only be `suppress`; `adopt`, active claims, missing claim tokens, and missing or malformed leases fail closed.

```json
[
  {"delivery_id": "relay-delivery-...", "disposition": "suppress"},
  {"delivery_id": "relay-delivery-...", "disposition": "adopt"}
]
```

Generate the review manifest against the installed Relay database. Supply the service and hooks' exact effective Claude wake directory explicitly; never infer it from the service home. Supply every same-runtime/session source, the one destination, and each endpoint's exact current scope:

```powershell
python -m app.tools.relay_endpoint_repair --dry-run `
  --home "$env:USERPROFILE\.pallium" `
  --db-url "sqlite:///$env:USERPROFILE/.pallium/data/pallium-relay.db" `
  --manifest .\relay-repair.json `
  --claude-wake-dir "$env:USERPROFILE\.pallium\claude-wake" `
  --dispositions .\relay-dispositions.json `
  --source relay-session-... --scope relay-session-...=git:old-a `
  --source relay-session-... --scope relay-session-...=git:old-b `
  --destination relay-session-... --scope relay-session-...=git:destination
```

Review the complete endpoint/message/delivery preimage, reservation evidence, dispositions, and printed SHA-256. Version 2 manifests replace a claim token with a domain-separated SHA-256 fingerprint; the raw token is never written to the manifest or repair ledger. Canonical SQLite UTC-naive lease timestamps are interpreted as UTC. Codex wake history is process-local, so historical Codex deliveries remain `unknown` and cannot be adopted; use explicit `suppress` only after confirming the work is duplicate or will be resent. Claude adoption is allowed only when the installed durable capability and intent stores are valid, unchanged, and clean for that exact delivery/session/scope.

Apply only the reviewed file and exact digest:

```powershell
python -m app.tools.relay_endpoint_repair --apply `
  --home "$env:USERPROFILE\.pallium" `
  --db-url "sqlite:///$env:USERPROFILE/.pallium/data/pallium-relay.db" `
  --manifest .\relay-repair.json `
  --acknowledge-digest <sha256>
```

An identical committed retry returns the ledgered result. Any database, endpoint, TTL, claim lease/token fingerprint, inventory, or wake-evidence drift refuses before delivery mutation; rerun dry-run and review a new digest. Repair never merges endpoints: alias sends still route to the destination, exact sends/replies to a source still route to that source, and occupied scopes remain occupied. When finished, restart with `scripts/restart-service.ps1` and verify `/health`, `/status` (including `embedding_provider_ok`), and `/debug/queue/health` on the installed port.

The installed launcher must use a dependency-complete Python and the supported
`python -m app.run service run --port <port>` path: `service run` applies the
managed `~/.pallium/config/.env` and service configuration. Do not use the
deprecated `scripts/install-service.ps1` merely to repoint development code or
run a service from a temporary worktree.

After any migration, verify the actual installed state rather than trusting
setup output:

- primary checkout is clean `main` at `origin/main`
- no host config or service launcher refers to the retired worktree
- `claude mcp get pallium` reports connected
- `codex --profile pallium-relay mcp list` resolves Pallium
- the OpenCode plugin suite passes from the primary checkout
- `/health`, `/status`, and `/debug/queue/health` respond; specifically check
  `embedding_provider_ok` and `ingestion.status`

## Health signals

Two endpoints report liveness. Read them together — a 200 alone does not mean
fully functional. `/health` is the liveness endpoint (always available);
`/status` provides diagnostics and is **SQLite-only** — it returns HTTP 501 when
another storage backend is configured.

| Endpoint | Field | Meaning |
|----------|-------|---------|
| `/health` | `status: ok` | Lifespan complete, vector index ready (or intentionally off). |
| `/health` | `status: initializing` (503) | Still starting — schema initialization / vector load in progress. |
| `/health` | `status: degraded` (200) | Reachable but **impaired**: vector was expected but the embedding provider failed to initialize. See `degraded_reasons`. |
| `/status` | `vector_expected` | Config intends vector search to run. |
| `/status` | `embedding_provider_ok` | `false` = vector expected but the embedding provider did not load. |
| `/status` | `ingestion.status` | `degraded` = an enabled package declares a provider credential that did not resolve. `issues` names the package, provider, and configured environment-variable name, never the secret. |

`degraded` stays HTTP 200 on purpose: the service is functional (lexical retrieval
still works), so orchestration should not hard-fail. The signal is the `status`
and `degraded_reasons` fields, and the dashboard badge turns non-green.

## Ingestion credential readiness

A declared `api_key_env` or `api_key_file` that resolves to no value makes
`/status.ingestion.status` degraded and the dashboard non-green. The service
keeps Relay and inspection available but starts with ingestion workers paused, and
points to the managed `.pallium/config/.env` file. Once the credential is
repaired and the service restarted, terminal items do not retry by themselves; use the
loopback-only `POST /debug/queue/retry-failed` operation for the matching
failure category.

## The embedding-provider gotcha

The most common silent degrade: vector search is enabled in config, but the
runtime the service launched under is missing the embedding provider's native
dependency (e.g. `onnxruntime`). The provider fails to initialize, the vector
index is never built, and **semantic search is silently disabled** — lexical-only
results, often near-empty for conceptual queries.

Before this signal existed, `/health` and `/status` stayed green in that state.
Now `embedding_provider_ok` goes `false` and `/health` reports `degraded`.

**When search returns too little:** check `embedding_provider_ok` first. If it is
`false`, the fix is the launch environment (install the embedding dependency into
the runtime the service actually uses), not the query or the data.
