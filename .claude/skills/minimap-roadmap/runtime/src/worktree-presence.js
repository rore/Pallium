import { encodeReferencePart } from "./pallium.js";

const FINISHED_STATUSES = new Set(["done", "shipped", "superseded", "cancelled", "canceled"]);

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

  const features = [], ambiguous = [];
  for (const [reference, matches] of byReference) {
    if (matches.length > 1) {
      ambiguous.push({ reference, keys: matches.map(({ key }) => key) });
      continue;
    }
    const feature = matches[0];
    if (includeCompleted || feature.versions.some((version) =>
      !FINISHED_STATUSES.has(String(version?.summary?.status || "").trim().toLowerCase()))) {
      if (features.length < Math.min(200, Math.max(0, limit))) features.push({ key: feature.key, id: feature.id });
      else partial = true;
    }
  }
  return { features, partial, ambiguous };
}
