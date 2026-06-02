import fs from "node:fs/promises";
import path from "node:path";
import { resolveMinimapHome } from "./sessions.js";

const REGISTRY_FILE = "server.json";

export function registryPath(minimapHome) {
  return path.join(minimapHome, REGISTRY_FILE);
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

export async function deleteServerRegistry(options = {}) {
  const home = resolveHome(options);
  try {
    await fs.unlink(registryPath(home));
  } catch (error) {
    if (error && error.code === "ENOENT") return;
    throw error;
  }
}
