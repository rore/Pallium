import path from "node:path";
import { fileURLToPath } from "node:url";
import { readServerRegistry, readRuntimeIdentity, SERVER_API_COMPATIBILITY } from "../runtime/src/server-registry.js";

export const localRuntime = await readRuntimeIdentity(fileURLToPath(new URL("../runtime/server.js", import.meta.url)));

export function isCompatibleRuntime(server) {
  const runtime = server?.runtime;
  return runtime?.apiCompatibility === SERVER_API_COMPATIBILITY
    && typeof runtime.version === "string" && runtime.version.length > 0
    && typeof runtime.sourcePath === "string" && path.isAbsolute(runtime.sourcePath);
}

export function isSameRuntime(server) {
  const normalize = (value) => process.platform === "win32" ? path.normalize(value).toLowerCase() : path.normalize(value);
  return isCompatibleRuntime(server) && server.runtime.version === localRuntime.version
    && normalize(server.runtime.sourcePath) === normalize(localRuntime.sourcePath);
}

export function replacementGuidance(server) {
  const runtime = server?.runtime;
  return `Running Minimap: version ${runtime?.version || "unknown"}, API ${runtime?.apiCompatibility ?? "unknown"}, source ${runtime?.sourcePath || "unknown"}.\n`
    + `Requested runtime: version ${localRuntime.version}, API ${localRuntime.apiCompatibility}, source ${localRuntime.sourcePath}.\n`
    + "This server is shared by roadmap/spec-review and other repositories. Replacement interrupts their sessions and may downgrade the runtime. Coordinate first, then run restart-server.mjs --replace-runtime to explicitly replace it.\n";
}

const HEALTH_TIMEOUT_MS = 1500;

export async function probeRunningServer(options = {}) {
  const entry = await readServerRegistry(options);
  if (!entry || typeof entry.port !== "number") return null;
  return await probePort(entry.port, entry);
}

export async function probePort(port, entry = null) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
  try {
    const response = await fetch(`http://127.0.0.1:${port}/health`, { signal: controller.signal });
    if (!response.ok) return null;
    const payload = await response.json();
    if (!payload || payload.ok !== true) return null;
    return {
      ...(entry || { port }),
      // Never substitute stale registry identity for absent live health fields.
      runtime: payload.runtime || null,
      pid: Number.isSafeInteger(payload.pid) && payload.pid > 0 ? payload.pid : null,
      participantMode: payload.participants?.mode || null,
      participantLinks: payload.participants?.links || null,
      participantConfigId: payload.participants?.configId || null,
    };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
