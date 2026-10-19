import { encodeReferencePart } from "./pallium.js";

const FINISHED_STATUSES = new Set(["done", "shipped", "superseded", "cancelled", "canceled"]);

export function selectBoardParticipantCandidates(workspace, { includeCompleted = false, limit = 200 } = {}) {
  const seen = new Set(), unfinished = [], completed = [];
  for (const group of workspace?.boardGroups || []) for (const item of group.items || []) {
    const fullItem = workspace.items?.[item?.id];
    if (item?.missing || !fullItem || seen.has(item.id)) continue;
    seen.add(item.id);
    const target = FINISHED_STATUSES.has(String(fullItem.status || "").trim().toLowerCase()) ? completed : unfinished;
    target.push(item.id);
  }
  const candidates = includeCompleted ? [...unfinished, ...completed] : unfinished;
  const count = Math.min(200, Math.max(0, limit));
  return { ids: candidates.slice(0, count), partial: candidates.length > count };
}

/** Select only aggregate-proven, unambiguous logical features for Pallium lookup. */
export function selectWorktreeParticipantCandidates(aggregate, { includeCompleted = false, limit = 200 } = {}) {
  const byKey = new Map();
  let partial = Boolean(aggregate?.partial);
  for (const feature of aggregate?.features || []) {
    if (typeof feature?.key !== "string" || !feature.key || typeof feature.id !== "string" || !feature.id
      || !Array.isArray(feature.versions) || !feature.versions.length) {
      partial = true;
      continue;
    }
    const existing = byKey.get(feature.key);
    if (existing) {
      if (existing.id !== feature.id) { existing.invalid = true; partial = true; }
      existing.versions.push(...feature.versions);
    } else byKey.set(feature.key, { key: feature.key, id: feature.id, versions: [...feature.versions] });
  }

  const byReference = new Map();
  for (const feature of byKey.values()) {
    if (feature.invalid) continue;
    let reference;
    try { reference = encodeReferencePart(feature.id); }
    catch { partial = true; continue; }
    const matches = byReference.get(reference) || [];
    matches.push(feature);
    byReference.set(reference, matches);
  }

  const unfinished = [], completed = [], ambiguous = [];
  for (const [reference, matches] of byReference) {
    if (matches.length > 1) {
      ambiguous.push({ reference, keys: matches.map(({ key }) => key) });
      continue;
    }
    const feature = matches[0];
    const candidate = { key: feature.key, id: feature.id };
    const isUnfinished = feature.versions.some((version) =>
      !FINISHED_STATUSES.has(String(version?.summary?.status || "").trim().toLowerCase()));
    if (isUnfinished) unfinished.push(candidate);
    else if (includeCompleted) completed.push(candidate);
  }
  const candidates = includeCompleted ? [...unfinished, ...completed] : unfinished;
  const limitCount = Math.min(200, Math.max(0, limit));
  if (candidates.length > limitCount) partial = true;
  return { features: candidates.slice(0, limitCount), partial, ambiguous };
}
