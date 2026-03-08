const FIXED_SECTIONS = ["Summary", "Why", "In Scope", "Out of Scope", "Done When", "Notes"];
const SCOPE_STORAGE_KEY = "roadmap-ui.scope-collapsed";

const state = {
  workspace: null,
  selectedItemId: null,
  currentItem: null,
  collapsedGroups: new Set(),
  scopeCollapsed: loadStoredScopePreference(),
  editorMode: "preview",
  dirtyStructured: false,
  dirtyRaw: false,
};

const layoutElement = document.querySelector("#layout-shell");
const boardPanelElement = document.querySelector("#board-panel");
const boardGroupsElement = document.querySelector("#board-groups");
const scopePanelElement = document.querySelector("#scope-panel");
const scopeContentElement = document.querySelector("#scope-content");
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
const extraSectionsPanel = document.querySelector("#extra-sections-panel");
const extraSectionsElement = document.querySelector("#extra-sections");
const modeButtons = Array.from(document.querySelectorAll("[data-editor-mode]"));
const modePanes = Array.from(document.querySelectorAll("[data-mode-pane]"));
const stackedLayoutMedia = window.matchMedia("(max-width: 980px)");

const fields = {
  id: document.querySelector("#field-id"),
  title: document.querySelector("#field-title"),
  status: document.querySelector("#field-status"),
  priority: document.querySelector("#field-priority"),
  commitment: document.querySelector("#field-commitment"),
  milestone: document.querySelector("#field-milestone"),
  Summary: document.querySelector("#section-summary"),
  Why: document.querySelector("#section-why"),
  "In Scope": document.querySelector("#section-in-scope"),
  "Out of Scope": document.querySelector("#section-out-of-scope"),
  "Done When": document.querySelector("#section-done-when"),
  Notes: document.querySelector("#section-notes"),
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
    // Ignore storage failures; the toggle still works for the session.
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

function renderBadges(item) {
  return [item.status, item.priority, item.commitment, item.milestone].filter(Boolean)
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

function isStackedLayout() {
  return stackedLayoutMedia.matches;
}

function scrollPanelIntoView(element) {
  element?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function syncMobileNavigation() {
  const hasItem = Boolean(state.selectedItemId);
  jumpToEditorButton.hidden = !hasItem;
  jumpToEditorButton.disabled = !hasItem;
}

function renderScopeChrome() {
  layoutElement.dataset.scopeCollapsed = String(state.scopeCollapsed);
  scopePanelElement.classList.toggle("scope-collapsed", state.scopeCollapsed);
  scopeToggleButton.textContent = state.scopeCollapsed ? "Expand" : "Collapse";
  scopeToggleButton.setAttribute("aria-expanded", state.scopeCollapsed ? "false" : "true");
  scopeToggleButton.setAttribute("aria-label", state.scopeCollapsed ? "Expand scope panel" : "Collapse scope panel");
}

function renderEditorChrome() {
  editorPanelElement.dataset.editorMode = state.editorMode;
  saveButton.textContent = "Save";
}

function syncWorkspaceChrome() {
  updateDocumentTitle();
  updateWorkspaceSummary();
  renderScopeChrome();
  renderEditorChrome();
  syncMobileNavigation();
}

function toggleScopePanel() {
  state.scopeCollapsed = !state.scopeCollapsed;
  persistScopePreference();
  renderScopeChrome();
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

async function saveBoardGroups() {
  const groups = state.workspace.boardGroups.map((group) => ({
    name: group.name,
    itemIds: group.items.map((item) => item.id),
  }));

  const workspace = await fetchJson("/api/board", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ groups }),
  });

  state.workspace = workspace;
  syncWorkspaceChrome();
}

async function persistGroupOrder(fromIndex, toIndex) {
  if (!state.workspace || fromIndex === toIndex) {
    return;
  }

  if (toIndex < 0 || toIndex >= state.workspace.boardGroups.length) {
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
    await saveBoardGroups();
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

function renderBoard() {
  if (!state.workspace) {
    boardGroupsElement.innerHTML = "";
    return;
  }

  if (state.workspace.boardGroups.length === 0) {
    boardGroupsElement.innerHTML = '<div class="empty-state">No board groups found in board.md.</div>';
    syncMobileNavigation();
    return;
  }

  const html = state.workspace.boardGroups
    .map((group, index) => {
      const collapsed = state.collapsedGroups.has(group.name);
      const items = group.items
        .map((item) => {
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
        })
        .join("");

      return `
        <section class="board-group${collapsed ? " board-group-collapsed" : ""}" data-group-index="${index}">
          <div class="board-group-header">
            <button class="collapse-toggle" data-group-toggle="${escapeHtml(group.name)}" type="button" aria-expanded="${collapsed ? "false" : "true"}">
              <span class="collapse-icon">${collapsed ? "+" : "-"}</span>
              <span class="group-name">${escapeHtml(group.name)}</span>
              <span class="group-count">${group.items.length}</span>
            </button>
            <div class="group-actions">
              <button class="order-button" data-move-group="up" data-group-index="${index}" type="button" aria-label="Move ${escapeHtml(group.name)} up" ${index === 0 ? "disabled" : ""}>Up</button>
              <button class="order-button" data-move-group="down" data-group-index="${index}" type="button" aria-label="Move ${escapeHtml(group.name)} down" ${index === state.workspace.boardGroups.length - 1 ? "disabled" : ""}>Down</button>
            </div>
          </div>
          <div class="board-item-list" ${collapsed ? "hidden" : ""}>${items}</div>
        </section>
      `;
    })
    .join("");

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
    button.addEventListener("click", () => {
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
}

function renderScope() {
  scopeContentElement.textContent = state.workspace?.scopeText ?? "";
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
  extraSectionsElement.innerHTML = "";
  extraSectionsPanel.hidden = true;
  rawTextElement.value = "";
  previewElement.className = "preview-surface preview-empty";
  previewElement.innerHTML = "Preview the current item or switch to Edit to change its core fields.";
  autosizeStructuredTextareas();
  syncMobileNavigation();
}

function getExtraSectionHeadings() {
  return Array.from(extraSectionsElement.querySelectorAll("textarea[data-extra-section]"))
    .map((textarea) => textarea.dataset.extraSection || "")
    .filter(Boolean);
}

function renderExtraSections(item) {
  const orderedHeadings = item.extraSectionOrder || Object.keys(item.extraSections || {});

  if (orderedHeadings.length === 0) {
    extraSectionsElement.innerHTML = "";
    extraSectionsPanel.hidden = true;
    return;
  }

  extraSectionsPanel.hidden = false;
  extraSectionsElement.innerHTML = orderedHeadings
    .map((heading) => {
      const safeHeading = escapeHtml(heading);
      return `
        <label>
          <span>${safeHeading}</span>
          <textarea data-extra-section="${safeHeading}" rows="6"></textarea>
        </label>
      `;
    })
    .join("");

  for (const textarea of extraSectionsElement.querySelectorAll("textarea[data-extra-section]")) {
    textarea.value = item.extraSections[textarea.dataset.extraSection] || "";
    autosizeTextarea(textarea);
    textarea.addEventListener("input", () => {
      autosizeTextarea(textarea);
      setDirtyState("structured", true);
      if (state.editorMode === "preview") {
        renderPreview();
      }
    });
  }
}

function getStructuredSections() {
  const sections = {};

  for (const sectionName of FIXED_SECTIONS) {
    sections[sectionName] = fields[sectionName].value;
  }

  for (const textarea of extraSectionsElement.querySelectorAll("textarea[data-extra-section]")) {
    sections[textarea.dataset.extraSection] = textarea.value;
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
  const orderedSections = [...FIXED_SECTIONS, ...getExtraSectionHeadings()];
  const sectionHtml = orderedSections
    .map((heading) => `
      <section class="preview-section">
        <h3>${escapeHtml(heading)}</h3>
        <div class="preview-markdown">${renderMarkdownToHtml(sections[heading] || "") || '<p class="muted">Empty section.</p>'}</div>
      </section>
    `)
    .join("");

  previewElement.className = "preview-surface";
  previewElement.innerHTML = `
    <header class="preview-header">
      <div>
        <p class="eyebrow preview-eyebrow">Item preview</p>
        <h2>${escapeHtml(metadata.title || state.currentItem.metadata.title || state.currentItem.id)}</h2>
        <p class="muted">${escapeHtml(state.currentItem.filePath)}</p>
      </div>
      <div class="preview-meta">
        ${[metadata.status, metadata.priority, metadata.commitment, metadata.milestone].filter(Boolean).map((value) => `<span class="badge">${escapeHtml(value)}</span>`).join("")}
      </div>
    </header>
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

  for (const sectionName of FIXED_SECTIONS) {
    fields[sectionName].value = item.sections[sectionName] || "";
  }

  renderExtraSections(item);
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

async function loadWorkspace(preferredItemId = state.selectedItemId) {
  try {
    const workspace = await fetchJson("/api/workspace");
    state.workspace = workspace;
    roadmapPathElement.textContent = workspace.roadmapPath;
    syncWorkspaceChrome();
    renderBoard();
    renderScope();
    setBanner("");

    const firstItemId = workspace.boardGroups.flatMap((group) => group.items).at(0)?.id;
    const itemIdToLoad = preferredItemId || firstItemId;

    if (itemIdToLoad) {
      await loadItem(itemIdToLoad, false);
    } else {
      resetEditor();
    }
  } catch (error) {
    state.workspace = null;
    roadmapPathElement.textContent = "Unavailable";
    syncWorkspaceChrome();
    boardGroupsElement.innerHTML = "";
    scopeContentElement.textContent = "";
    resetEditor();
    setBanner(error.message, "error");
  }
}

async function loadItem(itemId, rerenderBoard = true) {
  try {
    const item = await fetchJson(`/api/items/${encodeURIComponent(itemId)}`);
    state.selectedItemId = itemId;
    renderItem(item);
    applyEditorMode();
    if (rerenderBoard) {
      renderBoard();
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

function switchEditorMode(nextMode) {
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
      headers: {
        "Content-Type": "application/json",
      },
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

saveButton.addEventListener("click", () => {
  void saveCurrentItem();
});

refreshButton.addEventListener("click", () => {
  void loadWorkspace();
});

scopeToggleButton.addEventListener("click", () => {
  toggleScopePanel();
});

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
  if (state.editorMode === "preview") {
    renderPreview();
  }
});

rawTextElement.addEventListener("input", () => {
  setDirtyState("raw", true);
});

for (const button of modeButtons) {
  button.addEventListener("click", () => {
    switchEditorMode(button.dataset.editorMode);
  });
}

resetEditor();
renderScopeChrome();
applyEditorMode();
void loadWorkspace();


