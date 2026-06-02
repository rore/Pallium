import { readServerRegistry } from "../runtime/src/server-registry.js";

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
    const response = await fetch(`http://localhost:${port}/health`, { signal: controller.signal });
    if (!response.ok) return null;
    const payload = await response.json();
    if (payload && payload.ok === true) return entry || { port };
    return null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
