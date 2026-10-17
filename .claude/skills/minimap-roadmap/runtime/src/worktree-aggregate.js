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

async function git(root, ...argsAndOptions) {
  const last = argsAndOptions.at(-1);
  const options = last && typeof last === "object" && Object.hasOwn(last, "signal") ? argsAndOptions.pop() : {};
  const args = argsAndOptions;
  return (await execFileAsync("git", args, {
    cwd: root, windowsHide: true, shell: false, timeout: 5000,
    maxBuffer: 4 * 1024 * 1024, encoding: "utf8", signal: options.signal,
  })).stdout.trim();
}

async function ancestorBlobs(root, objects, signal) {
  if (objects.length > 500) throw new Error("ancestor item limit");
  const output = await new Promise((resolve, reject) => {
    const child = spawn("git", ["cat-file", "--batch"], { cwd: root, windowsHide: true, shell: false, signal });
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

const transitionKey = (changes) => hash(JSON.stringify([...changes].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)));

// Batch complete repository transitions, not one Git process per item or commit.
async function transitionHistory(source, base, cache, signal) {
  const key = `${base}:${source.git.headCommit}`;
  if (!cache.histories.has(key)) cache.histories.set(key, (async () => {
    if (cache.historyLoads >= 32) throw new Error("squash-evidence-limit");
    cache.historyLoads += 1;
    const raw = await git(source.repoRoot, "log", "--raw", "-z", "--no-abbrev", "--no-renames",
      "--first-parent", "--diff-merges=first-parent", "--max-count=65", "--format=%x00commit %H %P%x00",
      `${base}..${source.git.headCommit}`, { signal });
    const tokens = raw.split("\0"), commits = [];
    for (let i = 0; i < tokens.length; i += 1) {
      const token = tokens[i].replace(/^\n/, "");
      if (!token) continue;
      const header = token.match(/^commit ([0-9a-f]{40,64}) ((?:[0-9a-f]{40,64})(?: [0-9a-f]{40,64})*)$/i);
      if (header) {
        if (commits.length >= 64) throw new Error("squash-evidence-limit");
        const parents = header[2].split(" ");
        commits.push({ commit: header[1], parent: parents[0], merge: parents.length > 1, changes: new Map() });
        continue;
      }
      const change = token.match(/^:([0-7]{6}) ([0-7]{6}) ([0-9a-f]{40,64}) ([0-9a-f]{40,64}) [AMDT]$/i);
      const file = tokens[++i];
      if (!change || !commits.length || !file || /[\r\n]/.test(file)
        || commits.at(-1).changes.has(file)) throw new Error("squash-evidence-unavailable");
      if (cache.historyChanges >= 8192) throw new Error("squash-evidence-limit");
      cache.historyChanges += 1;
      commits.at(-1).changes.set(file, change.slice(1));
    }
    commits.reverse();
    let parent = base;
    const cumulative = new Map(), prefixes = [];
    for (const entry of commits) {
      if (entry.parent !== parent) throw new Error("squash-evidence-unavailable");
      parent = entry.commit;
      entry.signature = transitionKey(entry.changes);
      for (const [file, [oldMode, mode, oldOid, oid]] of entry.changes) {
        const previous = cumulative.get(file);
        if (previous && (previous[1] !== oldMode || previous[3] !== oldOid)) throw new Error("squash-evidence-unavailable");
        const change = [previous?.[0] ?? oldMode, mode, previous?.[2] ?? oldOid, oid];
        if (change[0] === mode && change[2] === oid) cumulative.delete(file);
        else cumulative.set(file, change);
      }
      prefixes.push({ signature: transitionKey(cumulative), additions: new Map([...cumulative]
        .filter(([, change]) => change[0] === "000000" && /^100(644|755)$/.test(change[1]))
        .map(([file, change]) => [file, change[3]])) });
    }
    if (parent !== source.git.headCommit) throw new Error("squash-evidence-unavailable");
    return { commits, prefixes };
  })());
  return cache.histories.get(key);
}

async function squashPaths(left, right, base, candidates, cache, signal) {
  const histories = [await transitionHistory(left, base, cache, signal), await transitionHistory(right, base, cache, signal)];
  const objects = new Map();
  for (const [index, history] of histories.entries()) {
    const integrations = new Set(histories[1 - index].commits.filter((entry) => !entry.merge).map((entry) => entry.signature));
    for (const prefix of history.prefixes) {
      if (!integrations.has(prefix.signature)) continue;
      for (const file of candidates.keys()) {
        const oid = prefix.additions.get(file);
        if (!oid) continue;
        if (objects.has(file) && objects.get(file) !== oid) throw new Error("squash-evidence-unavailable");
        objects.set(file, oid);
      }
    }
  }
  const parsed = objects.size ? await ancestorBlobs(left.repoRoot, [...objects].map(([file, oid]) => ({ file, oid })), signal)
    : { ids: new Map(), invalid: false };
  return { paths: new Map([...parsed.ids].filter(([file, id]) => candidates.get(file) === id)),
    uncertainty: parsed.invalid ? "squash-item-invalid" : null };
}

// Shared ancestry or exact whole-change squash equivalence establishes display identity.
// Git cannot distinguish an independently reproduced identical complete change.
// Missing Git evidence cannot create a direct proof; other proven links may still connect versions.
export async function sharedPaths(left, right, roadmapPath, cache, signal) {
  const breaks = new Set();
  try {
    const heads = [left.git.headCommit, right.git.headCommit].sort().join(":");
    let base = cache.bases.get(heads);
    if (base === undefined) {
      base = await git(left.repoRoot, "merge-base", left.git.headCommit, right.git.headCommit, { signal });
      cache.bases.set(heads, base);
    }
    if (!/^[0-9a-f]{40,64}$/i.test(base)) throw new Error("invalid merge base");
    const dirs = [path.posix.join(roadmapPath, "features"), path.posix.join(roadmapPath, "ideas")];
    const treeKey = `${base}:${roadmapPath}`;
    let tree = cache.trees.get(treeKey);
    if (!tree) {
      const records = (await git(left.repoRoot, "ls-tree", "-r", "-z", "--long", base, "--", ...dirs, { signal }))
        .split("\0").filter(Boolean).map((record) => {
          const match = record.match(/^[0-7]{6} blob ([0-9a-f]{40,64}) +\d+\t([\s\S]*)$/i);
          if (!match) throw new Error("ambiguous ancestor tree");
          return { oid: match[1], file: match[2] };
        });
      const objects = records.filter((entry) => !/[\r\n]/.test(entry.file) && entry.file.endsWith(".md"));
      let parsed;
      try {
        parsed = objects.length ? await ancestorBlobs(left.repoRoot, objects, signal) : { ids: new Map(), invalid: false };
      } catch (error) {
        if (signal?.aborted) throw signal.reason || error;
        if (error.message !== "ancestor item limit") throw error;
        // This fixed tree exceeds the cap for every pair in this request.
        cache.trees.set(treeKey, { ids: new Map(), uncertainty: "ancestor-item-limit" });
        throw error;
      }
      tree = { ids: parsed.ids, uncertainty: parsed.invalid || records.length !== objects.length && records.some((entry) => /[\r\n]/.test(entry.file))
        ? "ancestor-item-or-path-invalid" : null };
      cache.trees.set(treeKey, tree);
    }
    if (tree.uncertainty === "ancestor-item-limit") return { paths: new Map(), breaks: new Set(), uncertainty: tree.uncertainty };
    for (const [id, summary] of Object.entries(left.workspace.items)) {
      const file = relative(left.repoRoot, summary.filePath);
      const other = right.workspace.items[id];
      if (other && relative(right.repoRoot, other.filePath) === file
        && tree.ids.has(file) && tree.ids.get(file) !== id) breaks.add(file);
    }
    for (const source of [left, right]) {
      const key = `${base}:${source.git.headCommit}`;
      let paths = cache.deletions.get(key);
      if (!paths) {
        const output = await git(source.repoRoot, "log", "-z", "--format=", "--name-only", "--diff-filter=D", "--no-renames",
          "--diff-merges=first-parent", `${base}..${source.git.headCommit}`, "--", ...dirs, { signal });
        paths = new Set(output.split("\0").filter(Boolean));
        cache.deletions.set(key, paths);
      }
      for (const file of paths) breaks.add(file);
    }
    const paths = new Map([...tree.ids].filter(([file]) => !breaks.has(file)));
    const candidates = new Map();
    for (const [id, summary] of Object.entries(left.workspace.items)) {
      const file = relative(left.repoRoot, summary.filePath);
      const other = right.workspace.items[id];
      if (!tree.ids.has(file) && !breaks.has(file) && other
        && relative(right.repoRoot, other.filePath) === file) candidates.set(file, id);
    }
    let uncertainty = tree.uncertainty;
    if (candidates.size) {
      try {
        const squash = await squashPaths(left, right, base, candidates, cache, signal);
        for (const [file, id] of squash.paths) paths.set(file, id);
        uncertainty ||= squash.uncertainty;
      } catch (error) {
        if (signal?.aborted) throw signal.reason || error;
        uncertainty ||= error.message === "squash-evidence-limit" ? error.message : "squash-evidence-unavailable";
      }
    }
    return { paths, breaks, uncertainty };
  } catch (error) {
    if (signal?.aborted) throw signal.reason || error;
    return { paths: new Map(), breaks, uncertainty: error.message === "ancestor item limit" ? "ancestor-item-limit" : "git-evidence-unavailable" };
  }
}

// A chain of positive proofs identifies the same feature. Explicit identity breaks
// anywhere inside a chain invalidate the whole component, regardless of source order.
export function groupFeatureSources(sourcesByIdentity, lineage) {
  const groupBySource = new Map();
  const contradictions = [];
  for (const [identity, indexes] of sourcesByIdentity) {
    const [id, filePath] = JSON.parse(identity);
    const remaining = new Set(indexes);
    while (remaining.size) {
      const component = new Set([remaining.values().next().value]);
      const queue = [...component];
      remaining.delete(queue[0]);
      for (const sourceIndex of queue) {
        for (const other of [...remaining]) {
          const evidence = lineage.get(`${Math.min(sourceIndex, other)}:${Math.max(sourceIndex, other)}`);
          if (evidence?.paths.get(filePath) !== id) continue;
          component.add(other);
          queue.push(other);
          remaining.delete(other);
        }
      }
      const members = [...component].sort((a, b) => a - b);
      const broken = members.some((left, i) => members.slice(i + 1).some((right) =>
        lineage.get(`${left}:${right}`)?.breaks.has(filePath)));
      if (broken) contradictions.push({ id, filePath, sourceIndexes: members });
      for (const index of members) groupBySource.set(`${identity}:${index}`, `${identity}:${broken ? index : members[0]}`);
    }
  }
  return { groupBySource, contradictions };
}

async function conflicts(versions, displayRevisions, signal) {
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
    if (!displayRevisions.has(key)) displayRevisions.set(key, fs.readFile(file, { encoding: "utf8", signal })
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
export async function loadWorktreeAggregate(openRepoRoot, { openedOnly = false, signal } = {}) {
  if (signal?.aborted) throw signal.reason;
  let discovery;
  if (openedOnly) {
    const opened = await readWorktreeIdentity(openRepoRoot, { signal });
    discovery = { sources: opened ? [opened] : [], excluded: [], partial: false,
      unavailable: opened ? null : { reason: "not-git-or-unavailable" } };
  } else discovery = await discoverWorktreeSources(openRepoRoot, { signal });
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
    if (signal?.aborted) throw signal.reason;
    try {
      await requireRoadmapInSource(source.repoRoot, { signal });
      const workspace = await loadWorkspace(source.repoRoot, { signal });
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
      if (signal?.aborted) throw signal.reason || error;
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
  Object.defineProperty(result, "snapshotChecks", { value: loaded.map((source) => ({
    sourceKey: source.sourceKey, workspace: source.workspace,
  })), enumerable: false });
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
  const evidenceCache = { bases: new Map(), trees: new Map(), deletions: new Map(),
    histories: new Map(), historyLoads: 0, historyChanges: 0 };
  for (let i = 0; i < loaded.length; i += 1) {
    for (let j = i + 1; j < loaded.length; j += 1) {
      if (signal?.aborted) throw signal.reason;
      const evidence = await sharedPaths(loaded[i], loaded[j], relative(loaded[i].repoRoot, loaded[i].workspace.resolvedPath), evidenceCache, signal);
      lineage.set(`${i}:${j}`, evidence);
      if (evidence.uncertainty) {
        result.partial = true;
        result.coverage.identityUncertain.push({ leftSourceKey: loaded[i].sourceKey,
          rightSourceKey: loaded[j].sourceKey, reason: evidence.uncertainty });
      }
    }
  }
  const sourcesByIdentity = new Map();
  for (const [sourceIndex, source] of loaded.entries()) for (const [id, summary] of Object.entries(source.workspace.items)) {
    const identity = JSON.stringify([id, relative(source.repoRoot, summary.filePath)]);
    if (!sourcesByIdentity.has(identity)) sourcesByIdentity.set(identity, []);
    sourcesByIdentity.get(identity).push(sourceIndex);
  }
  const { groupBySource, contradictions } = groupFeatureSources(sourcesByIdentity, lineage);
  for (const entry of contradictions) {
    result.partial = true;
    result.coverage.identityUncertain.push({ reason: "identity-conflict", itemId: entry.id, filePath: entry.filePath,
      sourceKeys: entry.sourceIndexes.map((index) => loaded[index].sourceKey) });
  }
  const features = [];
  const featureCandidates = new Map();
  const featuresBySource = [];
  const displayRevisions = new Map();
  const groupMap = new Map();
  const appearanceOrder = [];
  for (const [sourceIndex, source] of loaded.entries()) {
    const sourceFeatures = new Map();
    featuresBySource.push(sourceFeatures);
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
      const candidateKey = JSON.stringify([id, filePath]);
      const groupKey = groupBySource.get(`${candidateKey}:${sourceIndex}`);
      const match = featureCandidates.get(groupKey);
      const feature = match || { key: hash(`${source.sourceKey}\0${id}\0${filePath}`), id, filePath,
        versions: [], groups: [], conflicts: [] };
      if (!match) { features.push(feature); featureCandidates.set(groupKey, feature); }
      sourceFeatures.set(id, feature);
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
    feature.conflicts = await conflicts(feature.versions, displayRevisions, signal);
  }
  const groupItemKeys = new Map([...groupMap.keys()].map((key) => [key, new Set()]));
  for (const appearance of appearanceOrder) {
    const group = groupMap.get(appearance.groupKey);
    const itemKeys = groupItemKeys.get(appearance.groupKey);
    if (appearance.missing) { group.items.push(appearance.missing); itemKeys.add(appearance.missing.key); continue; }
    const feature = featuresBySource[appearance.sourceIndex].get(appearance.id);
    if (itemKeys.has(feature.key)) continue;
    itemKeys.add(feature.key);
    const versions = feature.versions.filter((version) => `${version.groupKind === "board" ? "board:" + version.group : "unlisted"}` === appearance.groupKey);
    group.items.push({ key: feature.key, id: feature.id, versions, conflicts: await conflicts(versions, displayRevisions, signal) });
  }
  for (const source of loaded) {
    const current = await readWorktreeIdentity(source.repoRoot, { signal });
    if (!current) {
      result.partial = true;
      result.unavailable = { reason: "source-identity-unavailable", message: "A checkout could not be revalidated while the combined board loaded." };
      result.coverage.identityUncertain.push({ sourceKey: source.sourceKey, reason: "source-identity-unavailable" });
      result.workspace = null;
      return result;
    }
    if (current.sourceKey !== source.sourceKey || current.repoRoot !== source.repoRoot
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
