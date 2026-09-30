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
import fs from "node:fs/promises";
import { readFileSync, unlinkSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { readServerRegistry, deleteServerRegistry, readPalliumPreference, writePalliumPreference, clearPalliumPreference } from "../runtime/src/server-registry.js";
import { parsePalliumConfig, palliumConfigId } from "../runtime/src/pallium.js";
import { resolveMinimapHome } from "../runtime/src/sessions.js";
import { probePort } from "./health-check.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const requestedPort = Number(process.env.PORT || 4312);
const STOP_WAIT_TIMEOUT_MS = 5000;
const START_WAIT_TIMEOUT_MS = 10000;
const POLL_INTERVAL_MS = 100;

const restartLockPath = path.join(resolveMinimapHome(), "restart.lock");
const restartLockToken = randomUUID();
await fs.mkdir(path.dirname(restartLockPath), { recursive: true });
const lockDeadline = Date.now() + 30_000;
while (true) {
  try {
    await fs.writeFile(restartLockPath, JSON.stringify({ pid: process.pid, token: restartLockToken }), { flag: "wx" });
    break;
  } catch (error) {
    if (error?.code !== "EEXIST") throw error;
    let raw = null;
    let owner = null;
    try {
      raw = await fs.readFile(restartLockPath, "utf8");
      owner = JSON.parse(raw);
    } catch {}
    let stale = false;
    if (Number.isSafeInteger(owner?.pid) && owner.pid > 0) {
      // Signal 0 checks the launcher PID without stopping it or the server.
      try { process.kill(owner.pid, 0); } catch (error) { stale = error?.code === "ESRCH"; }
    }
    const stat = await fs.stat(restartLockPath).catch(() => null);
    if (stat && Date.now() - stat.mtimeMs > (owner ? 120_000 : 5_000)) stale = true;
    if (stale && raw !== null) {
      const current = await fs.readFile(restartLockPath, "utf8").catch(() => null);
      if (current === raw) await fs.unlink(restartLockPath).catch((error) => {
        if (error?.code !== "ENOENT") throw error;
      });
      continue;
    }
    if (Date.now() >= lockDeadline) {
      process.stderr.write("Another Minimap restart is still running.\n");
      process.exit(1);
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}
process.once("exit", () => {
  try {
    if (JSON.parse(readFileSync(restartLockPath, "utf8")).token === restartLockToken) unlinkSync(restartLockPath);
  } catch {}
});

const endpointExplicit = Object.hasOwn(process.env, "MINIMAP_PALLIUM_ENDPOINT");
const dashboardExplicit = Object.hasOwn(process.env, "MINIMAP_PALLIUM_DASHBOARD_ENDPOINT");
const stored = await readPalliumPreference();
let rawEndpoint = endpointExplicit ? process.env.MINIMAP_PALLIUM_ENDPOINT : (stored?.palliumEndpoint || "");
let rawDashboardEndpoint = dashboardExplicit
  ? process.env.MINIMAP_PALLIUM_DASHBOARD_ENDPOINT
  : (endpointExplicit ? "" : (stored?.palliumDashboardEndpoint || ""));
if (endpointExplicit && !String(rawEndpoint || "").trim()) rawDashboardEndpoint = "";
let palliumConfig = parsePalliumConfig(rawEndpoint, rawDashboardEndpoint);
if (palliumConfig.configured && !palliumConfig.endpoint) {
  if (endpointExplicit) {
    process.stderr.write("Invalid MINIMAP_PALLIUM_ENDPOINT; use a loopback HTTP origin or an empty value.\n");
    process.exit(1);
  }
  process.stderr.write("Ignoring an invalid stored Pallium endpoint; Participants remain disabled.\n");
  rawEndpoint = "";
  rawDashboardEndpoint = "";
  palliumConfig = parsePalliumConfig(rawEndpoint, rawDashboardEndpoint);
}
if (palliumConfig.dashboardConfigured && !palliumConfig.dashboardEndpoint) {
  if (dashboardExplicit) {
    process.stderr.write("Invalid MINIMAP_PALLIUM_DASHBOARD_ENDPOINT; use a loopback HTTP origin or an empty value.\n");
    process.exit(1);
  }
  process.stderr.write("Ignoring an invalid stored Pallium dashboard endpoint; participant links remain disabled.\n");
  rawDashboardEndpoint = "";
  palliumConfig = parsePalliumConfig(rawEndpoint, rawDashboardEndpoint);
}
if (palliumConfig.dashboardEndpoint && !palliumConfig.endpoint) {
  if (dashboardExplicit) {
    process.stderr.write("MINIMAP_PALLIUM_DASHBOARD_ENDPOINT requires MINIMAP_PALLIUM_ENDPOINT.\n");
    process.exit(1);
  }
  rawDashboardEndpoint = "";
  palliumConfig = parsePalliumConfig(rawEndpoint, rawDashboardEndpoint);
}
const expectedConfigId = palliumConfigId(palliumConfig);
const childEnv = { ...process.env, PORT: String(requestedPort) };
if (palliumConfig.endpoint) childEnv.MINIMAP_PALLIUM_ENDPOINT = palliumConfig.endpoint;
else delete childEnv.MINIMAP_PALLIUM_ENDPOINT;
if (palliumConfig.dashboardEndpoint) childEnv.MINIMAP_PALLIUM_DASHBOARD_ENDPOINT = palliumConfig.dashboardEndpoint;
else delete childEnv.MINIMAP_PALLIUM_DASHBOARD_ENDPOINT;
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
      tester.listen(port, "127.0.0.1");
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
async function shutdownIfMinimap(port, expectedPid = null) {
  const found = await probePort(port);
  if (!found) return false;
  try {
    const headers = expectedPid === null ? undefined : { "X-Minimap-Instance-Pid": String(expectedPid) };
    const resp = await fetch(`http://127.0.0.1:${port}/api/shutdown`, { method: "POST", headers });
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
      const resp = await fetch(`http://127.0.0.1:${existing.port}/api/shutdown`, { method: "POST" });
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
  env: childEnv,
  detached: true,
  stdio: ["ignore", "ignore", "ignore", "ipc"],
});
child.unref();

// The registry is shared; another restart may replace it before our first
// probe. The child reports its own bound port over IPC instead.
const ready = await new Promise((resolve) => {
  let settled = false;
  const finish = (message) => {
    if (settled) return;
    settled = true;
    clearTimeout(timer);
    resolve(message);
  };
  const timer = setTimeout(() => finish(null), START_WAIT_TIMEOUT_MS);
  child.once("message", finish);
  child.once("exit", () => finish(null));
  child.once("error", () => finish(null));
});

if (ready?.type !== "minimap-ready" || ready.pid !== child.pid || !Number.isInteger(ready.port)) {
  if (child.connected) child.disconnect();
  process.stderr.write("New server did not report its bound port within " + START_WAIT_TIMEOUT_MS + "ms.\n");
  process.exit(1);
}

const alive = await probePort(ready.port);
const registry = await readServerRegistry();
if (!alive || alive.participantConfigId !== expectedConfigId
    || registry?.pid !== child.pid || registry.port !== ready.port) {
  if (!alive) {
    process.stderr.write("Restarted child did not respond to /health.\n");
  } else if (alive.participantConfigId !== expectedConfigId) {
    process.stderr.write("Restarted server did not report the requested Participants configuration.\n");
  } else {
    process.stderr.write("Another server replaced the restarted child's registry entry.\n");
  }
  await shutdownIfMinimap(ready.port, child.pid);
  if (child.connected) child.disconnect();
  process.exitCode = 1;
} else {
  if (endpointExplicit || dashboardExplicit) {
    if (palliumConfig.endpoint) {
      await writePalliumPreference({
        palliumEndpoint: palliumConfig.endpoint,
        palliumDashboardEndpoint: palliumConfig.dashboardEndpoint,
      });
    } else await clearPalliumPreference();
  }

  try {
    await new Promise((resolve, reject) => {
      child.send({ type: "minimap-ready-ack" }, (error) => error ? reject(error) : resolve());
    });
  } catch (error) {
    await shutdownIfMinimap(ready.port, child.pid);
    if (child.connected) child.disconnect();
    process.stderr.write("Restart acknowledgement failed: " + error.message + "\n");
    process.exit(1);
  }
  if (child.connected) child.disconnect();

  const portNote = ready.port === requestedPort ? "" : " (requested " + requestedPort + ")";
  process.stdout.write("Minimap restarted on http://localhost:" + ready.port + portNote + " (pid " + child.pid + ").\n");
}
