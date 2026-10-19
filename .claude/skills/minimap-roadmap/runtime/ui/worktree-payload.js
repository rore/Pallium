// One wire representation for worktree snapshots; no DOM or runtime dependencies.
const FORMAT = "compact-v1";
function invalid() {
  throw Object.assign(new Error("Invalid compact worktree workspace. Reload the workspace."),
    { code: "invalid_worktree_payload" });
}
function table(entries, key) {
  if (!Array.isArray(entries)) invalid();
  const result = new Map();
  for (const entry of entries) {
    if (!entry || typeof entry[key] !== "string" || result.has(entry[key])) invalid();
    result.set(entry[key], entry);
  }
  return result;
}
function withoutContext(version) {
  const { sourceContext, ...result } = version;
  return result;
}

export function compactWorktreePayload(payload) {
  const features = table(payload.features, "key");
  return { ...payload, worktreeFormat: FORMAT,
    features: payload.features.map((feature) => ({ ...feature, versions: feature.versions.map(withoutContext) })),
    groups: payload.groups.map((group) => ({ ...group, items: group.items.map((row) => {
      if (row.missing) return { ...row, versions: row.versions.map(withoutContext) };
      const feature = features.get(row.key);
      if (!feature) invalid();
      const { versions, ...rest } = row;
      return { ...rest, versionIndexes: versions.map((version) => {
        const index = feature.versions.findIndex((candidate) => candidate.sourceKey === version.sourceKey
          && candidate.group === version.group && candidate.groupKind === version.groupKind);
        if (index === -1) invalid();
        return index;
      }) };
    }) })),
  };
}

export function expandWorktreePayload(payload) {
  if (!payload || !Object.hasOwn(payload, "worktreeFormat")) return payload;
  if (payload.worktreeFormat !== FORMAT) invalid();
  const sources = table(payload.sources, "sourceKey");
  const contexts = new Map([...sources].map(([key, source]) => [key, {
    sourceKey: source.sourceKey, repoRoot: source.repoRoot, label: source.label,
    git: source.git, roadmapBinding: source.roadmapBinding,
  }]));
  const expandVersion = (version) => {
    const sourceContext = contexts.get(version?.sourceKey);
    if (!sourceContext) invalid();
    return { ...version, sourceContext };
  };
  const features = table(payload.features, "key");
  const expanded = new Map([...features].map(([key, feature]) => {
    if (!Array.isArray(feature.versions)) invalid();
    return [key, { ...feature, versions: feature.versions.map(expandVersion) }];
  }));
  if (!Array.isArray(payload.groups)) invalid();
  const { worktreeFormat, ...rest } = payload;
  return { ...rest, features: [...expanded.values()], groups: payload.groups.map((group) => {
    if (!Array.isArray(group.items)) invalid();
    return { ...group, items: group.items.map((row) => {
      if (row.missing) {
        if (!Array.isArray(row.versions)) invalid();
        return { ...row, versions: row.versions.map(expandVersion) };
      }
      const feature = expanded.get(row.key);
      if (!feature || feature.id !== row.id || !Array.isArray(row.versionIndexes)) invalid();
      const { versionIndexes, ...item } = row;
      return { ...item, versions: versionIndexes.map((index) => {
        if (!Number.isInteger(index) || index < 0 || index >= feature.versions.length) invalid();
        const version = feature.versions[index];
        if (version.group !== group.name || version.groupKind !== group.kind) invalid();
        return version;
      }) };
    }) };
  }) };
}
