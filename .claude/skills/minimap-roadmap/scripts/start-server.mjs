#!/usr/bin/env node
import { probeRunningServer, probePort } from "./health-check.mjs";
import { readPalliumPreference, writePalliumPreference, clearPalliumPreference } from "../runtime/src/server-registry.js";
import { parsePalliumConfig, palliumConfigId } from "../runtime/src/pallium.js";

const requestedPort = Number(process.env.PORT || 4312);
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

if (palliumConfig.endpoint) process.env.MINIMAP_PALLIUM_ENDPOINT = palliumConfig.endpoint;
else delete process.env.MINIMAP_PALLIUM_ENDPOINT;
if (palliumConfig.dashboardEndpoint) process.env.MINIMAP_PALLIUM_DASHBOARD_ENDPOINT = palliumConfig.dashboardEndpoint;
else delete process.env.MINIMAP_PALLIUM_DASHBOARD_ENDPOINT;

const expectedConfigId = palliumConfigId(palliumConfig);

function configMatches(server) {
  return server?.participantConfigId === expectedConfigId;
}

function rejectConfigMismatch() {
  process.stderr.write("Minimap is already running with a different or unknown Participants configuration. Run restart-server.mjs with the requested Pallium endpoint settings.\n");
  process.exit(1);
}

async function persistExplicitPreference() {
  if (!endpointExplicit && !dashboardExplicit) return;
  if (palliumConfig.endpoint) {
    await writePalliumPreference({
      palliumEndpoint: palliumConfig.endpoint,
      palliumDashboardEndpoint: palliumConfig.dashboardEndpoint,
    });
  } else await clearPalliumPreference();
}

const existing = await probeRunningServer();
if (existing) {
  if (!configMatches(existing)) rejectConfigMismatch();
  await persistExplicitPreference();
  process.stdout.write(`Minimap already running at http://localhost:${existing.port} (pid ${existing.pid ?? "?"})\n`);
  process.exit(0);
}

// Tell the bundled server: do NOT fall forward on EADDRINUSE for the first port.
// If we lose the race against another launcher, we'll re-probe and exit cleanly.
process.env.MINIMAP_NO_PORT_FALLBACK = "1";

try {
  await import("../runtime/server.js");
  await persistExplicitPreference();
} catch (error) {
  if (error && error.code === "EADDRINUSE") {
    // Another launcher beat us. Re-probe directly on the requested port.
    const winner = await probePort(requestedPort);
    if (winner) {
      if (!configMatches(winner)) rejectConfigMismatch();
      await persistExplicitPreference();
      process.stdout.write(`Minimap already running at http://localhost:${requestedPort}\n`);
      process.exit(0);
    }
    process.stderr.write(`Port ${requestedPort} is in use by a non-minimap process.\n`);
    process.exit(1);
  }
  throw error;
}
