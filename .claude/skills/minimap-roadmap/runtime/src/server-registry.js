import fs from "node:fs/promises";
import path from "node:path";
import { resolveMinimapHome } from "./sessions.js";

const REGISTRY_FILE = "server.json";
const PREFERENCE_FILE = "pallium-preference.json";

// Bump only when the shared server API becomes incompatible with these clients.
export const SERVER_API_COMPATIBILITY = 1;

export async function readRuntimeIdentity(serverPath) {
  const sourcePath = await fs.realpath(serverPath);
  const pkg = JSON.parse(await fs.readFile(path.join(path.dirname(sourcePath), "package.json"), "utf8"));
  return { version: pkg.version || "0.0.0", apiCompatibility: SERVER_API_COMPATIBILITY, sourcePath };
}

export function registryPath(minimapHome) {
  return path.join(minimapHome, REGISTRY_FILE);
}

export function palliumPreferencePath(minimapHome) {
  return path.join(minimapHome, PREFERENCE_FILE);
}

function resolveHome(options) {
  return options?.minimapHome || resolveMinimapHome(options?.env || process.env, options?.platform || process.platform);
}

export async function readServerRegistry(options = {}) {
  const home = resolveHome(options);
  try {
    const raw = await fs.readFile(registryPath(home), "utf8");
    return JSON.parse(raw);
  } catch (error) {
    if (error && error.code === "ENOENT") return null;
    if (error instanceof SyntaxError) return null;
    throw error;
  }
}

export async function writeServerRegistry(entry, options = {}) {
  const home = resolveHome(options);
  await fs.mkdir(home, { recursive: true });
  await fs.writeFile(registryPath(home), `${JSON.stringify(entry, null, 2)}\n`, "utf8");
}

export async function readPalliumPreference(options = {}) {
  const home = resolveHome(options);
  try {
    const value = JSON.parse(await fs.readFile(palliumPreferencePath(home), "utf8"));
    if (!value || typeof value !== "object" || typeof value.palliumEndpoint !== "string" || !value.palliumEndpoint) return null;
    return {
      palliumEndpoint: value.palliumEndpoint,
      palliumDashboardEndpoint: typeof value.palliumDashboardEndpoint === "string" && value.palliumDashboardEndpoint ? value.palliumDashboardEndpoint : null,
    };
  } catch (error) {
    if (error?.code === "ENOENT" || error instanceof SyntaxError) return null;
    throw error;
  }
}

export async function writePalliumPreference(preference, options = {}) {
  if (!preference || typeof preference.palliumEndpoint !== "string" || !preference.palliumEndpoint) {
    throw new TypeError("preference.palliumEndpoint must be a non-empty string.");
  }
  if (preference.palliumDashboardEndpoint != null && (typeof preference.palliumDashboardEndpoint !== "string" || !preference.palliumDashboardEndpoint)) {
    throw new TypeError("preference.palliumDashboardEndpoint must be a non-empty string or null.");
  }
  const home = resolveHome(options);
  await fs.mkdir(home, { recursive: true });
  const value = { palliumEndpoint: preference.palliumEndpoint };
  if (preference.palliumDashboardEndpoint) value.palliumDashboardEndpoint = preference.palliumDashboardEndpoint;
  await fs.writeFile(palliumPreferencePath(home), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

export async function clearPalliumPreference(options = {}) {
  const home = resolveHome(options);
  try {
    await fs.unlink(palliumPreferencePath(home));
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

export async function deleteServerRegistry(options = {}) {
  const home = resolveHome(options);
  try {
    await fs.unlink(registryPath(home));
  } catch (error) {
    if (error && error.code === "ENOENT") return;
    throw error;
  }
}
