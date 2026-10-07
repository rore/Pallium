#!/usr/bin/env node
// Reports minimap server status. Exit codes follow systemctl conventions:
//   0 — server is running and healthy.
//   1 — registry exists but server is gone (stale). Registry is left alone here;
//       use stop-server.mjs to clean it up.
//   3 — server is not running (no registry).
import { readServerRegistry } from "../runtime/src/server-registry.js";
import { probePort } from "./health-check.mjs";
import { printLifecycleHistory } from "../runtime/src/server-lifecycle-log.js";

const entry = await readServerRegistry();
if (!entry || typeof entry.port !== "number") {
  process.stdout.write("Minimap is not running.\n");
  printLifecycleHistory();
  process.exit(3);
}

const probe = await probePort(entry.port, entry);
if (!probe) {
  process.stderr.write(
    `Minimap registry is stale: ${entry.port} (pid ${entry.pid ?? "?"}) is not responding to /health.\n`
    + `Run stop-server.mjs to clean up the stale registry.\n`,
  );
  printLifecycleHistory();
  process.exit(1);
}

const startedAt = entry.startedAt ?? "unknown";
process.stdout.write(
  `Minimap is running.\n`
  + `  port:      ${entry.port}\n`
  + `  pid:       ${probe.pid ?? "unknown"}\n`
  + `  version:   ${probe.runtime?.version ?? "unknown"}\n`
  + `  API:       ${probe.runtime?.apiCompatibility ?? "unknown"}\n`
  + `  source:    ${probe.runtime?.sourcePath ?? "unknown"}\n`
  + `  startedAt: ${startedAt}\n`
  + `  participants: ${probe.participantMode || "unknown"}\n`
  + `  participant links: ${probe.participantLinks || "unknown"}\n`
  + `  url:       http://localhost:${entry.port}/\n`,
);
printLifecycleHistory(undefined, probe.pid);
process.exit(0);
