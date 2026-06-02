#!/usr/bin/env node
import { probeRunningServer, probePort } from "./health-check.mjs";

const requestedPort = Number(process.env.PORT || 4312);

const existing = await probeRunningServer();
if (existing) {
  process.stdout.write(`Minimap already running at http://localhost:${existing.port} (pid ${existing.pid ?? "?"})\n`);
  process.exit(0);
}

// Tell the bundled server: do NOT fall forward on EADDRINUSE for the first port.
// If we lose the race against another launcher, we'll re-probe and exit cleanly.
process.env.MINIMAP_NO_PORT_FALLBACK = "1";

try {
  await import("../runtime/server.js");
} catch (error) {
  if (error && error.code === "EADDRINUSE") {
    // Another launcher beat us. Re-probe directly on the requested port.
    const winner = await probePort(requestedPort);
    if (winner) {
      process.stdout.write(`Minimap already running at http://localhost:${requestedPort}\n`);
      process.exit(0);
    }
    process.stderr.write(`Port ${requestedPort} is in use by a non-minimap process.\n`);
    process.exit(1);
  }
  throw error;
}
