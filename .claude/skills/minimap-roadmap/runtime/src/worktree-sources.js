import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const MAX_SOURCES = 25;
const METADATA_CONCURRENCY = 8;
const POINTER_BYTES = 4096;
const REFLOG_BYTES = 8192;

async function git(repoRoot, args, signal, trim = true) {
  const stdout = (await execFileAsync("git", args, {
    cwd: repoRoot, windowsHide: true, shell: false, timeout: 2000,
    maxBuffer: 1024 * 1024, encoding: "utf8", signal,
  })).stdout;
  return trim ? stdout.trim() : stdout;
}

function canonical(value) {
  const resolved = path.resolve(value);
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

async function context(repoRoot, signal) {
  let output;
  try {
    output = await git(repoRoot, ["rev-parse", "--path-format=absolute", "--show-toplevel",
      "--absolute-git-dir", "--git-common-dir", "--verify", "HEAD"], signal, false);
  } catch (error) {
    // Older Git may reject the option. Other failures must not launch four retries.
    if (!/unknown (?:option|switch)[\s\S]*path-format/i.test(error.stderr || "")) throw error;
  }
  const fields = output?.replace(/\r?\n$/, "").split(/\r?\n/);
  let root, gitDir, commonDir, commit;
  if (fields?.length === 4 && fields.slice(0, 3).every((field) => path.isAbsolute(field))
    && /^[0-9a-f]{40,64}$/i.test(fields[3])) {
    [root, gitDir, commonDir] = fields.slice(0, 3).map(canonical);
    commit = fields[3];
  } else {
    // Preserve legacy/unusual path framing rather than guessing newline boundaries.
    root = canonical(await git(repoRoot, ["rev-parse", "--show-toplevel"], signal));
    gitDir = canonical(await git(repoRoot, ["rev-parse", "--absolute-git-dir"], signal));
    commonDir = canonical(path.resolve(root, await git(repoRoot, ["rev-parse", "--git-common-dir"], signal)));
  }
  const [gitStat, commonStat, head] = await Promise.all([
    fs.stat(gitDir), fs.stat(commonDir), fs.readFile(path.join(gitDir, "HEAD"), { encoding: "utf8", signal }),
  ]);
  const branch = head.trim().match(/^ref:\s*(.+)$/);
  commit ??= await git(repoRoot, ["rev-parse", "HEAD"], signal);
  if (!/^[0-9a-f]{40,64}$/i.test(commit)) throw new Error("Invalid Git HEAD");
  const identity = (stat) => ({ birthtimeMs: stat.birthtimeMs, ino: stat.ino, dev: stat.dev });
  const key = createHash("sha256").update(`${commonDir}\0${gitDir}\0${gitStat.dev}:${gitStat.ino}`).digest("hex");
  return {
    repoRoot: root, sourceKey: key,
    git: { gitDir, commonDir, gitDirIdentity: identity(gitStat), commonDirIdentity: identity(commonStat),
      branchRef: branch?.[1] || null, headCommit: commit },
    label: path.basename(root),
  };
}

export async function readWorktreeIdentity(repoRoot, { signal } = {}) {
  try { return await context(repoRoot, signal); } catch (error) {
    if (signal?.aborted) throw signal.reason || error;
    return null;
  }
}

function parsePorcelain(output) {
  // `-z` emits NUL-delimited field/value pairs; a blank NUL separates entries.
  const fields = output.split("\0");
  const entries = [];
  let entry = {};
  for (let i = 0; i < fields.length; i += 1) {
    const field = fields[i];
    if (!field) { if (entry.worktree) entries.push(entry); entry = {}; continue; }
    const pair = field.match(/^(worktree|HEAD|branch) (.*)$/);
    if (pair) entry[pair[1]] = pair[2];
    else if (/^(detached|bare|locked|prunable)( |$)/.test(field)) entry[field.split(" ", 1)[0]] = true;
  }
  if (entry.worktree) entries.push(entry);
  return entries;
}

function within(parent, child) {
  const relative = path.relative(parent, child);
  return !relative || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

async function boundedRead(file, limit, tail, signal) {
  signal?.throwIfAborted();
  const handle = await fs.open(file, "r");
  try {
    const stat = await handle.stat();
    if (!stat.isFile() || (!tail && stat.size > limit)) return null;
    const position = tail ? Math.max(0, stat.size - limit) : 0;
    const buffer = Buffer.alloc(Math.min(stat.size, limit));
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, position);
    signal?.throwIfAborted();
    if (bytesRead !== buffer.length) return null;
    return { text: buffer.subarray(0, bytesRead).toString("utf8"), position };
  } finally { await handle.close(); }
}

async function candidateMetadata(record, commonDir, signal) {
  const candidate = { ...record, activity: null };
  try {
    signal?.throwIfAborted();
    if (!(await fs.stat(record.worktree)).isDirectory()) return { ...candidate, missing: true };
  } catch (error) {
    if (signal?.aborted) throw signal.reason || error;
    return { ...candidate, missing: true };
  }
  try {
    const gitPath = path.join(record.worktree, ".git");
    const stat = await fs.lstat(gitPath);
    if (stat.isSymbolicLink()) return candidate;
    let gitDir = gitPath;
    if (!stat.isDirectory()) {
      const pointer = await boundedRead(gitPath, POINTER_BYTES, false, signal);
      const match = pointer?.text.match(/^gitdir: ([^\r\n]+)\r?\n?$/);
      if (!match) return candidate;
      gitDir = path.resolve(record.worktree, match[1]);
    }
    gitDir = canonical(await fs.realpath(gitDir));
    if (gitDir !== commonDir && !within(path.join(commonDir, "worktrees"), gitDir)) return candidate;
    const log = canonical(await fs.realpath(path.join(gitDir, "logs", "HEAD")));
    if (!within(gitDir, log)) return candidate;
    const tail = await boundedRead(log, REFLOG_BYTES, true, signal);
    if (!tail) return candidate;
    const end = tail.text.lastIndexOf("\n");
    if (end < 0) return candidate;
    const start = tail.text.lastIndexOf("\n", end - 1) + 1;
    if (tail.position && start === 0) return candidate;
    const entry = tail.text.slice(start, end).replace(/\r$/, "");
    const match = entry.match(/^[0-9a-f]{40,64} [0-9a-f]{40,64} .+ <[^>]*> (\d+) [+-]\d{4}\t[^\r\n]*$/i);
    const timestamp = match ? Number(match[1]) : NaN;
    if (Number.isSafeInteger(timestamp)) candidate.activity = timestamp;
  } catch (error) {
    if (signal?.aborted) throw signal.reason || error;
    // Missing or unreadable activity is unknown, not failed source identity.
  }
  return candidate;
}

export async function discoverWorktreeSources(openRepoRoot, { signal } = {}) {
  const result = { sources: [], excluded: [], partial: false, unavailable: null };
  const opened = await readWorktreeIdentity(openRepoRoot, { signal });
  if (!opened) { result.unavailable = { reason: "not-git-or-unavailable" }; return result; }
  result.sources.push(opened);
  let records;
  try { records = parsePorcelain(await git(opened.repoRoot, ["worktree", "list", "--porcelain", "-z"], signal)); }
  catch (error) {
    if (signal?.aborted) throw signal.reason || error;
    result.partial = true; result.unavailable = { reason: "git-worktree-list-failed", message: error.message }; return result;
  }
  const candidates = records.filter((record) => canonical(record.worktree) !== opened.repoRoot);
  const ranked = [];
  let commonDir;
  try { commonDir = canonical(await fs.realpath(opened.git.commonDir)); }
  catch (error) {
    if (signal?.aborted) throw signal.reason || error;
    result.partial = true; result.unavailable = { reason: "git-worktree-list-failed", message: error.message }; return result;
  }
  for (let offset = 0; offset < candidates.length; offset += METADATA_CONCURRENCY) {
    signal?.throwIfAborted();
    const batch = await Promise.allSettled(candidates.slice(offset, offset + METADATA_CONCURRENCY).map(async (record) => {
      if (record.prunable) return record;
      return candidateMetadata(record, commonDir, signal);
    }));
    for (const entry of batch) {
      if (entry.status === "rejected") throw entry.reason;
      const record = entry.value;
      if (record.prunable || record.missing) {
        result.partial = true;
        result.excluded.push({ repoRoot: record.worktree, reason: record.prunable ? "prunable" : "missing-or-unavailable" });
      } else ranked.push(record);
    }
  }
  ranked.sort((left, right) => (right.activity ?? -1) - (left.activity ?? -1)
    || (canonical(left.worktree) < canonical(right.worktree) ? -1 : canonical(left.worktree) > canonical(right.worktree) ? 1 : 0));
  for (let offset = 0; offset < ranked.length;) {
    if (signal?.aborted) throw signal.reason;
    if (result.sources.length >= MAX_SOURCES) {
      result.partial = true;
      result.excluded.push(...ranked.slice(offset).map((record) => ({ repoRoot: record.worktree, reason: "source-limit" })));
      break;
    }
    const batch = ranked.slice(offset, offset + Math.min(4, MAX_SOURCES - result.sources.length));
    const reads = await Promise.allSettled(batch.map((record) => readWorktreeIdentity(record.worktree, { signal })));
    if (signal?.aborted) throw signal.reason;
    for (const [index, read] of reads.entries()) {
      if (read.status === "rejected") throw read.reason;
      const record = batch[index], candidate = read.value;
      if (!candidate) { result.partial = true; result.excluded.push({ repoRoot: record.worktree, reason: "missing-or-unavailable" }); continue; }
      if (candidate.git.commonDir !== opened.git.commonDir) { result.excluded.push({ repoRoot: record.worktree, reason: "different-common-git-dir" }); continue; }
      result.sources.push(candidate);
    }
    offset += batch.length;
  }
  return result;
}
