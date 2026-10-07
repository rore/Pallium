import { execFile, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { loadWorkspace, parseItemText } from "./roadmap.js";
import { discoverWorktreeSources, readWorktreeIdentity } from "./worktree-sources.js";
import { requireRoadmapInSource } from "./source-bound.js";

const execFileAsync = promisify(execFile);
const hash = (value) => createHash("sha256").update(value).digest("hex");
const relative = (root, file) => path.relative(root, path.isAbsolute(file) ? file : path.resolve(root, file)).replaceAll("\\", "/");

async function git(root, ...args) {
  return (await execFileAsync("git", args, {
    cwd: root, windowsHide: true, shell: false, timeout: 5000,
    maxBuffer: 4 * 1024 * 1024, encoding: "utf8",
  })).stdout.trim();
}

async function ancestorBlobs(root, objects) {
  if (objects.length > 500) throw new Error("ancestor item limit");
  const output = await new Promise((resolve, reject) => {
    const child = spawn("git", ["cat-file", "--batch"], { cwd: root, windowsHide: true, shell: false });
    const chunks = [];
    let size = 0;
    const timer = setTimeout(() => child.kill(), 5000);
    child.on("error", reject);
    child.stdin.on("error", reject);
    child.stdout.on("data", (chunk) => {
      size += chunk.length;
      if (size > 8 * 1024 * 1024) { child.kill(); return; }
      chunks.push(chunk);
    });
    child.stderr.resume();
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0 || size > 8 * 1024 * 1024) reject(new Error("ancestor batch unavailable"));
      else resolve(Buffer.concat(chunks));
    });
    child.stdin.end(objects.map((entry) => entry.oid).join("\n") + "\n");
  });
  const ids = new Map();
  let invalid = false;
  let offset = 0;
  for (const entry of objects) {
    const end = output.indexOf(10, offset);
    if (end < 0) throw new Error("invalid ancestor batch");
    const header = output.subarray(offset, end).toString("utf8").match(/^([0-9a-f]{40,64}) blob (\d+)$/i);
    if (!header || header[1] !== entry.oid) throw new Error("invalid ancestor blob");
    const length = Number(header[2]);
    if (!Number.isSafeInteger(length) || end + 1 + length >= output.length) throw new Error("invalid ancestor size");
    try { ids.set(entry.file, String(parseItemText(output.subarray(end + 1, end + 1 + length).toString("utf8"), entry.file).frontmatter.id)); }
    catch { invalid = true; /* Invalid ancestor item cannot establish identity. */ }
    offset = end + 2 + length;
  }
  if (offset !== output.length) throw new Error("invalid ancestor tail");
  return { ids, invalid };
}

// A matching id/path is only one feature when the file survived from common history.
// Missing, shallow, or oversized Git evidence fails closed: the versions stay separate.
async function sharedPaths(left, right, roadmapPath, cache) {
  try {
    const heads = [left.git.headCommit, right.git.headCommit].sort().join(":");
    let base = cache.bases.get(heads);
    if (base === undefined) {
      base = await git(left.repoRoot, "merge-base", left.git.headCommit, right.git.headCommit);
      cache.bases.set(heads, base);
    }
    if (!/^[0-9a-f]{40,64}$/i.test(base)) throw new Error("invalid merge base");
    const dirs = [path.posix.join(roadmapPath, "features"), path.posix.join(roadmapPath, "ideas")];
    const treeKey = `${base}:${roadmapPath}`;
    let tree = cache.trees.get(treeKey);
    if (!tree) {
      const records = (await git(left.repoRoot, "ls-tree", "-r", "-z", "--long", base, "--", ...dirs))
        .split("\0").filter(Boolean).map((record) => {
          const match = record.match(/^[0-7]{6} blob ([0-9a-f]{40,64}) +\d+\t([\s\S]*)$/i);
          if (!match) throw new Error("ambiguous ancestor tree");
          return { oid: match[1], file: match[2] };
        });
      const objects = records.filter((entry) => !/[\r\n]/.test(entry.file) && entry.file.endsWith(".md"));
      const parsed = objects.length ? await ancestorBlobs(left.repoRoot, objects) : { ids: new Map(), invalid: false };
      tree = { ids: parsed.ids, uncertainty: parsed.invalid || records.length !== objects.length && records.some((entry) => /[\r\n]/.test(entry.file))
        ? "ancestor-item-or-path-invalid" : null };
      cache.trees.set(treeKey, tree);
    }
    const deleted = new Set();
    for (const source of [left, right]) {
      const key = `${base}:${source.git.headCommit}`;
      let paths = cache.deletions.get(key);
      if (!paths) {
        const output = await git(source.repoRoot, "log", "-z", "--format=", "--name-only", "--diff-filter=D", "--no-renames", `${base}..${source.git.headCommit}`, "--", ...dirs);
        paths = new Set(output.split("\0").filter(Boolean));
        cache.deletions.set(key, paths);
      }
      for (const file of paths) deleted.add(file);
    }
    return { paths: new Map([...tree.ids].filter(([file]) => !deleted.has(file))), uncertainty: tree.uncertainty };
  } catch (error) {
    return { paths: new Map(), uncertainty: error.message === "ancestor item limit" ? "ancestor-item-limit" : "git-evidence-unavailable" };
  }
}

async function conflicts(versions, displayRevisions) {
  if (versions.length < 2) return [];
  const fields = ["title", "status", "priority", "commitment", "milestone", "kind"];
  const differences = fields.flatMap((field) => {
    const values = versions.map((version) => ({ field, sourceKey: version.sourceKey, value: version.summary[field] ?? "" }));
    return new Set(values.map((entry) => JSON.stringify(entry.value))).size > 1 ? values : [];
  });
  if (new Set(versions.map((version) => version.summary.revision)).size < 2) return differences;
  const normalized = await Promise.all(versions.map((version) => {
    const key = `${version.sourceKey}:${version.itemId}`;
    const file = path.isAbsolute(version.summary.filePath) ? version.summary.filePath
      : path.resolve(version.repoRoot, version.summary.filePath);
    if (!displayRevisions.has(key)) displayRevisions.set(key, fs.readFile(file, "utf8")
      .then((raw) => {
        const text = raw.replace(/^\uFEFF/, "");
        return hash(text) === version.summary.revision ? hash(text.replace(/\r\n?/g, "\n")) : version.summary.revision;
      })
      .catch(() => version.summary.revision));
    return displayRevisions.get(key);
  }));
  versions.forEach((version, index) => { version.displayRevision = normalized[index]; });
  if (new Set(normalized).size > 1) differences.push(...versions.map((version) => ({ field: "revision",
    sourceKey: version.sourceKey, value: version.summary.revision })));
  return differences;
}

/** Read-only, opened-first projection of compatible linked worktrees. */
export async function loadWorktreeAggregate(openRepoRoot, { openedOnly = false } = {}) {
  let discovery;
  if (openedOnly) {
    const opened = await readWorktreeIdentity(openRepoRoot);
    discovery = { sources: opened ? [opened] : [], excluded: [], partial: false,
      unavailable: opened ? null : { reason: "not-git-or-unavailable" } };
  } else discovery = await discoverWorktreeSources(openRepoRoot);
  const result = { ...discovery, workspace: null, features: [], groups: [],
    coverage: { loaded: 0, excluded: 0, missingBoardRefs: [], identityUncertain: [] } };
  if (openedOnly) {
    result.provisional = true;
    result.partial = true;
    result.coverage.pending = true;
  }
  if (!discovery.sources.length) return result;
  if (discovery.unavailable) result.partial = true;

  const loaded = [];
  for (const source of discovery.sources) {
    try {
      await requireRoadmapInSource(source.repoRoot);
      const workspace = await loadWorkspace(source.repoRoot);
      source.roadmapBinding = { roadmapPath: workspace.roadmapPath, resolvedPath: workspace.resolvedPath };
      source.availableLenses = workspace.availableLenses;
      source.availableFilters = workspace.availableFilters;
      if (source === discovery.sources[0]) result.workspace = workspace;
      else if (path.normalize(workspace.roadmapPath) !== path.normalize(result.workspace.roadmapPath)) {
        result.excluded.push({ repoRoot: source.repoRoot, sourceKey: source.sourceKey, reason: "incompatible-roadmap-config" });
        continue;
      }
      loaded.push({ ...source, workspace });
    } catch (error) {
      result.excluded.push({ repoRoot: source.repoRoot, sourceKey: source.sourceKey,
        reason: "workspace-load-failed", code: error.code || null, message: error.message });
      if (source === discovery.sources[0]) {
        result.unavailable = { reason: "opened-workspace-load-failed", code: error.code || null, message: error.message };
        result.partial = true;
        result.coverage.excluded = result.excluded.length;
        return result;
      }
    }
  }
  result.coverage.loaded = loaded.length;
  result.coverage.excluded = result.excluded.length;
  if (!loaded.length) { result.unavailable = { reason: "no-loadable-workspace" }; return result; }
  if (result.excluded.length) result.partial = true;

  for (const source of loaded.slice(1)) {
    for (const field of ["availableLenses", "availableFilters"]) {
      for (const entry of source.workspace[field]) {
        const existing = result.workspace[field].find((candidate) => candidate.key === entry.key);
        if (!existing) result.workspace[field].push({ ...entry });
        else for (const value of entry.values || []) {
          if (!existing.values.includes(value)) existing.values.push(value);
        }
      }
    }
  }

  const lineage = new Map();
  const evidenceCache = { bases: new Map(), trees: new Map(), deletions: new Map() };
  for (let i = 0; i < loaded.length; i += 1) {
    for (let j = i + 1; j < loaded.length; j += 1) {
      const evidence = await sharedPaths(loaded[i], loaded[j], relative(loaded[i].repoRoot, loaded[i].workspace.resolvedPath), evidenceCache);
      lineage.set(`${i}:${j}`, evidence.paths);
      if (evidence.uncertainty) {
        result.partial = true;
        result.coverage.identityUncertain.push({ leftSourceKey: loaded[i].sourceKey,
          rightSourceKey: loaded[j].sourceKey, reason: evidence.uncertainty });
      }
    }
  }
  const features = [];
  const displayRevisions = new Map();
  const groupMap = new Map();
  const appearanceOrder = [];
  for (const [sourceIndex, source] of loaded.entries()) {
    const sourceContext = { sourceKey: source.sourceKey, repoRoot: source.repoRoot,
      label: source.label, git: source.git, roadmapBinding: source.roadmapBinding };
    const memberships = new Map();
    for (const group of source.workspace.boardGroups) {
      const groupKey = `board:${group.name}`;
      if (!groupMap.has(groupKey)) groupMap.set(groupKey, { name: group.name, kind: "board", items: [] });
      for (const item of group.items) {
        if (item.missing) {
          const key = hash(`${source.sourceKey}\0missing\0${group.name}\0${item.id}`);
          const version = { sourceKey: source.sourceKey, repoRoot: source.repoRoot, itemId: item.id,
            summary: item, group: group.name, groupKind: "board", sourceContext };
          appearanceOrder.push({ groupKey, missing: { key, id: item.id, missing: true, versions: [version], conflicts: [] } });
          result.coverage.missingBoardRefs.push({ sourceKey: source.sourceKey, group: group.name, itemId: item.id });
        } else {
          const names = memberships.get(item.id) || [];
          names.push(group.name);
          memberships.set(item.id, names);
          appearanceOrder.push({ groupKey, sourceIndex, id: item.id });
        }
      }
    }
    for (const [id, summary] of Object.entries(source.workspace.items)) {
      const filePath = relative(source.repoRoot, summary.filePath);
      const match = features.find((feature) => feature.id === id && feature.filePath === filePath
        && feature.sourceIndexes.every((other) => lineage.get(`${Math.min(other, sourceIndex)}:${Math.max(other, sourceIndex)}`)?.get(filePath) === id));
      const feature = match || { key: hash(`${source.sourceKey}\0${id}\0${filePath}`), id, filePath,
        versions: [], groups: [], conflicts: [], sourceIndexes: [] };
      if (!match) features.push(feature);
      feature.sourceIndexes.push(sourceIndex);
      for (const groupName of memberships.get(id) || ["Not on a board"]) {
        const groupKind = memberships.has(id) ? "board" : "unlisted";
        const groupKey = groupKind === "board" ? `board:${groupName}` : "unlisted";
        if (!groupMap.has(groupKey)) groupMap.set(groupKey, { name: groupName, kind: groupKind, items: [] });
        const version = { sourceKey: source.sourceKey, repoRoot: source.repoRoot, itemId: id,
          summary, group: groupName, groupKind, sourceContext };
        feature.versions.push(version);
        if (!feature.groups.some((entry) => entry.name === groupName && entry.kind === groupKind)) feature.groups.push({ name: groupName, kind: groupKind });
        if (!memberships.has(id)) appearanceOrder.push({ groupKey, sourceIndex, id });
      }
    }
  }
  for (const feature of features) {
    feature.conflicts = await conflicts(feature.versions, displayRevisions);
    delete feature.sourceIndexes;
  }
  for (const appearance of appearanceOrder) {
    const group = groupMap.get(appearance.groupKey);
    if (appearance.missing) { group.items.push(appearance.missing); continue; }
    const feature = features.find((entry) => entry.id === appearance.id
      && entry.versions.some((version) => version.sourceKey === loaded[appearance.sourceIndex].sourceKey));
    if (group.items.some((item) => item.key === feature.key)) continue;
    const versions = feature.versions.filter((version) => `${version.groupKind === "board" ? "board:" + version.group : "unlisted"}` === appearance.groupKey);
    group.items.push({ key: feature.key, id: feature.id, versions, conflicts: await conflicts(versions, displayRevisions) });
  }
  for (const source of loaded) {
    const current = await readWorktreeIdentity(source.repoRoot);
    if (!current || current.sourceKey !== source.sourceKey || current.repoRoot !== source.repoRoot
      || JSON.stringify(current.git) !== JSON.stringify(source.git)) {
      result.partial = true;
      result.unavailable = { reason: "source-changed-during-read", message: "A checkout changed while the combined board loaded. Refresh to read one consistent snapshot." };
      result.coverage.identityUncertain.push({ sourceKey: source.sourceKey, reason: "source-changed-during-read" });
      result.workspace = null;
      return result;
    }
  }
  result.features = features;
  result.groups = [...groupMap.values()];
  return result;
}
