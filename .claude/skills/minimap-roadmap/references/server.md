# Server Lifecycle

Use the bundled scripts only. The skill is self-contained; the scripts handle every state correctly across platforms (Windows signal limitations, TIME_WAIT, race-against-another-launcher, stale registry).

## Local trust boundary

The server binds to IPv4 loopback (`127.0.0.1`) only. Every API request must come from a loopback peer and carry a loopback `Host`; when a browser supplies `Origin`, it must exactly match that request origin. Foreign origins are rejected before route work, while origin-less local CLI and lifecycle requests remain supported.

## Lifecycle commands

| Command | Exit codes | What it does |
| --- | --- | --- |
| `node <skill>/scripts/start-server.mjs` | 0 = running (started or already up); 1 = port held by non-minimap process | Probe `$MINIMAP_HOME/server.json`, validate `/health`, reuse if alive; otherwise bind. |
| `node <skill>/scripts/status.mjs` | 0 = running; 1 = stale registry; 3 = not running | Print port, pid, version, startedAt. |
| `node <skill>/scripts/stop-server.mjs` | 0 = stopped (or was already not running, or stale cleaned); 1 = shutdown failed | `POST /api/shutdown`, wait for the port to free. |
| `node <skill>/scripts/restart-server.mjs` | 0 = restarted; 1 = stop, start, or verification failed | Stop, spawn a fresh detached server, wait for `/health`, and shut down only that child if post-launch configuration verification fails (the receiving server validates its PID). |

Exit codes follow `systemctl` conventions for `status` (0/1/3 = running/stale/not-running).

## Discovery

`start-server.mjs` reads `$MINIMAP_HOME/server.json` and probes `/health`. If a minimap is already running, the launcher exits without spawning a second one. Both `minimap-roadmap` and `minimap-spec-review` use the same registry, so one running server transparently serves both modes.

## Multi-repo

The server is repo-agnostic. Every roadmap request carries its own repo identity via the `X-Minimap-Repo` header (set by the UI from the `#repo=...` URL hash). One server can serve any number of repos at once.

## Optional Pallium participants

Set `MINIMAP_PALLIUM_ENDPOINT` on a supported start or restart command to enable read-only participant lookup. Set `MINIMAP_PALLIUM_DASHBOARD_ENDPOINT` separately, and only for a reviewed compatible Pallium dashboard, to enable exact-session participant links. Both values must be explicit local HTTP origins such as `http://127.0.0.1:19836`; Minimap rejects remote, credential-bearing, redirected, or path-bearing endpoints before changing a running server or its saved preference. A successful command saves the validated settings under `$MINIMAP_HOME`, so later starts and restarts preserve them. An explicit empty dashboard value disables links while retaining lookup; an explicit empty lookup value disables lookup and clears both.

If `start-server.mjs` finds a healthy server and the requested or saved effective settings do not exactly match the server's verified effective identity, or a legacy server cannot verify it, the script exits with restart guidance instead of silently reusing it. `status.mjs` reports participant lookup and participant links independently as enabled, disabled, or unknown without exposing either origin. Do not edit the private preference file by hand; use the lifecycle scripts and environment variables.

When disabled, Minimap makes no Pallium HTTP requests and all normal roadmap behavior remains available. The server setting controls only the read-only item panel: the public `minimap roadmap item-ref` command and already-available Pallium MCP work-reference tools remain independent.

## URL

```text
http://localhost:<port>/#repo=<absolute-path-to-active-repo>&view=board
```

If the default port 4312 is busy the server falls forward; the actual bound port is in `$MINIMAP_HOME/server.json` and `status.mjs` prints it.
