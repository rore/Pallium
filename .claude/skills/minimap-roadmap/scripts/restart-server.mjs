#!/usr/bin/env node
// Restarts the minimap server. Composes stop-then-start, leaving a fresh
// server running in the background and exiting cleanly.
//
// Useful when a code change requires bouncing the server, or when an agent
// wants a known-good restart without thinking about port state.
//
// Exit codes:
//   0 — restart succeeded; new server is running and /health-checks ok.
//   1 — failed to stop, or new server did not come up within the timeout.
import net from "node:net";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { readServerRegistry, deleteServerRegistry } from "../runtime/src/server-registry.js";
import { probePort, probeRunningServer } from "./health-check.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const requestedPort = Number(process.env.PORT || 4312);
const STOP_WAIT_TIMEOUT_MS = 5000;
const START_WAIT_TIMEOUT_MS = 10000;
const POLL_INTERVAL_MS = 100;
// Port range we sweep for stray minimap servers before starting a new one.
// The bundled server's listenOnAvailablePort falls forward across this range
// when its preferred port is in TIME_WAIT, so a previous session that exited
// without updating the registry can leave a live server somewhere in here.
const SWEEP_PORTS_FROM = 4312;
const SWEEP_PORTS_TO = 4320;

// Test whether the port is actually bindable — survives the Windows TIME_WAIT
// window after a graceful stop, where /health is gone but the kernel still
// refuses bind(). probePort only tells us whether /health responds; this
// answers the related but different question of whether bind() would succeed.
function canBindPort(port) {
  return new Promise((resolve) => {
    const tester = net.createServer();
    let settled = false;
    const finish = (ok) => {
      if (settled) return;
      settled = true;
      try { tester.close(); } catch {}
      resolve(ok);
    };
    tester.once("error", () => finish(false));
    tester.once("listening", () => finish(true));
    try {
      tester.listen(port);
    } catch {
      finish(false);
    }
  });
}

// Politely ask any minimap server on `port` to shut down. Returns true when
// /api/shutdown returned ok (or we determined no minimap was there). Used as
// a defensive sweep — the registry only tracks ONE server, but earlier
// sessions can leave others alive on adjacent ports if a prior restart
// fell forward into TIME_WAIT.
async function shutdownIfMinimap(port) {
  const found = await probePort(port);
  if (!found) return false;
  try {
    const resp = await fetch(`http://localhost:${port}/api/shutdown`, { method: "POST" });
    return resp.ok;
  } catch {
    return false;
  }
}

// Sweep the canonical port range for stray minimap servers and shut them
// down. Survives multiple parallel sessions that each only knew about
// "their" registry entry.
async function sweepStrayMinimaps(skipPort = null) {
  const reaped = [];
  for (let port = SWEEP_PORTS_FROM; port <= SWEEP_PORTS_TO; port += 1) {
    if (port === skipPort) continue;
    const ok = await shutdownIfMinimap(port);
    if (ok) reaped.push(port);
  }
  if (reaped.length > 0) {
    process.stderr.write(`Reaped stray minimap servers on ports: ${reaped.join(", ")}\n`);
  }
  // Brief grace period so each shutdown finishes before the next bind.
  if (reaped.length > 0) {
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
}

// 1. Stop whatever is running.
const existing = await readServerRegistry();
if (existing && typeof existing.port === "number") {
  const probe = await probePort(existing.port, existing);
  if (probe) {
    try {
      const resp = await fetch(`http://localhost:${existing.port}/api/shutdown`, { method: "POST" });
      if (!resp.ok) {
        process.stderr.write(`Shutdown request returned ${resp.status}.\n`);
        process.exit(1);
      }
    } catch (error) {
      process.stderr.write(`Shutdown request failed: ${error.message}\n`);
      process.exit(1);
    }
    // Wait for /health to stop responding AND for the port to be bindable
    // again. The latter is what actually matters for the upcoming spawn —
    // on Windows the kernel can keep the port in TIME_WAIT after the server
    // process has exited, so /health goes silent before bind() is allowed.
    const deadline = Date.now() + STOP_WAIT_TIMEOUT_MS;
    let bindable = false;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
      const stillUp = Boolean(await probePort(existing.port));
      if (stillUp) continue;
      bindable = await canBindPort(existing.port);
      if (bindable) break;
    }
    if (!bindable) {
      process.stderr.write(`Port ${existing.port} did not become bindable within ${STOP_WAIT_TIMEOUT_MS}ms after shutdown.\n`);
      process.exit(1);
    }
  } else {
    // Stale registry — clean it up so the new server can write a fresh one.
    await deleteServerRegistry();
  }
}

// 1b. Belt-and-suspenders: sweep the canonical port range for any minimap
// server that the registry didn't know about. Catches the case where a
// previous restart fell forward into a TIME_WAIT'd port and updated the
// registry to that fall-forward port, leaving the original port's server
// alive but untracked. Without this, restarts compound rather than cycling.
await sweepStrayMinimaps();

// 2. Spawn the new server, detached, so it outlives this script.
//    Note: we do NOT set MINIMAP_NO_PORT_FALLBACK here. If the kernel still
//    has port 4312 in TIME_WAIT (Windows quirk), the bundled server's
//    listenOnAvailablePort will retry across attempts and find the port the
//    moment it's released. Pinning the port would turn that recoverable
//    blip into a hard failure.
const bundledServer = path.join(__dirname, "..", "runtime", "server.js");
const child = spawn(process.execPath, [bundledServer], {
  cwd: process.cwd(),
  env: { ...process.env, PORT: String(requestedPort) },
  detached: true,
  stdio: "ignore",
});
child.unref();

// 3. Wait for /health to come up. We do NOT require the port to equal
//    requestedPort because the bundled server may have fallen forward by
//    one or two ports if the kernel was still holding 4312. The registry
//    that probeRunningServer reads tells us where it actually landed.
const startDeadline = Date.now() + START_WAIT_TIMEOUT_MS;
let alive = null;
while (Date.now() < startDeadline) {
  await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  alive = await probeRunningServer();
  if (alive) break;
}

if (!alive) {
  process.stderr.write(`New server did not come up within ${START_WAIT_TIMEOUT_MS}ms.\n`);
  process.exit(1);
}

const portNote = alive.port === requestedPort ? "" : ` (requested ${requestedPort})`;
process.stdout.write(`Minimap restarted on http://localhost:${alive.port}${portNote} (pid ${alive.pid ?? "?"}).\n`);
process.exit(0);
