import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { decodeConfig, decodeRecord } from "./work-record/work-record-relationships.mjs";
import { requirePathInSource } from "./source-bound.js";

const MAX_RECORDS = 1000;
const MAX_RECORD_BYTES = 256 * 1024;
const MAX_TOTAL_BYTES = 128 * 1024 * 1024;
const MAX_REUSED_BYTES = 16 * 1024 * 1024;
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");

async function boundedNames(directory, prefix, suffix, signal) {
  const heap = [];
  let found = 0;
  const rise = (index) => {
    while (index > 0) {
      const parent = Math.floor((index - 1) / 2);
      if (heap[parent] >= heap[index]) break;
      [heap[parent], heap[index]] = [heap[index], heap[parent]];
      index = parent;
    }
  };
  const sink = () => {
    let index = 0;
    while (index * 2 + 1 < heap.length) {
      const left = index * 2 + 1, right = left + 1;
      const larger = right < heap.length && heap[right] > heap[left] ? right : left;
      if (heap[index] >= heap[larger]) break;
      [heap[index], heap[larger]] = [heap[larger], heap[index]];
      index = larger;
    }
  };
  try {
    for await (const entry of await fs.opendir(directory)) {
      if (signal?.aborted) throw signal.reason;
      const name = entry.name;
      if (!name.startsWith(prefix) || !name.endsWith(suffix)) continue;
      found++;
      if (heap.length < MAX_RECORDS) { heap.push(name); rise(heap.length - 1); }
      else if (name < heap[0]) { heap[0] = name; sink(); }
    }
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  return { names: heap.sort(), found };
}

async function readBounded(file, maximum, signal) {
  const handle = await fs.open(file, "r");
  try {
    const bytes = Buffer.allocUnsafe(maximum + 1);
    let length = 0;
    while (length < bytes.length) {
      if (signal?.aborted) throw signal.reason;
      const read = await handle.read(bytes, length, bytes.length - length, null);
      if (!read.bytesRead) break;
      length += read.bytesRead;
    }
    if (length > maximum) throw Object.assign(new Error("File exceeds related-work limit."), { code: "related_work_too_large" });
    return bytes.subarray(0, length);
  } finally { await handle.close(); }
}

export async function workflowConfigFingerprint(repoRoot, { signal } = {}) {
  const file = await requirePathInSource(repoRoot, path.join(repoRoot, "agent-workflow.yaml"), { signal });
  try { return hash(await readBounded(file, 64 * 1024, signal)); }
  catch (error) {
    if (error.code === "ENOENT") return "missing";
    if (error.code === "related_work_too_large") return "oversized";
    throw error;
  }
}

export function createRelatedWorkScanner() {
  const previous = new Map();
  return async function scan(repoRoot, { signal, sourceCommit } = {}) {
    const configPath = await requirePathInSource(repoRoot, path.join(repoRoot, "agent-workflow.yaml"), { signal });
    let configBytes;
    try {
      const stat = await fs.stat(configPath);
      if (stat.size > 64 * 1024) return { status: "unavailable", reason: "config_too_large", records: [], coverage: {} };
      configBytes = await readBounded(configPath, 64 * 1024, signal);
    } catch (error) {
      if (error.code === "ENOENT") return { status: "unavailable", reason: "missing_workflow", records: [], coverage: {} };
      if (error.code === "related_work_too_large") return { status: "unavailable", reason: "config_too_large", records: [], coverage: {} };
      throw error;
    }
    const config = decodeConfig(configBytes);
    if (config.status !== "ok") return { status: "unavailable", reason: config.reason, records: [], coverage: {} };
    const template = config.task_path;
    const [beforeSlug, afterSlug] = template.split("{slug}");
    const slash = beforeSlug.lastIndexOf("/");
    const directory = slash < 0 ? await fs.realpath(repoRoot)
      : await requirePathInSource(repoRoot, path.join(repoRoot, beforeSlug.slice(0, slash)), { signal });
    const prefix = beforeSlug.slice(slash + 1);
    const nextSlash = afterSlug.indexOf("/");
    const suffix = nextSlash < 0 ? afterSlug : afterSlug.slice(0, nextSlash);
    const { names, found } = await boundedNames(directory, prefix, suffix, signal);
    const coverage = { found, enumerations: 1, bodyReads: 0,
      invalid: 0, legacy: 0, unsupported: 0, unverified: 0, unreadable: 0, oversized: 0, overflow: Math.max(0, found - MAX_RECORDS) };
    const old = previous.get(repoRoot);
    const reuse = old?.configHash === hash(configBytes) && old.sourceCommit === sourceCommit ? old.records : new Map();
    const next = new Map();
    const records = [];
    let totalBytes = 0;
    let retainedBytes = 0;
    let indexBytes = 0;
    for (const name of names) {
      if (signal?.aborted) throw signal.reason;
      const slug = name.slice(prefix.length, name.length - suffix.length || undefined);
      const candidate = path.join(repoRoot, template.replace("{slug}", slug));
      try {
        const file = await requirePathInSource(repoRoot, candidate, { signal });
        const stat = await fs.stat(file);
        totalBytes += stat.size;
        if (stat.size > MAX_RECORD_BYTES || totalBytes > MAX_TOTAL_BYTES) { coverage.oversized++; continue; }
        const relative = path.relative(repoRoot, file).split(path.sep).join("/");
        const stamp = `${stat.dev}:${stat.ino}:${stat.size}:${stat.mtimeMs}:${stat.ctimeMs}`;
        let entry = reuse.get(relative);
        if (!entry || entry.stamp !== stamp) {
          coverage.bodyReads++;
          const bytes = await readBounded(file, MAX_RECORD_BYTES, signal);
          const decoded = decodeRecord(bytes, { task_path: template, record_path: relative });
          entry = { stamp, hash: hash(bytes), decoded };
        }
        if (retainedBytes + stat.size <= MAX_REUSED_BYTES) { next.set(relative, entry); retainedBytes += stat.size; }
        const decoded = entry.decoded;
        if (decoded.status === "declared") {
          if (decoded.relationships.sources === null) coverage.unverified++;
          const record = { id: decoded.work_record_ref, title: decoded.title, recordedState: decoded.recorded_state,
            sources: decoded.relationships.sources || [], pullRequests: decoded.relationships.pull_requests,
            path: relative, hash: entry.hash };
          const bytes = Buffer.byteLength(JSON.stringify(record));
          if (indexBytes + bytes > 8 * 1024 * 1024) coverage.overflow++;
          else { records.push(record); indexBytes += bytes; }
        } else if (decoded.status === "legacy") coverage.legacy++;
        else if (decoded.status === "unsupported") coverage.unsupported++;
        else coverage.invalid++;
      } catch (error) {
        if (signal?.aborted) throw signal.reason || error;
        if (error.code === "related_work_too_large") coverage.oversized++;
        else coverage.unreadable++;
      }
    }
    previous.delete(repoRoot);
    previous.set(repoRoot, { configHash: hash(configBytes), sourceCommit, records: next, retainedBytes });
    let allRetained = [...previous.values()].reduce((sum, value) => sum + value.retainedBytes, 0);
    while (previous.size > 16 || allRetained > MAX_REUSED_BYTES) {
      const oldest = previous.keys().next().value;
      allRetained -= previous.get(oldest).retainedBytes;
      previous.delete(oldest);
    }
    return { status: ["invalid", "legacy", "unsupported", "unverified", "unreadable", "oversized", "overflow"].some((field) => coverage[field] > 0) ? "partial" : "ok", records, coverage, taskPath: template,
      configHash: hash(configBytes) };
  };
}

export async function readIndexedRecord(repoRoot, record, taskPath, { signal } = {}) {
  const file = await requirePathInSource(repoRoot, path.join(repoRoot, record.path), { signal });
  let bytes;
  try { bytes = await readBounded(file, MAX_RECORD_BYTES, signal); }
  catch (error) {
    if (["related_work_too_large", "ENOENT", "ENOTDIR"].includes(error.code)) return null;
    throw error;
  }
  if (hash(bytes) !== record.hash) return null;
  const decoded = decodeRecord(bytes, { task_path: taskPath, record_path: record.path });
  return decoded.status === "declared" && decoded.work_record_ref === record.id ? new TextDecoder("utf-8", { fatal: true }).decode(bytes) : null;
}
