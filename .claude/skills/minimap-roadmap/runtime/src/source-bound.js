import fs from "node:fs/promises";
import path from "node:path";
import { AppError, resolveRoadmapRoot } from "./roadmap.js";
import { readWorktreeIdentity } from "./worktree-sources.js";

function within(root, target) {
  const relative = path.relative(root, target);
  return relative === "" || (relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative));
}

function sameStat(left, right) {
  return left?.dev === right?.dev && left?.ino === right?.ino && left?.birthtimeMs === right?.birthtimeMs;
}

export async function verifySourceContext(repoRoot, expected, { signal } = {}) {
  const actual = await readWorktreeIdentity(repoRoot, { signal });
  if (!actual || !expected || typeof expected !== "object"
    || actual.repoRoot !== expected.repoRoot || actual.sourceKey !== expected.sourceKey
    || actual.git.commonDir !== expected.git?.commonDir || actual.git.gitDir !== expected.git?.gitDir
    || !sameStat(actual.git.commonDirIdentity, expected.git.commonDirIdentity)
    || !sameStat(actual.git.gitDirIdentity, expected.git.gitDirIdentity)
    || actual.git.branchRef !== expected.git.branchRef
    || (!actual.git.branchRef && actual.git.headCommit !== expected.git.headCommit)) {
    throw new AppError("Checkout changed. Reload this source before continuing.", 409, "source_changed");
  }
  return actual;
}

async function realPathOrParent(target, signal) {
  if (signal?.aborted) throw signal.reason;
  try { return await fs.realpath(target); }
  catch (error) {
    if (error?.code !== "ENOENT") throw error;
    const parentPath = path.dirname(target);
    if (parentPath === target) throw error;
    const parent = await realPathOrParent(parentPath, signal);
    return path.join(parent, path.basename(target));
  }
}

export async function requirePathInSource(repoRoot, candidate, { signal } = {}) {
  if (signal?.aborted) throw signal.reason;
  if (typeof candidate !== "string" || !path.isAbsolute(candidate)) {
    throw new AppError("Bound file path must be absolute.", 400, "bad_request");
  }
  if (!within(path.resolve(repoRoot), path.resolve(candidate)) || path.resolve(candidate) === path.resolve(repoRoot)) {
    throw new AppError("File is outside the selected checkout.", 403, "source_path_escape");
  }
  const [rootReal, targetReal] = await Promise.all([fs.realpath(repoRoot), realPathOrParent(candidate, signal)]);
  if (!within(rootReal, targetReal) || targetReal === rootReal) {
    throw new AppError("File is outside the selected checkout.", 403, "source_path_escape");
  }
  return targetReal;
}

export async function requireRoadmapInSource(repoRoot, { signal } = {}) {
  await requirePathInSource(repoRoot, path.join(repoRoot, "roadmap.config.json"), { signal });
  const workspace = await resolveRoadmapRoot(repoRoot, { signal });
  await requirePathInSource(repoRoot, workspace.resolvedPath, { signal });
  for (const name of ["features", "ideas", "board.md", "scope.md"]) {
    await requirePathInSource(repoRoot, path.join(workspace.resolvedPath, name), { signal });
  }
  return workspace;
}
