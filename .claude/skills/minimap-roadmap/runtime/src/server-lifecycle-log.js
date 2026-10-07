import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolveMinimapHome } from "./sessions.js";

export const LIFECYCLE_LOG_LIMIT = 128 * 1024;
export function lifecycleLogPath(home = resolveMinimapHome()) {
  return path.join(home, "server-lifecycle.jsonl");
}

// Keep only known error identifiers and runtime-owned source locations, not
// messages, function names, arbitrary stack text, or paths to reviewed files.
export function lifecycleError(error, runtimeRoot) {
  try {
    const classes = ["Error", "TypeError", "RangeError", "ReferenceError", "SyntaxError", "URIError", "EvalError", "AggregateError"];
    const codes = ["EACCES", "EPERM", "ENOENT", "EEXIST", "ENOTDIR", "EISDIR", "ENOSPC", "EROFS", "EMFILE", "ENFILE", "EADDRINUSE", "EADDRNOTAVAIL", "EINVAL", "ERR_UNHANDLED_REJECTION", "ERR_OUT_OF_RANGE", "ERR_INVALID_ARG_VALUE", "ERR_INVALID_ARG_TYPE", "ERR_IPC_CHANNEL_CLOSED"];
    const name = error?.name, code = error?.code;
    const locations = [];
    for (const line of String(error?.stack || "").slice(0, 8192).split("\n").slice(1, 33)) {
      const match = line.match(/^\s+at (?:.* \()?((?:file:\/\/\/|[A-Za-z]:[\\/]|\/)[^()\r\n]+):(\d+):(\d+)\)?$/);
      if (!match) continue;
      let source;
      try { source = match[1].startsWith("file:") ? fileURLToPath(match[1]) : match[1]; } catch { continue; }
      const relative = path.relative(runtimeRoot, source);
      if (relative.startsWith("..") || path.isAbsolute(relative) || !/^[\w./\\-]+\.m?js$/.test(relative) || !fs.existsSync(source)) continue;
      locations.push(`${relative.replace(/\\/g, "/")}:${match[2]}:${match[3]}`);
      if (locations.length === 5) break;
    }
    return {
      class: classes.includes(name) ? name : "Error",
      ...(codes.includes(code) ? { code } : {}),
      locations,
    };
  } catch { return { class: "Error", locations: [] }; }
}

export function createLifecycleLog({ home = resolveMinimapHome(), sourcePath, version = "unknown", launchMode = "direct" }) {
  const logPath = lifecycleLogPath(home);
  return (event, details = {}) => {
    try {
      const record = { timestamp: new Date().toISOString(), pid: process.pid, parentPid: process.ppid, sourcePath, version, launchMode, event, ...details };
      const line = `${JSON.stringify(record)}\n`;
      if (Buffer.byteLength(line) > 4096) return;
      fs.mkdirSync(home, { recursive: true });
      // ponytail: one server normally writes per home; concurrent launch races
      // can lose rotation evidence. Add locking only if that evidence matters.
      const size = fs.existsSync(logPath) ? fs.statSync(logPath).size : 0;
      if (size + Buffer.byteLength(line) > LIFECYCLE_LOG_LIMIT) {
        fs.rmSync(`${logPath}.1`, { force: true });
        fs.renameSync(logPath, `${logPath}.1`);
      }
      fs.appendFileSync(logPath, line, { encoding: "utf8", mode: 0o600 });
    } catch { /* Diagnostics must never affect lifecycle or fatal semantics. */ }
  };
}

export function printLifecycleHistory(home = resolveMinimapHome(), livePid = null) {
  const logPath = lifecycleLogPath(home);
  process.stdout.write(`  lifecycle log: ${logPath}\n`);
  const events = [];
  for (const file of [`${logPath}.1`, logPath]) {
    let fd;
    try {
      fd = fs.openSync(file, "r");
      const size = fs.fstatSync(fd).size;
      const buffer = Buffer.alloc(Math.min(size, LIFECYCLE_LOG_LIMIT));
      fs.readSync(fd, buffer, 0, buffer.length, Math.max(0, size - buffer.length));
      for (const line of buffer.toString("utf8").split("\n")) {
        try { const event = JSON.parse(line); if (event && Number.isSafeInteger(event.pid)) events.push(event); } catch {}
      }
    } catch {} finally { if (fd !== undefined) try { fs.closeSync(fd); } catch {} }
  }
  const recent = events.slice(-8);
  process.stdout.write("  Recent lifecycle evidence (historical PIDs; not proof of the current cause):\n");
  if (!recent.length) process.stdout.write("    unavailable\n");
  for (const event of recent) process.stdout.write(`    ${JSON.stringify(event)}\n`);
  const latestStart = events.findLast((event) => ["startup", "started"].includes(event.event));
  const latestIsLive = Number.isSafeInteger(livePid) && (!latestStart || latestStart.pid === livePid);
  if (!latestIsLive && (!latestStart || !events.some((event) => event.event === "exit" && event.pid === latestStart.pid && event.timestamp >= latestStart.timestamp))) {
    process.stdout.write("  Final exit: unknown (no recorded exit; hard kill/job teardown cannot be logged).\n");
  }
}
