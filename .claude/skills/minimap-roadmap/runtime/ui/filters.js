// package/minimap/ui/filters.js
//
// Pure functional core of the board filter / lens / group derivation logic.
// DOM-free, state-free — every function takes its inputs as arguments. The
// state-aware variants (itemMatchesCurrentFilters, getFilteredBoardItemIds,
// getVisibleBoardGroups) live in app.js as thin shims that read state and
// delegate here.

export function normalizeFilterValues(value) {
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry).trim()).filter(Boolean);
  }
  const normalized = String(value ?? "").trim();
  return normalized ? [normalized] : [];
}

export function normalizeFilterMap(filters) {
  const normalized = {};
  for (const [key, values] of Object.entries(filters || {})) {
    const cleanKey = String(key || "").trim();
    const cleanValues = Array.from(new Set(normalizeFilterValues(values))).sort((left, right) => left.localeCompare(right));
    if (!cleanKey || cleanValues.length === 0) continue;
    normalized[cleanKey] = cleanValues;
  }
  return normalized;
}

export function itemMatchesFilters(item, ctx = {}) {
  if (!item) return false;
  const { searchQuery = "", activeFilters = {} } = ctx;
  if (searchQuery && !String(item.searchText || "").includes(searchQuery)) return false;
  for (const [key, selectedValues] of Object.entries(activeFilters)) {
    const itemValues = normalizeFilterValues(item.metadata?.[key]);
    if (!selectedValues.some((value) => itemValues.includes(value))) return false;
  }
  return true;
}

export function filterBoardItemIds(workspace, ctx = {}) {
  if (!workspace) return [];
  const orderedIds = workspace.boardGroups.flatMap((group) =>
    group.items.filter((item) => !item.missing).map((item) => item.id),
  );
  const searchActive = Boolean(ctx.searchQuery) || (ctx.activeFilters && Object.keys(ctx.activeFilters).length > 0);
  if (!searchActive) return orderedIds;
  return orderedIds.filter((itemId) => itemMatchesFilters(workspace.items?.[itemId], ctx));
}

export function getItemLensGroupValue(item, lensKey, opts) {
  const { defaultLensKey, unassignedKey } = opts || {};
  if (!item || lensKey === defaultLensKey) return "";
  if (lensKey === "kind") return item.kind || unassignedKey;
  return normalizeFilterValues(item.metadata?.[lensKey])[0] || unassignedKey;
}

export function buildDerivedVisibleGroups(workspace, lens, opts) {
  const { defaultLensKey, unassignedKey, unassignedLabel, searchQuery, activeFilters, showEmptyGroups = false } = opts || {};
  const groups = new Map();
  const preferredValues = Array.isArray(lens?.values) ? lens.values : [];

  preferredValues.forEach((value, index) => {
    groups.set(value, { name: value, groupKey: value, originalIndex: index, dropValue: value, items: [] });
  });

  const unassignedItems = [];
  for (const itemId of filterBoardItemIds(workspace, { searchQuery, activeFilters })) {
    const item = workspace.items?.[itemId];
    if (!item) continue;
    const groupValue = getItemLensGroupValue(item, lens.key, { defaultLensKey, unassignedKey });
    if (groupValue === unassignedKey) {
      unassignedItems.push(item);
      continue;
    }
    if (!groups.has(groupValue)) {
      groups.set(groupValue, {
        name: groupValue,
        groupKey: groupValue,
        originalIndex: preferredValues.length + groups.size,
        dropValue: groupValue,
        items: [],
      });
    }
    groups.get(groupValue).items.push(item);
  }

  const visibleGroups = Array.from(groups.values())
    .filter((group) => group.items.length > 0 || showEmptyGroups)
    .sort((left, right) => {
      if (left.originalIndex !== right.originalIndex) return left.originalIndex - right.originalIndex;
      return left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" });
    })
    .map((group, index) => ({
      ...group,
      originalIndex: index,
      isDerived: true,
      draggable: Boolean(lens.draggable && group.dropValue),
    }));

  if (unassignedItems.length > 0) {
    visibleGroups.push({
      name: unassignedLabel,
      groupKey: unassignedKey,
      originalIndex: visibleGroups.length,
      dropValue: "",
      items: unassignedItems,
      isDerived: true,
      draggable: false,
    });
  }

  return visibleGroups;
}
