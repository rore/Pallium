import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const REQUIRED_FRONTMATTER_KEYS = ["id", "title", "status", "priority", "commitment"];
export const OPTIONAL_FRONTMATTER_KEYS = ["milestone"];
export const EDITABLE_FRONTMATTER_KEYS = [...REQUIRED_FRONTMATTER_KEYS, ...OPTIONAL_FRONTMATTER_KEYS];
export const KNOWN_SECTIONS = [
  "Summary",
  "Why",
  "In Scope",
  "Out of Scope",
  "Done When",
  "Notes",
];

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const TEMPLATE_ROADMAP_ROOT = path.join(__dirname, "..", "templates", "roadmap");
const STARTER_FILE_NAMES = ["board.md", "scope.md"];
const STARTER_DIRECTORY_NAMES = ["features", "ideas"];
const STARTER_CONFIG_EXAMPLE = `{\n  "roadmapPath": "roadmap",\n  "lenses": {\n    "fields": {\n      "status": { "order": ["queued", "in-progress", "blocked", "done"], "draggable": true }\n    }\n  }\n}`;
const DEFAULT_LENS_FIELD_ORDER = {
  commitment: ["committed", "uncommitted"],
  priority: ["high", "medium", "low"],
  kind: ["feature", "idea"],
  status: ["queued", "in-progress", "blocked", "done"],
};
const DEFAULT_DRAGGABLE_LENS_FIELDS = new Set(["status", "commitment", "priority", "kind"]);
const FILTER_FACET_EXCLUDED_KEYS = new Set(["id", "title"]);
const LENS_EXCLUDED_KEYS = new Set(["id", "title", "labels"]);
const MAX_FILTER_VALUES = 8;
const MAX_GENERIC_LENS_VALUES = 8;

export class AppError extends Error {
  constructor(message, statusCode, code, details = null) {
    super(message);
    this.name = "AppError";
    this.statusCode = statusCode;
    this.code = code;
    this.details = details;
  }
}

function detectEol(text) {
  return text.includes("\r\n") ? "\r\n" : "\n";
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function trimBlankLines(value) {
  return value.replace(/^\s*\n/, "").replace(/\s*$/, "");
}

function hasMeaningfulSectionValue(value) {
  return String(value ?? "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim().length > 0;
}

function parseScalar(rawValue) {
  const value = rawValue.trim();

  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
    return value.slice(1, -1);
  }

  if (value === "null") {
    return null;
  }

  return value;
}

function normalizeMetadataScalar(value) {
  if (value === null || value === undefined) {
    return "";
  }

  return String(value).trim();
}

function normalizeMetadataValues(value) {
  if (Array.isArray(value)) {
    return value
      .map((entry) => normalizeMetadataScalar(entry))
      .filter(Boolean);
  }

  const normalized = normalizeMetadataScalar(value);
  return normalized ? [normalized] : [];
}

function uniqueSortedValues(values) {
  return Array.from(new Set(values.map((value) => String(value).trim()).filter(Boolean)))
    .sort((left, right) => left.localeCompare(right));
}

function uniqueValuesInOrder(values) {
  const seen = new Set();
  const ordered = [];

  for (const value of values) {
    const normalized = String(value).trim();
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    ordered.push(normalized);
  }

  return ordered;
}

function normalizeSearchText(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/\s+/g, " ")
    .trim();
}

function stripMarkdownForExcerpt(value) {
  return String(value ?? "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^[>\-*+]\s+/gm, "")
    .replace(/^\d+[.)]\s+/gm, "")
    .replace(/[\*_~]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function clampExcerpt(value, maxLength = 150) {
  if (!value || value.length <= maxLength) {
    return value;
  }

  const clipped = value.slice(0, Math.max(0, maxLength - 1)).trim().replace(/[.,;:!?-]+$/, "");
  return clipped ? `${clipped}?` : value.slice(0, maxLength - 1).trimEnd() + "?";
}

function buildItemOverview(itemRecord) {
  const preferredHeadings = ["Summary", "Goal", "Why", "In Scope", "Acceptance criteria", "Done When", "Notes"];
  const segments = itemRecord.parsed.segments.map((segment) => ({
    heading: segment.heading,
    content: itemRecord.parsed.sections[segment.heading] ?? "",
  }));

  let selected = segments.find((segment) => segment.heading === "Summary" && stripMarkdownForExcerpt(segment.content));
  if (!selected) {
    selected = segments.find((segment) => preferredHeadings.includes(segment.heading) && stripMarkdownForExcerpt(segment.content));
  }
  if (!selected) {
    selected = segments.find((segment) => stripMarkdownForExcerpt(segment.content));
  }

  return {
    heading: selected?.heading ?? "",
    excerpt: selected ? clampExcerpt(stripMarkdownForExcerpt(selected.content)) : "",
  };
}

function naturalValueCompare(left, right) {
  return String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" });
}

function sortValuesByPreferredOrder(values, preferredOrder = [], fallbackCompare = naturalValueCompare) {
  const orderIndex = new Map(preferredOrder.map((value, index) => [String(value), index]));

  return [...values].sort((left, right) => {
    const leftIndex = orderIndex.has(String(left)) ? orderIndex.get(String(left)) : Number.POSITIVE_INFINITY;
    const rightIndex = orderIndex.has(String(right)) ? orderIndex.get(String(right)) : Number.POSITIVE_INFINITY;

    if (leftIndex !== rightIndex) {
      return leftIndex - rightIndex;
    }

    return fallbackCompare(left, right);
  });
}

function formatScalar(value) {
  if (value === null || value === undefined || value === "") {
    return '""';
  }

  const stringValue = String(value);

  if (/^[A-Za-z0-9._-]+$/.test(stringValue)) {
    return stringValue;
  }

  return JSON.stringify(stringValue);
}

function shouldKeepOptionalValue(value) {
  return !(value === null || value === undefined || value === "");
}

function isScalarLikeValue(value) {
  return value === null || value === undefined || typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function isFrontmatterKeyName(key) {
  return /^[A-Za-z0-9_-]+$/.test(String(key || "").trim());
}

function parseEntryValue(rawLines) {
  const [firstLine, ...rest] = rawLines;
  const keyMatch = firstLine.match(/^([A-Za-z0-9_-]+):(.*)$/);

  if (!keyMatch) {
    throw new AppError("Invalid frontmatter format.", 422, "parse_error");
  }

  const inlineValue = keyMatch[2].trim();

  if (rest.length === 0) {
    return parseScalar(keyMatch[2]);
  }

  if (inlineValue !== "") {
    return undefined;
  }

  const listValues = [];
  for (const line of rest) {
    const listMatch = line.match(/^\s*[-]\s+(.*)$/);
    if (!listMatch) {
      return undefined;
    }
    listValues.push(parseScalar(listMatch[1]));
  }

  return listValues;
}

function parseFrontmatterBlock(rawFrontmatter) {
  const lines = rawFrontmatter.split(/\r?\n/);
  const entries = [];
  let current = null;

  for (const line of lines) {
    const keyMatch = line.match(/^([A-Za-z0-9_-]+):(.*)$/);

    if (keyMatch) {
      current = {
        key: keyMatch[1],
        rawLines: [line],
      };
      entries.push(current);
      continue;
    }

    if (!current) {
      throw new AppError("Invalid frontmatter format.", 422, "parse_error");
    }

    current.rawLines.push(line);
  }

  for (const entry of entries) {
    entry.value = parseEntryValue(entry.rawLines);
  }

  return entries;
}

function buildSearchText(itemRecord) {
  const parts = [
    itemRecord.id,
    itemRecord.kind,
  ];

  for (const [key, value] of Object.entries(itemRecord.parsed.metadataValues)) {
    parts.push(key);
    parts.push(...normalizeMetadataValues(value));
  }

  for (const segment of itemRecord.parsed.segments) {
    parts.push(segment.heading);
    parts.push(itemRecord.parsed.sections[segment.heading] ?? "");
  }

  return normalizeSearchText(parts.join("\n"));
}

function normalizeSummaryMetadata(itemRecord) {
  const metadata = {};

  for (const [key, value] of Object.entries(itemRecord.parsed.metadataValues)) {
    if (Array.isArray(value)) {
      const normalized = normalizeMetadataValues(value);
      if (normalized.length > 0) {
        metadata[key] = normalized;
      }
      continue;
    }

    const normalized = normalizeMetadataScalar(value);
    if (normalized) {
      metadata[key] = normalized;
    }
  }

  metadata.kind = itemRecord.kind;
  return metadata;
}

function makeItemSummary(itemRecord) {
  const metadata = normalizeSummaryMetadata(itemRecord);
  const overview = buildItemOverview(itemRecord);
  return {
    id: itemRecord.id,
    title: itemRecord.parsed.frontmatter.title,
    status: itemRecord.parsed.frontmatter.status,
    priority: itemRecord.parsed.frontmatter.priority,
    commitment: itemRecord.parsed.frontmatter.commitment,
    milestone: itemRecord.parsed.frontmatter.milestone ?? "",
    kind: itemRecord.kind,
    metadata,
    overviewHeading: overview.heading,
    overviewExcerpt: overview.excerpt,
    searchText: buildSearchText(itemRecord),
  };
}

function makeBoardItemSummary(itemSummary) {
  return {
    id: itemSummary.id,
    title: itemSummary.title,
    status: itemSummary.status,
    priority: itemSummary.priority,
    commitment: itemSummary.commitment,
    milestone: itemSummary.milestone,
    kind: itemSummary.kind,
    overviewHeading: itemSummary.overviewHeading,
    overviewExcerpt: itemSummary.overviewExcerpt,
  };
}

function buildAvailableFilters(itemSummaries) {
  const facets = new Map();

  for (const summary of Object.values(itemSummaries)) {
    for (const [key, rawValue] of Object.entries(summary.metadata || {})) {
      const values = normalizeMetadataValues(rawValue);
      if (values.length === 0) {
        continue;
      }

      if (!facets.has(key)) {
        facets.set(key, new Set());
      }

      const set = facets.get(key);
      for (const value of values) {
        set.add(value);
      }
    }
  }

  return Array.from(facets.entries())
    .map(([key, values]) => ({
      key,
      values: Array.from(values).sort((left, right) => left.localeCompare(right)),
    }))
    .filter((facet) => facet.values.length > 1 && facet.values.length <= MAX_FILTER_VALUES && !FILTER_FACET_EXCLUDED_KEYS.has(facet.key))
    .sort((left, right) => left.key.localeCompare(right.key));
}

function normalizeLensFieldConfig(rawConfig) {
  if (!rawConfig || typeof rawConfig !== "object" || Array.isArray(rawConfig)) {
    return {};
  }

  const normalized = {};

  for (const [field, options] of Object.entries(rawConfig)) {
    const key = String(field || "").trim();
    if (!isFrontmatterKeyName(key) || !options || typeof options !== "object" || Array.isArray(options)) {
      continue;
    }

    const entry = {};
    if (Array.isArray(options.order)) {
      const order = uniqueValuesInOrder(options.order);
      if (order.length > 0) {
        entry.order = order;
      }
    }

    if (typeof options.draggable === "boolean") {
      entry.draggable = options.draggable;
    }

    if (Object.keys(entry).length > 0) {
      normalized[key] = entry;
    }
  }

  return normalized;
}

function normalizeLensConfig(config) {
  return {
    fields: normalizeLensFieldConfig(config?.lenses?.fields),
  };
}

function getConfiguredLensField(workspaceConfig, field) {
  return workspaceConfig?.lenses?.fields?.[field] || null;
}

function getLensFieldOrder(workspaceConfig, field) {
  const configured = getConfiguredLensField(workspaceConfig, field);
  if (configured?.order?.length) {
    return configured.order;
  }

  return DEFAULT_LENS_FIELD_ORDER[field] || [];
}

function isLensFieldDraggable(workspaceConfig, field) {
  const configured = getConfiguredLensField(workspaceConfig, field);
  if (typeof configured?.draggable === "boolean") {
    return configured.draggable;
  }

  return DEFAULT_DRAGGABLE_LENS_FIELDS.has(field);
}

function humanizeLensKey(key) {
  return String(key || "")
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

export function deriveAvailableLenses(itemSummaries, workspaceConfig = { lenses: { fields: {} } }) {
  const fieldStats = new Map();

  for (const summary of Object.values(itemSummaries)) {
    for (const [key, rawValue] of Object.entries(summary.metadata || {})) {
      const normalizedKey = String(key || "").trim();
      if (!normalizedKey || LENS_EXCLUDED_KEYS.has(normalizedKey)) {
        continue;
      }

      const values = normalizeMetadataValues(rawValue);
      if (values.length === 0) {
        continue;
      }

      if (!fieldStats.has(normalizedKey)) {
        fieldStats.set(normalizedKey, {
          valueSet: new Set(),
          multiValue: false,
        });
      }

      const stats = fieldStats.get(normalizedKey);
      if (Array.isArray(rawValue) || values.length > 1) {
        stats.multiValue = true;
      }

      for (const value of values) {
        stats.valueSet.add(value);
      }
    }
  }

  const builtInOrder = ["status", "commitment", "priority", "kind", "milestone"];
  const lenses = [{ key: "board", label: "Board", kind: "board", draggable: false, values: [] }];

  for (const field of builtInOrder) {
    const stats = fieldStats.get(field);
    if (!stats || stats.valueSet.size < 2) {
      continue;
    }

    lenses.push({
      key: field,
      label: humanizeLensKey(field),
      kind: "derived",
      draggable: field !== "milestone" && isLensFieldDraggable(workspaceConfig, field),
      values: sortValuesByPreferredOrder(Array.from(stats.valueSet), getLensFieldOrder(workspaceConfig, field)),
    });
  }

  for (const [field, stats] of Array.from(fieldStats.entries()).sort((left, right) => left[0].localeCompare(right[0]))) {
    if (builtInOrder.includes(field) || stats.multiValue || stats.valueSet.size < 2 || stats.valueSet.size > MAX_GENERIC_LENS_VALUES) {
      continue;
    }

    lenses.push({
      key: field,
      label: humanizeLensKey(field),
      kind: "derived",
      draggable: isLensFieldDraggable(workspaceConfig, field),
      values: sortValuesByPreferredOrder(Array.from(stats.valueSet), getLensFieldOrder(workspaceConfig, field)),
    });
  }

  return lenses;
}

export function parseItemText(text, sourcePath = "item.md") {
  const eol = detectEol(text);
  const frontmatterMatch = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);

  if (!frontmatterMatch) {
    throw new AppError(`Missing or invalid frontmatter in ${sourcePath}.`, 422, "parse_error");
  }

  const rawFrontmatter = frontmatterMatch[1];
  const body = text.slice(frontmatterMatch[0].length);
  const frontmatterEntries = parseFrontmatterBlock(rawFrontmatter);
  const frontmatter = {};
  const metadataValues = {};

  for (const entry of frontmatterEntries) {
    if (entry.value !== undefined) {
      metadataValues[entry.key] = entry.value;
    }

    if (EDITABLE_FRONTMATTER_KEYS.includes(entry.key)) {
      frontmatter[entry.key] = entry.value;
    }
  }

  for (const key of REQUIRED_FRONTMATTER_KEYS) {
    if (!(key in frontmatter)) {
      throw new AppError(`Missing frontmatter key "${key}" in ${sourcePath}.`, 422, "parse_error");
    }
  }

  const headingRegex = /^##\s+(.+?)\s*$/gm;
  const matches = Array.from(body.matchAll(headingRegex));
  const prefix = matches.length > 0 ? body.slice(0, matches[0].index) : body;
  const sections = {};
  const segments = [];

  if (matches.length === 0) {
    throw new AppError(`Missing markdown sections in ${sourcePath}.`, 422, "parse_error");
  }

  for (let index = 0; index < matches.length; index += 1) {
    const match = matches[index];
    const heading = match[1].trim();
    const start = match.index;
    const end = index + 1 < matches.length ? matches[index + 1].index : body.length;
    const rawSection = body.slice(start, end);
    const headingLinePattern = new RegExp(`^##\\s+${escapeRegExp(heading)}\\s*\\r?\\n?`);
    const content = trimBlankLines(rawSection.replace(headingLinePattern, ""));
    sections[heading] = content;
    segments.push({ heading, rawSection });
  }

  return {
    eol,
    rawText: text,
    prefix,
    frontmatter,
    metadataValues,
    frontmatterEntries,
    sections,
    segments,
  };
}

function renderSection(heading, content, eol) {
  const cleaned = String(content ?? "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").trimEnd();

  if (cleaned.length === 0) {
    return `## ${heading}${eol}${eol}`;
  }

  return `## ${heading}${eol}${eol}${cleaned.replace(/\n/g, eol)}${eol}${eol}`;
}

export function serializeItem(parsedItem, updates) {
  const eol = parsedItem.eol;
  const metadata = { ...parsedItem.metadataValues, ...(updates.metadata || {}) };
  const sections = { ...parsedItem.sections, ...(updates.sections || {}) };
  const updatedMetadataNames = new Set(Object.keys(updates.metadata || {}).filter((key) => key !== "kind"));
  const updatedSectionNames = new Set(Object.keys(updates.sections || {}));
  const seenKeys = new Set();
  const frontmatterLines = [];

  for (const entry of parsedItem.frontmatterEntries) {
    if (REQUIRED_FRONTMATTER_KEYS.includes(entry.key)) {
      frontmatterLines.push(`${entry.key}: ${formatScalar(metadata[entry.key])}`);
    } else if (OPTIONAL_FRONTMATTER_KEYS.includes(entry.key)) {
      if (shouldKeepOptionalValue(metadata[entry.key])) {
        frontmatterLines.push(`${entry.key}: ${formatScalar(metadata[entry.key])}`);
      }
    } else if (updatedMetadataNames.has(entry.key) && isScalarLikeValue(metadata[entry.key])) {
      frontmatterLines.push(`${entry.key}: ${formatScalar(metadata[entry.key])}`);
    } else {
      frontmatterLines.push(...entry.rawLines);
    }
    seenKeys.add(entry.key);
  }

  for (const key of REQUIRED_FRONTMATTER_KEYS) {
    if (!seenKeys.has(key)) {
      frontmatterLines.push(`${key}: ${formatScalar(metadata[key])}`);
    }
  }

  for (const key of OPTIONAL_FRONTMATTER_KEYS) {
    if (!seenKeys.has(key) && shouldKeepOptionalValue(metadata[key])) {
      frontmatterLines.push(`${key}: ${formatScalar(metadata[key])}`);
    }
  }

  for (const key of updatedMetadataNames) {
    if (seenKeys.has(key) || !isFrontmatterKeyName(key) || !isScalarLikeValue(metadata[key])) {
      continue;
    }
    frontmatterLines.push(`${key}: ${formatScalar(metadata[key])}`);
    seenKeys.add(key);
  }

  const bodyParts = [parsedItem.prefix];
  const seenSections = new Set();
  const originalSectionNames = new Set(parsedItem.segments.map((segment) => segment.heading));

  for (const segment of parsedItem.segments) {
    if (KNOWN_SECTIONS.includes(segment.heading) || updatedSectionNames.has(segment.heading)) {
      bodyParts.push(renderSection(segment.heading, sections[segment.heading], eol));
    } else {
      bodyParts.push(segment.rawSection);
    }
    seenSections.add(segment.heading);
  }

  for (const heading of KNOWN_SECTIONS) {
    if (!seenSections.has(heading) && (originalSectionNames.has(heading) || hasMeaningfulSectionValue(sections[heading]))) {
      bodyParts.push(renderSection(heading, sections[heading], eol));
      seenSections.add(heading);
    }
  }

  for (const heading of updatedSectionNames) {
    if (!seenSections.has(heading) && (originalSectionNames.has(heading) || hasMeaningfulSectionValue(sections[heading]))) {
      bodyParts.push(renderSection(heading, sections[heading], eol));
      seenSections.add(heading);
    }
  }

  const normalizedBody = bodyParts.join("").replace(/\r\n/g, "\n").replace(/\r/g, "\n").replace(/\n/g, eol).trimEnd();
  return ["---", ...frontmatterLines, "---", "", normalizedBody, ""].join(eol);
}

export function serializeBoard(groups, eol = "\n") {
  const lines = [];

  for (const group of groups) {
    lines.push(`# ${group.name}`);
    for (const itemId of group.itemIds) {
      lines.push(`- ${itemId}`);
    }
    lines.push("");
  }

  return `${lines.join(eol).trimEnd()}${eol}`;
}

async function fileExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function safeStat(targetPath) {
  try {
    return await fs.stat(targetPath);
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
      return null;
    }

    throw error;
  }
}

function normalizeRepoRelativePath(repoRoot, targetPath) {
  return path.relative(path.resolve(repoRoot), path.resolve(targetPath)).replaceAll('\\', '/');
}

function normalizeDisplayPath(value) {
  return String(value || '').replaceAll('\\', '/');
}

function buildExpectedWorkspaceEntries(roadmapPath) {
  const base = normalizeDisplayPath(roadmapPath);
  return [
    `${base}/board.md`,
    `${base}/scope.md`,
    `${base}/features/`,
    `${base}/ideas/`,
  ];
}

function buildConfigErrorDetails(repoRoot, configPath, extra = {}) {
  return {
    configPath: configPath ? normalizeRepoRelativePath(repoRoot, configPath) : null,
    configMode: "override",
    canInitialize: false,
    suggestedConfig: STARTER_CONFIG_EXAMPLE,
    ...extra,
  };
}

function buildWorkspaceSetupDetails(repoRoot, workspace, extra = {}) {
  return {
    configPath: workspace.configPath ? normalizeRepoRelativePath(repoRoot, workspace.configPath) : null,
    configMode: workspace.configPath ? "override" : "default",
    roadmapPath: normalizeDisplayPath(workspace.roadmapPath),
    resolvedPath: normalizeRepoRelativePath(repoRoot, workspace.resolvedPath),
    expectedEntries: buildExpectedWorkspaceEntries(workspace.roadmapPath),
    missingEntries: [],
    canInitialize: true,
    ...extra,
  };
}

async function readRoadmapConfig(repoRoot) {
  const resolvedRepoRoot = path.resolve(repoRoot);
  const configPath = path.join(resolvedRepoRoot, "roadmap.config.json");
  let configuredPath = "roadmap";
  let parsedConfig = null;
  const hasConfig = await fileExists(configPath);

  if (hasConfig) {
    let rawConfig;

    try {
      rawConfig = await fs.readFile(configPath, "utf8");
    } catch {
      throw new AppError("Could not read roadmap.config.json.", 500, "config_error", buildConfigErrorDetails(resolvedRepoRoot, configPath));
    }

    try {
      parsedConfig = JSON.parse(rawConfig);
    } catch {
      throw new AppError("roadmap.config.json must contain valid JSON.", 422, "config_error", buildConfigErrorDetails(resolvedRepoRoot, configPath));
    }

    if (typeof parsedConfig.roadmapPath !== "string" || parsedConfig.roadmapPath.trim() === "") {
      throw new AppError('roadmap.config.json must define a non-empty string "roadmapPath".', 422, "config_error", buildConfigErrorDetails(resolvedRepoRoot, configPath));
    }

    configuredPath = parsedConfig.roadmapPath;
  }

  const resolvedPath = path.resolve(resolvedRepoRoot, configuredPath);
  const relative = path.relative(resolvedRepoRoot, resolvedPath);

  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new AppError("Configured roadmapPath must stay inside the repo root.", 422, "config_error", buildConfigErrorDetails(resolvedRepoRoot, configPath, {
      roadmapPath: normalizeDisplayPath(configuredPath),
      resolvedPath: normalizeDisplayPath(resolvedPath),
    }));
  }

  return {
    repoRoot: resolvedRepoRoot,
    configPath: hasConfig ? configPath : null,
    roadmapPath: configuredPath,
    resolvedPath,
    lenses: normalizeLensConfig(parsedConfig),
  };
}

async function validateWorkspaceShape(repoRoot, workspace) {
  const rootStat = await safeStat(workspace.resolvedPath);

  if (!rootStat) {
    throw new AppError(`Roadmap path not found: ${workspace.roadmapPath}`, 404, "setup_error", buildWorkspaceSetupDetails(repoRoot, workspace, {
      reason: "missing_root",
      missingEntries: [normalizeDisplayPath(workspace.roadmapPath)],
    }));
  }

  if (!rootStat.isDirectory()) {
    throw new AppError(`Roadmap path must be a directory: ${workspace.roadmapPath}`, 422, "setup_error", buildWorkspaceSetupDetails(repoRoot, workspace, {
      reason: "invalid_root",
      canInitialize: false,
    }));
  }

  const missingEntries = [];

  for (const directoryName of STARTER_DIRECTORY_NAMES) {
    const targetPath = path.join(workspace.resolvedPath, directoryName);
    const stats = await safeStat(targetPath);

    if (!stats) {
      missingEntries.push(`${normalizeDisplayPath(workspace.roadmapPath)}/${directoryName}/`);
      continue;
    }

    if (!stats.isDirectory()) {
      throw new AppError(`Roadmap workspace expects ${directoryName}/ to be a directory.`, 422, "setup_error", buildWorkspaceSetupDetails(repoRoot, workspace, {
        reason: "invalid_entry",
        canInitialize: false,
        invalidEntries: [`${normalizeDisplayPath(workspace.roadmapPath)}/${directoryName}/`],
      }));
    }
  }

  for (const fileName of STARTER_FILE_NAMES) {
    const targetPath = path.join(workspace.resolvedPath, fileName);
    const stats = await safeStat(targetPath);

    if (!stats) {
      missingEntries.push(`${normalizeDisplayPath(workspace.roadmapPath)}/${fileName}`);
      continue;
    }

    if (!stats.isFile()) {
      throw new AppError(`Roadmap workspace expects ${fileName} to be a file.`, 422, "setup_error", buildWorkspaceSetupDetails(repoRoot, workspace, {
        reason: "invalid_entry",
        canInitialize: false,
        invalidEntries: [`${normalizeDisplayPath(workspace.roadmapPath)}/${fileName}`],
      }));
    }
  }

  if (missingEntries.length > 0) {
    throw new AppError("Roadmap workspace is incomplete.", 404, "setup_error", buildWorkspaceSetupDetails(repoRoot, workspace, {
      reason: "missing_entries",
      missingEntries,
    }));
  }
}

async function ensureStarterFile(templateName, targetPath) {
  if (await fileExists(targetPath)) {
    return;
  }

  const templatePath = path.join(TEMPLATE_ROADMAP_ROOT, templateName);
  const templateText = await fs.readFile(templatePath, "utf8");
  await fs.writeFile(targetPath, templateText, "utf8");
}

export async function resolveRoadmapRoot(repoRoot) {
  return readRoadmapConfig(repoRoot);
}

export function parseBoardText(text, sourcePath = "board.md") {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const groups = [];
  let currentGroup = null;

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed === "") {
      continue;
    }

    if (trimmed.startsWith("# ")) {
      currentGroup = { name: trimmed.slice(2).trim(), itemIds: [] };
      groups.push(currentGroup);
      continue;
    }

    if (trimmed.startsWith("- ")) {
      if (!currentGroup) {
        throw new AppError(`Board item declared before a heading in ${sourcePath}.`, 422, "parse_error");
      }

      currentGroup.itemIds.push(trimmed.slice(2).trim());
      continue;
    }

    throw new AppError(`Unsupported board line "${trimmed}" in ${sourcePath}.`, 422, "parse_error");
  }

  return groups;
}

async function readUtf8(filePath, notFoundMessage) {
  try {
    return await fs.readFile(filePath, "utf8");
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
      throw new AppError(notFoundMessage, 404, "setup_error");
    }

    throw error;
  }
}

async function listMarkdownFiles(directoryPath) {
  const entries = await fs.readdir(directoryPath, { withFileTypes: true });
  return entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".md"))
    .map((entry) => path.join(directoryPath, entry.name));
}

async function loadItemIndex(roadmapRoot) {
  const featuresDir = path.join(roadmapRoot, "features");
  const ideasDir = path.join(roadmapRoot, "ideas");

  if (!(await fileExists(featuresDir)) || !(await fileExists(ideasDir))) {
    throw new AppError('Roadmap path must include "features" and "ideas" directories.', 404, "setup_error");
  }

  const files = [
    ...(await listMarkdownFiles(featuresDir)).map((filePath) => ({ filePath, kind: "feature" })),
    ...(await listMarkdownFiles(ideasDir)).map((filePath) => ({ filePath, kind: "idea" })),
  ];
  const index = new Map();

  for (const entry of files) {
    const text = await fs.readFile(entry.filePath, "utf8");
    const parsed = parseItemText(text, entry.filePath);
    const id = String(parsed.frontmatter.id);

    if (index.has(id)) {
      throw new AppError(`Duplicate item id "${id}" found in roadmap files.`, 422, "parse_error");
    }

    index.set(id, {
      id,
      kind: entry.kind,
      filePath: entry.filePath,
      parsed,
    });
  }

  return index;
}

export async function loadWorkspace(repoRoot) {
  const workspace = await resolveRoadmapRoot(repoRoot);
  await validateWorkspaceShape(repoRoot, workspace);
  const boardPath = path.join(workspace.resolvedPath, "board.md");
  const scopePath = path.join(workspace.resolvedPath, "scope.md");
  const boardText = await readUtf8(boardPath, "Missing roadmap board.md file.");
  const scopeText = await readUtf8(scopePath, "Missing roadmap scope.md file.");
  const groups = parseBoardText(boardText, boardPath);
  const itemIndex = await loadItemIndex(workspace.resolvedPath);
  const itemSummaries = {};
  const boardGroups = groups.map((group) => ({
    name: group.name,
    items: group.itemIds.map((id) => {
      const item = itemIndex.get(id);

      if (!item) {
        throw new AppError(`Board references missing item "${id}".`, 422, "parse_error");
      }

      const summary = itemSummaries[id] || makeItemSummary(item);
      itemSummaries[id] = summary;
      return makeBoardItemSummary(summary);
    }),
  }));

  for (const [id, item] of itemIndex.entries()) {
    if (!itemSummaries[id]) {
      itemSummaries[id] = makeItemSummary(item);
    }
  }

  return {
    repoName: path.basename(path.resolve(repoRoot)),
    roadmapPath: workspace.roadmapPath,
    resolvedPath: workspace.resolvedPath,
    boardGroups,
    scopeText,
    items: itemSummaries,
    availableFilters: buildAvailableFilters(itemSummaries),
    availableLenses: deriveAvailableLenses(itemSummaries, workspace),
  };
}

export async function initializeWorkspace(repoRoot) {
  const workspace = await readRoadmapConfig(repoRoot);
  const rootStat = await safeStat(workspace.resolvedPath);

  if (rootStat && !rootStat.isDirectory()) {
    throw new AppError(`Roadmap path must be a directory: ${workspace.roadmapPath}`, 422, "setup_error", buildWorkspaceSetupDetails(repoRoot, workspace, {
      reason: "invalid_root",
      canInitialize: false,
    }));
  }

  await fs.mkdir(workspace.resolvedPath, { recursive: true });

  for (const directoryName of STARTER_DIRECTORY_NAMES) {
    await fs.mkdir(path.join(workspace.resolvedPath, directoryName), { recursive: true });
  }

  for (const fileName of STARTER_FILE_NAMES) {
    await ensureStarterFile(fileName, path.join(workspace.resolvedPath, fileName));
  }

  return loadWorkspace(repoRoot);
}
export async function readItemById(repoRoot, id) {
  const workspace = await resolveRoadmapRoot(repoRoot);
  const itemIndex = await loadItemIndex(workspace.resolvedPath);
  const item = itemIndex.get(id);

  if (!item) {
    throw new AppError(`Roadmap item "${id}" was not found.`, 404, "not_found");
  }

  const extraSections = {};

  for (const heading of item.parsed.segments.map((segment) => segment.heading)) {
    if (!KNOWN_SECTIONS.includes(heading)) {
      extraSections[heading] = item.parsed.sections[heading] ?? "";
    }
  }

  return {
    id: item.id,
    kind: item.kind,
    filePath: path.relative(repoRoot, item.filePath),
    metadata: {
      ...item.parsed.frontmatter,
      milestone: item.parsed.frontmatter.milestone ?? "",
    },
    sections: Object.fromEntries(KNOWN_SECTIONS.map((heading) => [heading, item.parsed.sections[heading] ?? ""])),
    sectionOrder: item.parsed.segments.map((segment) => segment.heading),
    extraSections,
    extraSectionOrder: Object.keys(extraSections),
    rawText: item.parsed.rawText,
  };
}

export async function saveItemById(repoRoot, id, payload) {
  const workspace = await resolveRoadmapRoot(repoRoot);
  const itemIndex = await loadItemIndex(workspace.resolvedPath);
  const item = itemIndex.get(id);

  if (!item) {
    throw new AppError(`Roadmap item "${id}" was not found.`, 404, "not_found");
  }

  if (typeof payload.rawText === "string") {
    const reparsed = parseItemText(payload.rawText, item.filePath);

    if (String(reparsed.frontmatter.id) !== item.id) {
      throw new AppError("Raw item edits must preserve the item id.", 400, "bad_request");
    }

    await fs.writeFile(item.filePath, payload.rawText, "utf8");
    return readItemById(repoRoot, id);
  }

  const metadata = payload.metadata || {};
  const sections = payload.sections || {};
  const nextMetadata = { ...item.parsed.metadataValues };
  const nextSections = { ...item.parsed.sections };

  for (const key of REQUIRED_FRONTMATTER_KEYS) {
    nextMetadata[key] = key === "id" ? item.id : (metadata[key] ?? item.parsed.frontmatter[key]);
  }

  for (const key of OPTIONAL_FRONTMATTER_KEYS) {
    nextMetadata[key] = metadata[key] ?? item.parsed.frontmatter[key] ?? "";
  }

  for (const [key, value] of Object.entries(metadata)) {
    if (key === "id" || key === "kind" || !isFrontmatterKeyName(key) || !isScalarLikeValue(value)) {
      continue;
    }

    nextMetadata[key] = value;
  }

  for (const [heading, value] of Object.entries(sections)) {
    nextSections[heading] = value;
  }

  const serialized = serializeItem(item.parsed, {
    metadata: nextMetadata,
    sections: nextSections,
  });

  const nextKind = metadata.kind === "feature" || metadata.kind === "idea" ? metadata.kind : item.kind;
  const destinationPath = nextKind === item.kind
    ? item.filePath
    : path.join(workspace.resolvedPath, nextKind === "feature" ? "features" : "ideas", path.basename(item.filePath));

  if (destinationPath !== item.filePath && await fileExists(destinationPath)) {
    throw new AppError(`Roadmap item "${id}" already exists at the target kind path.`, 400, "bad_request");
  }

  await fs.writeFile(item.filePath, serialized, "utf8");

  if (destinationPath !== item.filePath) {
    await fs.rename(item.filePath, destinationPath);
  }

  return readItemById(repoRoot, id);
}

export async function saveScopeText(repoRoot, scopeText) {
  const workspace = await resolveRoadmapRoot(repoRoot);
  const scopePath = path.join(workspace.resolvedPath, "scope.md");
  const existingScopeText = await readUtf8(scopePath, "Missing roadmap scope.md file.");
  const eol = detectEol(existingScopeText);
  const normalized = String(scopeText ?? "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").trimEnd();
  const nextText = normalized.length === 0 ? "" : `${normalized}${eol}`;

  await fs.writeFile(scopePath, nextText.replace(/\n/g, eol), "utf8");
  return loadWorkspace(repoRoot);
}

export async function saveBoardByGroups(repoRoot, groupsPayload) {
  const workspace = await resolveRoadmapRoot(repoRoot);
  const boardPath = path.join(workspace.resolvedPath, "board.md");
  const existingBoardText = await readUtf8(boardPath, "Missing roadmap board.md file.");
  const eol = detectEol(existingBoardText);
  const itemIndex = await loadItemIndex(workspace.resolvedPath);

  if (!Array.isArray(groupsPayload) || groupsPayload.length === 0) {
    throw new AppError("Board update must provide at least one group.", 400, "bad_request");
  }

  const seenIds = new Set();
  const normalizedGroups = groupsPayload.map((group, index) => {
    if (!group || typeof group.name !== "string" || group.name.trim() === "") {
      throw new AppError(`Board group ${index + 1} must have a non-empty name.`, 400, "bad_request");
    }

    if (!Array.isArray(group.itemIds)) {
      throw new AppError(`Board group ${group.name} must include an itemIds array.`, 400, "bad_request");
    }

    const itemIds = group.itemIds.map((itemId) => {
      if (typeof itemId !== "string" || itemId.trim() === "") {
        throw new AppError(`Board group ${group.name} contains an invalid item id.`, 400, "bad_request");
      }

      if (!itemIndex.has(itemId)) {
        throw new AppError(`Board group ${group.name} references missing item "${itemId}".`, 422, "parse_error");
      }

      if (seenIds.has(itemId)) {
        throw new AppError(`Board item "${itemId}" is listed more than once.`, 400, "bad_request");
      }

      seenIds.add(itemId);
      return itemId;
    });

    return {
      name: group.name.trim(),
      itemIds,
    };
  });

  const serialized = serializeBoard(normalizedGroups, eol);
  await fs.writeFile(boardPath, serialized, "utf8");
  return loadWorkspace(repoRoot);
}












