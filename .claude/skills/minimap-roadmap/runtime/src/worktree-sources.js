import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const MAX_SOURCES = 16;

async function git(repoRoot, args) {
  return (await execFileAsync("git", args, {
    cwd: repoRoot, windowsHide: true, shell: false, timeout: 2000,
    maxBuffer: 1024 * 1024, encoding: "utf8",
  })).stdout.trim();
}

function canonical(value) {
  const resolved = path.resolve(value);
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

async function context(repoRoot) {
  const root = canonical(await git(repoRoot, ["rev-parse", "--show-toplevel"]));
  const gitDir = canonical(await git(repoRoot, ["rev-parse", "--absolute-git-dir"]));
  const commonDirRaw = await git(repoRoot, ["rev-parse", "--git-common-dir"]);
  const commonDir = canonical(path.resolve(root, commonDirRaw));
  const [gitStat, commonStat, head] = await Promise.all([
    fs.stat(gitDir), fs.stat(commonDir), fs.readFile(path.join(gitDir, "HEAD"), "utf8"),
  ]);
  const branch = head.trim().match(/^ref:\s*(.+)$/);
  const commit = await git(repoRoot, ["rev-parse", "HEAD"]);
  const identity = (stat) => ({ birthtimeMs: stat.birthtimeMs, ino: stat.ino, dev: stat.dev });
  const key = createHash("sha256").update(`${commonDir}\0${gitDir}\0${gitStat.dev}:${gitStat.ino}`).digest("hex");
  return {
    repoRoot: root, sourceKey: key,
    git: { gitDir, commonDir, gitDirIdentity: identity(gitStat), commonDirIdentity: identity(commonStat),
      branchRef: branch?.[1] || null, headCommit: commit },
    label: path.basename(root),
  };
}

export async function readWorktreeIdentity(repoRoot) {
  try { return await context(repoRoot); } catch { return null; }
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

export async function discoverWorktreeSources(openRepoRoot) {
  const result = { sources: [], excluded: [], partial: false, unavailable: null };
  const opened = await readWorktreeIdentity(openRepoRoot);
  if (!opened) { result.unavailable = { reason: "not-git-or-unavailable" }; return result; }
  result.sources.push(opened);
  let records;
  try { records = parsePorcelain(await git(opened.repoRoot, ["worktree", "list", "--porcelain", "-z"])); }
  catch (error) { result.partial = true; result.unavailable = { reason: "git-worktree-list-failed", message: error.message }; return result; }
  const candidates = records.filter((record) => canonical(record.worktree) !== opened.repoRoot);
  let inspected = 0;
  for (const record of candidates) {
    if (inspected >= MAX_SOURCES - 1) {
      result.partial = true; result.excluded.push({ repoRoot: record.worktree, reason: "source-limit" }); continue;
    }
    inspected += 1;
    if (record.prunable) { result.partial = true; result.excluded.push({ repoRoot: record.worktree, reason: "prunable" }); continue; }
    const candidate = await readWorktreeIdentity(record.worktree);
    if (!candidate) { result.partial = true; result.excluded.push({ repoRoot: record.worktree, reason: "missing-or-unavailable" }); continue; }
    if (candidate.git.commonDir !== opened.git.commonDir) { result.excluded.push({ repoRoot: record.worktree, reason: "different-common-git-dir" }); continue; }
    result.sources.push(candidate);
  }
  return result;
}
