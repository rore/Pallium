#!/usr/bin/env node
// Stops a running minimap server. Three exit states:
//   0 — server stopped (or was already not running, or stale registry cleaned up).
//   1 — something is on the port that responds but is not minimap; we leave it alone.
//
// Strategy:
//   1. Read $MINIMAP_HOME/server.json. Missing → "not running" → exit 0.
//   2. Probe /health on the registered port.
//      - Healthy minimap → POST /api/shutdown, wait briefly, verify port free.
//      - Anything else (timeout, refused, wrong shape) → registry is stale →
//        delete it and exit 0. We do NOT touch whatever process owns the port.
import { readServerRegistry, deleteServerRegistry } from "../runtime/src/server-registry.js";
import { probePort } from "./health-check.mjs";

const STOP_WAIT_TIMEOUT_MS = 3000;
const STOP_POLL_INTERVAL_MS = 50;

const entry = await readServerRegistry();
if (!entry || typeof entry.port !== "number") {
  process.stdout.write("Minimap is not running.\n");
  process.exit(0);
}

const probe = await probePort(entry.port, entry);
if (!probe) {
  // Stale registry. Either the server crashed or the port is held by an
  // unrelated process. Either way, the registry is no longer authoritative.
  await deleteServerRegistry();
  process.stdout.write(`Stale registry cleaned up (no minimap responding on port ${entry.port}).\n`);
  process.exit(0);
}

// Trigger graceful shutdown via the HTTP endpoint (cross-platform, unlike signals).
try {
  const response = await fetch(`http://localhost:${entry.port}/api/shutdown`, { method: "POST" });
  if (!response.ok) {
    process.stderr.write(`Shutdown request returned ${response.status}.\n`);
    process.exit(1);
  }
} catch (error) {
  process.stderr.write(`Shutdown request failed: ${error.message}\n`);
  process.exit(1);
}

// Wait for the server to actually exit (port becomes refused).
const deadline = Date.now() + STOP_WAIT_TIMEOUT_MS;
while (Date.now() < deadline) {
  await new Promise((resolve) => setTimeout(resolve, STOP_POLL_INTERVAL_MS));
  const stillUp = await probePort(entry.port);
  if (!stillUp) {
    process.stdout.write(`Minimap stopped (was on port ${entry.port}, pid ${entry.pid ?? "?"}).\n`);
    process.exit(0);
  }
}

process.stderr.write(`Minimap did not exit within ${STOP_WAIT_TIMEOUT_MS}ms.\n`);
process.exit(1);
