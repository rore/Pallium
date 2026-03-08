const FIXED_SECTIONS = ["Summary", "Why", "In Scope", "Out of Scope", "Done When", "Notes"];
const SCOPE_STORAGE_KEY = "roadmap-ui.scope-collapsed";
const SCOPE_WIDTH_STORAGE_KEY = "roadmap-ui.scope-width";
const DEFAULT_SCOPE_WIDTH = 272;
const MIN_SCOPE_WIDTH = 240;
const MAX_SCOPE_WIDTH = 440;
const EDITOR_MODES = new Set(["preview", "structured", "raw"]);

const state = {
  workspace: null,
  selectedItemId: null,
  currentItem: null,
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
const boardGroupsElement = document.querySelector("#board-groups");
const boardEditButton = document.querySelector("#board-edit-button");
const boardSaveButton = document.querySelector("#board-save-button");
const boardCancelButton = document.querySelector("#board-cancel-button");
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
const saveButton = document.querySelector("#save-button");
const refreshButton = document.querySelector("#refresh-button");
const statusBanner = document.querySelector("#status-banner");
const form = document.querySelector("#item-form");
const previewElement = document.querySelector("#item-preview");
const rawTextElement = document.querySelector("#raw-text");
const sectionsContainer = document.querySelector("#sections-container");
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

function getBoardItemById(itemId) {
  return state.workspace?.items?.[itemId] ?? null;
}

function getFirstBoardItemId(workspace = state.workspace) {
  return workspace?.boardGroups.flatMap((group) => group.items).at(0)?.id ?? null;
}

function renderBadges(item) {
  return [item.status, item.priority, item.commitment, item.milestone]
    .filter(Boolean)
    .map((value) => `<span class="badge">${escapeHtml(value)}</span>`)
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
  workspaceSummaryElement.textContent = state.workspace ? `${items} items / ${groups} groups` : "Unavailable";
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
  };
}

function buildRouteHash(itemId = state.selectedItemId, mode = state.editorMode) {
  const params = new URLSearchParams();

  if (itemId) {
    params.set("item", itemId);
  }

  const normalizedMode = normalizeEditorMode(mode);
  if (normalizedMode !== "preview") {
    params.set("mode", normalizedMode);
  }

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
  const hasItem = Boolean(state.selectedItemId);
  jumpToBoardButton.hidden = !stacked;
  jumpToBoardButton.disabled = !stacked;
  jumpToEditorButton.hidden = !stacked || !hasItem || state.boardEditMode;
  jumpToEditorButton.disabled = !stacked || !hasItem || state.boardEditMode;
}

function renderBoardChrome() {
  boardEditButton.hidden = state.boardEditMode;
  boardSaveButton.hidden = !state.boardEditMode;
  boardCancelButton.hidden = !state.boardEditMode;
  boardSaveButton.disabled = !state.boardDirty;
}

function renderScopeChrome() {
  const showResizer = !state.scopeCollapsed && isDesktopScopeLayout();

  layoutElement.dataset.scopeCollapsed = String(state.scopeCollapsed);
  layoutElement.style.setProperty("--scope-width", `${state.scopeWidth}px`);
  scopePanelElement.classList.toggle("scope-collapsed", state.scopeCollapsed);
  scopePanelElement.classList.toggle("scope-editing", state.scopeEditMode);
  scopeSubtitleElement.textContent = "";
  scopeSubtitleElement.hidden = true;
  scopeEditButton.hidden = state.scopeEditMode;
  scopeSaveButton.hidden = !state.scopeEditMode;
  scopeCancelButton.hidden = !state.scopeEditMode;
  scopeSaveButton.disabled = !state.scopeDirty;
  scopeToggleButton.hidden = state.scopeEditMode;
  scopeToggleButton.disabled = state.scopeEditMode;
  scopeToggleButton.textContent = state.scopeCollapsed ? "Expand" : "Collapse";
  scopeToggleButton.setAttribute("aria-expanded", state.scopeCollapsed ? "false" : "true");
  scopeResizerElement.hidden = !showResizer;
  scopeResizerElement.setAttribute("aria-hidden", showResizer ? "false" : "true");
  scopeResizerElement.setAttribute("aria-valuemin", String(MIN_SCOPE_WIDTH));
  scopeResizerElement.setAttribute("aria-valuemax", String(MAX_SCOPE_WIDTH));
  scopeResizerElement.setAttribute("aria-valuenow", String(state.scopeWidth));
}

function renderEditorChrome() {
  editorPanelElement.dataset.editorMode = state.editorMode;
  saveButton.textContent = "Save";
}

function syncWorkspaceChrome() {
  updateDocumentTitle();
  updateWorkspaceSummary();
  renderBoardChrome();
  renderScopeChrome();
  renderEditorChrome();
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

function renderBoardReadMode() {
  if (!state.workspace) {
    boardGroupsElement.innerHTML = "";
    return;
  }

  if (state.workspace.boardGroups.length === 0) {
    boardGroupsElement.innerHTML = '<div class="empty-state">No board groups found in board.md.</div>';
    syncMobileNavigation();
    return;
  }

  const html = state.workspace.boardGroups.map((group, index) => {
    const collapsed = state.collapsedGroups.has(group.name);
    const items = group.items.map((item) => {
      const active = item.id === state.selectedItemId ? " board-item-active" : "";
      return `
        <button class="board-item${active}" data-item-id="${escapeHtml(item.id)}" type="button" aria-pressed="${item.id === state.selectedItemId ? "true" : "false"}">
          <span class="board-item-top">
            <span class="board-item-title">${escapeHtml(item.title)}</span>
            <span class="board-item-kind">${escapeHtml(item.kind)}</span>
          </span>
          <span class="board-item-id">${escapeHtml(item.id)}</span>
          <span class="badge-row">${renderBadges(item)}</span>
        </button>
      `;
    }).join("");

    return `
      <section class="board-group${collapsed ? " board-group-collapsed" : ""}" data-group-index="${index}">
        <div class="board-group-header">
          <button class="collapse-toggle" data-group-toggle="${escapeHtml(group.name)}" type="button" aria-expanded="${collapsed ? "false" : "true"}">
            <span class="collapse-icon">${collapsed ? "+" : "-"}</span>
            <span class="group-name">${escapeHtml(group.name)}</span>
            <span class="group-count">${group.items.length}</span>
          </button>
          <div class="group-actions">
            <button class="order-button" data-move-group="up" data-group-index="${index}" type="button" ${index === 0 ? "disabled" : ""}>Up</button>
            <button class="order-button" data-move-group="down" data-group-index="${index}" type="button" ${index === state.workspace.boardGroups.length - 1 ? "disabled" : ""}>Down</button>
          </div>
        </div>
        <div class="board-item-list" ${collapsed ? "hidden" : ""}>${items}</div>
      </section>
    `;
  }).join("");

  boardGroupsElement.innerHTML = html;
  syncMobileNavigation();

  for (const button of boardGroupsElement.querySelectorAll("[data-item-id]")) {
    button.addEventListener("click", async () => {
      await loadItem(button.dataset.itemId);
      if (isStackedLayout()) {
        scrollPanelIntoView(editorPanelElement);
      }
    });
  }

  for (const button of boardGroupsElement.querySelectorAll("[data-group-toggle]")) {
    button.addEventListener("click", () => toggleGroup(button.dataset.groupToggle));
  }

  for (const button of boardGroupsElement.querySelectorAll("[data-move-group]")) {
    button.addEventListener("click", () => {
      const fromIndex = Number(button.dataset.groupIndex);
      const toIndex = button.dataset.moveGroup === "up" ? fromIndex - 1 : fromIndex + 1;
      void persistGroupOrder(fromIndex, toIndex);
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
                  <span class="board-item-title">${escapeHtml(item.title)}</span>
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
  if (state.boardEditMode) {
    renderBoardEditMode();
    return;
  }

  renderBoardReadMode();
}

function renderScope() {
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
  editorTitleElement.textContent = "Item";
  editorSubtitleElement.textContent = "Choose an item from the board.";
  saveButton.disabled = true;
  state.selectedItemId = null;
  form.reset();
  sectionsContainer.innerHTML = "";
  rawTextElement.value = "";
  previewElement.className = "preview-surface preview-empty";
  previewElement.innerHTML = "Preview the current item or switch to Edit to change its core fields.";
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
    previewElement.innerHTML = "Preview the current item or switch to Edit to change its core fields.";
    return;
  }

  const metadata = getStructuredMetadata();
  const sections = getStructuredSections();
  const orderedSections = getStructuredSectionHeadings().filter((heading) => Object.hasOwn(sections, heading));
  const sectionHtml = orderedSections.map((heading) => `
    <section class="preview-section">
      <h3>${escapeHtml(heading)}</h3>
      <div class="preview-markdown">${renderMarkdownToHtml(sections[heading] || "") || '<p class="muted">Empty section.</p>'}</div>
    </section>
  `).join("");
  const previewBadges = [metadata.status, metadata.priority, metadata.commitment, metadata.milestone]
    .filter(Boolean)
    .map((value) => `<span class="badge">${escapeHtml(value)}</span>`)
    .join("");

  previewElement.className = "preview-surface";
  previewElement.innerHTML = `
    ${previewBadges ? `<div class="preview-meta">${previewBadges}</div>` : ""}
    <div class="preview-body">${sectionHtml}</div>
  `;
}

function renderItem(item) {
  state.currentItem = item;
  state.dirtyStructured = false;
  state.dirtyRaw = false;
  saveButton.disabled = false;
  editorTitleElement.textContent = item.metadata.title;
  editorSubtitleElement.textContent = item.filePath;
  fields.id.value = item.metadata.id || "";
  fields.title.value = item.metadata.title || "";
  ensureSelectValue(fields.status, item.metadata.status || "queued");
  ensureSelectValue(fields.priority, item.metadata.priority || "medium");
  ensureSelectValue(fields.commitment, item.metadata.commitment || "uncommitted");
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
    throw new Error(payload?.error?.message || "Request failed.");
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

async function applyRouteStateFromLocation() {
  const route = readRouteState();
  const routeItemId = route.itemId || "";
  const currentItemId = state.selectedItemId || "";

  if (routeItemId && routeItemId !== currentItemId) {
    await loadWorkspace(routeItemId, {
      preferredMode: route.mode,
      syncRoute: false,
    });
    return;
  }

  if (!routeItemId && currentItemId) {
    await loadWorkspace(undefined, {
      preferredMode: route.mode,
      syncRoute: false,
    });
    return;
  }

  const nextMode = normalizeEditorMode(route.mode);
  if (nextMode !== state.editorMode) {
    state.editorMode = nextMode;
    applyEditorMode();
  }
}

async function loadWorkspace(preferredItemId = state.selectedItemId, options = {}) {
  try {
    const workspace = await fetchJson("/api/workspace");
    resetAncillaryEditModes();
    state.workspace = workspace;
    state.editorMode = normalizeEditorMode(options.preferredMode ?? state.editorMode);
    roadmapPathElement.textContent = workspace.roadmapPath;
    syncWorkspaceChrome();
    renderBoard();
    renderScope();
    setBanner("");

    const itemIdToLoad = preferredItemId && workspace.items?.[preferredItemId] ? preferredItemId : getFirstBoardItemId(workspace);
    if (itemIdToLoad) {
      await loadItem(itemIdToLoad, false, {
        syncRoute: options.syncRoute,
        replaceRoute: options.replaceRoute,
      });
    } else {
      resetEditor();
      if (options.syncRoute !== false) {
        syncRouteState({ replace: options.replaceRoute !== false });
      }
    }
  } catch (error) {
    state.workspace = null;
    roadmapPathElement.textContent = "Unavailable";
    resetAncillaryEditModes();
    syncWorkspaceChrome();
    boardGroupsElement.innerHTML = "";
    scopeContentElement.textContent = "";
    scopeTextElement.hidden = true;
    resetEditor();
    setBanner(error.message, "error");
  }
}

async function loadItem(itemId, rerenderBoard = true, options = {}) {
  try {
    const item = await fetchJson(`/api/items/${encodeURIComponent(itemId)}`);
    state.selectedItemId = itemId;
    renderItem(item);
    applyEditorMode();
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
function collectPayload() {
  return {
    metadata: getStructuredMetadata(),
    sections: getStructuredSections(),
  };
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
    await fetchJson(`/api/items/${encodeURIComponent(state.selectedItemId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
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
  void saveCurrentItem();
});

refreshButton.addEventListener("click", () => {
  void loadWorkspace();
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

jumpToBoardButton.addEventListener("click", () => {
  scrollPanelIntoView(boardPanelElement);
});

jumpToEditorButton.addEventListener("click", () => {
  if (state.selectedItemId) {
    scrollPanelIntoView(editorPanelElement);
  }
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

desktopScopeLayoutMedia.addEventListener("change", () => {
  renderScopeChrome();
});

stackedLayoutMedia.addEventListener("change", () => {
  renderScopeChrome();
  syncMobileNavigation();
});

resetEditor();
const initialRoute = readRouteState();
state.editorMode = initialRoute.mode;
renderScopeChrome();
applyEditorMode();
void loadWorkspace(initialRoute.itemId || state.selectedItemId, {
  preferredMode: initialRoute.mode,
  syncRoute: false,
}).then(() => {
  if (initialRoute.itemId || initialRoute.mode !== "preview") {
    void applyRouteStateFromLocation();
    return;
  }

  if (state.selectedItemId) {
    syncRouteState({ replace: true });
  }
});
