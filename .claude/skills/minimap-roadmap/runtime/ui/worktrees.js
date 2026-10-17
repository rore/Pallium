import { getItemLensGroupValue, itemMatchesFilters } from "./filters.js";

const UNASSIGNED_KEY = "__unassigned__";
const UNASSIGNED_LABEL = "Unassigned";
const CONFLICT_FIELDS = ["title", "status", "priority", "commitment", "milestone", "kind", "revision"];

export function versionDifferences(version, selected) {
  if (!selected || version.sourceKey === selected.sourceKey) return [];
  const differences = CONFLICT_FIELDS.filter((field) => field !== "revision")
    .filter((field) => JSON.stringify(version.summary[field] ?? "") !== JSON.stringify(selected.summary[field] ?? ""))
    .map((field) => `${field[0].toUpperCase()}${field.slice(1)}: ${version.summary[field] || "not set"} (selected: ${selected.summary[field] || "not set"})`);
  if ((version.displayRevision ?? version.summary.revision) !== (selected.displayRevision ?? selected.summary.revision)) differences.push("Content differs");
  return differences;
}

function conflictsForVersions(versions) {
  return CONFLICT_FIELDS.flatMap((field) => {
    const entries = versions.map((version) => ({ field, sourceKey: version.sourceKey, value: version.summary[field] ?? "" }));
    const compared = field === "revision"
      ? versions.map((version) => version.displayRevision ?? version.summary.revision ?? "")
      : entries.map((entry) => entry.value);
    return new Set(compared.map((value) => JSON.stringify(value))).size > 1 ? entries : [];
  });
}

function canonicalId(id) {
  return encodeURIComponent(String(id).normalize("NFC")).replace(/[!'()*]/g, (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`);
}

export function projectWorktreeGroups(aggregate, {
  lens = "board", searchQuery = "", activeFilters = {}, inPlay = false,
  participantCounts = new Map(), showEmptyGroups = false,
} = {}) {
  if (!aggregate) return [];
  const filtersActive = Boolean(searchQuery || inPlay || Object.keys(activeFilters).length);
  const definitions = aggregate.workspace?.availableLenses || [];
  const definition = definitions.find((entry) => entry.key === lens);
  const derived = lens !== "board" && Boolean(definition);
  const preferred = derived ? definition.values || [] : [];
  const groups = new Map();
  const addGroup = (key, name, kind, originalIndex) => {
    if (!groups.has(key)) groups.set(key, { name, kind, groupKey: key, originalIndex, items: [] });
    return groups.get(key);
  };

  if (derived) preferred.forEach((name, index) => addGroup(name, name, "derived", index));
  else aggregate.groups.forEach((group, index) => addGroup(`${group.kind}:${group.name}`, group.name, group.kind, index));

  const idCounts = new Map();
  const featuresByKey = new Map(aggregate.features.map((feature) => [feature.key, feature]));
  for (const feature of aggregate.features) {
    const id = canonicalId(feature.id);
    idCounts.set(id, (idCounts.get(id) || 0) + 1);
  }
  for (const group of aggregate.groups || []) {
    for (const item of group.items || []) {
      const feature = featuresByKey.get(item.key);
      if (!feature && item.missing) {
        if (!filtersActive && !derived) addGroup(`${group.kind}:${group.name}`, group.name, group.kind, 0).items.push({ ...item, title: item.id, sourceVersion: item.versions?.[0] });
        continue;
      }
      if (!feature) continue;
      const versions = item.versions.filter((version) => itemMatchesFilters({
        ...version.summary, id: version.itemId, searchText: version.summary.searchText,
      }, {
        searchQuery, activeFilters,
        inPlay,
        participantCounts: new Map([[version.itemId, { participantCount: idCounts.get(canonicalId(feature.id)) > 1 ? 0 : participantCounts.get(feature.key)?.participantCount || 0 }]]),
      }));
      if (!versions.length) continue;
      const byGroup = new Map();
      for (const version of versions) {
        const name = derived && version.groupKind !== "unlisted"
          ? (getItemLensGroupValue(version.summary, lens, { defaultLensKey: "board", unassignedKey: UNASSIGNED_KEY }) || UNASSIGNED_KEY)
          : version.group;
        const kind = derived && version.groupKind !== "unlisted" ? "derived" : version.groupKind;
        const key = derived && kind === "derived" ? name : `${kind}:${name}`;
        if (!byGroup.has(key)) byGroup.set(key, { name: name === UNASSIGNED_KEY ? UNASSIGNED_LABEL : name, kind, versions: [] });
        byGroup.get(key).versions.push(version);
      }
      for (const [key, entry] of byGroup) {
        const index = derived ? preferred.indexOf(entry.name) : aggregate.groups.findIndex((value) => value.kind === entry.kind && value.name === entry.name);
        const projected = addGroup(key, entry.name, entry.kind, index < 0 ? preferred.length + groups.size : index);
        const appearanceId = JSON.stringify([feature.key, entry.kind, entry.name]);
        const existing = derived && projected.items.find((card) => card.featureKey === feature.key);
        if (existing) {
          const sources = new Set(existing.matchingVersions.map((version) => `${version.sourceKey}\0${version.groupKind}\0${version.group}`));
          existing.matchingVersions.push(...entry.versions.filter((version) => !sources.has(`${version.sourceKey}\0${version.groupKind}\0${version.group}`)));
          const sourceOrder = new Map(feature.versions.map((version, order) => [`${version.sourceKey}\0${version.groupKind}\0${version.group}`, order]));
          existing.matchingVersions.sort((left, right) => sourceOrder.get(`${left.sourceKey}\0${left.groupKind}\0${left.group}`) - sourceOrder.get(`${right.sourceKey}\0${right.groupKind}\0${right.group}`));
          existing.versions = existing.matchingVersions;
          existing.sourceVersion = existing.matchingVersions[0];
          existing.conflicts = conflictsForVersions(existing.matchingVersions);
          Object.assign(existing, existing.sourceVersion.summary, {
            id: appearanceId, featureKey: feature.key, versions: existing.matchingVersions,
            matchingVersions: existing.matchingVersions, conflicts: existing.conflicts,
            sourceVersion: existing.sourceVersion,
          });
          continue;
        }
        projected.items.push({ ...entry.versions[0].summary, id: appearanceId, featureKey: feature.key,
          title: entry.versions[0].summary.title || feature.id, versions: entry.versions, matchingVersions: entry.versions,
          conflicts: conflictsForVersions(entry.versions), sourceVersion: entry.versions[0] });
      }
    }
  }
  return [...groups.values()].filter((group) => group.items.length || (showEmptyGroups && !inPlay && derived))
    .sort((a, b) => a.originalIndex - b.originalIndex || a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }));
}

export function countDistinctWorktreeFeatures(groups) {
  return new Set(groups.flatMap((group) => group.items.filter((item) => !item.missing).map((item) => item.featureKey || item.id))).size;
}

/** Retain only the current view. Consumers must treat its groups/items as read-only. */
export function createWorktreeProjector() {
  let previous;
  return (aggregate, options = {}) => {
    const signature = JSON.stringify([options.lens, options.searchQuery, options.activeFilters, options.inPlay, options.showEmptyGroups]);
    if (previous?.aggregate === aggregate && previous.signature === signature && previous.counts === options.participantCounts) return previous.result;
    const groups = projectWorktreeGroups(aggregate, options);
    const items = new Map(groups.flatMap((group) => group.items.filter((item) => !item.missing).map((item) => [item.id, item])));
    const result = { groups, items };
    previous = { aggregate, signature, counts: options.participantCounts, result };
    return result;
  };
}
