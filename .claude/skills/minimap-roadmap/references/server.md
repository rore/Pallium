# Server Lifecycle

Use the bundled scripts only. The skill is self-contained; the scripts handle every state correctly across platforms (Windows signal limitations, TIME_WAIT, race-against-another-launcher, stale registry).

## Local trust boundary

The server binds to IPv4 loopback (`127.0.0.1`) only. Every API request must come from a loopback peer and carry a loopback `Host`; when a browser supplies `Origin`, it must exactly match that request origin. Foreign origins are rejected before route work, while origin-less local CLI and lifecycle requests remain supported.

## Lifecycle commands

| Command | Exit codes | What it does |
| --- | --- | --- |
| `node <skill>/scripts/start-server.mjs` | 0 = running (started or reused); 1 = incompatible/unknown API, settings mismatch, or occupied port | Probe the registry and live `/health`; reuse only a compatible API with matching participant settings. |
| `node <skill>/scripts/status.mjs` | 0 = running; 1 = stale registry; 3 = not running | Print live identity, registry port/startedAt, and local lifecycle log path/recent evidence, including when stale or stopped. Legacy identity prints unknown. |
| `node <skill>/scripts/stop-server.mjs` | 0 = stopped (or was already not running, or stale cleaned); 1 = shutdown failed | `POST /api/shutdown`, wait for the port to free. |
| `node <skill>/scripts/restart-server.mjs [--replace-runtime]` | 0 = restarted; 1 = refusal, stop, start, or verification failure | Preflight registered/requested targets before any stop; default permits only the same runtime. Serialize per home, then stop/spawn and verify the child-reported port/identity/configuration. Failed cleanup targets only its own child PID. |

Exit codes follow `systemctl` conventions for `status` (0/1/3 = running/stale/not-running).

## Local lifecycle diagnostics

The common server entry records startup identity (PID/parent PID, runtime source/version, port and known launch mode), graceful shutdown reasons, observed exit codes, and sanitized startup/cleanup/fatal errors under the resolved `$MINIMAP_HOME`. Foreground starts and detached restarts use the same logger. `server-lifecycle.jsonl` rotates at 128 KiB to one backup, `server-lifecycle.jsonl.1`, with a 4 KiB event limit. `status.mjs` shows the path and the last eight retained events without changing its exit codes.

These local records contain no request bodies, roadmap/spec content, environment dump, raw stderr or arbitrary error messages. Error evidence retains only recognized native class/code and up to five runtime-relative JavaScript source locations. Message detail is deliberately lost to avoid storing private content or credentials. The fatal monitor is observational: errors still terminate normally and normal stderr is unchanged. Logging I/O failure cannot block startup or shutdown.

Historical events are not proof of the current failure's cause. A verified live PID does not receive a missing-exit warning. Forced termination (including Windows hard kills/job teardown) and failures before the logger loads may leave no final event; missing exit evidence means **unknown**, not a diagnosed crash. Concurrent launch races can lose rotation evidence or briefly exceed the rotation threshold. This is bounded best-effort diagnostics, not telemetry, a watchdog, or a guarantee of recovery.

## Discovery

`start-server.mjs` reads `$MINIMAP_HOME/server.json` and probes `/health`. A compatible running API is reused even when package versions or runtime sources differ. Unknown/legacy or incompatible API identity is refused without shutdown or saved preference changes. The same checks apply to a race winner on the requested port. Both skills share one registry/server across repositories.

## Shared runtime replacement

Health reports `runtime: { version, apiCompatibility, sourcePath }` and live `pid`. API compatibility is integer 1; it changes only for incompatible server API changes, independently of package release versions.

Routine restart requires both the running version and canonical real server source path to match this launcher's bundled runtime, and the live PID/port to match this home's registry. An unregistered requested-port server requires explicit replacement even with matching runtime identity: the same copy can serve another home. Version alone cannot distinguish development checkouts or installed copies. Editing code in place at the same path/version remains routine; this is location identity, not content attestation. Separate copies require explicit replacement even when their bytes match.

If restart refuses, inspect its running/requested version and source, coordinate with anyone using the shared board/spec server, then use `node <skill>/scripts/restart-server.mjs --replace-runtime` only when replacement is intended. This flag allows a different, incompatible, older, or unknown runtime to be replaced; it is not an automatic upgrade and interrupts all clients of that server. Explicit `stop-server.mjs` remains an intentional shared shutdown, not a version upgrade shortcut.

Restart checks every registered/requested target before any shutdown, does not sweep unrelated adjacent ports, and sends the live PID guard when available. Legacy servers cannot offer the new ownership guarantees. Update each relevant installed skill folder using the existing copy-in installation method (or its checkout link); old launcher copies cannot be retroactively protected. Updating files alone does not replace a running server.

## Multi-repo

The server is repo-agnostic. Roadmap requests carry the repo chosen by the UI's `#repo=...` URL hash in `X-Minimap-Repo`, or in `X-Minimap-Repo-Encoded` for paths that cannot be sent as an ASCII HTTP header. One server can serve any number of repos at once.

The browser's **Across worktrees** board reads `GET /api/worktree-workspace` for the opened repo. Its source-specific requests use `/api/source/...` plus the returned `X-Minimap-Source-Context`; the server rechecks the live Git checkout and roadmap location, and source-bound item/board/scope writes require `expectedRevision`. Source-bound spec paths cannot escape the checkout. The UI uses `X-Minimap-Repo-Encoded` for non-ASCII paths when needed. Do not construct or reuse a source context from a guessed path, stale response, or another repo. This is a UI safety boundary, not a new agent roadmap-editing workflow: agents continue to edit only their assigned checkout's canonical files and do not automatically copy changes across worktrees.

The source menu separately reads `GET /api/worktree-sources`: this lists discovered Git checkouts without roadmap parsing, ancestry aggregation, or participant lookup. Cached choices are discovery evidence only. Opening a choice uses `GET /api/worktree-source-workspace` with that identity in `X-Minimap-Source-Context` and its repository header; the response contains `{source, workspace}` with a fresh validated roadmap binding. Subsequent item operations use the bound route family. Discovery refresh never replaces an editor's captured context or draft, and failed refresh retains last-known choices with an unavailable cue. A failed checkout open can be retried with Refresh or the current-source choice, which rediscovers before binding. Counts distinguish discovered checkouts from loaded roadmaps and participant coverage.

## Optional Pallium participants

Across initially requests `GET /api/worktree-workspace?openedOnly=1` alongside the full aggregate. The opened-only response has `provisional: true`, `partial: true`, and `coverage.pending: true`: it validates and loads only the opened checkout, without sibling discovery, cross-checkout ancestry, or participant lookup. The only accepted query value is one `openedOnly=1`; other or repeated values return 400. Its feature totals and In play coverage are incomplete, not the final Across result. The full response replaces this provisional board without restoring older user selections, filters, grouping, or layout. Same-scope Refresh keeps the last board and editor available while updating; a failed full read keeps usable provisional or last-known content with an error and Refresh retry. Provisional participant counts and details remain unknown until full feature identity is resolved.

Set `MINIMAP_PALLIUM_ENDPOINT` on a supported start or restart command to enable read-only participant lookup. Set `MINIMAP_PALLIUM_DASHBOARD_ENDPOINT` separately, and only for a reviewed compatible Pallium dashboard, to enable exact-session participant links. Both values must be explicit local HTTP origins such as `http://127.0.0.1:19836`; Minimap rejects remote, credential-bearing, redirected, or path-bearing endpoints before changing a running server or its saved preference. A successful command saves the validated settings under `$MINIMAP_HOME`, so later starts and restarts preserve them. An explicit empty dashboard value disables links while retaining lookup; an explicit empty lookup value disables lookup and clears both.

If `start-server.mjs` finds a healthy server and the requested or saved effective settings do not exactly match the server's verified effective identity, or a legacy server cannot verify it, the script exits with restart guidance instead of silently reusing it. `status.mjs` reports participant lookup and participant links independently as enabled, disabled, or unknown without exposing either origin. Do not edit the private preference file by hand; use the lifecycle scripts and environment variables.

When disabled, Minimap makes no Pallium HTTP requests and all normal roadmap behavior remains available. The server setting controls only the read-only item panel: the public `minimap roadmap item-ref` command and already-available Pallium MCP work-reference tools remain independent.

## URL

```text
http://localhost:<port>/#repo=<absolute-path-to-active-repo>&view=board
```

If the default port 4312 is busy the server falls forward; the actual bound port is in `$MINIMAP_HOME/server.json` and `status.mjs` prints it.
