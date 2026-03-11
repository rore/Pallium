const FIXED_SECTIONS = ["Summary", "Why", "In Scope", "Out of Scope", "Done When", "Notes"];
const SCOPE_STORAGE_KEY = "roadmap-ui.scope-collapsed";
const SCOPE_WIDTH_STORAGE_KEY = "roadmap-ui.scope-width";
const DEFAULT_SCOPE_WIDTH = 272;
const MIN_SCOPE_WIDTH = 240;
const MAX_SCOPE_WIDTH = 440;
const DEFAULT_LENS_KEY = "board";
const DEFAULT_BOARD_LAYOUT = "list";
const BOARD_LAYOUTS = new Set(["list", "columns"]);
const UNASSIGNED_GROUP_KEY = "__unassigned__";
const UNASSIGNED_GROUP_LABEL = "Unassigned";
const EDITOR_MODES = new Set(["preview", "structured", "raw"]);

const state = {
  workspace: null,
  setupState: null,
  selectedItemId: null,
  currentItem: null,
  activeLens: DEFAULT_LENS_KEY,
  boardLayout: DEFAULT_BOARD_LAYOUT,
  dragItemId: null,
  dragClickSuppressUntil: 0,
  lensesExpanded: false,
  searchQuery: "",
  activeFilters: {},
  filtersExpanded: false,
  collapsedGroups: new Set(),
  scopeCollapsed: loadStoredScopePreference(),
  scopeWidth: loadStoredScopeWidth(),
  editorMode: "preview",
  dirtyStructured: false,
  dirtyRaw: false,
  boardEditMode: false,
  boardDraft: null,
  boardDirty: false,
  scopeEditMode: false,
  scopeDraft: "",
  scopeDirty: false,
};

const layoutElement = document.querySelector("#layout-shell");
const boardPanelElement = document.querySelector("#board-panel");
const boardControlsElement = document.querySelector("#board-controls");
const boardGroupsElement = document.querySelector("#board-groups");
const boardEditButton = document.querySelector("#board-edit-button");
const boardSaveButton = document.querySelector("#board-save-button");
const boardCancelButton = document.querySelector("#board-cancel-button");
const boardSearchInput = document.querySelector("#board-search");
const boardLensSwitcherElement = document.querySelector("#board-lens-switcher");
const boardViewToggleButton = document.querySelector("#board-view-toggle");
const boardLayoutControlsElement = document.querySelector("#board-layout-controls");
const boardLayoutListButton = document.querySelector("#board-layout-list");
const boardLayoutColumnsButton = document.querySelector("#board-layout-columns");
const boardFilterToggleButton = document.querySelector("#board-filter-toggle");
const boardClearFiltersButton = document.querySelector("#board-clear-filters");
const boardFiltersElement = document.querySelector("#board-filters");
const scopePanelElement = document.querySelector("#scope-panel");
const scopeContentElement = document.querySelector("#scope-content");
const scopeTextElement = document.querySelector("#scope-text");
const scopeEditButton = document.querySelector("#scope-edit-button");
const scopeSaveButton = document.querySelector("#scope-save-button");
const scopeCancelButton = document.querySelector("#scope-cancel-button");
const scopeSubtitleElement = document.querySelector("#scope-subtitle");
const scopeResizerElement = document.querySelector("#scope-resizer");
const scopeToggleButton = document.querySelector("#scope-toggle");
const jumpToBoardButton = document.querySelector("#jump-to-board");
const jumpToEditorButton = document.querySelector("#jump-to-editor");
const roadmapPathElement = document.querySelector("#roadmap-path");
const workspaceSummaryElement = document.querySelector("#workspace-summary");
const repoNameElement = document.querySelector("#repo-name");
const editorTitleElement = document.querySelector("#editor-title");
const editorSubtitleElement = document.querySelector("#editor-subtitle");
const editorPanelElement = document.querySelector("#editor-panel");
const editorPanelAnchor = document.querySelector("#editor-panel-anchor");
const editorOverlayElement = document.querySelector("#editor-overlay");
const editorOverlaySlotElement = document.querySelector("#editor-overlay-slot");
const editorOverlayBackdrop = document.querySelector("#editor-overlay-backdrop");
const editorCancelButton = document.querySelector("#editor-cancel-button");
const editorOverlayCloseButton = document.querySelector("#editor-overlay-close");
const saveButton = document.querySelector("#save-button");
const refreshButton = document.querySelector("#refresh-button");
const statusBanner = document.querySelector("#status-banner");
const form = document.querySelector("#item-form");
const previewElement = document.querySelector("#item-preview");
const rawTextElement = document.querySelector("#raw-text");
const sectionsContainer = document.querySelector("#sections-container");
const editorTabsElement = document.querySelector("#editor-tabs");
const setupViewElement = document.querySelector("#setup-view");
const modeButtons = Array.from(document.querySelectorAll("[data-editor-mode]"));
const modePanes = Array.from(document.querySelectorAll("[data-mode-pane]"));
const stackedLayoutMedia = window.matchMedia("(max-width: 980px)");
const desktopScopeLayoutMedia = window.matchMedia("(min-width: 1321px)");

const fields = {
  id: document.querySelector("#field-id"),
  title: document.querySelector("#field-title"),
  status: document.querySelector("#field-status"),
  priority: document.querySelector("#field-priority"),
  commitment: document.querySelector("#field-commitment"),
  boardGroup: document.querySelector("#field-board-group"),
  milestone: document.querySelector("#field-milestone"),
};

function loadStoredScopePreference() {
  try {
    return window.localStorage.getItem(SCOPE_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function persistScopePreference() {
  try {
    window.localStorage.setItem(SCOPE_STORAGE_KEY, String(state.scopeCollapsed));
  } catch {
    // Ignore storage failures.
  }
}

function clampScopeWidth(width) {
  return Math.max(MIN_SCOPE_WIDTH, Math.min(MAX_SCOPE_WIDTH, Math.round(width)));
}

function loadStoredScopeWidth() {
  try {
    const rawValue = Number(window.localStorage.getItem(SCOPE_WIDTH_STORAGE_KEY));
    return Number.isFinite(rawValue) && rawValue > 0 ? clampScopeWidth(rawValue) : DEFAULT_SCOPE_WIDTH;
  } catch {
    return DEFAULT_SCOPE_WIDTH;
  }
}

function persistScopeWidth() {
  try {
    window.localStorage.setItem(SCOPE_WIDTH_STORAGE_KEY, String(state.scopeWidth));
  } catch {
    // Ignore storage failures.
  }
}

function setBanner(message, tone = "info") {
  if (!message) {
    statusBanner.hidden = true;
    statusBanner.textContent = "";
    statusBanner.dataset.tone = "";
    return;
  }

  statusBanner.hidden = false;
  statusBanner.dataset.tone = tone;
  statusBanner.textContent = message;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderInlineMarkdown(value) {
  let html = escapeHtml(value);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  return html;
}

function renderMarkdownToHtml(markdown) {
  const normalized = String(markdown || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = normalized.split("\n");
  const blocks = [];
  let paragraphLines = [];
  let listItems = [];
  let orderedListItems = [];
  let codeLines = [];
  let inCodeBlock = false;

  function flushParagraph() {
    if (paragraphLines.length === 0) {
      return;
    }
    blocks.push(`<p>${renderInlineMarkdown(paragraphLines.join(" "))}</p>`);
    paragraphLines = [];
  }

  function flushList() {
    if (listItems.length > 0) {
      blocks.push(`<ul>${listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ul>`);
      listItems = [];
    }

    if (orderedListItems.length > 0) {
      blocks.push(`<ol>${orderedListItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ol>`);
      orderedListItems = [];
    }
  }

  function flushCodeBlock() {
    if (codeLines.length === 0) {
      return;
    }
    blocks.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    codeLines = [];
  }
  for (const line of lines) {
    if (line.startsWith("```")) {
      flushParagraph();
      flushList();
      if (inCodeBlock) {
        flushCodeBlock();
      }
      inCodeBlock = !inCodeBlock;
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    const trimmed = line.trim();

    if (trimmed === "") {
      flushParagraph();
      flushList();
      continue;
    }

    const unorderedMatch = trimmed.match(/^[-*]\s+(.+)$/);
    if (unorderedMatch) {
      flushParagraph();
      orderedListItems = [];
      listItems.push(unorderedMatch[1]);
      continue;
    }

    const orderedMatch = trimmed.match(/^\d+[.]\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      listItems = [];
      orderedListItems.push(orderedMatch[1]);
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = headingMatch[1].length;
      blocks.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      continue;
    }

    paragraphLines.push(trimmed);
  }

  flushParagraph();
  flushList();
  flushCodeBlock();
  return blocks.join("");
}

function ensureSelectValue(select, value) {
  if (!Array.from(select.options).some((option) => option.value === value)) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  }

  select.value = value;
}

function getBoardItems() {
  return state.workspace?.boardGroups.flatMap((group) => group.items) ?? [];
}

function getBoardItemById(itemId, workspace = state.workspace) {
  return workspace?.items?.[itemId] ?? null;
}

function getAvailableLenses(workspace = state.workspace) {
  return Array.isArray(workspace?.availableLenses) && workspace.availableLenses.length > 0
    ? workspace.availableLenses
    : [{ key: DEFAULT_LENS_KEY, label: "Board", kind: "board", draggable: false, values: [] }];
}

function normalizeLensKey(value, workspace = state.workspace) {
  const normalized = String(value || "").trim() || DEFAULT_LENS_KEY;
  return getAvailableLenses(workspace).some((lens) => lens.key === normalized) ? normalized : DEFAULT_LENS_KEY;
}

function getActiveLensDefinition(workspace = state.workspace) {
  const activeKey = normalizeLensKey(state.activeLens, workspace);
  return getAvailableLenses(workspace).find((lens) => lens.key === activeKey) || getAvailableLenses(workspace)[0];
}

function isBoardLensActive(workspace = state.workspace) {
  return getActiveLensDefinition(workspace)?.key === DEFAULT_LENS_KEY;
}

function normalizeBoardLayout(value) {
  return BOARD_LAYOUTS.has(String(value || "").trim()) ? String(value || "").trim() : DEFAULT_BOARD_LAYOUT;
}

function isColumnsLayoutActive() {
  return normalizeBoardLayout(state.boardLayout) === "columns";
}

function normalizeSearchQuery(value) {
  return String(value ?? "").trim().toLowerCase();
}

function normalizeFilterValues(value) {
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry).trim()).filter(Boolean);
  }

  const normalized = String(value ?? "").trim();
  return normalized ? [normalized] : [];
}

function normalizeFilterMap(filters) {
  const normalized = {};

  for (const [key, values] of Object.entries(filters || {})) {
    const cleanKey = String(key || "").trim();
    const cleanValues = Array.from(new Set(normalizeFilterValues(values))).sort((left, right) => left.localeCompare(right));
    if (!cleanKey || cleanValues.length === 0) {
      continue;
    }
    normalized[cleanKey] = cleanValues;
  }

  return normalized;
}

function parseRouteFilters(params) {
  const filters = {};

  for (const token of params.getAll("f")) {
    const separatorIndex = token.indexOf(":");
    if (separatorIndex <= 0) {
      continue;
    }

    const key = token.slice(0, separatorIndex).trim();
    const value = token.slice(separatorIndex + 1).trim();
    if (!key || !value) {
      continue;
    }

    if (!filters[key]) {
      filters[key] = [];
    }
    filters[key].push(value);
  }

  return normalizeFilterMap(filters);
}

function serializeRouteFilters(params, filters) {
  const normalized = normalizeFilterMap(filters);
  const keys = Object.keys(normalized).sort((left, right) => left.localeCompare(right));

  for (const key of keys) {
    for (const value of normalized[key]) {
      params.append("f", `${key}:${value}`);
    }
  }
}

function isSearchActive() {
  return Boolean(state.searchQuery) || Object.keys(state.activeFilters).length > 0;
}

function itemMatchesCurrentFilters(itemId, workspace = state.workspace) {
  const item = getBoardItemById(itemId, workspace);
  if (!item) {
    return false;
  }

  if (state.searchQuery && !String(item.searchText || "").includes(state.searchQuery)) {
    return false;
  }

  for (const [key, selectedValues] of Object.entries(state.activeFilters)) {
    const itemValues = normalizeFilterValues(item.metadata?.[key]);
    if (!selectedValues.some((value) => itemValues.includes(value))) {
      return false;
    }
  }

  return true;
}

function getFilteredBoardItemIds(workspace = state.workspace) {
  if (!workspace) {
    return [];
  }

  const orderedIds = workspace.boardGroups.flatMap((group) => group.items.map((item) => item.id));
  return isSearchActive() ? orderedIds.filter((itemId) => itemMatchesCurrentFilters(itemId, workspace)) : orderedIds;
}

function getItemLensGroupValue(item, lensKey) {
  if (!item || lensKey === DEFAULT_LENS_KEY) {
    return "";
  }

  if (lensKey === "kind") {
    return item.kind || UNASSIGNED_GROUP_KEY;
  }

  return normalizeFilterValues(item.metadata?.[lensKey])[0] || UNASSIGNED_GROUP_KEY;
}

function buildDerivedVisibleGroups(workspace, lens) {
  const groups = new Map();
  const preferredValues = Array.isArray(lens?.values) ? lens.values : [];
  const showEmptyGroups = isColumnsLayoutActive() && preferredValues.length > 0;

  preferredValues.forEach((value, index) => {
    groups.set(value, {
      name: value,
      groupKey: value,
      originalIndex: index,
      dropValue: value,
      items: [],
    });
  });

  const unassignedItems = [];
  for (const itemId of getFilteredBoardItemIds(workspace)) {
    const item = getBoardItemById(itemId, workspace);
    if (!item) {
      continue;
    }

    const groupValue = getItemLensGroupValue(item, lens.key);
    if (groupValue === UNASSIGNED_GROUP_KEY) {
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
      if (left.originalIndex !== right.originalIndex) {
        return left.originalIndex - right.originalIndex;
      }
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
      name: UNASSIGNED_GROUP_LABEL,
      groupKey: UNASSIGNED_GROUP_KEY,
      originalIndex: visibleGroups.length,
      dropValue: "",
      items: unassignedItems,
      isDerived: true,
      draggable: false,
    });
  }

  return visibleGroups;
}

function getVisibleBoardGroups(workspace = state.workspace) {
  if (!workspace) {
    return [];
  }

  const activeLens = getActiveLensDefinition(workspace);
  if (!activeLens || activeLens.key === DEFAULT_LENS_KEY) {
    return workspace.boardGroups
      .map((group, index) => ({
        name: group.name,
        originalIndex: index,
        items: isSearchActive() ? group.items.filter((item) => itemMatchesCurrentFilters(item.id, workspace)) : group.items,
        isDerived: false,
        draggable: false,
      }))
      .filter((group) => group.items.length > 0 || !isSearchActive());
  }

  return buildDerivedVisibleGroups(workspace, activeLens);
}

function getVisibleBoardItemIds(workspace = state.workspace) {
  return getVisibleBoardGroups(workspace).flatMap((group) => group.items.map((item) => item.id));
}

function getFirstBoardItemId(workspace = state.workspace) {
  return workspace?.boardGroups.flatMap((group) => group.items).at(0)?.id ?? null;
}

function getFirstVisibleBoardItemId(workspace = state.workspace) {
  return getVisibleBoardItemIds(workspace).at(0) ?? null;
}

function canDragItemsInActiveLens(workspace = state.workspace) {
  const lens = getActiveLensDefinition(workspace);
  return Boolean(lens && lens.kind === "derived" && lens.draggable && !state.boardEditMode);
}

function canDragItemsInColumnLayout(workspace = state.workspace) {
  const lens = getActiveLensDefinition(workspace);
  if (!lens || state.boardEditMode || !isColumnsLayoutActive()) {
    return false;
  }

  if (lens.key === DEFAULT_LENS_KEY) {
    return true;
  }

  return Boolean(lens.kind === "derived" && lens.draggable);
}

function humanizeFilterKey(key) {
  return String(key || "")
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function stripMarkdownToPlainText(value) {
  return String(value ?? "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^[>\-*+]\s+/gm, "")
    .replace(/^\d+[.)]\s+/gm, "")
    .replace(/[\\*_~]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function hasUnsavedCurrentItemChanges() {

  return state.dirtyStructured || state.dirtyRaw;
}

function confirmDiscardCurrentItemChanges(nextItemId) {
  if (!state.currentItem || !hasUnsavedCurrentItemChanges() || nextItemId === state.selectedItemId) {
    return true;
  }

  if (state.dirtyRaw) {
    return window.confirm("Discard unsaved raw markdown changes and open another item?");
  }

  return window.confirm("Discard unsaved item changes and open another item?");
}

function isSetupMode() {
  return Boolean(state.setupState);
}

function buildSetupState(error) {
  if (!error || !["setup_error", "config_error"].includes(error.code)) {
    return null;
  }

  const details = error.details || {};
  const reason = details.reason || error.code;
  const title = error.code === "config_error" ? "Roadmap config needs attention" : "Roadmap workspace needs setup";
  const description = error.code === "config_error"
    ? "Minimap could not resolve a usable roadmap path from the current repo configuration."
    : "Minimap could not load a usable roadmap workspace from the current repo state.";

  return {
    code: error.code,
    title,
    message: error.message,
    description,
    reason,
    canInitialize: details.canInitialize === true,
    roadmapPath: details.roadmapPath || "roadmap",
    resolvedPath: details.resolvedPath || details.roadmapPath || "roadmap",
    configPath: details.configPath || null,
    configMode: details.configMode || "default",
    expectedEntries: Array.isArray(details.expectedEntries) ? details.expectedEntries : [],
    missingEntries: Array.isArray(details.missingEntries) ? details.missingEntries : [],
    invalidEntries: Array.isArray(details.invalidEntries) ? details.invalidEntries : [],
    suggestedConfig: details.suggestedConfig || "",
  };
}

function renderSetupList(entries, emptyCopy) {
  if (!entries || entries.length === 0) {
    return `<p class="muted">${escapeHtml(emptyCopy)}</p>`;
  }

  return `<ul class="setup-list">${entries.map((entry) => `<li><code>${escapeHtml(entry)}</code></li>`).join("")}</ul>`;
}

function renderSetupView() {
  if (!setupViewElement) {
    return;
  }

  if (!state.setupState) {
    setupViewElement.hidden = true;
    setupViewElement.innerHTML = "";
    return;
  }

  const setup = state.setupState;
  const locationSummary = setup.configPath
    ? `Using ${setup.configPath} to point minimap at ${setup.roadmapPath}.`
    : `No roadmap.config.json found. Minimap defaults to ${setup.roadmapPath}.`;
  const statusSummary = setup.canInitialize
    ? "Minimap can scaffold the starter roadmap files directly in this repo."
    : "This state needs a manual config or path fix before the workspace can load.";
  const stats = [
    { label: "Expected", value: setup.expectedEntries.length },
    { label: "Missing", value: setup.missingEntries.length },
    { label: "Invalid", value: setup.invalidEntries.length },
  ];
  const statsHtml = stats.map(({ label, value }) => `
    <div class="setup-stat">
      <span class="setup-stat-label">${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value))}</strong>
    </div>
  `).join("");
  const actionHtml = setup.canInitialize
    ? '<div class="setup-actions"><button class="primary-button" type="button" data-setup-action="initialize">Create starter roadmap workspace</button></div>'
    : "";
  const invalidCard = setup.invalidEntries.length > 0
    ? `
      <section class="setup-card">
        <div class="setup-card-header">
          <p class="setup-kicker">Needs manual fix</p>
          <h3>Correct these entries</h3>
        </div>
        ${renderSetupList(setup.invalidEntries, "No invalid entries were provided.")}
      </section>
    `
    : "";
  const configHelp = setup.suggestedConfig
    ? `
      <section class="setup-card setup-card-wide">
        <div class="setup-card-header">
          <p class="setup-kicker">Suggested config</p>
          <h3>Point minimap at a custom roadmap path</h3>
        </div>
        <pre class="setup-code">${escapeHtml(setup.suggestedConfig)}</pre>
      </section>
    `
    : "";

  editorTitleElement.textContent = setup.title;
  editorSubtitleElement.textContent = setup.roadmapPath;
  setupViewElement.hidden = false;
  setupViewElement.innerHTML = `
    <div class="setup-shell">
      <section class="setup-hero">
        <div class="setup-hero-copy">
          <p class="setup-kicker">${escapeHtml(setup.code === "config_error" ? "Config" : "Onboarding")}</p>
          <h3>${escapeHtml(setup.title)}</h3>
          <p class="setup-lead">${escapeHtml(setup.description)}</p>
          <p class="setup-message">${escapeHtml(setup.message)}</p>
          <div class="setup-path-row">
            <span class="setup-path-label">Roadmap path</span>
            <code>${escapeHtml(setup.roadmapPath)}</code>
          </div>
          <p class="muted">${escapeHtml(locationSummary)}</p>
        </div>
        <div class="setup-hero-side">
          <div class="setup-stat-grid">${statsHtml}</div>
          <p class="setup-side-copy">${escapeHtml(statusSummary)}</p>
          ${actionHtml}
        </div>
      </section>
      <div class="setup-grid">
        <section class="setup-card">
          <div class="setup-card-header">
            <p class="setup-kicker">Expected workspace</p>
            <h3>Starter file shape</h3>
          </div>
          ${renderSetupList(setup.expectedEntries, "No expected entries were provided.")}
        </section>
        <section class="setup-card">
          <div class="setup-card-header">
            <p class="setup-kicker">Missing now</p>
            <h3>What is not present yet</h3>
          </div>
          ${renderSetupList(setup.missingEntries, "Nothing is missing, but the current setup still needs attention.")}
        </section>
        <section class="setup-card setup-card-note">
          <div class="setup-card-header">
            <p class="setup-kicker">Next step</p>
            <h3>${escapeHtml(setup.canInitialize ? "Create the starter workspace" : "Fix the current path")}</h3>
          </div>
          <p>${escapeHtml(setup.canInitialize
            ? "Use the action above to scaffold board.md, scope.md, features/, and ideas/ directly in the configured roadmap path."
            : "Fix the config or missing path first, then refresh minimap to load the workspace.")}</p>
        </section>
        ${invalidCard}
        ${configHelp}
      </div>
    </div>
  `;

  const initializeButton = setupViewElement.querySelector('[data-setup-action="initialize"]');
  if (initializeButton) {
    initializeButton.addEventListener("click", () => {
      void initializeWorkspaceFromSetup();
    });
  }
}

function normalizeBadgeToken(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function getBadgeTone(field, value) {
  const normalizedValue = normalizeBadgeToken(value);

  if (field === "status") {
    if (normalizedValue === "done") {
      return "status-done";
    }
    if (normalizedValue === "blocked") {
      return "status-blocked";
    }
    if (normalizedValue === "in-progress") {
      return "status-progress";
    }
    if (normalizedValue === "queued") {
      return "status-queued";
    }
  }

  if (field === "commitment") {
    if (normalizedValue === "committed") {
      return "commitment-committed";
    }
    if (normalizedValue === "uncommitted") {
      return "commitment-uncommitted";
    }
  }

  return "neutral";
}

function renderBadge(value, field = "") {
  const normalizedField = normalizeBadgeToken(field);
  const tone = getBadgeTone(normalizedField, value);
  const classes = ["badge", `badge-tone-${tone}`];
  if (normalizedField) {
    classes.push(`badge-field-${normalizedField}`);
  }
  return `<span class="${classes.join(" ")}">${escapeHtml(value)}</span>`;
}

function renderBadges(item, excludeKey = "") {
  return [
    excludeKey === "status" ? null : { field: "status", value: item.status },
    excludeKey === "priority" ? null : { field: "priority", value: item.priority },
    excludeKey === "commitment" ? null : { field: "commitment", value: item.commitment },
    excludeKey === "milestone" ? null : { field: "milestone", value: item.milestone },
  ]
    .filter((entry) => entry?.value)
    .map((entry) => renderBadge(entry.value, entry.field))
    .join("");
}

function updateDocumentTitle() {
  const repoName = state.workspace?.repoName || repoNameElement.textContent || "Roadmap";
  repoNameElement.textContent = repoName;
  document.title = `${repoName} Roadmap`;
}

function updateWorkspaceSummary() {
  const groups = state.workspace?.boardGroups.length ?? 0;
  const items = getBoardItems().length;
  const activeLens = getActiveLensDefinition();
  const visibleItems = getVisibleBoardItemIds().length;

  if (state.setupState) {
    workspaceSummaryElement.textContent = "Setup required";
    return;
  }

  if (!state.workspace) {
    workspaceSummaryElement.textContent = "Unavailable";
    return;
  }

  if (activeLens?.key !== DEFAULT_LENS_KEY) {
    workspaceSummaryElement.textContent = `${visibleItems} shown / ${items} items / ${activeLens.label}`;
    return;
  }

  if (isSearchActive()) {
    workspaceSummaryElement.textContent = `${visibleItems} shown / ${items} items / ${groups} groups`;
    return;
  }

  workspaceSummaryElement.textContent = `${items} items / ${groups} groups`;
}

function normalizeEditorMode(mode) {
  return EDITOR_MODES.has(mode) ? mode : "preview";
}

function readRouteState() {
  const rawHash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : "";
  const params = new URLSearchParams(rawHash);
  return {
    itemId: params.get("item") || "",
    mode: normalizeEditorMode(params.get("mode") || "preview"),
    lens: params.get("lens") || DEFAULT_LENS_KEY,
    layout: normalizeBoardLayout(params.get("layout") || DEFAULT_BOARD_LAYOUT),
    query: normalizeSearchQuery(params.get("q") || ""),
    filters: parseRouteFilters(params),
  };
}

function buildRouteHash(itemId = state.selectedItemId, mode = state.editorMode) {
  const params = new URLSearchParams();
  const persistSelectedItem = !shouldUseEditorOverlay() || state.editorOverlayOpen;

  if (persistSelectedItem && itemId) {
    params.set("item", itemId);
  }

  const normalizedMode = normalizeEditorMode(mode);
  if (persistSelectedItem && normalizedMode !== "preview") {
    params.set("mode", normalizedMode);
  }

  const lensKey = normalizeLensKey(state.activeLens);
  if (lensKey !== DEFAULT_LENS_KEY) {
    params.set("lens", lensKey);
  }

  const layout = normalizeBoardLayout(state.boardLayout);
  if (layout !== DEFAULT_BOARD_LAYOUT) {
    params.set("layout", layout);
  }

  if (state.searchQuery) {
    params.set("q", state.searchQuery);
  }

  serializeRouteFilters(params, state.activeFilters);

  const serialized = params.toString();
  return serialized ? `#${serialized}` : "";
}

function syncRouteState({ replace = false } = {}) {
  const nextHash = buildRouteHash();
  if (window.location.hash === nextHash) {
    return;
  }

  const nextUrl = `${window.location.pathname}${window.location.search}${nextHash}`;
  if (replace) {
    window.history.replaceState(null, "", nextUrl);
    return;
  }

  window.history.pushState(null, "", nextUrl);
}

function isStackedLayout() {
  return stackedLayoutMedia.matches;
}

function isDesktopScopeLayout() {
  return desktopScopeLayoutMedia.matches;
}

function scrollPanelIntoView(element) {
  element?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function syncMobileNavigation() {
  const stacked = isStackedLayout();
  const hasInlineItem = Boolean(state.selectedItemId) && !shouldUseEditorOverlay();
  jumpToBoardButton.hidden = !stacked || shouldUseEditorOverlay();
  jumpToBoardButton.disabled = !stacked || shouldUseEditorOverlay();
  jumpToEditorButton.hidden = !stacked || !hasInlineItem || state.boardEditMode;
  jumpToEditorButton.disabled = !stacked || !hasInlineItem || state.boardEditMode;
}

function shouldUseEditorOverlay() {
  return !isSetupMode() && isColumnsLayoutActive();
}

function renderEditorPresentation() {
  const useOverlay = shouldUseEditorOverlay();
  const showOverlay = useOverlay && state.editorOverlayOpen && Boolean(state.currentItem && state.selectedItemId);

  if (useOverlay) {
    if (editorOverlaySlotElement && editorPanelElement.parentElement !== editorOverlaySlotElement) {
      editorOverlaySlotElement.appendChild(editorPanelElement);
    }
  } else if (editorPanelAnchor && editorPanelElement.parentElement !== layoutElement) {
    layoutElement.insertBefore(editorPanelElement, editorPanelAnchor);
  }

  layoutElement.dataset.editorOverlayOpen = String(showOverlay);
  document.body.dataset.editorOverlayOpen = String(showOverlay);
  if (editorOverlayElement) {
    editorOverlayElement.hidden = !showOverlay;
    editorOverlayElement.setAttribute("aria-hidden", showOverlay ? "false" : "true");
    editorOverlayElement.dataset.open = String(showOverlay);
  }
}

function confirmCloseCurrentItem() {
  if (!state.currentItem || !hasUnsavedCurrentItemChanges()) {
    return true;
  }

  if (state.dirtyRaw) {
    return window.confirm("Discard unsaved raw markdown changes and close the item?");
  }

  return window.confirm("Discard unsaved item changes and close the item?");
}

function closeEditorOverlay(force = false) {
  if (!force && !confirmCloseCurrentItem()) {
    return false;
  }

  state.editorOverlayOpen = false;
  resetEditor();
  syncWorkspaceChrome();
  renderBoard();
  syncRouteState({ replace: true });
  return true;
}

function renderLayoutControls() {
  if (!boardLayoutControlsElement || !boardLayoutListButton || !boardLayoutColumnsButton) {
    return;
  }

  const hidden = isSetupMode() || state.boardEditMode || !state.workspace;
  boardLayoutControlsElement.hidden = hidden;

  if (hidden) {
    return;
  }

  const activeLayout = normalizeBoardLayout(state.boardLayout);
  const buttons = [
    [boardLayoutListButton, "list"],
    [boardLayoutColumnsButton, "columns"],
  ];

  for (const [button, layoutKey] of buttons) {
    const active = layoutKey === activeLayout;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
    button.disabled = active;
  }
}

function positionLensControls() {
  if (!boardLensSwitcherElement || !boardViewToggleButton || !boardControlsElement || boardLensSwitcherElement.hidden) {
    return;
  }

  if (window.innerWidth <= 760) {
    boardLensSwitcherElement.style.left = "0px";
    boardLensSwitcherElement.style.right = "0px";
    boardLensSwitcherElement.style.top = "42px";
    return;
  }

  boardLensSwitcherElement.style.right = "auto";

  const controlsRect = boardControlsElement.getBoundingClientRect();
  const triggerRect = boardViewToggleButton.getBoundingClientRect();
  const desiredLeft = triggerRect.left - controlsRect.left;
  const desiredTop = triggerRect.bottom - controlsRect.top + 6;
  const panelWidth = boardLensSwitcherElement.offsetWidth;
  const maxLeft = Math.max(0, controlsRect.width - panelWidth);
  const clampedLeft = Math.min(Math.max(0, desiredLeft), maxLeft);

  boardLensSwitcherElement.style.left = `${Math.round(clampedLeft)}px`;
  boardLensSwitcherElement.style.top = `${Math.round(desiredTop)}px`;
}

function renderLensControls() {
  if (!boardLensSwitcherElement || !boardViewToggleButton) {
    return;
  }

  if (!state.workspace) {
    boardViewToggleButton.hidden = true;
    boardLensSwitcherElement.hidden = true;
    boardLensSwitcherElement.innerHTML = "";
    return;
  }

  const lenses = getAvailableLenses();
  const activeLens = getActiveLensDefinition();
  const activeLensKey = normalizeLensKey(state.activeLens);
  const hasAlternateLenses = lenses.length > 1;
  const showLenses = hasAlternateLenses && state.lensesExpanded && !state.boardEditMode;

  boardViewToggleButton.hidden = !hasAlternateLenses;
  boardViewToggleButton.disabled = !hasAlternateLenses || state.boardEditMode;
  boardViewToggleButton.textContent = activeLensKey === DEFAULT_LENS_KEY ? "Group by" : `By ${activeLens.label.toLowerCase()}`;
  boardViewToggleButton.setAttribute("aria-label", activeLensKey === DEFAULT_LENS_KEY ? "Change board grouping" : `Change board grouping, current: ${activeLens.label}`);
  boardViewToggleButton.setAttribute("aria-expanded", showLenses ? "true" : "false");
  boardViewToggleButton.classList.toggle("is-active", showLenses || activeLensKey !== DEFAULT_LENS_KEY);

  if (!showLenses) {
    boardLensSwitcherElement.hidden = true;
    boardLensSwitcherElement.innerHTML = "";
    boardLensSwitcherElement.style.left = "";
    boardLensSwitcherElement.style.right = "";
    boardLensSwitcherElement.style.top = "";
    return;
  }

  const buttonsHtml = lenses.map((lens) => `
    <button class="board-lens-button${lens.key === activeLensKey ? " is-active" : ""}" data-lens-key="${escapeHtml(lens.key)}" type="button">${escapeHtml(lens.label)}</button>
  `).join("");

  boardLensSwitcherElement.hidden = false;
  boardLensSwitcherElement.innerHTML = `<div class="board-lens-buttons">${buttonsHtml}</div>`;
  positionLensControls();

  for (const button of boardLensSwitcherElement.querySelectorAll("[data-lens-key]")) {
    button.addEventListener("click", () => {
      state.activeLens = button.dataset.lensKey || DEFAULT_LENS_KEY;
      state.lensesExpanded = false;
      void syncVisibleSelection({ replaceRoute: true });
    });
  }
}

function renderSearchControls() {
  if (!boardSearchInput || !boardViewToggleButton || !boardFilterToggleButton || !boardFiltersElement || !boardClearFiltersButton) {
    return;
  }

  const facets = state.workspace?.availableFilters ?? [];
  const activeFilterKeys = Object.keys(state.activeFilters);
  const activeFilterCount = activeFilterKeys.reduce((count, key) => count + (state.activeFilters[key]?.length || 0), 0);
  const showFilters = facets.length > 0 && state.filtersExpanded;

  boardSearchInput.value = state.searchQuery;
  boardSearchInput.disabled = !state.workspace || state.boardEditMode;
  boardFilterToggleButton.disabled = facets.length === 0 || state.boardEditMode;
  boardFilterToggleButton.textContent = activeFilterCount > 0 ? `Filters (${activeFilterCount})` : "Filters";
  boardFilterToggleButton.setAttribute("aria-expanded", showFilters ? "true" : "false");
  boardFilterToggleButton.classList.toggle("is-active", showFilters || activeFilterCount > 0);
  boardClearFiltersButton.disabled = !isSearchActive() || state.boardEditMode;

  renderLensControls();

  boardFiltersElement.hidden = !showFilters;
  boardFiltersElement.innerHTML = showFilters
    ? facets.map((facet) => {
        const activeValues = new Set(state.activeFilters[facet.key] || []);
        const chips = facet.values.map((value) => `
          <button class="filter-chip${activeValues.has(value) ? " is-active" : ""}" data-filter-key="${escapeHtml(facet.key)}" data-filter-value="${escapeHtml(value)}" type="button" ${state.boardEditMode ? "disabled" : ""}>${escapeHtml(value)}</button>
        `).join("");

        return `
          <section class="filter-group">
            <div class="filter-group-label">${escapeHtml(humanizeFilterKey(facet.key))}</div>
            <div class="filter-chip-row">${chips}</div>
          </section>
        `;
      }).join("")
    : "";

  if (!showFilters) {
    return;
  }

  for (const button of boardFiltersElement.querySelectorAll("[data-filter-key]")) {
    button.addEventListener("click", () => {
      const key = button.dataset.filterKey;
      const value = button.dataset.filterValue;
      const nextFilters = normalizeFilterMap({ ...state.activeFilters });
      const values = new Set(nextFilters[key] || []);

      if (values.has(value)) {
        values.delete(value);
      } else {
        values.add(value);
      }

      if (values.size === 0) {
        delete nextFilters[key];
      } else {
        nextFilters[key] = Array.from(values).sort((left, right) => left.localeCompare(right));
      }

      state.activeFilters = normalizeFilterMap(nextFilters);
      void syncVisibleSelection({ replaceRoute: true });
    });
  }
}

function renderBoardChrome() {
  const setupMode = isSetupMode();
  const boardLensActive = isBoardLensActive();
  const listLayoutActive = !isColumnsLayoutActive();
  boardEditButton.hidden = setupMode || state.boardEditMode || !boardLensActive || !listLayoutActive;
  boardSaveButton.hidden = setupMode || !state.boardEditMode;
  boardCancelButton.hidden = setupMode || !state.boardEditMode;
  boardControlsElement.hidden = setupMode;
  boardSaveButton.disabled = !state.boardDirty;
  renderLayoutControls();
  renderSearchControls();
}

function renderScopeChrome() {
  const setupMode = isSetupMode();
  const showResizer = !setupMode && !state.scopeCollapsed && isDesktopScopeLayout();

  layoutElement.dataset.scopeCollapsed = String(state.scopeCollapsed);
  layoutElement.style.setProperty("--scope-width", `${state.scopeWidth}px`);
  scopePanelElement.classList.toggle("scope-collapsed", state.scopeCollapsed);
  scopePanelElement.classList.toggle("scope-editing", state.scopeEditMode);
  scopeSubtitleElement.textContent = "";
  scopeSubtitleElement.hidden = true;
  scopeEditButton.hidden = setupMode || state.scopeEditMode || state.scopeCollapsed;
  scopeSaveButton.hidden = setupMode || !state.scopeEditMode;
  scopeCancelButton.hidden = setupMode || !state.scopeEditMode;
  scopeSaveButton.disabled = !state.scopeDirty;
  scopeToggleButton.hidden = setupMode || state.scopeEditMode;
  scopeToggleButton.disabled = setupMode || state.scopeEditMode;
  scopeToggleButton.textContent = state.scopeCollapsed ? "Open" : "Collapse";
  scopeToggleButton.setAttribute("aria-expanded", state.scopeCollapsed ? "false" : "true");
  scopeResizerElement.hidden = !showResizer;
  scopeResizerElement.setAttribute("aria-hidden", showResizer ? "false" : "true");
  scopeResizerElement.setAttribute("aria-valuemin", String(MIN_SCOPE_WIDTH));
  scopeResizerElement.setAttribute("aria-valuemax", String(MAX_SCOPE_WIDTH));
  scopeResizerElement.setAttribute("aria-valuenow", String(state.scopeWidth));
}

function renderEditorChrome() {
  const setupMode = isSetupMode();
  const hasItem = Boolean(state.currentItem && state.selectedItemId);
  const useOverlay = shouldUseEditorOverlay() && state.editorOverlayOpen && hasItem;
  const overlayPreview = useOverlay && state.editorMode === "preview";
  editorPanelElement.dataset.editorMode = state.editorMode;
  saveButton.hidden = setupMode;
  editorTabsElement.hidden = setupMode;

  if (editorCancelButton) {
    editorCancelButton.hidden = true;
    editorCancelButton.disabled = true;
  }

  if (editorOverlayCloseButton) {
    editorOverlayCloseButton.hidden = true;
    editorOverlayCloseButton.disabled = true;
  }

  if (setupMode) {
    for (const pane of modePanes) {
      pane.hidden = true;
    }
    return;
  }

  if (state.editorMode === "preview") {
    saveButton.hidden = !overlayPreview;
    saveButton.textContent = "Close";
    saveButton.disabled = !hasItem;
    return;
  }

  const dirty = state.editorMode === "raw" ? state.dirtyRaw : state.dirtyStructured;
  saveButton.hidden = false;
  saveButton.textContent = "Save";
  saveButton.disabled = !hasItem || !dirty;

  if (editorCancelButton) {
    editorCancelButton.hidden = !hasItem;
    editorCancelButton.disabled = !hasItem;
  }
}

function syncWorkspaceChrome() {
  const setupMode = isSetupMode();
  document.body.dataset.setupMode = String(setupMode);
  layoutElement.dataset.setupMode = String(setupMode);
  layoutElement.dataset.boardLayout = normalizeBoardLayout(state.boardLayout);
  updateDocumentTitle();
  updateWorkspaceSummary();
  renderBoardChrome();
  renderScopeChrome();
  renderEditorChrome();
  renderEditorPresentation();
  renderSetupView();
  syncMobileNavigation();
}

function toggleScopePanel() {
  if (state.scopeEditMode) {
    return;
  }

  state.scopeCollapsed = !state.scopeCollapsed;
  persistScopePreference();
  renderScopeChrome();
}

function beginScopeResize(event) {
  if (!isDesktopScopeLayout() || state.scopeCollapsed) {
    return;
  }

  event.preventDefault();
  const startX = event.clientX;
  const startWidth = state.scopeWidth;
  document.body.classList.add("is-resizing-scope");

  function handlePointerMove(moveEvent) {
    const nextWidth = clampScopeWidth(startWidth + (startX - moveEvent.clientX));
    if (nextWidth !== state.scopeWidth) {
      state.scopeWidth = nextWidth;
      renderScopeChrome();
    }
  }

  function stopResize() {
    document.body.classList.remove("is-resizing-scope");
    window.removeEventListener("pointermove", handlePointerMove);
    window.removeEventListener("pointerup", stopResize);
    window.removeEventListener("pointercancel", stopResize);
    persistScopeWidth();
  }

  window.addEventListener("pointermove", handlePointerMove);
  window.addEventListener("pointerup", stopResize);
  window.addEventListener("pointercancel", stopResize);
}

function toggleGroup(name) {
  if (state.collapsedGroups.has(name)) {
    state.collapsedGroups.delete(name);
  } else {
    state.collapsedGroups.add(name);
  }

  renderBoard();
}

function reorderGroups(groups, fromIndex, toIndex) {
  const nextGroups = [...groups];
  const [moved] = nextGroups.splice(fromIndex, 1);
  nextGroups.splice(toIndex, 0, moved);
  return nextGroups;
}

function cloneBoardDraftFromWorkspace() {
  return state.workspace?.boardGroups.map((group) => ({
    name: group.name,
    itemIds: group.items.map((item) => item.id),
  })) ?? [];
}

function markBoardDirty() {
  state.boardDirty = true;
  renderBoardChrome();
}

function findBoardDraftItem(itemId) {
  if (!state.boardDraft) {
    return { groupIndex: -1, itemIndex: -1 };
  }

  for (let groupIndex = 0; groupIndex < state.boardDraft.length; groupIndex += 1) {
    const itemIndex = state.boardDraft[groupIndex].itemIds.indexOf(itemId);
    if (itemIndex >= 0) {
      return { groupIndex, itemIndex };
    }
  }

  return { groupIndex: -1, itemIndex: -1 };
}

function moveDraftGroup(fromIndex, toIndex) {
  if (!state.boardDraft || fromIndex === toIndex || toIndex < 0 || toIndex >= state.boardDraft.length) {
    return;
  }

  state.boardDraft = reorderGroups(state.boardDraft, fromIndex, toIndex);
  markBoardDirty();
  renderBoard();
}

function updateDraftGroupName(groupIndex, nextName) {
  if (!state.boardDraft?.[groupIndex]) {
    return;
  }

  state.boardDraft[groupIndex].name = nextName;
  markBoardDirty();
}
function moveDraftItemToGroup(itemId, targetGroupIndex) {
  if (!state.boardDraft?.[targetGroupIndex]) {
    return;
  }

  const { groupIndex, itemIndex } = findBoardDraftItem(itemId);
  if (groupIndex < 0 || itemIndex < 0 || groupIndex === targetGroupIndex) {
    return;
  }

  state.boardDraft[groupIndex].itemIds.splice(itemIndex, 1);
  state.boardDraft[targetGroupIndex].itemIds.push(itemId);
  markBoardDirty();
  renderBoard();
}

function moveDraftItemWithinGroup(groupIndex, itemIndex, direction) {
  const group = state.boardDraft?.[groupIndex];
  if (!group) {
    return;
  }

  const targetIndex = direction === "up" ? itemIndex - 1 : itemIndex + 1;
  if (targetIndex < 0 || targetIndex >= group.itemIds.length) {
    return;
  }

  const [itemId] = group.itemIds.splice(itemIndex, 1);
  group.itemIds.splice(targetIndex, 0, itemId);
  markBoardDirty();
  renderBoard();
}

function startBoardEditMode() {
  if (!state.workspace) {
    return;
  }

  state.boardEditMode = true;
  state.boardDraft = cloneBoardDraftFromWorkspace();
  state.boardDirty = false;
  renderBoardChrome();
  renderBoard();
}

function cancelBoardEditMode(force = false) {
  if (state.boardEditMode && state.boardDirty && !force) {
    if (!window.confirm("Discard unsaved board changes?")) {
      return;
    }
  }

  state.boardEditMode = false;
  state.boardDraft = null;
  state.boardDirty = false;
  renderBoardChrome();
  renderBoard();
}

async function persistImmediateBoardOrder(groups) {
  const workspace = await fetchJson("/api/board", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ groups }),
  });

  state.workspace = workspace;
  syncWorkspaceChrome();
}

async function persistGroupOrder(fromIndex, toIndex) {
  if (!state.workspace || fromIndex === toIndex || toIndex < 0 || toIndex >= state.workspace.boardGroups.length) {
    return;
  }

  const previousGroups = state.workspace.boardGroups;
  state.workspace = {
    ...state.workspace,
    boardGroups: reorderGroups(previousGroups, fromIndex, toIndex),
  };
  renderBoard();
  setBanner("Saving board order...");

  try {
    const groups = state.workspace.boardGroups.map((group) => ({
      name: group.name,
      itemIds: group.items.map((item) => item.id),
    }));
    await persistImmediateBoardOrder(groups);
    renderBoard();
    setBanner("Board order saved.", "success");
  } catch (error) {
    state.workspace = {
      ...state.workspace,
      boardGroups: previousGroups,
    };
    renderBoard();
    setBanner(error.message, "error");
  }
}

async function saveBoardDraft() {
  if (!state.boardDraft) {
    return;
  }

  boardSaveButton.disabled = true;
  setBanner("Saving board...");

  try {
    const workspace = await fetchJson("/api/board", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ groups: state.boardDraft }),
    });

    state.workspace = workspace;
    state.boardEditMode = false;
    state.boardDraft = null;
    state.boardDirty = false;
    syncWorkspaceChrome();
    renderBoard();
    renderScope();
    setBanner("Board saved.", "success");
  } catch (error) {
    renderBoardChrome();
    setBanner(error.message, "error");
  }
}

function buildBoardGroupOptions(selectedIndex) {
  return (state.boardDraft ?? [])
    .map((group, index) => {
      const label = group.name.trim() || `Group ${index + 1}`;
      return `<option value="${index}" ${index === selectedIndex ? "selected" : ""}>${escapeHtml(label)}</option>`;
    })
    .join("");
}

function getBoardGroupIndexForItem(itemId, workspace = state.workspace) {
  if (!workspace || !itemId) {
    return -1;
  }

  return workspace.boardGroups.findIndex((group) => group.items.some((item) => item.id === itemId));
}

function renderBoardGroupField(itemId = state.selectedItemId) {
  if (!fields.boardGroup) {
    return;
  }

  const groups = state.workspace?.boardGroups ?? [];
  const selectedIndex = getBoardGroupIndexForItem(itemId);

  if (groups.length === 0) {
    fields.boardGroup.innerHTML = '<option value="">No board groups</option>';
    fields.boardGroup.disabled = true;
    return;
  }

  const options = groups.map((group, index) => {
    const label = group.name.trim() || `Group ${index + 1}`;
    return `<option value="${index}">${escapeHtml(label)}</option>`;
  }).join("");

  fields.boardGroup.innerHTML = selectedIndex < 0
    ? `<option value="" selected>Not on board</option>${options}`
    : options;
  fields.boardGroup.disabled = false;
  fields.boardGroup.value = selectedIndex >= 0 ? String(selectedIndex) : "";
}

function buildBoardGroupsWithMovedItem(itemId, targetGroupIndex, boardGroups = buildBoardGroupsPayload()) {
  if (!itemId || !Number.isInteger(targetGroupIndex) || targetGroupIndex < 0 || targetGroupIndex >= boardGroups.length) {
    return null;
  }

  const sourceGroupIndex = boardGroups.findIndex((group) => group.itemIds.includes(itemId));
  if (sourceGroupIndex < 0 || sourceGroupIndex === targetGroupIndex) {
    return null;
  }

  const groups = boardGroups.map((group) => ({
    ...group,
    itemIds: [...group.itemIds],
  }));

  groups[sourceGroupIndex] = {
    ...groups[sourceGroupIndex],
    itemIds: groups[sourceGroupIndex].itemIds.filter((currentId) => currentId !== itemId),
  };
  groups[targetGroupIndex] = {
    ...groups[targetGroupIndex],
    itemIds: [...groups[targetGroupIndex].itemIds.filter((currentId) => currentId !== itemId), itemId],
  };

  return groups;
}

function clearBoardDragState() {
  state.dragItemId = null;
  for (const dropZone of boardGroupsElement.querySelectorAll("[data-lens-drop-value], [data-board-drop-group-index]")) {
    dropZone.classList.remove("is-drop-target");
  }
  for (const element of boardGroupsElement.querySelectorAll(".is-dragging")) {
    element.classList.remove("is-dragging");
  }
}

function buildBoardCardBodyMarkup(item, activeLensKey, extraMetaHtml = "") {
  const metaParts = [];
  if (activeLensKey !== "kind") {
    metaParts.push(`<span class="board-item-kind">${escapeHtml(item.kind)}</span>`);
  }
  if (extraMetaHtml) {
    metaParts.push(extraMetaHtml);
  }

  const metaHtml = metaParts.length > 0 ? `<span class="board-item-meta">${metaParts.join("")}</span>` : "";
  const overview = item.overviewExcerpt ? `<span class="board-item-overview">${escapeHtml(item.overviewExcerpt)}</span>` : "";

  return `
    <span class="board-item-top">
      <span class="board-item-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</span>
      ${metaHtml}
    </span>
    <span class="board-item-id">${escapeHtml(item.id)}</span>
    ${overview}
    <span class="badge-row">${renderBadges(item, activeLensKey)}</span>
  `;
}

function buildBoardGroupsPayload(boardGroups = state.workspace?.boardGroups ?? []) {
  return boardGroups.map((group) => ({
    name: group.name,
    itemIds: group.items.map((item) => item.id),
  }));
}

async function persistBoardColumnMove(itemId, targetGroupIndex) {
  if (!state.workspace || !itemId || !Number.isInteger(targetGroupIndex) || targetGroupIndex < 0 || targetGroupIndex >= state.workspace.boardGroups.length) {
    return;
  }

  const groups = buildBoardGroupsWithMovedItem(itemId, targetGroupIndex);
  if (!groups) {
    return;
  }

  setBanner("Updating board group...");

  try {
    const workspace = await fetchJson("/api/board", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ groups }),
    });

    const keepItemOpen = !shouldUseEditorOverlay() || (state.editorOverlayOpen && state.selectedItemId === itemId);
    state.workspace = workspace;
    if (!keepItemOpen) {
      state.editorOverlayOpen = false;
    }
    syncWorkspaceChrome();
    await syncVisibleSelection({
      preferredItemId: keepItemOpen ? itemId : "",
      replaceRoute: true,
      forceReloadItem: keepItemOpen,
    });
    setBanner("Board updated.", "success");
  } catch (error) {
    setBanner(error.message, "error");
  }
}

async function persistDerivedLensMove(itemId, targetValue) {
  const activeLens = getActiveLensDefinition();
  if (!activeLens || activeLens.key === DEFAULT_LENS_KEY || !activeLens.draggable || !targetValue) {
    return;
  }

  setBanner(`Updating ${activeLens.label.toLowerCase()}...`);

  try {
    await fetchJson(`/api/items/${encodeURIComponent(itemId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        metadata: {
          [activeLens.key]: targetValue,
        },
      }),
    });

    const keepItemOpen = !shouldUseEditorOverlay() || (state.editorOverlayOpen && state.selectedItemId === itemId);
    if (!keepItemOpen) {
      state.editorOverlayOpen = false;
    }
    await loadWorkspace(keepItemOpen ? itemId : "", {
      replaceRoute: true,
      forceReloadItem: keepItemOpen,
      preferredLayout: state.boardLayout,
      preferredLens: state.activeLens,
    });
    setBanner(`${activeLens.label} updated.`, "success");
  } catch (error) {
    setBanner(error.message, "error");
  }
}

function renderBoardColumnsMode() {
  if (!state.workspace) {
    boardGroupsElement.innerHTML = "";
    return;
  }

  const activeLens = getActiveLensDefinition();
  const visibleGroups = getVisibleBoardGroups();
  const allowColumnDrag = canDragItemsInColumnLayout();
  const boardGrouping = activeLens?.key === DEFAULT_LENS_KEY;

  if (visibleGroups.length === 0) {
    boardGroupsElement.innerHTML = `
      <div class="empty-state">
        <div>No roadmap items match the current view.</div>
        <div class="board-empty-hint">Clear the query or filters to see the full board again.</div>
      </div>
    `;
    syncMobileNavigation();
    return;
  }

  const columnsHtml = visibleGroups.map((group) => {
    const dropAttributes = allowColumnDrag
      ? (boardGrouping
        ? `data-board-drop-group-index="${group.originalIndex}"`
        : (group.dropValue ? `data-lens-drop-value="${escapeHtml(group.dropValue)}"` : ""))
      : "";

    const cardsHtml = group.items.map((item) => {
      const activeClass = item.id === state.selectedItemId && state.editorOverlayOpen ? " board-column-card-active" : "";
      const dragHandle = allowColumnDrag
        ? `<span class="board-column-card-drag" data-drag-item-id="${escapeHtml(item.id)}" draggable="true" role="button" tabindex="0" aria-label="Move ${escapeHtml(item.title)}" title="Drag to move ${escapeHtml(item.title)}">::</span>`
        : "";

      return `
        <article class="board-column-card${activeClass}" title="${escapeHtml(item.title)}">
          <div class="board-column-card-main" data-item-dblopen="${escapeHtml(item.id)}" title="${escapeHtml(item.title)}">
            ${buildBoardCardBodyMarkup(item, activeLens?.key)}
          </div>
          <div class="board-column-card-actions">
            <button class="ghost-button board-column-card-open" data-item-open="${escapeHtml(item.id)}" type="button" aria-label="Open ${escapeHtml(item.title)}">Open</button>
            ${dragHandle}
          </div>
        </article>
      `;
    }).join("");

    return `
      <section class="board-column">
        <div class="board-column-header">
          <div class="board-column-heading">
            <span class="board-column-name">${escapeHtml(group.name)}</span>
            <span class="group-count">${group.items.length}</span>
          </div>
        </div>
        <div class="board-column-list${dropAttributes ? " board-column-dropzone" : ""}" ${dropAttributes}>
          ${cardsHtml || '<div class="board-column-empty">No visible items.</div>'}
        </div>
      </section>
    `;
  }).join("");

  boardGroupsElement.innerHTML = `<div class="board-columns">${columnsHtml}</div>`;
  syncMobileNavigation();

  for (const button of boardGroupsElement.querySelectorAll("[data-item-open]")) {
    button.addEventListener("click", async () => {
      if (Date.now() < state.dragClickSuppressUntil) {
        return;
      }

      await openBoardItemPreview(button.dataset.itemOpen);
    });
  }

  for (const panel of boardGroupsElement.querySelectorAll("[data-item-dblopen]")) {
    panel.addEventListener("dblclick", async () => {
      if (Date.now() < state.dragClickSuppressUntil) {
        return;
      }

      await openBoardItemPreview(panel.dataset.itemDblopen);
    });
  }

  if (!allowColumnDrag) {
    return;
  }

  for (const handle of boardGroupsElement.querySelectorAll("[data-drag-item-id]")) {
    handle.addEventListener("dragstart", (event) => {
      const itemId = handle.dataset.dragItemId || "";
      if (!itemId) {
        event.preventDefault();
        return;
      }

      state.dragItemId = itemId;
      state.dragClickSuppressUntil = Date.now() + 350;
      handle.classList.add("is-dragging");
      event.dataTransfer?.setData("text/plain", itemId);
      event.dataTransfer?.setData("application/x-minimap-item-id", itemId);
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
      }
    });

    handle.addEventListener("dragend", () => {
      state.dragClickSuppressUntil = Date.now() + 350;
      clearBoardDragState();
    });
  }

  for (const dropZone of boardGroupsElement.querySelectorAll("[data-board-drop-group-index], [data-lens-drop-value]")) {
    dropZone.addEventListener("dragover", (event) => {
      event.preventDefault();
      dropZone.classList.add("is-drop-target");
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = "move";
      }
    });

    dropZone.addEventListener("dragleave", () => {
      dropZone.classList.remove("is-drop-target");
    });

    dropZone.addEventListener("drop", (event) => {
      event.preventDefault();
      const itemId = event.dataTransfer?.getData("application/x-minimap-item-id")
        || event.dataTransfer?.getData("text/plain")
        || state.dragItemId
        || "";
      state.dragClickSuppressUntil = Date.now() + 350;
      clearBoardDragState();
      if (!itemId) {
        return;
      }

      if (dropZone.dataset.boardDropGroupIndex) {
        void persistBoardColumnMove(itemId, Number(dropZone.dataset.boardDropGroupIndex));
        return;
      }

      if (dropZone.dataset.lensDropValue) {
        void persistDerivedLensMove(itemId, dropZone.dataset.lensDropValue || "");
      }
    });
  }
}

function renderBoardReadMode() {
  if (!state.workspace) {
    boardGroupsElement.innerHTML = "";
    return;
  }

  if (isColumnsLayoutActive()) {
    renderBoardColumnsMode();
    return;
  }

  if (state.workspace.boardGroups.length === 0 && isBoardLensActive()) {
    boardGroupsElement.innerHTML = '<div class="empty-state">No board groups found in board.md.</div>';
    syncMobileNavigation();
    return;
  }

  const activeLens = getActiveLensDefinition();
  const visibleGroups = getVisibleBoardGroups();
  const filtered = isSearchActive();
  const allowGroupReorder = activeLens?.key === DEFAULT_LENS_KEY;
  const allowDerivedDrag = canDragItemsInActiveLens();

  if (visibleGroups.length === 0) {
    boardGroupsElement.innerHTML = `
      <div class="empty-state">
        <div>No roadmap items match the current view.</div>
        <div class="board-empty-hint">Clear the query or filters to see the full board again.</div>
      </div>
    `;
    syncMobileNavigation();
    return;
  }

  const html = visibleGroups.map((group) => {
    const collapsed = state.collapsedGroups.has(group.name);
    const items = group.items.map((item) => {
      const active = item.id === state.selectedItemId ? " board-item-active" : "";
      const dragHint = allowDerivedDrag ? '<span class="board-item-drag">Move</span>' : "";
      return `
        <button class="board-item${active}${allowDerivedDrag ? " board-item-draggable" : ""}" data-item-id="${escapeHtml(item.id)}" type="button" title="${escapeHtml(item.title)}" aria-label="Open ${escapeHtml(item.title)}" aria-pressed="${item.id === state.selectedItemId ? "true" : "false"}" ${allowDerivedDrag ? 'draggable="true"' : ""}>
          ${buildBoardCardBodyMarkup(item, activeLens?.key, dragHint)}
        </button>
      `;
    }).join("");

    const groupActions = allowGroupReorder
      ? `
          <div class="group-actions">
            <button class="order-button" data-move-group="up" data-group-index="${group.originalIndex}" type="button" ${(filtered || group.originalIndex === 0) ? "disabled" : ""}>Up</button>
            <button class="order-button" data-move-group="down" data-group-index="${group.originalIndex}" type="button" ${(filtered || group.originalIndex === state.workspace.boardGroups.length - 1) ? "disabled" : ""}>Down</button>
          </div>
        `
      : "";

    return `
      <section class="board-group${collapsed ? " board-group-collapsed" : ""}${allowDerivedDrag && group.dropValue ? " board-group-droppable" : ""}" data-group-index="${group.originalIndex}">
        <div class="board-group-header">
          <button class="collapse-toggle${allowDerivedDrag && group.dropValue ? " board-group-dropzone" : ""}" data-group-toggle="${escapeHtml(group.name)}" type="button" aria-expanded="${collapsed ? "false" : "true"}" ${allowDerivedDrag && group.dropValue ? `data-lens-drop-value="${escapeHtml(group.dropValue)}"` : ""}>
            <span class="collapse-icon">${collapsed ? "+" : "-"}</span>
            <span class="group-name">${escapeHtml(group.name)}</span>
            <span class="group-count">${group.items.length}</span>
          </button>
          ${groupActions}
        </div>
        <div class="board-item-list" ${collapsed ? "hidden" : ""}>${items}</div>
      </section>
    `;
  }).join("");

  boardGroupsElement.innerHTML = html;
  syncMobileNavigation();

  for (const button of boardGroupsElement.querySelectorAll("[data-item-id]")) {
    button.addEventListener("click", async () => {
      if (Date.now() < state.dragClickSuppressUntil) {
        return;
      }

      await openBoardItemPreview(button.dataset.itemId);
    });
  }

  for (const button of boardGroupsElement.querySelectorAll("[data-group-toggle]")) {
    button.addEventListener("click", () => {
      if (Date.now() < state.dragClickSuppressUntil) {
        return;
      }

      toggleGroup(button.dataset.groupToggle);
    });
  }

  for (const button of boardGroupsElement.querySelectorAll("[data-move-group]")) {
    button.addEventListener("click", () => {
      const fromIndex = Number(button.dataset.groupIndex);
      const toIndex = button.dataset.moveGroup === "up" ? fromIndex - 1 : fromIndex + 1;
      void persistGroupOrder(fromIndex, toIndex);
    });
  }

  if (!allowDerivedDrag) {
    return;
  }

  for (const button of boardGroupsElement.querySelectorAll("[data-item-id]")) {
    button.addEventListener("dragstart", (event) => {
      const itemId = button.dataset.itemId || "";
      if (!itemId) {
        event.preventDefault();
        return;
      }

      if (state.dragItemId && state.dragItemId !== itemId) {
        event.preventDefault();
        return;
      }

      state.dragItemId = itemId;
      state.dragClickSuppressUntil = Date.now() + 350;
      button.classList.add("is-dragging");
      event.dataTransfer?.setData("text/plain", itemId);
      event.dataTransfer?.setData("application/x-minimap-item-id", itemId);
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
      }
    });

    button.addEventListener("dragend", () => {
      button.classList.remove("is-dragging");
      state.dragClickSuppressUntil = Date.now() + 350;
      if (!state.dragItemId || state.dragItemId === button.dataset.itemId) {
        clearBoardDragState();
      }
    });
  }

  for (const group of boardGroupsElement.querySelectorAll("[data-lens-drop-value]")) {
    group.addEventListener("dragover", (event) => {
      event.preventDefault();
      group.classList.add("is-drop-target");
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = "move";
      }
    });

    group.addEventListener("dragleave", () => {
      group.classList.remove("is-drop-target");
    });

    group.addEventListener("drop", (event) => {
      event.preventDefault();
      const itemId = event.dataTransfer?.getData("application/x-minimap-item-id")
        || event.dataTransfer?.getData("text/plain")
        || state.dragItemId
        || "";
      state.dragClickSuppressUntil = Date.now() + 350;
      clearBoardDragState();
      if (!itemId) {
        return;
      }
      void persistDerivedLensMove(itemId, group.dataset.lensDropValue || "");
    });
  }
}

function renderBoardEditMode() {
  const groups = state.boardDraft ?? [];

  if (groups.length === 0) {
    boardGroupsElement.innerHTML = '<div class="empty-state">No board groups to edit.</div>';
    return;
  }

  const html = groups.map((group, groupIndex) => {
    const itemsHtml = group.itemIds.length === 0
      ? '<div class="group-empty">No items in this group.</div>'
      : group.itemIds.map((itemId, itemIndex) => {
          const item = getBoardItemById(itemId);
          if (!item) {
            return "";
          }

          return `
            <div class="board-edit-item" data-board-item-row="${escapeHtml(item.id)}">
              <div class="board-edit-item-main">
                <div class="board-item-top">
                  <span class="board-item-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</span>
                  <span class="board-item-kind">${escapeHtml(item.kind)}</span>
                </div>
                <span class="board-item-id">${escapeHtml(item.id)}</span>
              </div>
              <div class="board-edit-toolbar">
                <select class="board-item-group-select" data-board-item-group="${escapeHtml(item.id)}" aria-label="Group for ${escapeHtml(item.title)}">${buildBoardGroupOptions(groupIndex)}</select>
                <div class="group-actions board-item-move-actions">
                  <button class="order-button" data-board-item-move="up" data-item-id="${escapeHtml(item.id)}" type="button" ${itemIndex === 0 ? "disabled" : ""}>Up</button>
                  <button class="order-button" data-board-item-move="down" data-item-id="${escapeHtml(item.id)}" type="button" ${itemIndex === group.itemIds.length - 1 ? "disabled" : ""}>Down</button>
                </div>
              </div>
            </div>
          `;
        }).join("");

    return `
      <section class="board-group board-edit-group" data-board-group="${groupIndex}">
        <div class="board-group-header board-edit-header">
          <label class="board-group-name-field">
            <span class="visually-hidden">Group name</span>
            <input class="board-group-name-input" data-board-group-name="${groupIndex}" type="text" value="${escapeHtml(group.name)}" placeholder="Group name" />
          </label>
          <span class="group-count">${group.itemIds.length}</span>
          <div class="group-actions">
            <button class="order-button" data-board-group-move="up" data-group-index="${groupIndex}" type="button" ${groupIndex === 0 ? "disabled" : ""}>Up</button>
            <button class="order-button" data-board-group-move="down" data-group-index="${groupIndex}" type="button" ${groupIndex === groups.length - 1 ? "disabled" : ""}>Down</button>
          </div>
        </div>
        <div class="board-edit-items">${itemsHtml}</div>
      </section>
    `;
  }).join("");

  boardGroupsElement.innerHTML = html;
  syncMobileNavigation();

  for (const input of boardGroupsElement.querySelectorAll("[data-board-group-name]")) {
    input.addEventListener("input", () => updateDraftGroupName(Number(input.dataset.boardGroupName), input.value));
  }

  for (const button of boardGroupsElement.querySelectorAll("[data-board-group-move]")) {
    button.addEventListener("click", () => {
      const fromIndex = Number(button.dataset.groupIndex);
      const toIndex = button.dataset.boardGroupMove === "up" ? fromIndex - 1 : fromIndex + 1;
      moveDraftGroup(fromIndex, toIndex);
    });
  }
  for (const select of boardGroupsElement.querySelectorAll("[data-board-item-group]")) {
    select.addEventListener("change", () => {
      moveDraftItemToGroup(select.dataset.boardItemGroup, Number(select.value));
    });
  }

  for (const button of boardGroupsElement.querySelectorAll("[data-board-item-move]")) {
    button.addEventListener("click", () => {
      const itemId = button.dataset.itemId;
      const { groupIndex, itemIndex } = findBoardDraftItem(itemId);
      moveDraftItemWithinGroup(groupIndex, itemIndex, button.dataset.boardItemMove);
    });
  }
}

function renderBoard() {
  if (isSetupMode()) {
    const setup = state.setupState;
    boardGroupsElement.innerHTML = `
      <div class="setup-sidebar">
        <section class="setup-sidebar-card setup-sidebar-card-primary">
          <p class="setup-kicker">Workspace path</p>
          <h3>${escapeHtml(setup.roadmapPath)}</h3>
          <p class="muted">${escapeHtml(setup.configPath ? `Configured through ${setup.configPath}.` : "Using the default roadmap path.")}</p>
        </section>
        <section class="setup-sidebar-card">
          <div class="setup-mini-stat-list">
            <div class="setup-mini-stat"><span>Missing</span><strong>${escapeHtml(String(setup.missingEntries.length))}</strong></div>
            <div class="setup-mini-stat"><span>Invalid</span><strong>${escapeHtml(String(setup.invalidEntries.length))}</strong></div>
          </div>
          <p class="setup-sidebar-copy">${escapeHtml(setup.message)}</p>
        </section>
      </div>
    `;
    return;
  }

  if (state.boardEditMode) {
    renderBoardEditMode();
    return;
  }

  renderBoardReadMode();
}

function renderScope() {
  if (isSetupMode()) {
    const setup = state.setupState;
    const steps = setup.canInitialize
      ? [
          "Use the create action in the main panel to scaffold the starter roadmap files.",
          "Review the generated board.md and scope.md once the workspace loads.",
          "Start editing roadmap items from the normal board and item views.",
        ]
      : [
          "Fix the configured roadmap path or the invalid entry called out in the main panel.",
          "Make sure minimap can find board.md, scope.md, features/, and ideas/.",
          "Refresh the app after the files or config are corrected.",
        ];

    scopeContentElement.hidden = false;
    scopeTextElement.hidden = true;
    scopeContentElement.innerHTML = `
      <div class="setup-side-stack">
        <section class="setup-card setup-card-compact">
          <div class="setup-card-header">
            <p class="setup-kicker">Checklist</p>
            <h3>What minimap expects</h3>
          </div>
          ${renderSetupList(setup.expectedEntries, "No expected entries were provided.")}
        </section>
        <section class="setup-card setup-card-compact">
          <div class="setup-card-header">
            <p class="setup-kicker">Recovery path</p>
            <h3>${escapeHtml(setup.canInitialize ? "Create and continue" : "Fix and refresh")}</h3>
          </div>
          <ol class="setup-steps">${steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol>
        </section>
      </div>
    `;
    return;
  }

  scopeContentElement.hidden = state.scopeEditMode;
  scopeTextElement.hidden = !state.scopeEditMode;

  if (state.scopeEditMode) {
    if (scopeTextElement.value !== state.scopeDraft) {
      scopeTextElement.value = state.scopeDraft;
    }
    return;
  }

  const scopeHtml = renderMarkdownToHtml(state.workspace?.scopeText ?? "");
  scopeContentElement.innerHTML = scopeHtml || '<p class="muted">No scope notes yet.</p>';
}

function setDirtyState(kind, value) {
  if (kind === "structured") {
    state.dirtyStructured = value;
  }

  if (kind === "raw") {
    state.dirtyRaw = value;
  }

  renderEditorChrome();
}

function autosizeTextarea(textarea) {
  if (!textarea) {
    return;
  }

  textarea.style.height = "0px";
  textarea.style.height = `${Math.max(textarea.scrollHeight, 92)}px`;
}

function autosizeStructuredTextareas() {
  for (const textarea of form.querySelectorAll("textarea")) {
    if (textarea === rawTextElement) {
      continue;
    }

    autosizeTextarea(textarea);
  }
}

function resetEditor() {
  state.currentItem = null;
  state.dirtyStructured = false;
  state.dirtyRaw = false;
  state.editorOverlayOpen = false;
  editorTitleElement.textContent = "Item";
  editorSubtitleElement.textContent = "Choose an item from the board.";
  saveButton.disabled = true;
  state.selectedItemId = null;
  form.reset();
  if (fields.boardGroup) {
    fields.boardGroup.innerHTML = "";
    fields.boardGroup.disabled = true;
  }
  sectionsContainer.innerHTML = "";
  rawTextElement.value = "";
  previewElement.className = "preview-surface preview-empty";
  previewElement.innerHTML = "Choose an item from the board to read it here.";
  autosizeStructuredTextareas();
  syncMobileNavigation();
}

function getSectionValueFromItem(item, heading) {
  return item?.sections?.[heading] ?? item?.extraSections?.[heading] ?? "";
}

function getStructuredSectionHeadings(item = state.currentItem) {
  const ordered = [];
  const seen = new Set();
  const originalOrder = Array.isArray(item?.sectionOrder) ? item.sectionOrder : [];
  const fallbackHeadings = [...FIXED_SECTIONS, ...Object.keys(item?.extraSections || {})];

  function append(heading) {
    if (!heading || seen.has(heading)) {
      return;
    }

    const value = getSectionValueFromItem(item, heading);
    const hasContent = String(value ?? "").trim().length > 0;
    if (!hasContent && !originalOrder.includes(heading)) {
      return;
    }

    ordered.push(heading);
    seen.add(heading);
  }

  for (const heading of originalOrder) {
    append(heading);
  }

  for (const heading of fallbackHeadings) {
    append(heading);
  }

  return ordered;
}

function renderStructuredSections(item) {
  const headings = getStructuredSectionHeadings(item);

  sectionsContainer.innerHTML = headings.map((heading) => {
    const safeHeading = escapeHtml(heading);
    const rowCount = heading === "Notes" ? 5 : 4;
    return `
      <label class="structured-section-field">
        <span>${safeHeading}</span>
        <textarea data-section-heading="${safeHeading}" rows="${rowCount}"></textarea>
      </label>
    `;
  }).join("");

  for (const textarea of sectionsContainer.querySelectorAll("textarea[data-section-heading]")) {
    textarea.value = getSectionValueFromItem(item, textarea.dataset.sectionHeading);
    autosizeTextarea(textarea);
    textarea.addEventListener("input", () => {
      autosizeTextarea(textarea);
      setDirtyState("structured", true);
      renderPreview();
    });
  }
}

function getStructuredSections() {
  const sections = {};

  for (const textarea of sectionsContainer.querySelectorAll("textarea[data-section-heading]")) {
    sections[textarea.dataset.sectionHeading] = textarea.value;
  }

  return sections;
}

function getStructuredMetadata() {
  return {
    id: fields.id.value,
    title: fields.title.value,
    status: fields.status.value,
    priority: fields.priority.value,
    commitment: fields.commitment.value,
    milestone: fields.milestone.value.trim(),
  };
}

function renderPreview() {
  if (!state.currentItem) {
    previewElement.className = "preview-surface preview-empty";
    previewElement.innerHTML = "Choose an item from the board to read it here.";
    return;
  }

  const metadata = getStructuredMetadata();
  const sections = getStructuredSections();
  const orderedSections = getStructuredSectionHeadings().filter((heading) => Object.hasOwn(sections, heading));
  const previewBadges = [
    { field: "status", value: metadata.status },
    { field: "priority", value: metadata.priority },
    { field: "commitment", value: metadata.commitment },
    { field: "milestone", value: metadata.milestone },
  ]
    .filter((entry) => entry.value)
    .map((entry) => renderBadge(entry.value, entry.field))
    .join("");
  const sectionHtml = orderedSections.map((heading) => `
    <section class="preview-section">
      <div class="preview-section-header">
        <h3>${escapeHtml(heading)}</h3>
      </div>
      <div class="preview-markdown">${renderMarkdownToHtml(sections[heading] || "") || '<p class="muted">Empty section.</p>'}</div>
    </section>
  `).join("");

  previewElement.className = "preview-surface preview-reading";
  previewElement.innerHTML = `
    ${previewBadges ? `<div class="preview-meta">${previewBadges}</div>` : ""}
    <div class="preview-body">${sectionHtml || '<p class="muted">This item does not have any readable sections yet.</p>'}</div>
  `;
}

function renderItem(item) {
  state.currentItem = item;
  state.dirtyStructured = false;
  state.dirtyRaw = false;
  editorTitleElement.textContent = item.metadata.title;
  editorSubtitleElement.textContent = item.filePath;
  fields.id.value = item.metadata.id || "";
  fields.title.value = item.metadata.title || "";
  ensureSelectValue(fields.status, item.metadata.status || "queued");
  ensureSelectValue(fields.priority, item.metadata.priority || "medium");
  ensureSelectValue(fields.commitment, item.metadata.commitment || "uncommitted");
  renderBoardGroupField(item.metadata.id || item.id);
  fields.milestone.value = item.metadata.milestone || "";
  renderStructuredSections(item);
  rawTextElement.value = item.rawText || "";
  autosizeStructuredTextareas();
  renderPreview();
  syncMobileNavigation();
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();

  if (!response.ok) {
    const error = new Error(payload?.error?.message || "Request failed.");
    error.code = payload?.error?.code || "request_failed";
    error.details = payload?.error?.details || null;
    error.statusCode = response.status;
    throw error;
  }

  return payload;
}

function resetAncillaryEditModes() {
  state.boardEditMode = false;
  state.boardDraft = null;
  state.boardDirty = false;
  state.scopeEditMode = false;
  state.scopeDraft = "";
  state.scopeDirty = false;
}

async function syncVisibleSelection(options = {}) {
  const visibleItemIds = getVisibleBoardItemIds();
  const preferredItemId = options.preferredItemId || "";
  const useOverlay = shouldUseEditorOverlay();

  syncWorkspaceChrome();
  renderBoard();

  if (visibleItemIds.length === 0) {
    resetEditor();
    if (options.syncRoute !== false) {
      syncRouteState({ replace: options.replaceRoute !== false });
    }
    return;
  }

  const nextItemId = [preferredItemId, state.selectedItemId, visibleItemIds[0]].find((itemId) => itemId && visibleItemIds.includes(itemId)) || visibleItemIds[0];
  const shouldShowItem = !useOverlay || state.editorOverlayOpen || Boolean(preferredItemId) || options.forceReloadItem === true;

  if (!shouldShowItem) {
    if (useOverlay) {
      resetEditor();
      syncWorkspaceChrome();
      renderBoard();
    } else if (state.selectedItemId && !visibleItemIds.includes(state.selectedItemId)) {
      resetEditor();
      syncWorkspaceChrome();
      renderBoard();
    }

    if (options.syncRoute !== false) {
      syncRouteState({ replace: options.replaceRoute !== false });
    }
    return;
  }

  const shouldReloadItem = options.forceReloadItem === true || nextItemId !== state.selectedItemId || !state.currentItem;
  if (shouldReloadItem) {
    await loadItem(nextItemId, true, {
      syncRoute: options.syncRoute,
      replaceRoute: options.replaceRoute === true,
      openOverlay: useOverlay,
    });
    return;
  }

  if (useOverlay) {
    state.editorOverlayOpen = true;
    syncWorkspaceChrome();
    renderBoard();
  }

  if (options.syncRoute !== false) {
    syncRouteState({ replace: options.replaceRoute !== false });
  }
}

async function applyRouteStateFromLocation() {
  const route = readRouteState();
  state.activeLens = normalizeLensKey(route.lens);
  state.boardLayout = normalizeBoardLayout(route.layout);
  state.editorOverlayOpen = route.layout === "columns" && Boolean(route.itemId);
  state.searchQuery = route.query;
  state.activeFilters = route.filters;
  state.filtersExpanded = Object.keys(route.filters).length > 0;

  const nextMode = normalizeEditorMode(route.mode);
  if (nextMode !== state.editorMode) {
    state.editorMode = nextMode;
    applyEditorMode();
  }

  await syncVisibleSelection({
    preferredItemId: route.itemId || state.selectedItemId,
    replaceRoute: true,
  });
}
async function loadWorkspace(preferredItemId = state.selectedItemId, options = {}) {
  try {
    const workspace = await fetchJson("/api/workspace");
    resetAncillaryEditModes();
    state.setupState = null;
    state.workspace = workspace;
    state.activeLens = normalizeLensKey(options.preferredLens ?? state.activeLens, workspace);
    state.boardLayout = normalizeBoardLayout(options.preferredLayout ?? state.boardLayout);
    state.editorMode = normalizeEditorMode(options.preferredMode ?? state.editorMode);
    roadmapPathElement.textContent = workspace.roadmapPath;
    renderScope();
    setBanner("");

    const fallbackItemId = shouldUseEditorOverlay() ? "" : (getFirstVisibleBoardItemId(workspace) || getFirstBoardItemId(workspace));
    await syncVisibleSelection({
      preferredItemId: preferredItemId && workspace.items?.[preferredItemId] ? preferredItemId : fallbackItemId,
      syncRoute: options.syncRoute,
      replaceRoute: options.replaceRoute,
      forceReloadItem: options.forceReloadItem === true || Boolean(preferredItemId),
    });
  } catch (error) {
    state.workspace = null;
    state.setupState = buildSetupState(error);
    roadmapPathElement.textContent = state.setupState?.roadmapPath || "Unavailable";
    resetAncillaryEditModes();
    resetEditor();
    syncWorkspaceChrome();
    renderBoard();
    renderScope();

    if (!state.setupState) {
      boardGroupsElement.innerHTML = "";
      scopeContentElement.textContent = "";
      scopeTextElement.hidden = true;
      setBanner(error.message, "error");
      return;
    }

    setBanner("");
  }
}

async function loadItem(itemId, rerenderBoard = true, options = {}) {
  try {
    if (options.mode) {
      state.editorMode = normalizeEditorMode(options.mode);
    }
    if (typeof options.openOverlay === "boolean") {
      state.editorOverlayOpen = options.openOverlay;
    }
    const item = await fetchJson(`/api/items/${encodeURIComponent(itemId)}`);
    state.selectedItemId = itemId;
    renderItem(item);
    applyEditorMode();
    syncWorkspaceChrome();
    if (rerenderBoard) {
      renderBoard();
    }
    if (options.syncRoute !== false) {
      syncRouteState({ replace: options.replaceRoute === true });
    }
    setBanner("");
  } catch (error) {
    setBanner(error.message, "error");
  }
}
async function openBoardItemPreview(itemId) {
  if (!itemId) {
    return;
  }

  const useOverlay = shouldUseEditorOverlay();
  if (itemId === state.selectedItemId && state.currentItem) {
    state.editorOverlayOpen = useOverlay;
    switchEditorMode("preview", { replaceRoute: false });
    syncWorkspaceChrome();
    renderBoard();
    syncRouteState();
    if (!useOverlay && isStackedLayout()) {
      scrollPanelIntoView(editorPanelElement);
    }
    return;
  }

  if (!confirmDiscardCurrentItemChanges(itemId)) {
    return;
  }

  await loadItem(itemId, true, { mode: "preview", openOverlay: useOverlay });
  if (!useOverlay && isStackedLayout()) {
    scrollPanelIntoView(editorPanelElement);
  }
}

async function initializeWorkspaceFromSetup() {
  if (!state.setupState?.canInitialize) {
    return;
  }

  setBanner("Creating starter roadmap workspace...");

  try {
    await fetchJson("/api/setup/initialize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    await loadWorkspace("", { replaceRoute: true });
    setBanner("Roadmap workspace created.", "success");
  } catch (error) {
    state.setupState = buildSetupState(error) || state.setupState;
    syncWorkspaceChrome();
    renderBoard();
    renderScope();
    if (!state.setupState) {
      setBanner(error.message, "error");
      return;
    }

    setBanner("");
  }
}
function collectPayload() {
  return {
    metadata: getStructuredMetadata(),
    sections: getStructuredSections(),
  };
}
function cancelCurrentItemEdits() {
  if (!state.currentItem) {
    return;
  }

  if (state.editorMode === "preview") {
    if (shouldUseEditorOverlay() && state.editorOverlayOpen) {
      closeEditorOverlay();
    }
    return;
  }

  renderItem(state.currentItem);
  state.dirtyStructured = false;
  state.dirtyRaw = false;
  state.editorMode = "preview";
  applyEditorMode();
  syncRouteState({ replace: true });
}


function currentModeFamily(mode) {
  return mode === "raw" ? "raw" : "structured";
}

function canSwitchEditorMode(nextMode) {
  const currentFamily = currentModeFamily(state.editorMode);
  const nextFamily = currentModeFamily(nextMode);

  if (currentFamily === nextFamily) {
    return true;
  }

  if (currentFamily === "structured" && state.dirtyStructured) {
    return window.confirm("Discard unsaved structured changes and switch to raw mode?");
  }

  if (currentFamily === "raw" && state.dirtyRaw) {
    return window.confirm("Discard unsaved raw markdown changes and switch back to the structured editor?");
  }

  return true;
}

function applyEditorMode() {
  renderEditorChrome();

  for (const button of modeButtons) {
    const active = button.dataset.editorMode === state.editorMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  }

  for (const pane of modePanes) {
    pane.hidden = pane.dataset.modePane !== state.editorMode;
  }

  if (state.editorMode === "preview") {
    renderPreview();
  }

  if (state.editorMode === "structured") {
    autosizeStructuredTextareas();
  }
}

function switchEditorMode(nextMode, options = {}) {
  if (nextMode === state.editorMode) {
    return;
  }

  if (!canSwitchEditorMode(nextMode)) {
    return;
  }

  if (currentModeFamily(state.editorMode) === "structured" && currentModeFamily(nextMode) === "raw") {
    setDirtyState("structured", false);
    if (state.currentItem) {
      renderItem(state.currentItem);
    }
  }

  if (currentModeFamily(state.editorMode) === "raw" && currentModeFamily(nextMode) === "structured") {
    setDirtyState("raw", false);
    if (state.currentItem) {
      renderItem(state.currentItem);
    }
  }

  state.editorMode = nextMode;
  applyEditorMode();

  if (options.syncRoute !== false) {
    syncRouteState({ replace: options.replaceRoute !== false });
  }
}

async function saveCurrentItem() {
  if (!state.selectedItemId) {
    return;
  }

  saveButton.disabled = true;
  setBanner(state.editorMode === "raw" ? "Saving raw item..." : "Saving item...");

  try {
    const payload = state.editorMode === "raw" ? { rawText: rawTextElement.value } : collectPayload();
    const nextBoardGroupIndex = state.editorMode === "structured" && fields.boardGroup && fields.boardGroup.value !== ""
      ? Number(fields.boardGroup.value)
      : -1;
    const currentBoardGroupIndex = getBoardGroupIndexForItem(state.selectedItemId);

    await fetchJson(`/api/items/${encodeURIComponent(state.selectedItemId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (state.editorMode === "structured" && Number.isInteger(nextBoardGroupIndex) && nextBoardGroupIndex >= 0 && nextBoardGroupIndex !== currentBoardGroupIndex) {
      const groups = buildBoardGroupsWithMovedItem(state.selectedItemId, nextBoardGroupIndex);
      if (groups) {
        await fetchJson("/api/board", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ groups }),
        });
      }
    }

    await loadWorkspace(state.selectedItemId);
    setBanner("Saved.", "success");
  } catch (error) {
    setBanner(error.message, "error");
  } finally {
    saveButton.disabled = false;
  }
}

function startScopeEditMode() {
  if (!state.workspace) {
    return;
  }

  state.scopeCollapsed = false;
  persistScopePreference();
  state.scopeEditMode = true;
  state.scopeDraft = state.workspace.scopeText || "";
  state.scopeDirty = false;
  renderScopeChrome();
  renderScope();
  scopeTextElement.focus();
  scopeTextElement.setSelectionRange(scopeTextElement.value.length, scopeTextElement.value.length);
}

function cancelScopeEditMode(force = false) {
  if (state.scopeEditMode && state.scopeDirty && !force) {
    if (!window.confirm("Discard unsaved scope changes?")) {
      return;
    }
  }

  state.scopeEditMode = false;
  state.scopeDraft = state.workspace?.scopeText || "";
  state.scopeDirty = false;
  renderScopeChrome();
  renderScope();
}

async function saveScopeDraft() {
  scopeSaveButton.disabled = true;
  setBanner("Saving scope...");

  try {
    const workspace = await fetchJson("/api/scope", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scopeText: state.scopeDraft }),
    });

    state.workspace = workspace;
    state.scopeEditMode = false;
    state.scopeDraft = workspace.scopeText || "";
    state.scopeDirty = false;
    syncWorkspaceChrome();
    renderBoard();
    renderScope();
    setBanner("Scope saved.", "success");
  } catch (error) {
    renderScopeChrome();
    setBanner(error.message, "error");
  }
}

saveButton.addEventListener("click", () => {
  if (state.editorMode === "preview") {
    if (shouldUseEditorOverlay() && state.editorOverlayOpen) {
      closeEditorOverlay();
    }
    return;
  }

  void saveCurrentItem();
});

refreshButton.addEventListener("click", () => {
  void loadWorkspace();
});

setupViewElement.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const action = target?.closest("[data-setup-action]");
  if (!action) {
    return;
  }

  if (action.dataset.setupAction === "initialize") {
    void initializeWorkspaceFromSetup();
  }
});

boardEditButton.addEventListener("click", () => {
  startBoardEditMode();
});

boardSaveButton.addEventListener("click", () => {
  void saveBoardDraft();
});

boardCancelButton.addEventListener("click", () => {
  cancelBoardEditMode();
});

scopeEditButton.addEventListener("click", () => {
  startScopeEditMode();
});

scopeSaveButton.addEventListener("click", () => {
  void saveScopeDraft();
});

scopeCancelButton.addEventListener("click", () => {
  cancelScopeEditMode();
});

scopeToggleButton.addEventListener("click", () => {
  toggleScopePanel();
});

scopeResizerElement.addEventListener("pointerdown", beginScopeResize);

boardSearchInput.addEventListener("input", () => {
  state.searchQuery = normalizeSearchQuery(boardSearchInput.value);
  void syncVisibleSelection({ replaceRoute: true });
});

boardLayoutListButton?.addEventListener("click", () => {
  state.boardLayout = DEFAULT_BOARD_LAYOUT;
  state.lensesExpanded = false;
  syncWorkspaceChrome();
  renderBoard();
  void syncVisibleSelection({ replaceRoute: true });
});

boardLayoutColumnsButton?.addEventListener("click", () => {
  if (!confirmCloseCurrentItem()) {
    return;
  }

  state.boardLayout = "columns";
  state.lensesExpanded = false;
  resetEditor();
  syncWorkspaceChrome();
  renderBoard();
  syncRouteState({ replace: true });
});

boardViewToggleButton.addEventListener("click", () => {
  if (!state.workspace || getAvailableLenses().length <= 1 || state.boardEditMode) {
    return;
  }

  state.lensesExpanded = !state.lensesExpanded;
  if (state.lensesExpanded) {
    state.filtersExpanded = false;
  }
  renderBoardChrome();
});

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Node) || !state.lensesExpanded) {
    return;
  }

  const clickedLensControl = boardViewToggleButton?.contains(target) || boardLensSwitcherElement?.contains(target);
  if (!clickedLensControl) {
    state.lensesExpanded = false;
    renderBoardChrome();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.editorOverlayOpen && shouldUseEditorOverlay()) {
    closeEditorOverlay();
    return;
  }

  if (event.key !== "Escape" || !state.lensesExpanded) {
    return;
  }

  state.lensesExpanded = false;
  renderBoardChrome();
});

boardFilterToggleButton.addEventListener("click", () => {
  if (!state.workspace?.availableFilters?.length || state.boardEditMode) {
    return;
  }

  state.filtersExpanded = !state.filtersExpanded;
  if (state.filtersExpanded) {
    state.lensesExpanded = false;
  }
  renderBoardChrome();
});

boardClearFiltersButton.addEventListener("click", () => {
  state.searchQuery = "";
  state.activeFilters = {};
  state.filtersExpanded = false;
  void syncVisibleSelection({ replaceRoute: true });
});

jumpToBoardButton.addEventListener("click", () => {
  scrollPanelIntoView(boardPanelElement);
});

jumpToEditorButton.addEventListener("click", () => {
  if (state.selectedItemId) {
    scrollPanelIntoView(editorPanelElement);
  }
});

editorOverlayBackdrop?.addEventListener("click", () => {
  closeEditorOverlay();
});

editorOverlayCloseButton?.addEventListener("click", () => {
  closeEditorOverlay();
});

editorCancelButton?.addEventListener("click", () => {
  cancelCurrentItemEdits();
});

form.addEventListener("input", (event) => {
  if (event.target instanceof HTMLTextAreaElement) {
    autosizeTextarea(event.target);
  }

  setDirtyState("structured", true);
  renderPreview();
});

rawTextElement.addEventListener("input", () => {
  setDirtyState("raw", true);
});

scopeTextElement.addEventListener("input", () => {
  state.scopeDraft = scopeTextElement.value;
  state.scopeDirty = true;
  renderScopeChrome();
});

for (const button of modeButtons) {
  button.addEventListener("click", () => {
    switchEditorMode(button.dataset.editorMode);
  });
}

window.addEventListener("hashchange", () => {
  void applyRouteStateFromLocation();
});

window.addEventListener("resize", () => {
  if (state.lensesExpanded) {
    positionLensControls();
  }
});

desktopScopeLayoutMedia.addEventListener("change", () => {
  renderScopeChrome();
});

stackedLayoutMedia.addEventListener("change", () => {
  renderScopeChrome();
  syncMobileNavigation();
});
resetEditor();
const initialRoute = readRouteState();
state.activeLens = initialRoute.lens;
state.boardLayout = initialRoute.layout;
state.editorMode = initialRoute.mode;
state.searchQuery = initialRoute.query;
state.activeFilters = initialRoute.filters;
state.filtersExpanded = Object.keys(initialRoute.filters).length > 0;
renderScopeChrome();
applyEditorMode();
void loadWorkspace(initialRoute.itemId || state.selectedItemId, {
  preferredLens: initialRoute.lens,
  preferredLayout: initialRoute.layout,
  preferredMode: initialRoute.mode,
  syncRoute: false,
}).then(() => {
  if (initialRoute.itemId || initialRoute.mode !== "preview" || initialRoute.lens !== DEFAULT_LENS_KEY || initialRoute.layout !== DEFAULT_BOARD_LAYOUT || initialRoute.query || Object.keys(initialRoute.filters).length > 0) {
    void applyRouteStateFromLocation();
    return;
  }

  if (state.selectedItemId) {
    syncRouteState({ replace: true });
  }
});

