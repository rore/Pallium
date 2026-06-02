# Server Lifecycle

The skill is self-contained and bundles its own minimap runtime in `runtime/` plus lifecycle scripts in `scripts/`.

Use the bundled scripts only. Do not curl the server, send signals to it, edit `$MINIMAP_HOME/server.json` by hand, or invoke `node package/minimap/server.js` directly — the scripts handle every state correctly across platforms.

## Lifecycle commands

| Command | Exit codes | What it does |
| --- | --- | --- |
| `node <skill>/scripts/start-server.mjs` | 0 = running (started or already up); 1 = port held by non-minimap process | Probe `$MINIMAP_HOME/server.json`, validate `/health`, reuse if alive; otherwise bind. Race-safe. |
| `node <skill>/scripts/status.mjs` | 0 = running; 1 = stale registry; 3 = not running | Read registry + `/health`. Prints port, pid, version, startedAt. |
| `node <skill>/scripts/stop-server.mjs` | 0 = stopped (or was already not running, or stale cleaned); 1 = shutdown failed | `POST /api/shutdown`, wait for port to free. Stale registry: clean it up and exit 0. |
| `node <skill>/scripts/restart-server.mjs` | 0 = restarted; 1 = stop or start failed | Stop running instance, spawn a fresh detached server, wait for `/health`. |

`status.mjs` exit codes follow `systemctl` conventions (0/1/3 = running/stale/not-running).

## Discovery

`start-server.mjs` reads `$MINIMAP_HOME/server.json`, probes `/health`, and exits early if a minimap server is already running on the listed port. Otherwise it starts one. Both `minimap-roadmap` and `minimap-spec-review` use the same registry, so a single running server transparently serves both modes.

## Multi-repo

The server is repo-agnostic — every roadmap request carries its own repo identity via the `X-Minimap-Repo` header (set by the UI from the `#repo=...` URL hash), so one server instance can serve any number of repos.

## UI URL

Open the roadmap for a specific repo by passing its absolute path in the URL hash:

```text
http://localhost:4312/#repo=/abs/path/to/repo&view=board
```

If port 4312 is busy, the server falls forward to the next free port. The actual bound port is recorded in `$MINIMAP_HOME/server.json` — `status.mjs` prints it.
