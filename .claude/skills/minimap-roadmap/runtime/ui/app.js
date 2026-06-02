const FIXED_SECTIONS = ["Summary", "Why", "In Scope", "Out of Scope", "Done When", "Notes"];
const SCOPE_STORAGE_KEY = "roadmap-ui.scope-collapsed";
const SCOPE_WIDTH_STORAGE_KEY = "roadmap-ui.scope-width";
const SPEC_FILES_COLLAPSED_STORAGE_KEY = "spec-sessions.files-collapsed";
// Stored as a fraction of the spec-doc width (e.g. 0.62 = body is 62% of the
// pane, margin gets the rest). Migrated from a legacy pixel-width key on read.
const SPEC_BODY_WIDTH_STORAGE_KEY = "spec-sessions.body-frac";
const LEGACY_SPEC_BODY_WIDTH_STORAGE_KEY = "spec-sessions.body-width";
const DEFAULT_SCOPE_WIDTH = 272;
const MIN_SCOPE_WIDTH = 240;
const MAX_SCOPE_WIDTH = 440;
// Fraction of the doc area dedicated to the spec body. Margin column gets the
// remainder. Tuned so a ~1100px viewport still shows margin cards in full.
const DEFAULT_SPEC_BODY_FRAC = 0.66;
const MIN_SPEC_BODY_FRAC = 0.4;
const MAX_SPEC_BODY_FRAC = 0.82;
const MIN_SPEC_MARGIN_WIDTH = 240;
const SPEC_REVIEW_REFRESH_MS = 5000;
const SPEC_COMMENT_FILTERS = new Set(["open", "all", "resolved"]);
const SPEC_COMMENT_ANCHOR_MODES = new Set(["global", "section", "quote"]);
const SPEC_REVIEW_TABS = new Set(["comments", "suggestions"]);
const SPEC_SUGGESTION_ANCHOR_MODES = new Set(["quote", "section"]);
const DEFAULT_LENS_KEY = "board";
const DEFAULT_BOARD_LAYOUT = "list";
const BOARD_LAYOUTS = new Set(["list", "columns"]);
const UNASSIGNED_GROUP_KEY = "__unassigned__";
const UNASSIGNED_GROUP_LABEL = "Unassigned";
const EDITOR_MODES = new Set(["preview", "structured", "raw"]);

const state = {
  appMode: "roadmap",
  repoPath: "",
  workspace: null,
  setupState: null,
  selectedItemId: null,
  currentItem: null,
  activeLens: DEFAULT_LENS_KEY,
  boardLayout: DEFAULT_BOARD_LAYOUT,
  dragItemId: null,
  dragColumnIndex: null,
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
  spec: {
    sessions: [],
    selectedPath: "",
    context: null,
    content: "",
    commentComposerOpen: false,
    replyComposerCommentId: "",
    selectedQuote: "",
    activeAnchorCommentId: "",
    anchorHighlightTimer: null,
    reviewTab: "comments",
    commentFilter: "open",
    commentSort: "newest",
    expandedResolvedCommentIds: new Set(),
    replyDrafts: new Map(),
    loadError: null,
    commentAnchorMode: "global",
    suggestionComposerOpen: false,
    suggestionAnchorMode: "quote",
    previewSuggestionId: "",
    suggestionPreview: null,
    filesCollapsed: loadStoredSpecFilesPreference(),
    bodyFrac: loadStoredSpecBodyFrac(),
    resizingMargin: false,
    viewMode: "review",          // "read" | "review"
    showComments: true,
    showSuggestions: true,
    showResolved: false,
    sidebarSearch: "",
    composerTarget: null,        // { kind: "comment" | "suggestion", anchorId: string|"__file" }
  },
};

const roadmapModeButton = document.querySelector("#roadmap-mode-button");
const specModeButton = document.querySelector("#spec-mode-button");
const specWorkbenchElement = document.querySelector("#spec-workbench");
const specSidebarElement = document.querySelector("#spec-sidebar");
const specSidebarSearchInput = document.querySelector("#spec-sidebar-search");
const specFilesToggleButton = document.querySelector("#spec-files-toggle");
const specAttachForm = document.querySelector("#spec-attach-form");
const specAttachPathInput = document.querySelector("#spec-attach-path");
const specSessionListElement = document.querySelector("#spec-session-list");
const specFileTitleElement = document.querySelector("#spec-file-title");
const specFileSubtitleElement = document.querySelector("#spec-file-subtitle");
const specFileContentElement = document.querySelector("#spec-file-content");
const specContextToolbarElement = document.querySelector("#spec-context-toolbar");
const specDocElement = document.querySelector("#spec-doc");
const specGutterElement = document.querySelector("#spec-gutter");
const specMarginElement = document.querySelector("#spec-margin");
const specViewSegButtons = Array.from(document.querySelectorAll("[data-spec-view]"));
const specLayerSegButtons = Array.from(document.querySelectorAll("[data-spec-layer]"));
const specResolvedToggleButton = document.querySelector("#spec-resolved-toggle");
const specCommentForm = document.querySelector("#spec-comment-form");
const specCommentCancelButton = document.querySelector("#spec-comment-cancel-button");
const specCommentByInput = document.querySelector("#spec-comment-by");
const specParticipantsFacepile = document.querySelector("#spec-participants-facepile");
const specParticipantsPopover = document.querySelector("#spec-participants-popover");
const specCommentKindInput = document.querySelector("#spec-comment-kind");
const specCommentAnchorInput = document.querySelector("#spec-comment-anchor");
const specCommentAnchorLabelElement = document.querySelector("#spec-comment-anchor-label");
const specCommentAnchorSummaryElement = document.querySelector("#spec-comment-anchor-summary");
const specCommentTextInput = document.querySelector("#spec-comment-text");
const specCommentGlobalInput = document.querySelector("#spec-comment-global");
const specSuggestionForm = document.querySelector("#spec-suggestion-form");
const specSuggestionCancelButton = document.querySelector("#spec-suggestion-cancel-button");
const specSuggestionByInput = document.querySelector("#spec-suggestion-by");
const specSuggestionKindInput = document.querySelector("#spec-suggestion-kind");
const specSuggestionAnchorInput = document.querySelector("#spec-suggestion-anchor");
const specSuggestionAnchorLabelElement = document.querySelector("#spec-suggestion-anchor-label");
const specSuggestionAnchorSummaryElement = document.querySelector("#spec-suggestion-anchor-summary");
const specSuggestionContentInput = document.querySelector("#spec-suggestion-content");
const specSuggestionRationaleInput = document.querySelector("#spec-suggestion-rationale");
const specCommentAnchorModeButtons = Array.from(document.querySelectorAll("[data-comment-anchor-mode]"));
const specSuggestionAnchorModeButtons = Array.from(document.querySelectorAll("[data-suggestion-anchor-mode]"));
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
const modeTitleElement = document.querySelector("#mode-title");
const modeEyebrowElement = document.querySelector("#mode-eyebrow");
const editorTitleElement = document.querySelector("#editor-title");
const editorSubtitleElement = document.querySelector("#editor-subtitle");
const editorPanelElement = document.querySelector("#editor-panel");
const editorPanelAnchor = document.querySelector("#editor-panel-anchor");
const editorOverlayElement = document.querySelector("#editor-overlay");
const editorOverlaySlotElement = document.querySelector("#editor-overlay-slot");
const editorOverlayBackdrop = document.querySelector("#editor-overlay-backdrop");
const editorCancelButton = document.querySelector("#editor-cancel-button");
const openInSpecButton = document.querySelector("#open-in-spec-button");
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
  extraMetadataContainer: document.querySelector("#extra-metadata-fields"),
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

function loadStoredSpecFilesPreference() {
  try {
    const stored = window.localStorage.getItem(SPEC_FILES_COLLAPSED_STORAGE_KEY);
    return stored === "true";
  } catch {
    return false;
  }
}

function persistSpecFilesPreference() {
  try {
    window.localStorage.setItem(SPEC_FILES_COLLAPSED_STORAGE_KEY, String(state.spec.filesCollapsed));
  } catch {
    // Ignore storage failures.
  }
}

function clampSpecBodyFrac(frac) {
  if (!Number.isFinite(frac)) return DEFAULT_SPEC_BODY_FRAC;
  return Math.min(MAX_SPEC_BODY_FRAC, Math.max(MIN_SPEC_BODY_FRAC, frac));
}

function loadStoredSpecBodyFrac() {
  try {
    const raw = Number(window.localStorage.getItem(SPEC_BODY_WIDTH_STORAGE_KEY));
    if (Number.isFinite(raw) && raw > 0 && raw <= 1) return clampSpecBodyFrac(raw);
    // One-time migration: older builds stored a pixel width. Discard it.
    window.localStorage.removeItem(LEGACY_SPEC_BODY_WIDTH_STORAGE_KEY);
    return DEFAULT_SPEC_BODY_FRAC;
  } catch {
    return DEFAULT_SPEC_BODY_FRAC;
  }
}

function persistSpecBodyFrac() {
  try {
    window.localStorage.setItem(SPEC_BODY_WIDTH_STORAGE_KEY, String(state.spec.bodyFrac));
  } catch {
    // Ignore storage failures.
  }
}

function setBanner(message, tone = "info") {
  if (!message) {
    statusBanner.hidden = true;
    statusBanner.innerHTML = "";
    statusBanner.dataset.tone = "";
    return;
  }

  statusBanner.hidden = false;
  statusBanner.dataset.tone = tone;
  statusBanner.innerHTML = `
    <span class="status-banner-message">${escapeHtml(message)}</span>
    <button class="status-banner-dismiss" type="button" aria-label="Dismiss status">&times;</button>
  `;
}

async function copyTextToClipboard(text) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to legacy path
  }
  try {
    const helper = document.createElement("textarea");
    helper.value = text;
    helper.setAttribute("readonly", "");
    helper.style.position = "absolute";
    helper.style.left = "-9999px";
    document.body.appendChild(helper);
    helper.select();
    document.execCommand("copy");
    document.body.removeChild(helper);
    return true;
  } catch {
    return false;
  }
}

function bindMissingItemCopyButtons() {
  // Wire Copy buttons (and id-text spans) on rendered "missing item" placeholder
  // cards. The card carries data-copy-text attributes; clicking copies them and
  // briefly flashes a confirmation banner so the user sees the click registered.
  for (const node of boardGroupsElement.querySelectorAll("[data-copy-text]")) {
    if (node.dataset.copyBound === "1") {
      continue;
    }
    node.dataset.copyBound = "1";
    node.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const text = node.dataset.copyText || "";
      if (!text) return;
      const ok = await copyTextToClipboard(text);
      setBanner(ok ? "Copied to clipboard." : "Could not copy to clipboard.", ok ? "success" : "error");
    });
  }
}

function renderWorkspaceWarnings() {
  // Surface non-fatal warnings emitted by loadWorkspace (e.g. orphan board ids).
  // The placeholder cards in the columns are the primary affordance; this banner
  // gives a one-line summary so the warning is visible even if the user is
  // looking at a different column.
  const warnings = Array.isArray(state.workspace?.warnings) ? state.workspace.warnings : [];
  if (warnings.length === 0) {
    return false;
  }
  const message = warnings.map((entry) => entry.message || "").filter(Boolean).join(" ");
  if (!message) {
    return false;
  }
  setBanner(message, "warning");
  return true;
}

function clearTransientBanner() {
  // Clears the status banner unless there are sticky workspace-level warnings,
  // in which case re-renders them. Use this instead of setBanner("") whenever
  // an in-flow operation finishes successfully (item load, save, etc.) so that
  // workspace warnings (e.g. orphan board items) stay visible.
  if (renderWorkspaceWarnings()) {
    return;
  }
  setBanner("");
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

function stripLeadingFrontmatter(text) {
  // YAML frontmatter at the start of a markdown file: a `---` fence on its
  // own line, then arbitrary content, then a closing `---` fence. We render
  // the body only; the frontmatter is structured metadata that the roadmap
  // mode surfaces separately, and bare YAML rendered as markdown produces
  // the noisy "id: ... title: ... labels:" paragraphs we want to avoid.
  return String(text || "").replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
}

function parseLeadingFrontmatter(text) {
  // Lightweight client-side parser for the common shape: `key: value` per
  // line, plus YAML-style list values written as either inline `[a, b]` or
  // on subsequent indented `- item` lines (which is how `labels:` looks).
  // We ignore anything more exotic — the server is the source of truth for
  // strict parsing; this is only used for the spec view's metadata header.
  const match = String(text || "").match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (!match) return null;
  const lines = match[1].split(/\r?\n/);
  const metadata = {};
  let currentKey = null;
  for (const line of lines) {
    const keyMatch = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (keyMatch) {
      const key = keyMatch[1];
      const rest = keyMatch[2].trim();
      if (rest === "" || rest === "[]") {
        metadata[key] = rest === "[]" ? [] : "";
        currentKey = key;
        continue;
      }
      // Inline list: [a, b, c]
      const inlineList = rest.match(/^\[(.*)\]$/);
      if (inlineList) {
        metadata[key] = inlineList[1].split(",").map((s) => s.trim()).filter(Boolean);
        currentKey = null;
        continue;
      }
      // Plain scalar; trim surrounding quotes so badge text reads cleanly.
      metadata[key] = rest.replace(/^"(.*)"$/, "$1").replace(/^'(.*)'$/, "$1");
      currentKey = null;
      continue;
    }
    // Continuation of a list value: an indented `- item` line.
    const listItemMatch = line.match(/^\s+-\s+(.+)$/);
    if (listItemMatch && currentKey) {
      const value = listItemMatch[1].trim().replace(/^"(.*)"$/, "$1").replace(/^'(.*)'$/, "$1");
      if (!Array.isArray(metadata[currentKey])) {
        metadata[currentKey] = metadata[currentKey] === "" || metadata[currentKey] === undefined ? [] : [metadata[currentKey]];
      }
      metadata[currentKey].push(value);
    }
  }
  return metadata;
}

function buildSpecDocHeaderHtml(frontmatter) {
  // Mirror the roadmap "Read" view header: a big title, then a row of
  // canonical metadata pills. Render only when the file's frontmatter
  // actually contains values worth showing — otherwise return empty so
  // a plain spec/note file stays clean.
  if (!frontmatter || typeof frontmatter !== "object") return "";
  const title = typeof frontmatter.title === "string" ? frontmatter.title.trim() : "";
  const badges = renderMetadataBadges(frontmatter);
  if (!title && !badges) return "";
  const titleHtml = title ? `<h1 class="spec-doc-title">${escapeHtml(title)}</h1>` : "";
  const badgesHtml = badges ? `<div class="spec-doc-meta">${badges}</div>` : "";
  return `<header class="spec-doc-header">${titleHtml}${badgesHtml}</header>`;
}

function renderMarkdownToHtml(markdown) {
  const normalized = String(markdown || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const sourceLines = normalized.split("\n");
  const blocks = [];

  function expandIndentation(value) {
    return String(value || "").replace(/\t/g, "    ");
  }

  function getIndentation(value) {
    const expanded = expandIndentation(value);
    const match = expanded.match(/^(\s*)/);
    return match ? match[1].length : 0;
  }

  function getListMarker(value) {
    const expanded = expandIndentation(value);
    let match = expanded.match(/^(\s*)([-*])\s+(.+)$/);
    if (match) {
      return { indent: match[1].length, ordered: false, content: match[3] };
    }

    match = expanded.match(/^(\s*)(\d+)\.\s+(.+)$/);
    if (match) {
      return { indent: match[1].length, ordered: true, content: match[3] };
    }

    return null;
  }

  function isHorizontalRule(value) {
    return /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/.test(value);
  }

  function splitTableRow(value) {
    const trimmed = String(value || "").trim();
    const withoutEdges = trimmed.replace(/^\|/, "").replace(/\|$/, "");
    return withoutEdges.split("|").map((cell) => cell.trim());
  }

  function isTableDelimiterLine(value) {
    const cells = splitTableRow(value);
    return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
  }

  function tableAlignments(value) {
    return splitTableRow(value).map((cell) => {
      const left = cell.startsWith(":");
      const right = cell.endsWith(":");
      if (left && right) {
        return "center";
      }
      if (right) {
        return "right";
      }
      return "left";
    });
  }

  function isTableStart(index) {
    return index + 1 < sourceLines.length
      && sourceLines[index].includes("|")
      && isTableDelimiterLine(sourceLines[index + 1]);
  }

  function parseTable(startIndex) {
    const headerCells = splitTableRow(sourceLines[startIndex]);
    const alignments = tableAlignments(sourceLines[startIndex + 1]);
    const rows = [];
    let index = startIndex + 2;

    while (index < sourceLines.length && sourceLines[index].trim() && sourceLines[index].includes("|")) {
      rows.push(splitTableRow(sourceLines[index]));
      index += 1;
    }

    const alignStyle = (cellIndex) => ` style="text-align: ${alignments[cellIndex] || "left"}"`;
    const header = `<thead><tr>${headerCells.map((cell, cellIndex) => `<th${alignStyle(cellIndex)}>${renderInlineMarkdown(cell)}</th>`).join("")}</tr></thead>`;
    const body = rows.length
      ? `<tbody>${rows.map((row) => `<tr>${headerCells.map((_, cellIndex) => `<td${alignStyle(cellIndex)}>${renderInlineMarkdown(row[cellIndex] || "")}</td>`).join("")}</tr>`).join("")}</tbody>`
      : "";

    return {
      html: `<div class="markdown-table-wrap"><table>${header}${body}</table></div>`,
      nextIndex: index,
    };
  }

  function parseBlockquote(startIndex) {
    const quoteLines = [];
    let index = startIndex;

    while (index < sourceLines.length) {
      const match = sourceLines[index].match(/^>\s?(.*)$/);
      if (!match) {
        break;
      }
      quoteLines.push(match[1]);
      index += 1;
    }

    const quoteHtml = renderMarkdownToHtml(quoteLines.join("\n"));
    return {
      html: `<blockquote>${quoteHtml}</blockquote>`,
      nextIndex: index,
    };
  }

  function parseCodeBlock(startIndex) {
    const codeLines = [];
    let index = startIndex + 1;

    while (index < sourceLines.length && !sourceLines[index].startsWith("```")) {
      codeLines.push(sourceLines[index]);
      index += 1;
    }

    if (index < sourceLines.length && sourceLines[index].startsWith("```")) {
      index += 1;
    }

    return {
      html: `<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`,
      nextIndex: index,
    };
  }

  function parseParagraph(startIndex) {
    const paragraphLines = [];
    let index = startIndex;

    while (index < sourceLines.length) {
      const rawLine = sourceLines[index];
      const trimmed = rawLine.trim();
      if (!trimmed) {
        break;
      }
      if (trimmed.startsWith("```") || trimmed.startsWith(">") || trimmed.match(/^(#{1,6})\s+(.+)$/) || getListMarker(rawLine) || isHorizontalRule(trimmed) || isTableStart(index)) {
        break;
      }

      paragraphLines.push(trimmed);
      index += 1;
    }

    return {
      html: `<p>${renderInlineMarkdown(paragraphLines.join(" "))}</p>`,
      nextIndex: index,
    };
  }

  function parseList(startIndex, baseIndent, ordered) {
    const tagName = ordered ? "ol" : "ul";
    const items = [];
    let index = startIndex;

    while (index < sourceLines.length) {
      const marker = getListMarker(sourceLines[index]);
      if (!marker || marker.indent !== baseIndent || marker.ordered !== ordered) {
        break;
      }

      const paragraphLines = [marker.content.trim()];
      const children = [];
      index += 1;

      while (index < sourceLines.length) {
        const rawLine = sourceLines[index];
        const trimmed = rawLine.trim();

        if (!trimmed) {
          let lookahead = index + 1;
          while (lookahead < sourceLines.length && !sourceLines[lookahead].trim()) {
            lookahead += 1;
          }
          if (lookahead >= sourceLines.length) {
            index = lookahead;
            break;
          }

          const nextMarker = getListMarker(sourceLines[lookahead]);
          const nextIndent = getIndentation(sourceLines[lookahead]);
          const nextTrimmed = sourceLines[lookahead].trim();
          if ((nextMarker && nextMarker.indent <= baseIndent) || (!nextMarker && nextIndent <= baseIndent && !nextTrimmed.startsWith("```") && !nextTrimmed.match(/^(#{1,6})\s+(.+)$/))) {
            index = lookahead;
            break;
          }

          index = lookahead;
          continue;
        }

        if (trimmed.startsWith("```")) {
          const parsedCode = parseCodeBlock(index);
          children.push(parsedCode.html);
          index = parsedCode.nextIndex;
          continue;
        }

        const nestedMarker = getListMarker(rawLine);
        if (nestedMarker) {
          if (nestedMarker.indent > baseIndent) {
            const parsedList = parseList(index, nestedMarker.indent, nestedMarker.ordered);
            children.push(parsedList.html);
            index = parsedList.nextIndex;
            continue;
          }

          break;
        }

        const indent = getIndentation(rawLine);
        if (trimmed.match(/^(#{1,6})\s+(.+)$/) && indent <= baseIndent) {
          break;
        }

        if (indent > baseIndent) {
          paragraphLines.push(trimmed);
          index += 1;
          continue;
        }

        break;
      }

      const paragraphHtml = renderInlineMarkdown(paragraphLines.join(" "));
      if (children.length > 0) {
        items.push(`<li><p>${paragraphHtml}</p>${children.join("")}</li>`);
      } else {
        items.push(`<li>${paragraphHtml}</li>`);
      }
    }

    return {
      html: `<${tagName}>${items.join("")}</${tagName}>`,
      nextIndex: index,
    };
  }

  let index = 0;
  while (index < sourceLines.length) {
    const rawLine = sourceLines[index];
    const trimmed = rawLine.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const parsedCode = parseCodeBlock(index);
      blocks.push(parsedCode.html);
      index = parsedCode.nextIndex;
      continue;
    }

    if (trimmed.startsWith(">")) {
      const parsedQuote = parseBlockquote(index);
      blocks.push(parsedQuote.html);
      index = parsedQuote.nextIndex;
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      blocks.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      index += 1;
      continue;
    }

    const listMarker = getListMarker(rawLine);
    if (listMarker) {
      const parsedList = parseList(index, listMarker.indent, listMarker.ordered);
      blocks.push(parsedList.html);
      index = parsedList.nextIndex;
      continue;
    }

    if (isHorizontalRule(trimmed)) {
      blocks.push("<hr />");
      index += 1;
      continue;
    }

    if (isTableStart(index)) {
      const parsedTable = parseTable(index);
      blocks.push(parsedTable.html);
      index = parsedTable.nextIndex;
      continue;
    }

    const paragraph = parseParagraph(index);
    blocks.push(paragraph.html);
    index = paragraph.nextIndex;
  }

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

  const orderedIds = workspace.boardGroups.flatMap((group) => group.items.filter((item) => !item.missing).map((item) => item.id));
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
  return workspace?.boardGroups.flatMap((group) => group.items).find((item) => !item?.missing)?.id ?? null;
}

function getFirstVisibleBoardItemId(workspace = state.workspace) {
  return getVisibleBoardItemIds(workspace).at(0) ?? null;
}

function isMissingBoardItem(item) {
  return Boolean(item && item.missing === true);
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

function canReorderColumnsInColumnLayout(workspace = state.workspace) {
  const lens = getActiveLensDefinition(workspace);
  return Boolean(
    lens
    && lens.key === DEFAULT_LENS_KEY
    && !state.boardEditMode
    && isColumnsLayoutActive()
    && !isSearchActive(),
  );
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

const CORE_METADATA_FIELDS = ["status", "priority", "commitment", "milestone"];
const RESERVED_METADATA_KEYS = new Set(["id", "title", "kind", "labels", ...CORE_METADATA_FIELDS]);

function normalizeMetadataValue(value) {
  if (value === null || value === undefined || Array.isArray(value) || typeof value === "object") {
    return "";
  }

  return String(value).trim();
}

function getCustomMetadataEntries(metadata, options = {}) {
  const excludeKey = normalizeBadgeToken(options.excludeKey || "");
  const maxCount = Number.isFinite(options.maxCount) ? options.maxCount : Number.POSITIVE_INFINITY;
  const entries = Object.entries(metadata || {})
    .map(([key, value]) => ({ key, value: normalizeMetadataValue(value) }))
    .filter((entry) => entry.value && !RESERVED_METADATA_KEYS.has(entry.key) && normalizeBadgeToken(entry.key) !== excludeKey)
    .sort((left, right) => humanizeFilterKey(left.key).localeCompare(humanizeFilterKey(right.key)));

  return entries.slice(0, maxCount);
}

function buildMetadataBadgeEntries(metadata, options = {}) {
  const excludeKey = normalizeBadgeToken(options.excludeKey || "");
  const cardMode = options.cardMode === true;
  const entries = CORE_METADATA_FIELDS
    .filter((field) => normalizeBadgeToken(field) !== excludeKey)
    .map((field) => ({ field, value: normalizeMetadataValue(metadata?.[field]), showFieldLabel: false }))
    .filter((entry) => entry.value);

  const customEntries = getCustomMetadataEntries(metadata, { excludeKey, maxCount: cardMode ? 2 : Number.POSITIVE_INFINITY })
    .map((entry) => ({ field: entry.key, value: entry.value, showFieldLabel: true }));

  return [...entries, ...customEntries];
}

function renderBadge(value, field = "", options = {}) {
  const normalizedField = normalizeBadgeToken(field);
  const tone = getBadgeTone(normalizedField, value);
  const classes = ["badge", `badge-tone-${tone}`];
  if (normalizedField) {
    classes.push(`badge-field-${normalizedField}`);
  }
  const label = options.showFieldLabel && normalizedField
    ? `${humanizeFilterKey(normalizedField)}: ${value}`
    : value;
  return `<span class="${classes.join(" ")}">${escapeHtml(label)}</span>`;
}

function getBadgeMetadata(item) {
  if (!item || typeof item !== "object") {
    return {};
  }

  if (item.metadata && typeof item.metadata === "object") {
    return item.metadata;
  }

  return Object.fromEntries(CORE_METADATA_FIELDS
    .map((field) => [field, normalizeMetadataValue(item[field])])
    .filter(([, value]) => value));
}

function renderMetadataBadges(metadata, excludeKey = "", options = {}) {
  return buildMetadataBadgeEntries(metadata || {}, { ...options, excludeKey })
    .map((entry) => renderBadge(entry.value, entry.field, { showFieldLabel: entry.showFieldLabel }))
    .join("");
}

function renderBadges(item, excludeKey = "", options = {}) {
  return renderMetadataBadges(getBadgeMetadata(item), excludeKey, options);
}

function updateDocumentTitle() {
  const repoName = state.workspace?.repoName || repoNameElement.textContent || "";
  if (repoName) repoNameElement.textContent = repoName;
  const specMode = document.body.dataset.appMode === "spec";
  const modeLabel = specMode ? "Spec sessions" : "Roadmap";
  document.title = repoName ? `Minimap — ${repoName} · ${modeLabel}` : `Minimap — ${modeLabel}`;
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
    view: params.get("view") || "roadmap",
    specFile: params.get("file") || "",
    itemId: params.get("item") || "",
    mode: normalizeEditorMode(params.get("mode") || "preview"),
    lens: params.get("lens") || DEFAULT_LENS_KEY,
    layout: normalizeBoardLayout(params.get("layout") || DEFAULT_BOARD_LAYOUT),
    query: normalizeSearchQuery(params.get("q") || ""),
    filters: parseRouteFilters(params),
    repo: params.get("repo") || "",
  };
}

function buildRouteHash(itemId = state.selectedItemId, mode = state.editorMode) {
  const params = new URLSearchParams();

  if (state.repoPath) {
    params.set("repo", state.repoPath);
  }

  if (state.appMode === "spec") {
    params.set("view", "spec");
    if (state.spec.selectedPath) {
      params.set("file", state.spec.selectedPath);
    }
    return `#${params.toString()}`;
  }

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

  if (openInSpecButton) {
    // The Review button stays visible in every editor mode while an item is
    // loaded — it opens a spec session on the item file regardless of whether
    // the user is in read, edit, or raw mode.
    openInSpecButton.hidden = setupMode || !hasItem;
    openInSpecButton.disabled = !hasItem;
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
  applyAppMode();
}

function toggleScopePanel() {
  if (state.scopeEditMode) {
    return;
  }

  state.scopeCollapsed = !state.scopeCollapsed;
  persistScopePreference();
  renderScopeChrome();
}

function toggleSpecFilesPanel() {
  state.spec.filesCollapsed = !state.spec.filesCollapsed;
  persistSpecFilesPreference();
  applyAppMode();
}

function beginSpecMarginResize(event) {
  if (isStackedLayout()) {
    return;
  }
  if (state.spec.viewMode !== "review") {
    return;
  }
  // The gutter contains both the rail (drag-to-resize) and the hover-add
  // "+" button. A pointerdown on the button must NOT start a resize
  // gesture — pointer capture on the gutter would swallow the click.
  if (event.target instanceof Element && event.target.closest(".spec-gutter-add")) {
    return;
  }

  state.spec.resizingMargin = true;
  state.spec.resizeStartX = event.clientX;
  // Snapshot the doc width so we convert pixel deltas → fraction deltas.
  state.spec.resizeStartDocWidth = specDocElement.clientWidth || 1;
  state.spec.resizeStartFrac = state.spec.bodyFrac;
  applyAppMode();
  specGutterElement.setPointerCapture(event.pointerId);
}

function updateSpecMarginResize(event) {
  if (!state.spec.resizingMargin) {
    return;
  }

  // Drag right -> body fraction grows. Drag left -> body shrinks (margin grows).
  const dx = event.clientX - (state.spec.resizeStartX || 0);
  const docW = state.spec.resizeStartDocWidth || specDocElement.clientWidth || 1;
  const next = (state.spec.resizeStartFrac || DEFAULT_SPEC_BODY_FRAC) + dx / docW;
  state.spec.bodyFrac = clampSpecBodyFrac(next);
  applyAppMode();
  layoutSpecMargin();
}

function endSpecMarginResize(event) {
  if (!state.spec.resizingMargin) {
    return;
  }

  state.spec.resizingMargin = false;
  persistSpecBodyFrac();
  applyAppMode();
  try {
    specGutterElement.releasePointerCapture(event.pointerId);
  } catch {
    // Pointer capture may already be released.
  }
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

function getEditableMetadataOptions(key, currentValue = "") {
  const values = [];
  const lens = state.workspace?.availableLenses?.find((entry) => entry.key === key);
  const facet = state.workspace?.availableFilters?.find((entry) => entry.key === key);

  if (Array.isArray(lens?.values)) {
    values.push(...lens.values);
  }
  if (Array.isArray(facet?.values)) {
    values.push(...facet.values);
  }
  if (currentValue) {
    values.push(currentValue);
  }

  return Array.from(new Set(values.map((value) => String(value).trim()).filter(Boolean)));
}

function renderExtraMetadataFields(item = state.currentItem) {
  if (!fields.extraMetadataContainer) {
    return;
  }

  const entries = getCustomMetadataEntries(item?.metadata, { maxCount: Number.POSITIVE_INFINITY });
  if (entries.length === 0) {
    fields.extraMetadataContainer.hidden = true;
    fields.extraMetadataContainer.innerHTML = "";
    return;
  }

  fields.extraMetadataContainer.hidden = false;
  fields.extraMetadataContainer.innerHTML = entries.map((entry) => {
    const key = escapeHtml(entry.key);
    const label = escapeHtml(humanizeFilterKey(entry.key));
    const value = escapeHtml(entry.value);
    const options = getEditableMetadataOptions(entry.key, entry.value);

    if (options.length >= 2) {
      const optionMarkup = ['<option value=""></option>', ...options.map((option) => {
        const selected = option === entry.value ? " selected" : "";
        return `<option value="${escapeHtml(option)}"${selected}>${escapeHtml(option)}</option>`;
      })].join("");
      return `<label><span>${label}</span><select data-extra-metadata-key="${key}">${optionMarkup}</select></label>`;
    }

    return `<label><span>${label}</span><input data-extra-metadata-key="${key}" type="text" value="${value}" /></label>`;
  }).join("");

  for (const input of fields.extraMetadataContainer.querySelectorAll("[data-extra-metadata-key]")) {
    input.addEventListener("input", () => {
      setDirtyState("structured", true);
      renderPreview();
    });
    input.addEventListener("change", () => {
      setDirtyState("structured", true);
      renderPreview();
    });
  }
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

function buildBoardGroupsWithPlacedItem(itemId, targetGroupIndex, beforeItemId = "", boardGroups = buildBoardGroupsPayload()) {
  if (!itemId || !Number.isInteger(targetGroupIndex) || targetGroupIndex < 0 || targetGroupIndex >= boardGroups.length) {
    return null;
  }

  const sourceGroupIndex = boardGroups.findIndex((group) => group.itemIds.includes(itemId));
  if (sourceGroupIndex < 0) {
    return null;
  }

  const groups = boardGroups.map((group) => ({
    ...group,
    itemIds: group.itemIds.filter((currentId) => currentId !== itemId),
  }));

  const targetItems = [...groups[targetGroupIndex].itemIds];
  let insertIndex = targetItems.length;

  if (beforeItemId) {
    const nextIndex = targetItems.indexOf(beforeItemId);
    if (nextIndex >= 0) {
      insertIndex = nextIndex;
    }
  }

  targetItems.splice(insertIndex, 0, itemId);
  groups[targetGroupIndex] = {
    ...groups[targetGroupIndex],
    itemIds: targetItems,
  };

  const unchanged = boardGroups.every((group, index) => {
    if (group.itemIds.length !== groups[index].itemIds.length) {
      return false;
    }
    return group.itemIds.every((currentId, itemIndex) => currentId === groups[index].itemIds[itemIndex]);
  });

  return unchanged ? null : groups;
}


function clearBoardDragState() {
  state.dragItemId = null;
  state.dragColumnIndex = null;
  for (const dropZone of boardGroupsElement.querySelectorAll("[data-lens-drop-value], [data-board-drop-group-index], [data-board-column-drop-index]")) {
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
  const specLink = state.workspace?.specSessionsByItemId?.[item.id];
  const specBadge = specLink
    ? `<span class="board-item-spec-badge" title="${escapeHtml(buildSpecBadgeTitle(specLink))}" aria-label="${escapeHtml(buildSpecBadgeTitle(specLink))}">💬 ${specLink.openComments}${specLink.pendingSuggestions > 0 ? ` · ✎ ${specLink.pendingSuggestions}` : ""}</span>`
    : "";

  return `
    <span class="board-item-top">
      <span class="board-item-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</span>
      ${metaHtml}
    </span>
    <span class="board-item-id">${escapeHtml(item.id)}</span>
    ${overview}
    <span class="badge-row">${renderBadges(item, activeLensKey, { cardMode: true })}${specBadge}</span>
  `;
}

function buildMissingBoardCardInner(item) {
  // Inert placeholder for an id listed in board.md that has no matching
  // feature/idea file. Surfaces enough context for the user (or an agent)
  // to fix the drift: the orphan id, where it appears, what's missing, and
  // a copy-to-clipboard for both the id and a one-line fix instruction.
  const groupHeading = item.groupName ? ` under "${item.groupName}"` : "";
  const fixInstruction = `The roadmap board references "${item.id}"${groupHeading} but the feature file is missing. Either create roadmap/features/${item.id}.md or remove the line from roadmap/board.md.`;
  return `
    <span class="board-item-missing-header">
      <span class="board-item-missing-icon" aria-hidden="true">⚠</span>
      <span class="board-item-missing-label">Missing roadmap item</span>
    </span>
    <span class="board-item-missing-id" title="Click to copy id" data-copy-text="${escapeHtml(item.id)}">${escapeHtml(item.id)}</span>
    <span class="board-item-missing-explain">Listed in board.md${groupHeading ? ` ${escapeHtml(groupHeading.trim())}` : ""} but no matching file in <code>roadmap/features/</code> or <code>roadmap/ideas/</code>.</span>
    <span class="board-item-missing-fix">Fix: create <code>roadmap/features/${escapeHtml(item.id)}.md</code>, or remove the line from <code>roadmap/board.md</code>.</span>
    <span class="board-item-missing-actions">
      <button class="ghost-button board-item-missing-copy" type="button" data-copy-text="${escapeHtml(item.id)}" title="Copy the missing id">Copy id</button>
      <button class="ghost-button board-item-missing-copy" type="button" data-copy-text="${escapeHtml(fixInstruction)}" title="Copy a one-line fix instruction you can paste to an agent">Copy fix instructions</button>
    </span>
  `;
}

function renderMissingBoardCardColumn(item) {
  return `
    <article class="board-column-card board-column-card-missing" title="Missing roadmap item: ${escapeHtml(item.id)}" aria-label="Missing roadmap item ${escapeHtml(item.id)}">
      ${buildMissingBoardCardInner(item)}
    </article>
  `;
}

function renderMissingBoardCardRead(item) {
  return `
    <div class="board-item board-item-missing" role="group" aria-label="Missing roadmap item ${escapeHtml(item.id)}" title="Missing roadmap item: ${escapeHtml(item.id)}">
      ${buildMissingBoardCardInner(item)}
    </div>
  `;
}

function buildSpecBadgeTitle(specLink) {
  const parts = [];
  if (specLink.openComments > 0) {
    parts.push(`${specLink.openComments} open comment${specLink.openComments === 1 ? "" : "s"}`);
  }
  if (specLink.pendingSuggestions > 0) {
    parts.push(`${specLink.pendingSuggestions} pending suggestion${specLink.pendingSuggestions === 1 ? "" : "s"}`);
  }
  if (parts.length === 0) {
    return "Spec session attached";
  }
  return `Spec session: ${parts.join(", ")}`;
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

async function persistBoardItemPlacement(itemId, targetGroupIndex, beforeItemId = "") {
  if (!state.workspace || !itemId || !Number.isInteger(targetGroupIndex) || targetGroupIndex < 0 || targetGroupIndex >= state.workspace.boardGroups.length) {
    return;
  }

  const groups = buildBoardGroupsWithPlacedItem(itemId, targetGroupIndex, beforeItemId);
  if (!groups) {
    return;
  }

  setBanner("Updating board order...");

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
  const allowColumnReorder = canReorderColumnsInColumnLayout();
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
    const reorderAttributes = allowColumnReorder ? `data-board-column-drop-index="${group.originalIndex}"` : "";

    const cardsHtml = group.items.map((item) => {
      if (isMissingBoardItem(item)) {
        return renderMissingBoardCardColumn(item);
      }
      const activeClass = item.id === state.selectedItemId && state.editorOverlayOpen ? " board-column-card-active" : "";
      const dragHandle = allowColumnDrag
        ? `<span class="board-column-card-drag" data-drag-item-id="${escapeHtml(item.id)}" draggable="true" role="button" tabindex="0" aria-label="Move ${escapeHtml(item.title)}" title="Drag to move ${escapeHtml(item.title)}">::</span>`
        : "";
      const placementAttributes = boardGrouping && allowColumnDrag
        ? `data-board-drop-group-index="${group.originalIndex}" data-board-drop-before-id="${escapeHtml(item.id)}"`
        : "";

      return `
        <article class="board-column-card${activeClass}${placementAttributes ? " board-column-dropzone" : ""}" title="${escapeHtml(item.title)}" ${placementAttributes}>
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
      <section class="board-column${allowColumnReorder ? " board-column-reorderable" : ""}${reorderAttributes ? " board-column-reorder-dropzone" : ""}" ${reorderAttributes}>
        <div class="board-column-header">
          <div class="board-column-heading">
            <span class="board-column-name">${escapeHtml(group.name)}</span>
            <span class="group-count">${group.items.length}</span>
          </div>
          ${allowColumnReorder
            ? `<button class="board-column-reorder-handle" data-drag-column-index="${group.originalIndex}" draggable="true" type="button" aria-label="Reorder ${escapeHtml(group.name)} column" title="Drag to reorder ${escapeHtml(group.name)}">::</button>`
            : ""}
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

  bindMissingItemCopyButtons();

  for (const panel of boardGroupsElement.querySelectorAll("[data-item-dblopen]")) {
    panel.addEventListener("dblclick", async () => {
      if (Date.now() < state.dragClickSuppressUntil) {
        return;
      }

      await openBoardItemPreview(panel.dataset.itemDblopen);
    });
  }

  if (allowColumnDrag) {
    for (const handle of boardGroupsElement.querySelectorAll("[data-drag-item-id]")) {
      handle.addEventListener("dragstart", (event) => {
        const itemId = handle.dataset.dragItemId || "";
        if (!itemId || state.dragColumnIndex !== null) {
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

    for (const dropZone of boardGroupsElement.querySelectorAll("[data-board-drop-group-index], [data-lens-drop-value], [data-board-drop-before-id]")) {
      dropZone.addEventListener("dragover", (event) => {
        if (!state.dragItemId) {
          return;
        }

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
        if (!state.dragItemId) {
          return;
        }

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

        if (dropZone.dataset.boardDropBeforeId) {
          void persistBoardItemPlacement(
            itemId,
            Number(dropZone.dataset.boardDropGroupIndex),
            dropZone.dataset.boardDropBeforeId || "",
          );
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

  if (!allowColumnReorder) {
    return;
  }

  for (const handle of boardGroupsElement.querySelectorAll("[data-drag-column-index]")) {
    handle.addEventListener("dragstart", (event) => {
      const columnIndex = Number(handle.dataset.dragColumnIndex);
      if (!Number.isInteger(columnIndex) || state.dragItemId) {
        event.preventDefault();
        return;
      }

      state.dragColumnIndex = columnIndex;
      state.dragClickSuppressUntil = Date.now() + 350;
      handle.classList.add("is-dragging");
      handle.closest(".board-column")?.classList.add("is-dragging");
      event.dataTransfer?.setData("text/plain", String(columnIndex));
      event.dataTransfer?.setData("application/x-minimap-column-index", String(columnIndex));
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
      }
    });

    handle.addEventListener("dragend", () => {
      state.dragClickSuppressUntil = Date.now() + 350;
      clearBoardDragState();
    });
  }

  for (const dropZone of boardGroupsElement.querySelectorAll("[data-board-column-drop-index]")) {
    dropZone.addEventListener("dragover", (event) => {
      if (!Number.isInteger(state.dragColumnIndex)) {
        return;
      }

      const targetIndex = Number(dropZone.dataset.boardColumnDropIndex);
      if (!Number.isInteger(targetIndex) || targetIndex === state.dragColumnIndex) {
        return;
      }

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
      if (!Number.isInteger(state.dragColumnIndex)) {
        return;
      }

      event.preventDefault();
      const fromIndex = Number(
        event.dataTransfer?.getData("application/x-minimap-column-index")
          || event.dataTransfer?.getData("text/plain")
          || state.dragColumnIndex,
      );
      const toIndex = Number(dropZone.dataset.boardColumnDropIndex);
      state.dragClickSuppressUntil = Date.now() + 350;
      clearBoardDragState();
      if (!Number.isInteger(fromIndex) || !Number.isInteger(toIndex) || fromIndex === toIndex) {
        return;
      }

      void persistGroupOrder(fromIndex, toIndex);
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
      if (isMissingBoardItem(item)) {
        return renderMissingBoardCardRead(item);
      }
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

  bindMissingItemCopyButtons();

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
  if (fields.extraMetadataContainer) {
    fields.extraMetadataContainer.hidden = true;
    fields.extraMetadataContainer.innerHTML = "";
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
  const metadata = {
    ...(state.currentItem?.metadata || {}),
    id: fields.id.value,
    title: fields.title.value,
    status: fields.status.value,
    priority: fields.priority.value,
    commitment: fields.commitment.value,
    milestone: fields.milestone.value.trim(),
  };

  if (fields.extraMetadataContainer) {
    for (const input of fields.extraMetadataContainer.querySelectorAll("[data-extra-metadata-key]")) {
      const key = input.dataset.extraMetadataKey;
      if (!key) {
        continue;
      }
      metadata[key] = input.value.trim();
    }
  }

  return metadata;
}

function renderPreview() {
  if (!state.currentItem) {
    previewElement.className = "preview-surface preview-empty";
    previewElement.innerHTML = "Choose an item from the board to read it here.";
    return;
  }

  const useDraftState = state.dirtyStructured;
  const metadata = useDraftState ? getStructuredMetadata() : state.currentItem.metadata;
  const orderedSections = getStructuredSectionHeadings(state.currentItem);
  const sections = useDraftState
    ? getStructuredSections()
    : Object.fromEntries(orderedSections.map((heading) => [heading, getSectionValueFromItem(state.currentItem, heading)]));
  const visibleSections = orderedSections.filter((heading) => Object.hasOwn(sections, heading));
  const previewBadges = renderMetadataBadges(metadata);
  const itemTitle = (metadata && metadata.title) || state.currentItem.title || "";
  const sectionHtml = visibleSections.map((heading) => `
    <section class="preview-section">
      <h2>${escapeHtml(heading)}</h2>
      <div class="preview-markdown">${renderMarkdownToHtml(sections[heading] || "") || '<p class="muted">Empty section.</p>'}</div>
    </section>
  `).join("");

  previewElement.className = "preview-surface preview-reading";
  previewElement.innerHTML = `
    ${itemTitle ? `<h1 class="preview-title">${escapeHtml(itemTitle)}</h1>` : ""}
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
  renderExtraMetadataFields(item);
  renderStructuredSections(item);
  rawTextElement.value = item.rawText || "";
  autosizeStructuredTextareas();
  renderPreview();
  syncMobileNavigation();
}

async function fetchJson(url, options = {}) {
  const isRoadmapEndpoint =
    url.startsWith("/api/workspace")
    || url.startsWith("/api/board")
    || url.startsWith("/api/scope")
    || url.startsWith("/api/items/")
    || url.startsWith("/api/setup/");

  let finalOptions = options;
  // Empty state.repoPath is deliberate single-repo cwd-fallback mode — the server
  // resolves to its own cwd. Don't "fix" this by sending an empty header; do that
  // and any user without #repo= will get a 400 if the server is launched from a
  // directory unrelated to the repo they expect to see.
  if (isRoadmapEndpoint && state.repoPath) {
    const headers = new Headers(options.headers || {});
    headers.set("X-Minimap-Repo", state.repoPath);
    finalOptions = { ...options, headers };
  }

  const response = await fetch(url, finalOptions);
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

function specPathParam(filePath) {
  return encodeURIComponent(filePath || state.spec.selectedPath || "");
}

function normalizeSpecUiPath(filePath) {
  return String(filePath || "").replaceAll("\\", "/").toLowerCase();
}

function sameSpecUiPath(left, right) {
  return normalizeSpecUiPath(left) === normalizeSpecUiPath(right);
}

function headingPathFromInput(value) {
  return String(value || "").split(">").map((part) => part.trim()).filter(Boolean);
}

function sectionHeadingPathFromInput(value) {
  const explicitPath = headingPathFromInput(value);
  if (explicitPath.length !== 1) {
    return explicitPath;
  }

  const normalizedInput = normalizeAnchorWhitespace(explicitPath[0]).toLowerCase();
  const matches = (state.spec.context?.outline || []).filter((heading) => normalizeAnchorWhitespace(heading.title).toLowerCase() === normalizedInput);
  return matches.length === 1 ? matches[0].headingPath : explicitPath;
}

function normalizeAnchorWhitespace(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function buildWhitespaceNormalizedMap(value) {
  const normalized = [];
  const originalIndexes = [];
  let lastWasSpace = true;

  const source = String(value || "");
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (/\s/.test(char)) {
      if (!lastWasSpace) {
        normalized.push(" ");
        originalIndexes.push(index);
        lastWasSpace = true;
      }
      continue;
    }

    normalized.push(char);
    originalIndexes.push(index);
    lastWasSpace = false;
  }

  if (normalized.at(-1) === " ") {
    normalized.pop();
    originalIndexes.pop();
  }

  return {
    text: normalized.join(""),
    originalIndexes,
  };
}

// Like buildWhitespaceNormalizedMap, but also strips inline markdown markers
// that the spec renderer hides (backtick code spans, **bold**, *italic*) so a
// rendered DOM selection like "Both shipped (ClawMem, agentmemory)" can be
// matched back to source markdown that was "Both shipped (`ClawMem`, `agentmemory`)".
//
// Each char in the returned text maps to its origin source offset via
// originalIndexes — for stripped markers (backticks, asterisks) the markers
// themselves are excluded; only inner-span chars survive in the map. Match
// against the same renderer that renderInlineMarkdown uses (only those three
// patterns); other markdown ([](), ![]) is left literal because the renderer
// does not strip them either.
function buildRenderedNormalizedMap(value) {
  const source = String(value || "");
  const normalized = [];
  const originalIndexes = [];
  let lastWasSpace = true;

  const pushChar = (char, sourceIndex) => {
    if (/\s/.test(char)) {
      if (!lastWasSpace) {
        normalized.push(" ");
        originalIndexes.push(sourceIndex);
        lastWasSpace = true;
      }
      return;
    }
    normalized.push(char);
    originalIndexes.push(sourceIndex);
    lastWasSpace = false;
  };

  // Try to detect the start of an inline marker at `index`. Returns the
  // 1-or-2-char marker string if a balanced closer exists later in the
  // source, or "" otherwise. This deliberately mirrors renderInlineMarkdown's
  // greedy-but-non-nested matching; complex markdown (escapes, nesting) is
  // left literal so we never lose chars from the source map.
  const detectMarker = (index) => {
    const ch = source[index];
    const next = source[index + 1];
    if (ch === "`") {
      const close = source.indexOf("`", index + 1);
      // Renderer requires non-empty inner content: `[^`]+`
      if (close > index + 1) return "`";
      return "";
    }
    if (ch === "*" && next === "*") {
      // Match ** ... ** (non-greedy on first ** close)
      const close = source.indexOf("**", index + 2);
      if (close > index + 2) return "**";
      return "";
    }
    if (ch === "*") {
      // Single * for italics — renderer matches /\*([^*]+)\*/ (no nested *).
      // Find the next unescaped single * that is NOT part of **.
      let cursor = index + 1;
      while (cursor < source.length) {
        if (source[cursor] === "*") {
          // Bare star is the closer if it's not the start of **.
          if (source[cursor + 1] !== "*") return "*";
          // ** sequence inside an italic span — bail; renderer wouldn't match.
          return "";
        }
        cursor += 1;
      }
      return "";
    }
    return "";
  };

  let i = 0;
  while (i < source.length) {
    const marker = detectMarker(i);
    if (!marker) {
      pushChar(source[i], i);
      i += 1;
      continue;
    }

    const innerStart = i + marker.length;
    const close = source.indexOf(marker, innerStart);
    if (close === -1 || close === innerStart) {
      // detectMarker promised a closer, but be defensive.
      pushChar(source[i], i);
      i += 1;
      continue;
    }

    // Emit inner chars with their actual source offsets; markers themselves
    // are skipped (they don't appear in the rendered text).
    for (let k = innerStart; k < close; k += 1) {
      pushChar(source[k], k);
    }
    i = close + marker.length;
  }

  if (normalized.at(-1) === " ") {
    normalized.pop();
    originalIndexes.pop();
  }

  return {
    text: normalized.join(""),
    originalIndexes,
  };
}

function sourceQuoteForRenderedSelection(selectionText) {
  const normalizedSelection = normalizeAnchorWhitespace(selectionText);
  if (!normalizedSelection) {
    return "";
  }

  // Try the markdown-aware map first — selections from the rendered DOM lack
  // backticks / ** / * that the source carries, so a literal source lookup
  // would miss. The map walks markers as the renderer does, so the rendered
  // selection lines up with the stripped view.
  const renderedSource = buildRenderedNormalizedMap(state.spec.content);
  let matchIndex = renderedSource.text.indexOf(normalizedSelection);
  let mapped = renderedSource;

  // Fall back to the plain whitespace-normalized map (preserves markers).
  // Matters when the user selects a code-span itself: rendered text contains
  // the inner content, but if the user copied source-form text (with backticks)
  // we still want to find it.
  if (matchIndex === -1) {
    const literalSource = buildWhitespaceNormalizedMap(state.spec.content);
    matchIndex = literalSource.text.indexOf(normalizedSelection);
    mapped = literalSource;
  }

  if (matchIndex === -1) {
    return selectionText.trim();
  }

  const start = mapped.originalIndexes[matchIndex];
  const end = mapped.originalIndexes[matchIndex + normalizedSelection.length - 1] + 1;
  return state.spec.content.slice(start, end).trim();
}

function getSpecSelectionText() {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
    return "";
  }

  const range = selection.getRangeAt(0);
  const container = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE
    ? range.commonAncestorContainer
    : range.commonAncestorContainer.parentElement;
  if (!container || !specFileContentElement.contains(container)) {
    return "";
  }

  return selection.toString().trim();
}

function captureSpecSelectedQuote() {
  const selectedText = getSpecSelectionText();
  state.spec.selectedQuote = selectedText ? sourceQuoteForRenderedSelection(selectedText) : "";
}

function specAnchorSummary(mode, value) {
  if (mode === "global") {
    return "File-level comment";
  }
  if (mode === "section") {
    return value ? `Anchored to section: ${value}` : "Anchored to section";
  }
  if (!value) {
    return "Anchored to selected text";
  }
  const normalized = normalizeVisibleText(value);
  return `Anchored to: ${normalized.length > 96 ? `${normalized.slice(0, 96)}...` : normalized}`;
}

function setSpecCommentAnchorMode(mode) {
  state.spec.commentAnchorMode = SPEC_COMMENT_ANCHOR_MODES.has(mode) ? mode : "global";
  renderSpecCommentAnchorMode();
}

function renderSpecCommentAnchorMode() {
  specCommentAnchorModeButtons.forEach((button) => {
    const active = button.dataset.commentAnchorMode === state.spec.commentAnchorMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });

  const globalMode = state.spec.commentAnchorMode === "global";
  specCommentGlobalInput.checked = globalMode;
  specCommentAnchorInput.closest("label").hidden = globalMode;
  specCommentAnchorSummaryElement.textContent = specAnchorSummary(state.spec.commentAnchorMode, specCommentAnchorInput.value);
  if (globalMode) {
    specCommentAnchorInput.value = "";
    return;
  }

  if (state.spec.commentAnchorMode === "section") {
    specCommentAnchorLabelElement.textContent = "Section";
    specCommentAnchorInput.placeholder = "Heading > Subheading";
    return;
  }

  specCommentAnchorLabelElement.textContent = "Quote";
  specCommentAnchorInput.placeholder = "Exact quote from the file";
}

function setSpecSuggestionAnchorMode(mode) {
  state.spec.suggestionAnchorMode = SPEC_SUGGESTION_ANCHOR_MODES.has(mode) ? mode : "quote";
  renderSpecSuggestionAnchorMode();
}

function renderSpecSuggestionAnchorMode() {
  specSuggestionAnchorModeButtons.forEach((button) => {
    const active = button.dataset.suggestionAnchorMode === state.spec.suggestionAnchorMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });

  if (state.spec.suggestionAnchorMode === "section") {
    specSuggestionAnchorLabelElement.textContent = "Section";
    specSuggestionAnchorInput.placeholder = "Heading > Subheading";
    specSuggestionAnchorSummaryElement.textContent = specAnchorSummary("section", specSuggestionAnchorInput.value);
    return;
  }

  specSuggestionAnchorLabelElement.textContent = "Quote";
  specSuggestionAnchorInput.placeholder = "Exact quote from the file";
  specSuggestionAnchorSummaryElement.textContent = specAnchorSummary("quote", specSuggestionAnchorInput.value);
}

function normalizeVisibleText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

// Mirror of stripMarkdownSyntax in src/sessions.js (kept in sync via the
// tri-tree parity test). Strips inline markdown markers and leading heading
// hashes so a quote captured from a rendered view (no backticks, no `### `)
// still finds its block in the rendered HTML, and vice versa.
function stripMarkdownSyntaxForUi(value) {
  return String(value || "")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/[`*_]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

// Decode literal backslash escapes (\n, \r, \t, \\) in suggestion content.
// Authors — particularly LLMs — sometimes emit `\n` as a two-character
// literal instead of a real newline. Without this the diff body renders the
// `\n` glyphs verbatim, which is unreadable. We decode conservatively: only
// the four common escapes, only when not already a real newline.
function decodeLiteralEscapes(value) {
  if (typeof value !== "string" || value.indexOf("\\") === -1) return String(value || "");
  return value.replace(/\\([nrt\\])/g, (_, ch) => {
    if (ch === "n") return "\n";
    if (ch === "r") return "\r";
    if (ch === "t") return "\t";
    return "\\";
  });
}

function specBlockCandidates() {
  return Array.from(specFileContentElement.querySelectorAll("h1, h2, h3, h4, h5, h6, p, li, pre, th, td"));
}

function quoteForSpecBlock(element) {
  const visibleText = normalizeVisibleText(element?.textContent || "");
  return visibleText ? sourceQuoteForRenderedSelection(visibleText) : "";
}

function hideSpecContextToolbar() {
  specContextToolbarElement.hidden = true;
  specContextToolbarElement.dataset.quote = "";
}

function showSpecContextToolbar(quote, rect) {
  if (!quote || !rect || !state.spec.context) {
    hideSpecContextToolbar();
    return;
  }
  // Position above the selection, centered horizontally on its midpoint.
  // Falls back below the selection if there's no room above.
  const toolbarWidth = 152;
  const toolbarHeight = 32;
  const cx = rect.left + rect.width / 2;
  let left = Math.round(cx - toolbarWidth / 2);
  left = Math.min(Math.max(8, left), window.innerWidth - toolbarWidth - 8);
  let top = Math.round(rect.top - toolbarHeight - 6);
  if (top < 8) {
    top = Math.round(rect.bottom + 6);
  }
  specContextToolbarElement.dataset.quote = quote;
  specContextToolbarElement.style.left = `${left}px`;
  specContextToolbarElement.style.top = `${top}px`;
  specContextToolbarElement.hidden = false;
}

function selectedSpecRangeRect() {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
    return null;
  }
  const range = selection.getRangeAt(0);
  const rect = range.getBoundingClientRect();
  return rect.width || rect.height ? rect : null;
}

function showSpecToolbarForSelection() {
  captureSpecSelectedQuote();
  const rect = selectedSpecRangeRect();
  if (!state.spec.selectedQuote || !rect) {
    return false;
  }
  showSpecContextToolbar(state.spec.selectedQuote, rect);
  return true;
}

function openSpecComposer(kind, quote = "") {
  const cleanQuote = quote.trim();
  if (kind === "suggestion") {
    if (!cleanQuote) {
      setBanner("Select text or use a paragraph action to suggest an edit.", "error");
      return;
    }
    state.spec.selectedQuote = cleanQuote;
    state.spec.commentComposerOpen = false;
    state.spec.suggestionComposerOpen = true;
    specSuggestionAnchorInput.value = cleanQuote;
    setSpecSuggestionAnchorMode("quote");
    showSpecComposerForm("suggestion");
    specSuggestionContentInput.focus();
    return;
  }

  state.spec.selectedQuote = cleanQuote;
  state.spec.suggestionComposerOpen = false;
  state.spec.commentComposerOpen = true;
  if (cleanQuote) {
    specCommentAnchorInput.value = cleanQuote;
    setSpecCommentAnchorMode("quote");
  } else {
    // No selection → anchor to the document's first H1 if available.
    // The legacy `__file` (global) anchor is kept in the schema but no
    // longer surfaced as an authoring choice.
    const firstHeading = specFileContentElement.querySelector("h1, h2, h3");
    const headingText = firstHeading ? normalizeVisibleText(firstHeading.textContent) : "";
    if (headingText) {
      specCommentAnchorInput.value = headingText;
      setSpecCommentAnchorMode("section");
    } else {
      specCommentAnchorInput.value = "";
      setSpecCommentAnchorMode("global");
    }
  }
  showSpecComposerForm("comment");
  specCommentTextInput.focus();
}

// Open the comment composer pre-anchored to a specific block in the spec
// body. Used by the hover-to-add `+` button in the gutter — gives the
// user an obvious way to add a comment without having to first select
// text. Headings get a section anchor (matches what they'd get if they
// typed the heading by hand); paragraphs and list items get a quote
// anchor against the block's visible text.
function openSpecComposerForBlock(block) {
  if (!block) return;
  const tag = (block.tagName || "").toLowerCase();
  // selectedQuote is for live text selection only; the gutter "+" path
  // doesn't need it. Leaving it stale would suppress the hover button
  // on the next mousemove.
  state.spec.selectedQuote = "";
  state.spec.suggestionComposerOpen = false;
  state.spec.commentComposerOpen = true;
  if (tag.startsWith("h") && tag.length === 2) {
    const headingText = normalizeVisibleText(block.textContent);
    specCommentAnchorInput.value = headingText;
    setSpecCommentAnchorMode("section");
  } else {
    const quote = quoteForSpecBlock(block);
    if (quote) {
      specCommentAnchorInput.value = quote;
      setSpecCommentAnchorMode("quote");
    } else {
      specCommentAnchorInput.value = "";
      setSpecCommentAnchorMode("global");
    }
  }
  showSpecComposerForm("comment");
  specCommentTextInput.focus();
}

// Show the (hidden) composer form as a floating panel anchored to the file pane.
// It overlays the spec doc so it doesn't shift layout while open.
function showSpecComposerForm(kind) {
  const form = kind === "suggestion" ? specSuggestionForm : specCommentForm;
  const other = kind === "suggestion" ? specCommentForm : specSuggestionForm;
  if (other) other.hidden = true;
  if (!form) return;
  form.hidden = false;
  // Position the form: center horizontally over the spec body, near the top.
  // (Keep CSS simple: it's `position: fixed` styled below.)
}

function hideSpecComposerForm() {
  if (specCommentForm) specCommentForm.hidden = true;
  if (specSuggestionForm) specSuggestionForm.hidden = true;
  state.spec.commentComposerOpen = false;
  state.spec.suggestionComposerOpen = false;
}

function headingElementForPath(headingPath = []) {
  if (!headingPath.length) {
    return null;
  }

  const headings = Array.from(specFileContentElement.querySelectorAll("h1, h2, h3, h4, h5, h6"));
  const stack = [];

  for (const heading of headings) {
    const level = Number(heading.tagName.slice(1));
    stack.length = level - 1;
    stack[level - 1] = normalizeVisibleText(heading.textContent);
    if (stack.length === headingPath.length && headingPath.every((part, index) => normalizeVisibleText(part) === stack[index])) {
      return heading;
    }
  }

  return null;
}

function blockElementForQuote(quote) {
  const normalizedQuote = normalizeVisibleText(quote);
  if (!normalizedQuote) {
    return null;
  }

  const candidates = specBlockCandidates();
  // 1. literal whitespace-normalized match — fastest and most precise
  const literal = candidates.find((element) => normalizeVisibleText(element.textContent).includes(normalizedQuote));
  if (literal) return literal;

  // 2. markdown-stripped fallback — the quote may include backticks or a
  // `### ` heading prefix that the rendered HTML's textContent doesn't,
  // or vice versa. Stripping both sides catches that drift.
  const strippedQuote = stripMarkdownSyntaxForUi(quote);
  if (!strippedQuote) return null;
  return candidates.find((element) => stripMarkdownSyntaxForUi(element.textContent).includes(strippedQuote)) || null;
}

function clearSpecAnchorHighlight() {
  if (state.spec.anchorHighlightTimer) {
    window.clearTimeout(state.spec.anchorHighlightTimer);
    state.spec.anchorHighlightTimer = null;
  }
  specFileContentElement.querySelectorAll(".is-spec-anchor-highlight").forEach((element) => {
    element.classList.remove("is-spec-anchor-highlight");
  });
}

function clearSpecSuggestionPreview() {
  specFileContentElement.querySelectorAll("[data-spec-diff-preview-id]").forEach((element) => {
    element.remove();
  });
  specFileContentElement.querySelectorAll(".is-spec-suggestion-preview-anchor").forEach((element) => {
    element.classList.remove("is-spec-suggestion-preview-anchor");
  });
}

function scrollSpecTargetIntoView(target) {
  // Find the first scrollable ancestor (the spec-doc grid is the scroll
  // container in the workbench). Falls back to the spec body element if
  // no ancestor is scrollable, and finally to the window.
  const scroller = findScrollableAncestor(target);
  if (!scroller || scroller === document.scrollingElement) {
    // Window-level scroll: only act if the target is fully off-screen.
    const rect = target.getBoundingClientRect();
    const viewportTop = 0;
    const viewportBottom = window.innerHeight;
    if (rect.top >= viewportTop && rect.bottom <= viewportBottom) return;
    target.scrollIntoView({ behavior: "smooth", block: "nearest" });
    return;
  }

  // Container-level scroll: compute the minimum delta needed to bring
  // the target into the visible area, with a small padding so the
  // highlighted text doesn't hug the edge. If the target is already
  // fully visible, do nothing — scrolling on a click that didn't need
  // to scroll loses the reader's place.
  const targetRect = target.getBoundingClientRect();
  const scrollerRect = scroller.getBoundingClientRect();
  const padding = 24;
  const above = targetRect.top - (scrollerRect.top + padding);
  const below = targetRect.bottom - (scrollerRect.bottom - padding);
  let delta = 0;
  if (above < 0) {
    // Target is above the visible area → scroll up just enough.
    delta = above;
  } else if (below > 0) {
    // Target is below → scroll down just enough.
    delta = below;
  } else {
    // Already visible. Don't scroll.
    return;
  }
  scroller.scrollTo({
    top: Math.max(0, scroller.scrollTop + delta),
    behavior: "smooth",
  });
}

function findScrollableAncestor(element) {
  let current = element?.parentElement;
  while (current && current !== document.body) {
    const style = getComputedStyle(current);
    const canScrollY = (style.overflowY === "auto" || style.overflowY === "scroll");
    if (canScrollY && current.scrollHeight > current.clientHeight + 1) return current;
    current = current.parentElement;
  }
  return document.scrollingElement || document.documentElement;
}

function anchorTargetElement(item) {
  const anchor = item?.anchor || {};
  if (anchor.scope === "global") {
    return specFileContentElement.firstElementChild;
  }
  if (anchor.scope === "section") {
    return headingElementForPath(anchor.headingPath || []);
  }
  return blockElementForQuote(anchor.quote);
}

function focusSpecAnchorItem(item, activeKey) {
  if (!item) {
    return;
  }

  state.spec.activeAnchorCommentId = activeKey;
  clearSpecAnchorHighlight();
  renderSpecComments();

  if (item.anchorStatus?.status && item.anchorStatus.status !== "resolved") {
    // The anchor's quote/section is no longer in the file (often after a
    // suggestion was applied that rewrote the anchored text). Tell the
    // user calmly — this is expected, not an error condition.
    setBanner("The anchored text is no longer in the file — nothing to jump to.", "info");
    return;
  }

  const target = anchorTargetElement(item);
  if (!target) {
    setBanner("Could not find the anchored text in the rendered file.", "error");
    return;
  }

  // If the anchored quote has been hidden by a replace/delete diff
  // block (the quote's span gets `.spec-anchor-hidden-by-diff` so the
  // diff visually stands in for it), the literal anchor element can
  // collapse to zero height — pulsing it is invisible. Pulse the
  // adjacent diff block instead so the reader sees what the comment
  // is anchored to.
  const hiddenAnchorSpan = item.anchor?.quote
    ? findInlineQuoteSpan(target, item.anchor.quote)
    : null;
  let pulseTarget = target;
  let pulseAsDiff = false;
  if (hiddenAnchorSpan && hiddenAnchorSpan.classList.contains("spec-anchor-hidden-by-diff")) {
    // The diff block was inserted right after the target paragraph.
    const diff = target.nextElementSibling && target.nextElementSibling.classList?.contains("spec-diff-block")
      ? target.nextElementSibling
      : null;
    if (diff) {
      pulseTarget = diff;
      pulseAsDiff = true;
    }
  }

  // The CSS animation runs for 1.6s and ends transparent, so visually
  // the pulse is already gone by then. Strip the class shortly after
  // so a re-click can re-trigger the animation (animations don't
  // restart while the class is present).
  const pulseClass = pulseAsDiff ? "is-spec-diff-pulse" : "is-spec-anchor-highlight";
  pulseTarget.classList.remove(pulseClass);
  void pulseTarget.offsetWidth;
  pulseTarget.classList.add(pulseClass);
  scrollSpecTargetIntoView(pulseTarget);
  state.spec.anchorHighlightTimer = window.setTimeout(() => {
    pulseTarget.classList.remove(pulseClass);
    state.spec.anchorHighlightTimer = null;
  }, 1700);
  setBanner("");
}

function focusSpecCommentAnchor(commentId) {
  const comment = (state.spec.context?.comments || []).find((candidate) => candidate.id === commentId);
  focusSpecAnchorItem(comment, commentId);
}

// Suggestions point at a *change* in the body, not just a phrase, so
// clicking a suggestion card jumps to its diff block (the +/- visible
// in the body) rather than the bare anchor. The diff block is what the
// reader actually wants to evaluate; the anchor is just where it lives.
// For applied/dismissed suggestions where the diff isn't currently
// rendered (Resolved toggle off), fall back to the original anchor.
function focusSpecSuggestionAnchor(suggestionId) {
  const suggestion = (state.spec.context?.suggestions || []).find((candidate) => candidate.id === suggestionId);
  if (!suggestion) return;
  state.spec.activeAnchorCommentId = `suggestion:${suggestionId}`;
  clearSpecAnchorHighlight();
  renderSpecComments();

  const diff = specFileContentElement.querySelector(
    `[data-spec-diff-suggestion-id="${CSS.escape(suggestionId)}"]`,
  );
  if (diff) {
    scrollSpecTargetIntoView(diff);
    diff.classList.remove("is-spec-diff-pulse");
    void diff.offsetWidth;
    diff.classList.add("is-spec-diff-pulse");
    window.setTimeout(() => diff.classList.remove("is-spec-diff-pulse"), 1500);
    setBanner("");
    return;
  }

  // No diff in the body (resolved suggestion, Resolved toggle off, or
  // orphaned). Fall back to the anchor jump and the regular reasons.
  focusSpecAnchorItem(suggestion, `suggestion:${suggestionId}`);
}

function renderSpecInlineSuggestionPreview(suggestion, preview) {
  clearSpecSuggestionPreview();
  const target = anchorTargetElement(suggestion);
  if (!target) {
    return;
  }

  const previewElement = document.createElement("div");
  previewElement.className = "spec-diff-block is-preview";
  previewElement.dataset.specDiffPreviewId = suggestion.id;
  const beforeHtml = (preview.before || "")
    .split(/\r?\n/)
    .map((line) => `<span class="spec-diff-line del">${escapeHtml(line)}</span>`)
    .join("");
  const afterHtml = (preview.after || "")
    .split(/\r?\n/)
    .map((line) => `<span class="spec-diff-line add">${escapeHtml(line)}</span>`)
    .join("");
  previewElement.innerHTML = `
    <div class="spec-diff-meta">
      <span class="spec-diff-pill is-preview">Preview · ${escapeHtml(suggestion.kind)}</span>
      <span>· not applied</span>
    </div>
    ${beforeHtml}${afterHtml}`;

  target.classList.add("is-spec-suggestion-preview-anchor");
  target.insertAdjacentElement("afterend", previewElement);
  scrollSpecTargetIntoView(previewElement);
  layoutSpecMargin();
}

function formatRelativeTime(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function applyAppMode() {
  const specMode = state.appMode === "spec";
  document.body.dataset.appMode = state.appMode;
  document.body.classList.toggle("is-resizing-spec-margin", state.spec.resizingMargin);
  layoutElement.hidden = specMode;
  specWorkbenchElement.hidden = !specMode;
  specSidebarElement.dataset.collapsed = String(state.spec.filesCollapsed);
  specWorkbenchElement.style.setProperty("--spec-body-frac", String(state.spec.bodyFrac));
  specFilesToggleButton.textContent = state.spec.filesCollapsed ? "›" : "‹";
  specFilesToggleButton.setAttribute("aria-expanded", state.spec.filesCollapsed ? "false" : "true");
  specFilesToggleButton.setAttribute("aria-label", state.spec.filesCollapsed ? "Expand files" : "Collapse files");
  specDocElement.dataset.viewMode = state.spec.viewMode;
  specDocElement.dataset.showComments = String(state.spec.showComments);
  specDocElement.dataset.showSuggestions = String(state.spec.showSuggestions);
  specDocElement.dataset.showResolved = String(state.spec.showResolved);
  syncSpecToolbarChrome();
  roadmapModeButton.classList.toggle("is-active", !specMode);
  specModeButton.classList.toggle("is-active", specMode);
  roadmapModeButton.setAttribute("aria-selected", specMode ? "false" : "true");
  specModeButton.setAttribute("aria-selected", specMode ? "true" : "false");
  roadmapPathElement.hidden = specMode;
  workspaceSummaryElement.hidden = specMode;
  repoNameElement.hidden = specMode;
  // In spec mode, the workbench owns the chrome — keep the topbar quiet so
  // the spec page reads as a real desk tool, not a hero-styled chat product.
  modeEyebrowElement.hidden = specMode;
  modeEyebrowElement.textContent = "";
  modeTitleElement.textContent = specMode ? "Spec sessions" : "Roadmap";
  updateDocumentTitle();
}

// ──────────────────────────────────────────────────────────────────────
// Spec workbench rendering — margin-style layout
//
// The pane has three regions:
//   • Body (left)   — the rendered spec, sitting on a warm "page" surface.
//   • Gutter        — a thin rail with anchor dots + drag handle.
//   • Margin (right)— absolutely-positioned comment & suggestion cards,
//                     each biased toward its anchor's y position with a
//                     downward-only collision pass so they never overlap.
// ──────────────────────────────────────────────────────────────────────

// ── Participants facepile ───────────────────────────────────────────────
// A Google-Docs-style stacked-circle indicator over the comments column.
// Surfaces who has touched this spec — comment / reply / suggestion authors
// across all four kinds — plus the current viewer (whatever is in the actor
// input, defaulting to "human"). The viewer is always present, even before
// they comment, because looking at the doc IS a form of presence.

const FACEPILE_COLORS = [
  // Distinct, accessible-on-light backgrounds. Hash-stable per actor name.
  "#1f6feb", "#cf222e", "#2da44e", "#9333ea", "#bf8700",
  "#0969da", "#a40e26", "#1a7f37", "#6639ba", "#7d4900",
];

function colorForActor(name) {
  // Simple deterministic hash → palette index. Same name always gets the
  // same color across sessions and across views.
  const str = String(name || "");
  let hash = 0;
  for (let i = 0; i < str.length; i += 1) {
    hash = (hash * 31 + str.charCodeAt(i)) | 0;
  }
  return FACEPILE_COLORS[Math.abs(hash) % FACEPILE_COLORS.length];
}

function initialsForActor(name) {
  const cleaned = String(name || "").trim();
  if (!cleaned) return "?";
  // Split on non-letter/digit; take first letter of up to 2 segments.
  const parts = cleaned.split(/[^A-Za-z0-9]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function currentSpecActor() {
  const value = (specCommentByInput?.value || "").trim();
  return value || "human";
}

function collectSpecParticipants() {
  // Returns [{ name, count, isViewer }] sorted by count desc, name asc.
  // The viewer is always present (with isViewer:true). If the viewer has
  // also authored content, their count includes it.
  const counts = new Map();
  const ctx = state.spec?.context;
  const bump = (name) => {
    const key = String(name || "").trim();
    if (!key) return;
    counts.set(key, (counts.get(key) || 0) + 1);
  };
  for (const comment of (ctx?.comments || [])) {
    bump(comment.by);
    for (const reply of (comment.replies || [])) bump(reply.by);
  }
  for (const suggestion of (ctx?.suggestions || [])) {
    bump(suggestion.by);
    for (const reply of (suggestion.replies || [])) bump(reply.by);
  }

  const viewer = currentSpecActor();
  if (!counts.has(viewer)) {
    counts.set(viewer, 0);
  }

  return Array.from(counts.entries())
    .map(([name, count]) => ({ name, count, isViewer: name === viewer }))
    .sort((left, right) => {
      // Viewer first, then by action count desc, then by name asc — gives a
      // stable order that puts "you" front-and-center but doesn't lie about
      // counts.
      if (left.isViewer && !right.isViewer) return -1;
      if (right.isViewer && !left.isViewer) return 1;
      if (left.count !== right.count) return right.count - left.count;
      return left.name.localeCompare(right.name);
    });
}

function renderSpecParticipantsFacepile() {
  if (!specParticipantsFacepile) return;
  // Hide entirely when there is no spec session loaded.
  if (!state.spec?.context && !state.spec?.selectedPath) {
    specParticipantsFacepile.hidden = true;
    return;
  }
  specParticipantsFacepile.hidden = false;

  const participants = collectSpecParticipants();
  const total = participants.length;
  const visible = participants.slice(0, 3);
  const overflow = Math.max(0, total - visible.length);

  const circlesHtml = visible.map((p) => `
    <span class="spec-facepile-circle${p.isViewer ? " is-viewer" : ""}"
          style="background:${escapeHtml(colorForActor(p.name))}"
          title="${escapeHtml(p.name)}${p.isViewer ? " (you)" : ""}"
    >${escapeHtml(initialsForActor(p.name))}</span>
  `).join("");
  specParticipantsFacepile.querySelector(".spec-facepile-circles").innerHTML = circlesHtml;

  const overflowEl = specParticipantsFacepile.querySelector(".spec-facepile-overflow");
  if (overflow > 0) {
    overflowEl.textContent = `+${overflow}`;
    overflowEl.hidden = false;
  } else {
    overflowEl.hidden = true;
  }

  const label = specParticipantsFacepile.querySelector("[data-spec-participants-label]");
  if (label) {
    label.textContent = total === 1 ? "1 participant" : `${total} participants`;
  }

  // If the popover is open, refresh its contents in place so updates flow
  // through (e.g. a comment arrives while the popover is open).
  if (specParticipantsPopover && !specParticipantsPopover.hidden) {
    renderSpecParticipantsPopover(participants);
  }
}

function renderSpecParticipantsPopover(participants = collectSpecParticipants()) {
  if (!specParticipantsPopover) return;
  const itemsHtml = participants.map((p) => {
    const meta = p.isViewer
      ? (p.count > 0 ? `${p.count} action${p.count === 1 ? "" : "s"} · you` : "viewing")
      : `${p.count} action${p.count === 1 ? "" : "s"}`;
    return `
      <li class="spec-popover-item${p.isViewer ? " is-viewer" : ""}">
        <span class="spec-facepile-circle"
              style="background:${escapeHtml(colorForActor(p.name))}"
              aria-hidden="true"
        >${escapeHtml(initialsForActor(p.name))}</span>
        <span class="spec-popover-name">${escapeHtml(p.name)}</span>
        <span class="spec-popover-meta">${escapeHtml(meta)}</span>
      </li>
    `;
  }).join("");
  specParticipantsPopover.innerHTML = `
    <div class="spec-popover-head">Participants <span class="spec-popover-count">${participants.length}</span></div>
    <ul class="spec-popover-list" role="list">${itemsHtml}</ul>
  `;
}

function toggleSpecParticipantsPopover(forceState) {
  if (!specParticipantsFacepile || !specParticipantsPopover) return;
  const willOpen = typeof forceState === "boolean"
    ? forceState
    : specParticipantsPopover.hidden;
  if (willOpen) {
    renderSpecParticipantsPopover();
    specParticipantsPopover.hidden = false;
    specParticipantsFacepile.setAttribute("aria-expanded", "true");
  } else {
    specParticipantsPopover.hidden = true;
    specParticipantsFacepile.setAttribute("aria-expanded", "false");
  }
}

function syncSpecToolbarChrome() {
  const ctx = state.spec.context;
  const comments = ctx?.comments || [];
  const suggestions = ctx?.suggestions || [];
  const totalC = comments.length;
  const totalS = suggestions.length;
  document.querySelectorAll('[data-spec-count="comments"]').forEach((el) => { el.textContent = totalC; });
  document.querySelectorAll('[data-spec-count="suggestions"]').forEach((el) => { el.textContent = totalS; });
  renderSpecParticipantsFacepile();
  specViewSegButtons.forEach((btn) => {
    const active = btn.dataset.specView === state.spec.viewMode;
    btn.classList.toggle("is-on", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  // The layer / Resolved toggles only mean something in Review mode.
  // Disable them in Read mode so the user doesn't poke them and watch
  // nothing happen (or worse, briefly something happens that contradicts
  // "Read = pure spec").
  const isReview = state.spec.viewMode === "review";
  specLayerSegButtons.forEach((btn) => {
    const layer = btn.dataset.specLayer;
    const active = layer === "comments" ? state.spec.showComments : state.spec.showSuggestions;
    btn.classList.toggle("is-on", active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
    btn.disabled = !isReview;
  });
  if (specResolvedToggleButton) {
    specResolvedToggleButton.classList.toggle("is-on", state.spec.showResolved);
    specResolvedToggleButton.setAttribute("aria-pressed", state.spec.showResolved ? "true" : "false");
    specResolvedToggleButton.disabled = !isReview;
  }
}

function renderSpecSessions() {
  const sessions = state.spec.sessions;
  const search = state.spec.sidebarSearch.trim().toLowerCase();
  const filtered = !search
    ? sessions
    : sessions.filter((s) => (
        (s.title || "").toLowerCase().includes(search)
          || (s.relativePath || "").toLowerCase().includes(search)
          || (s.targetFile || "").toLowerCase().includes(search)
      ));

  if (!filtered.length) {
    specSessionListElement.innerHTML = sessions.length
      ? '<p class="spec-sidebar-empty">No files match this search.</p>'
      : '<p class="spec-sidebar-empty">No attached files yet.</p>';
    return;
  }

  // Group by repo root (or "tmp"/"unfiled" for files without one).
  const groups = new Map();
  for (const session of filtered) {
    const repoRoot = (session.repoRoot || "").trim();
    let groupKey;
    let groupLabel;
    if (repoRoot) {
      groupLabel = repoRoot.split("/").filter(Boolean).pop() || repoRoot;
      groupKey = repoRoot.toLowerCase();
    } else {
      groupKey = "__unfiled";
      groupLabel = "unfiled";
    }
    if (!groups.has(groupKey)) {
      groups.set(groupKey, { label: groupLabel, sessions: [] });
    }
    groups.get(groupKey).sessions.push(session);
  }

  // Sort each group's sessions by lastActiveAt desc.
  const groupArray = Array.from(groups.values());
  groupArray.sort((a, b) => a.label.localeCompare(b.label));
  groupArray.forEach((g) => {
    g.sessions.sort((left, right) => String(right.lastActiveAt || "").localeCompare(String(left.lastActiveAt || "")));
  });

  const html = groupArray.map((group) => {
    const rows = group.sessions.map((session) => {
      const active = sameSpecUiPath(session.targetFile, state.spec.selectedPath);
      const summary = sessionActivitySummary(session);
      const pulseAttr = summary.pulseAttr ? ` data-pulse="${summary.pulseAttr}"` : "";
      return `
        <div class="spec-session-row-wrap${active ? " is-active" : ""}">
          <button class="spec-session-row${active ? " is-active" : ""}" type="button" data-spec-session-path="${escapeHtml(session.targetFile)}"${pulseAttr}>
            <span class="spec-session-icon" aria-hidden="true"></span>
            <span class="spec-session-meta">
              <span class="spec-session-name" title="${escapeHtml(session.title || session.targetFile)}">${escapeHtml(session.title || session.targetFile)}</span>
              <span class="spec-session-sub">
                <span class="spec-session-time">${escapeHtml(formatRelativeTime(session.lastActiveAt))}</span>
                ${summary.pulses}
              </span>
            </span>
          </button>
          <button class="spec-session-remove" type="button" data-spec-session-remove="${escapeHtml(session.targetFile)}" aria-label="Remove session" title="Remove session">×</button>
        </div>`;
    }).join("");
    return `<div class="spec-session-group-label" title="${escapeHtml(group.label)}"><span>${escapeHtml(group.label)}</span></div>${rows}`;
  }).join("");

  specSessionListElement.innerHTML = html;
}

function sessionActivitySummary(session) {
  // Counts come from two sources:
  // - For the currently-loaded session, prefer state.spec.context (live,
  //   reflects local edits before refreshSpecReviewState catches up).
  // - For other sessions, fall back to session.counts which the list
  //   endpoint now precomputes from the JSONL files.
  // The list endpoint can't compute "orphan" without re-resolving each
  // anchor against the file, so orphan counts only show on the active
  // session.
  const isActive = sameSpecUiPath(session.targetFile, state.spec.selectedPath) && state.spec.context;
  let open = 0, pending = 0, orphan = 0;
  if (isActive) {
    open = (state.spec.context.comments || []).filter((c) => c.status !== "resolved").length;
    pending = (state.spec.context.suggestions || []).filter((s) => s.status === "pending" || s.status === "accepted").length;
    orphan = [
      ...(state.spec.context.comments || []),
      ...(state.spec.context.suggestions || []),
    ].filter((item) => item.anchorStatus && item.anchorStatus.status && item.anchorStatus.status !== "resolved").length;
  } else if (session.counts) {
    open = session.counts.openComments || 0;
    pending = session.counts.pendingSuggestions || 0;
  }
  let pulseAttr = "";
  const parts = [];
  if (open) {
    parts.push(`<span class="spec-pulse" title="${open} open comment${open === 1 ? "" : "s"}"><span class="spec-pulse-dot is-open"></span>${open}</span>`);
    pulseAttr = "open";
  }
  if (pending) {
    parts.push(`<span class="spec-pulse" title="${pending} pending suggestion${pending === 1 ? "" : "s"}"><span class="spec-pulse-dot is-pending"></span>${pending}</span>`);
    if (!pulseAttr) pulseAttr = "pending";
  }
  if (orphan) {
    parts.push(`<span class="spec-pulse" title="${orphan} item${orphan === 1 ? "" : "s"} with broken anchors"><span class="spec-pulse-dot is-orphan"></span>${orphan}</span>`);
    pulseAttr = "orphan";
  }
  return { pulses: parts.join(""), pulseAttr };
}

function renderSpecFile() {
  const context = state.spec.context;
  if (state.spec.loadError) {
    const session = state.spec.sessions.find((candidate) => candidate.targetFile === state.spec.selectedPath);
    const missingTarget = state.spec.loadError.code === "target_missing";
    specFileTitleElement.textContent = session?.title || "Missing file";
    specFileSubtitleElement.textContent = session?.relativePath || session?.targetFile || state.spec.selectedPath || "Attached file";
    specFileContentElement.className = "spec-body spec-body-error";
    specFileContentElement.innerHTML = `
      <div class="spec-file-error-card">
        <p class="spec-file-error-kicker">${missingTarget ? "File no longer exists" : "Could not load file"}</p>
        <h2>${escapeHtml(missingTarget ? "This attached file is missing." : "This session could not be loaded.")}</h2>
        <p>${escapeHtml(state.spec.loadError.message || "The file could not be loaded.")}</p>
        <button class="spec-toolbar-button" type="button" data-spec-missing-remove="${escapeHtml(state.spec.selectedPath)}">Remove session</button>
      </div>
    `;
    specMarginElement.innerHTML = "";
    hideSpecContextToolbar();
    return;
  }

  if (!context) {
    specFileTitleElement.textContent = "File";
    specFileSubtitleElement.textContent = "";
    specFileContentElement.className = "spec-body spec-body-empty";
    specFileContentElement.textContent = "Choose or attach a spec session.";
    specMarginElement.innerHTML = "";
    hideSpecContextToolbar();
    return;
  }

  specFileTitleElement.textContent = context.session.title || "File";
  specFileSubtitleElement.textContent = context.session.relativePath || context.session.targetFile;
  specFileContentElement.className = context.session.markdown ? "spec-body spec-body-markdown" : "spec-body spec-body-plain";
  if (context.session.markdown) {
    const frontmatter = parseLeadingFrontmatter(state.spec.content);
    const headerHtml = buildSpecDocHeaderHtml(frontmatter);
    // If the frontmatter has a title, mirror it into the toolbar slot so the
    // tab title and the doc heading agree. Roadmap items reach this branch.
    if (frontmatter && typeof frontmatter.title === "string" && frontmatter.title.trim()) {
      specFileTitleElement.textContent = frontmatter.title.trim();
    }
    specFileContentElement.innerHTML = headerHtml + renderMarkdownToHtml(stripLeadingFrontmatter(state.spec.content));
  } else {
    specFileContentElement.innerHTML = `<pre><code>${escapeHtml(state.spec.content)}</code></pre>`;
  }

  // Wrap quote-anchored ranges so they're hoverable + clickable.
  decorateSpecAnchors();

  state.spec.selectedQuote = "";
  state.spec.activeAnchorCommentId = "";
  clearSpecAnchorHighlight();
  hideSpecContextToolbar();
}

function commentMatchesFilter(comment) {
  // Resolved visibility now comes from showResolved; orphan-and-stale stay visible.
  if (state.spec.showResolved) {
    return true;
  }
  return comment.status !== "resolved";
}

function specCommentTimestamp(comment) {
  return Date.parse(comment.createdAt || "") || 0;
}

function sortedSpecComments(comments) {
  return [...comments].sort((left, right) => specCommentTimestamp(right) - specCommentTimestamp(left));
}

function captureSpecReplyDraft() {
  if (!state.spec.replyComposerCommentId) {
    return;
  }
  const textarea = specMarginElement.querySelector(`.spec-card-reply-form[data-comment-id="${CSS.escape(state.spec.replyComposerCommentId)}"] textarea`);
  if (textarea) {
    state.spec.replyDrafts.set(state.spec.replyComposerCommentId, textarea.value);
  }
}

function focusActiveSpecReplyDraft() {
  if (!state.spec.replyComposerCommentId) {
    return;
  }
  const textarea = specMarginElement.querySelector(`.spec-card-reply-form[data-comment-id="${CSS.escape(state.spec.replyComposerCommentId)}"] textarea`);
  if (textarea) {
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  }
}

function scrollSpecReviewCardIntoView(cardId, type = "comment") {
  const selector = type === "suggestion"
    ? `[data-suggestion-id="${CSS.escape(cardId)}"]`
    : `[data-comment-id="${CSS.escape(cardId)}"]`;
  const card = specMarginElement.querySelector(selector);
  if (!card) {
    return;
  }
  card.scrollIntoView({ behavior: "smooth", block: "center" });
}

// Build a dictionary describing where each comment / suggestion lives in the
// rendered body — used by the margin layout pass to align cards next to text.
// Returns: { byId: Map<id, { el, top }>, idsInOrder: [...] }
function indexSpecAnchors() {
  const map = new Map();
  if (!specFileContentElement) return map;
  const bodyTop = specFileContentElement.getBoundingClientRect().top + specFileContentElement.scrollTop;

  function pushAnchor(id, el) {
    if (!el || map.has(id)) return;
    const r = el.getBoundingClientRect();
    map.set(id, { el, top: r.top - bodyTop + specFileContentElement.scrollTop });
  }

  // File-level pin: top of body.
  pushAnchor("__file", specFileContentElement);

  for (const comment of state.spec.context?.comments || []) {
    const target = anchorTargetElement(comment);
    if (target) pushAnchor(`comment:${comment.id}`, target);
  }
  for (const suggestion of state.spec.context?.suggestions || []) {
    const diffEl = specFileContentElement.querySelector(`[data-spec-diff-suggestion-id="${CSS.escape(suggestion.id)}"]`);
    const target = (diffEl && diffEl.offsetParent !== null) ? diffEl : anchorTargetElement(suggestion);
    if (target) pushAnchor(`suggestion:${suggestion.id}`, target);
  }
  return map;
}

function renderSpecComments() {
  if (!specMarginElement) return;
  const ctx = state.spec.context;
  syncSpecToolbarChrome();

  if (state.spec.loadError) {
    specMarginElement.innerHTML = '<p class="spec-margin-empty">Remove this stale session or restore the missing file to continue reviewing.</p>';
    closeAllComposers();
    return;
  }
  if (!ctx) {
    specMarginElement.innerHTML = '<p class="spec-margin-empty">Choose a spec session to review.</p>';
    closeAllComposers();
    return;
  }

  // Render diff blocks first (they affect layout for suggestions).
  renderSpecDiffBlocks();
  // Then capture any open reply draft, then rebuild the margin DOM.
  captureSpecReplyDraft();

  const comments = (ctx.comments || []).filter(commentMatchesFilter);
  // Active vs. resolved bucket: pending suggestions stay in the active
  // margin; applied/rejected get tucked under the Resolved toggle so the
  // active list focuses on what still needs attention.
  const suggestions = (ctx.suggestions || []).filter((s) => {
    if (s.status === "pending" || s.status === "accepted") return true;
    return state.spec.showResolved;
  });
  const showComments = state.spec.showComments;
  const showSuggestions = state.spec.showSuggestions;

  const items = [];
  if (showComments) {
    for (const comment of sortedSpecComments(comments)) {
      items.push({ kind: "comment", item: comment });
    }
  }
  if (showSuggestions) {
    for (const suggestion of suggestions) {
      items.push({ kind: "suggestion", item: suggestion });
    }
  }

  if (!items.length) {
    specMarginElement.innerHTML = comments.length || suggestions.length
      ? '<p class="spec-margin-empty">No items match the current view.</p>'
      : '<p class="spec-margin-empty">Hover a paragraph and click the + in the gutter to add the first comment.</p>';
    layoutSpecMargin();
    return;
  }

  const html = items.map(({ kind, item }) => {
    return kind === "comment" ? renderMarginCommentCard(item) : renderMarginSuggestionCard(item);
  }).join("");
  specMarginElement.innerHTML = html;
  layoutSpecMargin();
}

function renderMarginCommentCard(comment) {
  const anchor = comment.anchor || {};
  const isFile = anchor.scope === "global";
  const isSection = anchor.scope === "section";
  // "File-level" is a legacy anchor scope no longer offered when authoring;
  // existing comments still render with a quiet "Whole file" label.
  const anchorTag = isFile
    ? "Whole file"
    : isSection
      ? (anchor.headingPath || []).join(" › ")
      : truncate(anchor.quote || "", 64);

  const isResolved = comment.status === "resolved";
  const collapsedResolved = isResolved && !state.spec.expandedResolvedCommentIds.has(comment.id);
  const isActive = state.spec.activeAnchorCommentId === comment.id;

  const replies = (comment.replies || []).map((reply) => `
    <div class="spec-card-reply">
      <span class="spec-card-reply-author ${actorColorClass(reply.by)}">${escapeHtml(formatActorLabel(reply.by))}</span>
      <p>${escapeHtml(reply.text)}</p>
    </div>`).join("");

  const isReplying = state.spec.replyComposerCommentId === comment.id;
  const replyForm = isReplying ? `
    <form class="spec-card-reply-form" data-comment-id="${escapeHtml(comment.id)}">
      <textarea rows="2" placeholder="Reply">${escapeHtml(state.spec.replyDrafts.get(comment.id) || "")}</textarea>
      <div class="spec-card-actions">
        <button class="spec-card-action" type="button" data-comment-action="cancel-reply">Cancel</button>
        <span class="spec-card-actions-spacer"></span>
        <button class="spec-card-action is-primary" type="submit">Send</button>
      </div>
    </form>` : "";

  const orphanWarning = comment.anchorStatus && comment.anchorStatus.status && comment.anchorStatus.status !== "resolved"
    ? `<p class="spec-card-orphan">Anchor ${escapeHtml(comment.anchorStatus.status)}</p>`
    : "";
  const anchorRewritten = comment.anchorRewrittenAt && !orphanWarning
    ? `<p class="spec-card-anchor-rewritten">Anchor updated after edit</p>`
    : "";

  const dataAnchorId = isFile ? "__file" : `comment:${comment.id}`;
  // Note: the schema still carries comment.kind (concern/question/etc.)
  // for backward compatibility, but the UI no longer maps it to color
  // or any other visual treatment. Comments are visually uniform.
  const cls = [
    "spec-margin-card",
    isFile ? "is-global" : "",
    isResolved ? "is-resolved" : "",
    isActive ? "is-active" : "",
    collapsedResolved ? "is-collapsed" : "",
  ].filter(Boolean).join(" ");

  return `
    <article class="${cls}" data-comment-id="${escapeHtml(comment.id)}" data-card-anchor-id="${escapeHtml(dataAnchorId)}" title="Click to jump to anchor">
      <header class="spec-card-head">
        <span class="spec-card-author ${actorColorClass(comment.by)}">${escapeHtml(formatActorLabel(comment.by))}</span>
        <span class="spec-card-anchor-tag${isFile ? " is-file" : ""}">${escapeHtml(anchorTag || "")}</span>
        <span class="spec-card-when">${escapeHtml(formatRelativeTime(comment.createdAt))}</span>
      </header>
      ${collapsedResolved ? `
        <p class="spec-card-text spec-card-collapsed-summary">${escapeHtml(comment.text)}</p>
        <div class="spec-card-actions">
          <button class="spec-card-action" type="button" data-comment-action="toggle-resolved">Show</button>
          <span class="spec-card-actions-spacer"></span>
          <button class="spec-card-action" type="button" data-comment-action="reopen">Reopen</button>
        </div>
      ` : `
        <p class="spec-card-text">${escapeHtml(comment.text)}</p>
        ${replies ? `<div class="spec-card-replies">${replies}</div>` : ""}
        ${orphanWarning}
        ${anchorRewritten}
        ${isReplying ? replyForm : `
          <div class="spec-card-actions">
            <button class="spec-card-action" type="button" data-comment-action="reply">Reply</button>
            <span class="spec-card-actions-spacer"></span>
            <button class="spec-card-action" type="button" data-comment-action="${isResolved ? "reopen" : "resolve"}">${isResolved ? "Reopen" : "Resolve"}</button>
          </div>
        `}
      `}
    </article>`;
}

function renderMarginSuggestionCard(suggestion) {
  const status = suggestion.status;
  const pending = status === "pending";
  const accepted = status === "accepted";
  const applied = status === "applied";
  const rejected = status === "rejected";
  const reviewed = accepted || rejected;
  // The inline diff block in the body IS the preview — there's no separate
  // "Preview" action. Apply / Dismiss / Accept act on the visible diff.
  const canApply = pending || accepted;
  const isActive = state.spec.activeAnchorCommentId === `suggestion:${suggestion.id}`;
  const dataAnchorId = `suggestion:${suggestion.id}`;

  const anchor = suggestion.anchor || {};
  const anchorTag = anchor.scope === "section"
    ? (anchor.headingPath || []).join(" › ")
    : truncate(anchor.quote || "", 64);

  const cls = [
    "spec-margin-card is-suggestion",
    `is-status-${status}`,
    isActive ? "is-active" : "",
    applied ? "is-applied" : "",
  ].filter(Boolean).join(" ");

  const orphanWarning = suggestion.anchorStatus && suggestion.anchorStatus.status && suggestion.anchorStatus.status !== "resolved"
    ? `<p class="spec-card-orphan">Anchor ${escapeHtml(suggestion.anchorStatus.status)}</p>`
    : "";

  const actions = [];
  // Replies are available on every suggestion (pending or terminal) —
  // a comment thread on the change itself is useful at any stage.
  const replyKey = `suggestion:${suggestion.id}`;
  const isReplying = state.spec.replyComposerCommentId === replyKey;
  if (!isReplying) {
    actions.push('<button class="spec-card-action" type="button" data-suggestion-action="reply">Reply</button>');
  }
  if (!applied) {
    if (pending) {
      // Two-action lifecycle: Dismiss removes from review; Apply writes
      // the change to the file. The legacy `accepted` state still exists
      // in the schema but no longer has a UI affordance — pending →
      // applied/rejected is the only path you can take from here.
      actions.push('<button class="spec-card-action is-danger" type="button" data-suggestion-action="reject">Dismiss</button>');
    }
    if (reviewed) {
      actions.push('<button class="spec-card-action" type="button" data-suggestion-action="reopen">Reopen</button>');
    }
    if (canApply) {
      actions.push('<button class="spec-card-action is-primary" type="button" data-suggestion-action="apply">Apply</button>');
    }
  } else {
    // Applied suggestions are normally read-only, but offer a Rollback
    // action that reverts the file change and puts the suggestion back
    // to pending. The server refuses if the file has drifted since
    // apply, so this is safe to expose.
    if (suggestion.kind !== "delete" && suggestion.originalAnchor) {
      actions.push('<button class="spec-card-action" type="button" data-suggestion-action="rollback" title="Revert this change in the file and put the suggestion back to pending">Roll back</button>');
    }
  }

  const rationale = suggestion.rationale
    ? `<div class="spec-card-field">
         <span class="spec-card-field-label">Why</span>
         <p class="spec-card-field-text">${escapeHtml(suggestion.rationale)}</p>
       </div>`
    : "";

  // Suggestion cards no longer carry an explicit "Anchored to" field
  // or a separate "view in body" link. Both are redundant: the diff
  // block in the body IS the change, and clicking anywhere on the
  // suggestion card now scrolls + pulses that diff. Same single
  // affordance the reader's eye expects ("click the card to find what
  // it's about"), but pointing at the change rather than the bare
  // anchor — which is what the reader actually wants to evaluate.

  // Status appears in the kind tag only when it's something the user
  // should notice: "applied" or "rejected" reach a terminal state worth
  // calling out; "pending" is the default and adds no information; the
  // legacy "accepted" status no longer has a UI authoring path.
  const showStatusInTag = status === "applied" || status === "rejected";
  const kindTag = showStatusInTag
    ? `${escapeHtml(suggestion.kind)} · ${escapeHtml(status)}`
    : escapeHtml(suggestion.kind);
  const anchorRewritten = suggestion.anchorRewrittenAt
    ? `<p class="spec-card-anchor-rewritten">Anchor updated after edit</p>`
    : "";

  const replies = (suggestion.replies || []).map((reply) => `
    <div class="spec-card-reply">
      <span class="spec-card-reply-author ${actorColorClass(reply.by)}">${escapeHtml(formatActorLabel(reply.by))}</span>
      <p>${escapeHtml(reply.text)}</p>
    </div>`).join("");
  const replyForm = isReplying ? `
    <form class="spec-card-reply-form" data-suggestion-reply-id="${escapeHtml(suggestion.id)}">
      <textarea rows="2" placeholder="Reply">${escapeHtml(state.spec.replyDrafts.get(replyKey) || "")}</textarea>
      <div class="spec-card-actions">
        <button class="spec-card-action" type="button" data-suggestion-action="cancel-reply">Cancel</button>
        <span class="spec-card-actions-spacer"></span>
        <button class="spec-card-action is-primary" type="submit">Send</button>
      </div>
    </form>` : "";

  return `
    <article class="${cls}" data-suggestion-id="${escapeHtml(suggestion.id)}" data-card-anchor-id="${escapeHtml(dataAnchorId)}" title="Click to view the change in the spec">
      <header class="spec-card-head">
        <span class="spec-card-author ${actorColorClass(suggestion.by)}">${escapeHtml(formatActorLabel(suggestion.by))}</span>
        <span class="spec-card-anchor-tag is-suggestion">${kindTag}</span>
        <span class="spec-card-when">${escapeHtml(formatRelativeTime(suggestion.createdAt))}</span>
      </header>
      ${rationale}
      ${replies ? `<div class="spec-card-replies">${replies}</div>` : ""}
      ${orphanWarning}
      ${anchorRewritten}
      ${replyForm}
      ${actions.length ? `<div class="spec-card-actions">${actions.join("")}</div>` : ""}
    </article>`;
}

function truncate(text, max = 64) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  if (value.length <= max) return value;
  return value.slice(0, max - 1) + "…";
}

// Actor strings have drifted across forms over the project's life:
// the original plan used `human:local` / `ai:claude` / `ai:codex`;
// the CLI reference at one point switched to `claude:local` /
// `codex:local`; new defaults emit short names (`human`, `claude`,
// `codex`).  The display layer normalizes all of these to a short
// label so the card header stays readable.
//
// Rule: strip a trailing `:local` first (so `human:local` collapses
// to `human` rather than to `local` after the kind prefix is
// removed), then strip a leading `human:` or `ai:`, then strip a
// trailing `@host` suffix.  Whatever's left is the label.  Unknown
// shapes pass through unchanged.
function formatActorLabel(by) {
  let value = String(by || "").trim();
  if (!value) return "";
  value = value.replace(/:local$/i, "");
  value = value.replace(/^(human|ai):/i, "");
  value = value.replace(/@.+$/, "");
  return value;
}

// Map a normalized actor label to a CSS class so cards can color the
// author by channel (human / claude / codex) without each card having
// to know the palette.  Anything we don't recognize falls back to the
// neutral `is-other` class, which inherits the default text color.
function actorColorClass(by) {
  const label = formatActorLabel(by).toLowerCase();
  if (!label) return "is-other";
  if (label === "human") return "is-human";
  if (label === "claude") return "is-claude";
  if (label === "codex") return "is-codex";
  return "is-other";
}

function closeAllComposers() {
  if (specCommentForm) specCommentForm.hidden = true;
  if (specSuggestionForm) specSuggestionForm.hidden = true;
}

// Render the inline diff blocks for visible suggestions.  When the
// suggestions layer is off, we strip them.  Each diff block carries a
// data-spec-diff-suggestion-id so renderSpecComments can find them as
// anchor targets. We only remove blocks that are tied to a suggestion;
// preview-only blocks (data-spec-diff-preview-id) are left alone.
function renderSpecDiffBlocks() {
  if (!specFileContentElement) return;
  // Remove only suggestion-tied diff blocks. Preview blocks survive.
  specFileContentElement.querySelectorAll(".spec-diff-block[data-spec-diff-suggestion-id]").forEach((el) => el.remove());
  // And clear any "anchor hidden because diff is showing" state.
  specFileContentElement.querySelectorAll(".spec-anchor-hidden-by-diff").forEach((el) => {
    el.classList.remove("spec-anchor-hidden-by-diff");
  });

  // Read mode shows the pure spec — no diffs, no anchor decorations. Bail
  // before reinserting, otherwise the periodic refresh would silently add
  // diffs back into a Read-mode body a few seconds after the user switched.
  if (state.spec.viewMode !== "review") return;
  if (!state.spec.showSuggestions) return;

  for (const suggestion of state.spec.context?.suggestions || []) {
    // Resolved suggestions (applied / rejected) only show their inline
    // diff when the user explicitly opts in via the Resolved toggle.
    if ((suggestion.status === "rejected" || suggestion.status === "applied") && !state.spec.showResolved) continue;
    insertSpecDiffBlock(suggestion);
  }
}

function insertSpecDiffBlock(suggestion) {
  const target = anchorTargetElement(suggestion);
  if (!target) return;
  const block = document.createElement("div");
  block.className = `spec-diff-block is-status-${suggestion.status}`;
  block.dataset.specDiffSuggestionId = suggestion.id;

  const beforeText = suggestion.anchor?.quote
    || (suggestion.anchor?.scope === "section" ? `# ${(suggestion.anchor.headingPath || []).join(" > ")}` : "");
  // Some suggestion authors (LLMs especially) write a literal `\n` instead of
  // a real newline. Decode common backslash escapes before splitting so the
  // diff renders as line content, not as `\n` glyphs in the body. Trim
  // leading/trailing blank lines for a tighter diff visual; the stored
  // content is unchanged.
  const afterTextRaw = suggestion.kind === "delete" ? "" : (suggestion.content || "");
  const afterText = decodeLiteralEscapes(afterTextRaw).replace(/^[\r\n]+|[\r\n]+$/g, "");

  // Pick `before` / `after` lines for the diff body. For replace+delete the
  // before line is the anchored quote; for insert_after we only show the
  // added lines, with a dim header indicating where they go.
  const beforeHtml = (suggestion.kind === "insert_after" || !beforeText)
    ? ""
    : beforeText.split(/\r?\n/).map((line) => `<span class="spec-diff-line del">${escapeHtml(line)}</span>`).join("");
  const afterHtml = afterText
    ? afterText.split(/\r?\n/).map((line) => `<span class="spec-diff-line add">${escapeHtml(line)}</span>`).join("")
    : "";

  block.innerHTML = `
    <div class="spec-diff-meta">
      <span class="spec-diff-pill is-${escapeHtml(suggestion.kind)}">${escapeHtml(suggestion.kind)}</span>
      <span>· <span class="${actorColorClass(suggestion.by)}">${escapeHtml(formatActorLabel(suggestion.by))}</span></span>
      <span class="spec-diff-meta-spacer"></span>
      <span class="spec-diff-status is-${escapeHtml(suggestion.status)}">${escapeHtml(suggestion.status)}</span>
    </div>
    ${beforeHtml}${afterHtml}`;

  // For replace and delete we want the anchored quote span itself to be
  // hidden so the diff visually replaces it. For insert_after we just sit
  // below the anchor.
  if ((suggestion.kind === "replace" || suggestion.kind === "delete") && suggestion.anchor?.quote) {
    // Try to hide a sub-element matching the quote inside the target.
    const span = findInlineQuoteSpan(target, suggestion.anchor.quote);
    if (span) {
      span.classList.add("spec-anchor-hidden-by-diff");
      // Insert the diff AFTER the target block, not inside it. Putting a
      // <div> directly inside a <p> is invalid HTML (browsers auto-fix
      // by closing the <p> early, which collapses the visible block to
      // zero height) and breaks click-to-jump on comments anchored to
      // the same quote — the pulse would land on a hidden span.
      target.insertAdjacentElement("afterend", block);
      return;
    }
  }

  target.insertAdjacentElement("afterend", block);
}

function findInlineQuoteSpan(scope, quote) {
  if (!scope || !quote) return null;
  const normalized = normalizeVisibleText(quote);
  // Quote anchors don't pre-wrap text, so we look for a span we may have
  // injected in decorateSpecAnchors.
  return Array.from(scope.querySelectorAll(".spec-anchor-quote")).find((el) => {
    return normalizeVisibleText(el.textContent) === normalized;
  });
}

// Wrap each unique quote-anchored substring in a hoverable span so the
// margin card can highlight it. Only items that would actually appear in
// the active margin get a body-level mark — if the only thing anchored
// to a phrase is hidden (e.g. resolved with the Resolved toggle off),
// the underline is hidden too. The body and the comment pane stay in
// sync: an underline always corresponds to a card you can click.
function decorateSpecAnchors() {
  const ctx = state.spec.context;
  if (!ctx || !specFileContentElement) return;
  // Strip any anchor-quote spans from a previous pass before re-walking.
  // This lets the function be called when toggle state changes without
  // having to rebuild the whole body.
  undecorateSpecAnchors();

  // Read mode shows the spec without any review chrome — no anchor
  // underlines, no diff blocks, no margin cards. Skip decoration so the
  // periodic refresh can't silently re-add underlines a few seconds in.
  if (state.spec.viewMode !== "review") return;

  const visibleComments = (ctx.comments || []).filter(commentMatchesFilter);
  const visibleSuggestions = (ctx.suggestions || []).filter((s) => {
    if (s.status === "pending" || s.status === "accepted") return true;
    return state.spec.showResolved;
  });
  const layerComments = state.spec.showComments ? visibleComments : [];
  const layerSuggestions = state.spec.showSuggestions ? visibleSuggestions : [];

  const quoteAnchors = [...layerComments, ...layerSuggestions]
    .map((item) => item.anchor)
    .filter((a) => a && a.scope === "anchor" && a.quote)
    .map((a) => a.quote);

  // De-duplicate while preserving order.
  const seen = new Set();
  const unique = [];
  for (const q of quoteAnchors) { if (!seen.has(q)) { seen.add(q); unique.push(q); } }

  for (const quote of unique) {
    decorateSpecAnchorQuote(quote);
  }
}

function undecorateSpecAnchors() {
  if (!specFileContentElement) return;
  // Replace each anchor-quote span with its text content, merging
  // adjacent text nodes back together via normalize().
  const spans = specFileContentElement.querySelectorAll(".spec-anchor-quote");
  for (const span of spans) {
    const parent = span.parentNode;
    if (!parent) continue;
    parent.replaceChild(document.createTextNode(span.textContent || ""), span);
    parent.normalize();
  }
}

function decorateSpecAnchorQuote(quote) {
  // Walk text nodes inside the spec body, find the first one that contains
  // the literal quote, and wrap it in a span. We only wrap one occurrence.
  const walker = document.createTreeWalker(specFileContentElement, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (!node.nodeValue) return NodeFilter.FILTER_REJECT;
      // Skip text inside spans we already inserted, or inside diff blocks.
      const parent = node.parentElement;
      if (!parent) return NodeFilter.FILTER_REJECT;
      if (parent.closest(".spec-anchor-quote")) return NodeFilter.FILTER_REJECT;
      if (parent.closest(".spec-diff-block")) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const idx = node.nodeValue.indexOf(quote);
    if (idx === -1) continue;
    const before = node.nodeValue.slice(0, idx);
    const match = node.nodeValue.slice(idx, idx + quote.length);
    const after = node.nodeValue.slice(idx + quote.length);
    const span = document.createElement("span");
    span.className = "spec-anchor-quote";
    span.dataset.specAnchorQuote = "1";
    span.textContent = match;
    const frag = document.createDocumentFragment();
    if (before) frag.appendChild(document.createTextNode(before));
    frag.appendChild(span);
    if (after) frag.appendChild(document.createTextNode(after));
    node.parentNode.replaceChild(frag, node);
    return;
  }
}

// Place each margin card next to its anchor's y position; if cards
// would overlap, slide the lower one down. Also draws gutter dots.
// Orphaned cards (anchor no longer exists in the file) are stacked
// at the bottom so they don't collide with anchored cards.
// The trailing "+ comment" button is placed below the last card.
// Place each margin card next to its anchor's y position; if cards
// would overlap, slide the lower one down. Also draws gutter dots.
// Orphaned cards (anchor no longer exists in the file) are stacked
// at the bottom so they don't collide with anchored cards.
function layoutSpecMargin() {
  if (!specMarginElement || !specGutterElement) return;
  if (state.spec.viewMode !== "review") return;

  const cards = Array.from(specMarginElement.querySelectorAll(".spec-margin-card"));
  const anchors = indexSpecAnchors();

  // Clear gutter dots (the hover-add button is kept; it's not a dot).
  specGutterElement.querySelectorAll(".spec-gutter-dot").forEach((el) => el.remove());

  const placements = [];
  const orphanCards = [];
  for (const card of cards) {
    const anchorId = card.dataset.cardAnchorId;
    if (!anchorId) continue;
    const anchor = anchors.get(anchorId);
    if (!anchor && anchorId !== "__file") {
      // Orphan: anchor in the file is gone (e.g. after applying a suggestion
      // that replaced or deleted the anchored quote). Keep the card visible
      // by stacking it at the bottom of the margin instead of leaving it
      // at the implicit top, where it would overlap the first anchored card.
      orphanCards.push(card);
      continue;
    }
    const desired = anchor ? anchor.top : 0;
    placements.push({ card, desired, anchorId });
  }
  // File-level cards float to the top regardless.
  placements.sort((a, b) => {
    const af = a.anchorId === "__file";
    const bf = b.anchorId === "__file";
    if (af && !bf) return -1;
    if (bf && !af) return 1;
    return a.desired - b.desired;
  });

  let cursor = 0;
  const gap = 10;
  // Track which gutter Y positions already got a dot — multiple cards
  // anchored to the same place in the body (a comment + a suggestion on
  // the same quote, for example) should share a single dot, otherwise
  // duplicates stack invisibly on top of each other and the later cards
  // look anchorless. We treat anchors within 12px of each other as the
  // same group — comments anchor to the source paragraph, suggestions
  // can anchor to the diff block right next to it, and visually they
  // sit at the same gutter level.
  const placedDots = []; // { y, el }
  const sameRowTolerance = 12;
  for (const p of placements) {
    const top = Math.max(p.desired, cursor);
    p.card.style.top = top + "px";
    cursor = top + p.card.offsetHeight + gap;

    if (p.anchorId !== "__file") {
      const isSuggestion = p.card.classList.contains("is-suggestion");
      const isApplied = p.card.classList.contains("is-applied");
      const isActive = p.card.classList.contains("is-active");
      const existing = placedDots.find((d) => Math.abs(d.y - p.desired) <= sameRowTolerance);
      if (existing) {
        // Promote the shared dot's styling to suggestion/applied if any
        // card sharing this anchor is more "actionable" — suggestion
        // outranks comment visually so the dot type matches what's at
        // the anchor.
        if (isSuggestion) existing.el.classList.add("is-suggestion");
        if (isApplied) existing.el.classList.add("is-applied");
        if (isActive) existing.el.classList.add("is-active");
        continue;
      }
      const dot = document.createElement("span");
      dot.className = "spec-gutter-dot" + (isSuggestion ? " is-suggestion" : "") + (isApplied ? " is-applied" : "") + (isActive ? " is-active" : "");
      dot.style.top = p.desired + "px";
      specGutterElement.appendChild(dot);
      placedDots.push({ y: p.desired, el: dot });
    }
  }

  // Orphan cards: stack below the anchored ones, with extra spacing
  // so they read as a separate group. No gutter dots — they have no
  // anchor to point to.
  if (orphanCards.length) {
    cursor += 16;
    for (const card of orphanCards) {
      card.classList.add("is-orphan");
      card.style.top = cursor + "px";
      cursor += card.offsetHeight + gap;
    }
  }
  // Strip the class from any cards that recovered an anchor on this pass.
  for (const p of placements) {
    p.card.classList.remove("is-orphan");
  }
}



async function loadSpecSessions(options = {}) {
  const payload = await fetchJson("/api/spec-sessions");
  state.spec.sessions = payload.sessions || [];
  if (state.spec.selectedPath && !state.spec.sessions.some((session) => sameSpecUiPath(session.targetFile, state.spec.selectedPath))) {
    state.spec.selectedPath = "";
    state.spec.context = null;
    state.spec.content = "";
    state.spec.loadError = null;
  }
  if (!state.spec.selectedPath && state.spec.sessions.length > 0) {
    state.spec.selectedPath = state.spec.sessions[0].targetFile;
  }
  renderSpecSessions();
  applyAppMode();

  if (state.spec.selectedPath && options.loadSelected !== false) {
    await loadSpecSession(state.spec.selectedPath, { clearBanner: options.clearBanner });
  } else {
    renderSpecFile();
    renderSpecComments();
  }
}

async function loadSpecSession(filePath, options = {}) {
  const activeReplyId = state.spec.replyComposerCommentId;
  const shouldRestoreReplyFocus = Boolean(activeReplyId && specMarginElement.contains(document.activeElement));
  captureSpecReplyDraft();
  state.spec.selectedPath = filePath;
  state.spec.loadError = null;
  let context;
  let content;
  try {
    context = await fetchJson(`/api/spec-sessions/by-file/context?path=${specPathParam(filePath)}`);
    content = await fetchJson(`/api/spec-sessions/by-file/content?path=${specPathParam(filePath)}`);
  } catch (error) {
    state.spec.context = null;
    state.spec.content = "";
    state.spec.previewSuggestionId = "";
    state.spec.suggestionPreview = null;
    state.spec.loadError = {
      code: error.code,
      message: error.message,
      statusCode: error.statusCode,
    };
    renderSpecSessions();
    renderSpecFile();
    renderSpecComments();
    syncRouteState({ replace: true });
    if (options.clearBanner !== false) {
      setBanner(error.code === "target_missing" ? "Attached file no longer exists. Remove the session or restore the file." : error.message, "error");
    }
    return;
  }
  state.spec.context = context;
  state.spec.content = content.content || "";
  state.spec.loadError = null;
  state.spec.previewSuggestionId = "";
  state.spec.suggestionPreview = null;
  renderSpecSessions();
  renderSpecFile();
  renderSpecComments();
  if (shouldRestoreReplyFocus) {
    focusActiveSpecReplyDraft();
  }
  if (options.clearBanner !== false) {
    setBanner("");
  }
  syncRouteState({ replace: true });
}

async function removeSpecSession(filePath) {
  if (!filePath) {
    return;
  }

  const session = state.spec.sessions.find((candidate) => sameSpecUiPath(candidate.targetFile, filePath));
  const label = session?.title || filePath;
  if (!window.confirm(`Remove minimap session for ${label}? This does not delete the file.`)) {
    return;
  }

  await fetchJson(`/api/spec-sessions/by-file?path=${specPathParam(filePath)}`, {
    method: "DELETE",
  });

  state.spec.sessions = state.spec.sessions.filter((candidate) => !sameSpecUiPath(candidate.targetFile, filePath));
  if (sameSpecUiPath(state.spec.selectedPath, filePath)) {
    state.spec.selectedPath = state.spec.sessions[0]?.targetFile || "";
    state.spec.context = null;
    state.spec.content = "";
    state.spec.loadError = null;
  }

  await loadSpecSessions({ loadSelected: Boolean(state.spec.selectedPath), clearBanner: false });
  if (!state.spec.selectedPath) {
    renderSpecFile();
    renderSpecComments();
    syncRouteState({ replace: true });
  }
  setBanner("Spec session removed.", "success");
}

async function refreshSpecReviewState() {
  if (!state.spec.selectedPath) {
    return;
  }

  const activeReplyId = state.spec.replyComposerCommentId;
  const shouldRestoreReplyFocus = Boolean(activeReplyId && specMarginElement.contains(document.activeElement));
  captureSpecReplyDraft();

  const context = await fetchJson(`/api/spec-sessions/by-file/context?path=${specPathParam(state.spec.selectedPath)}`);
  state.spec.context = context;
  renderSpecComments();
  syncSpecToolbarChrome();

  if (shouldRestoreReplyFocus) {
    focusActiveSpecReplyDraft();
  }
}

// Build an absolute filesystem path by combining the active repo with a
// repo-relative path. Tolerant of mixed separators because state.repoPath
// can be a Windows path while the relative side comes from server JSON
// (which uses path.relative — also platform-dependent). Server-side
// path.resolve handles either as long as we don't mash a leading "/" into
// a Windows root.
function joinRepoPath(repoPath, relPath) {
  if (!repoPath) return relPath;
  if (!relPath) return repoPath;
  const trimmedRepo = repoPath.replace(/[\\/]+$/, "");
  const trimmedRel = relPath.replace(/^[\\/]+/, "");
  // Use the separator the repo path is already using; default to / for portability.
  const sep = trimmedRepo.includes("\\") ? "\\" : "/";
  return `${trimmedRepo}${sep}${trimmedRel}`;
}

async function openCurrentItemAsSpecSession() {
  const item = state.currentItem;
  if (!item || !item.filePath) {
    setBanner("No item is loaded.", "error");
    return;
  }
  // item.filePath is repo-relative (path.relative(repoRoot, item.filePath) on
  // the server). Build the absolute path so the spec-session attach succeeds
  // regardless of the server's cwd.
  const absolutePath = state.repoPath
    ? joinRepoPath(state.repoPath, item.filePath)
    : item.filePath;
  try {
    await switchAppMode("spec");
    await attachSpecSession(absolutePath);
  } catch (error) {
    setBanner(error.message || "Could not open spec session for this item.", "error");
  }
}

async function attachSpecSession(filePath) {
  const result = await fetchJson("/api/spec-sessions/attach", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file: filePath }),
  });
  state.spec.selectedPath = result.session.targetFile;
  await loadSpecSessions();
  syncRouteState({ replace: true });
  setBanner(result.created ? "Spec session attached." : "Spec session reopened.", "success");
}

async function addSpecComment() {
  if (!state.spec.selectedPath) {
    return;
  }
  const anchorValue = specCommentAnchorInput.value.trim();
  const body = {
    file: state.spec.selectedPath,
    by: specCommentByInput.value,
    kind: specCommentKindInput.value,
    text: specCommentTextInput.value,
  };

  if (state.spec.commentAnchorMode === "global") {
    body.scope = "global";
  } else if (state.spec.commentAnchorMode === "section") {
    body.scope = "section";
    body.headingPath = sectionHeadingPathFromInput(anchorValue);
  } else {
    body.quote = anchorValue;
  }

  await fetchJson("/api/spec-sessions/by-file/comments", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  state.spec.commentComposerOpen = false;
  state.spec.selectedQuote = "";
  setSpecCommentAnchorMode("global");
  specCommentAnchorInput.value = "";
  specCommentTextInput.value = "";
  await refreshSpecReviewState();
  setBanner("Comment added.", "success");
}

async function addSpecSuggestion() {
  if (!state.spec.selectedPath) {
    return;
  }

  const anchorValue = specSuggestionAnchorInput.value.trim();
  const body = {
    file: state.spec.selectedPath,
    by: specSuggestionByInput.value,
    kind: specSuggestionKindInput.value,
    content: specSuggestionContentInput.value,
    rationale: specSuggestionRationaleInput.value,
  };

  if (state.spec.suggestionAnchorMode === "section") {
    body.scope = "section";
    body.headingPath = sectionHeadingPathFromInput(anchorValue);
  } else {
    body.quote = anchorValue;
  }

  await fetchJson("/api/spec-sessions/by-file/suggestions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  state.spec.suggestionComposerOpen = false;
  state.spec.selectedQuote = "";
  setSpecSuggestionAnchorMode("quote");
  specSuggestionAnchorInput.value = "";
  specSuggestionContentInput.value = "";
  specSuggestionRationaleInput.value = "";
  await refreshSpecReviewState();
  setBanner("Suggestion added.", "success");
}

async function replyToSpecComment(commentId, text) {
  await fetchJson(`/api/spec-sessions/by-file/comments/${encodeURIComponent(commentId)}/reply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file: state.spec.selectedPath,
      by: specCommentByInput.value || "human",
      text,
    }),
  });
  state.spec.replyComposerCommentId = "";
  state.spec.replyDrafts.delete(commentId);
  await refreshSpecReviewState();
  scrollSpecReviewCardIntoView(commentId);
  setBanner("Reply added.", "success");
}

async function replyToSpecSuggestion(suggestionId, text) {
  await fetchJson(`/api/spec-sessions/by-file/suggestions/${encodeURIComponent(suggestionId)}/reply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file: state.spec.selectedPath,
      by: specSuggestionByInput.value || specCommentByInput.value || "human",
      text,
    }),
  });
  // We share the reply-composer state with comments — keyed by the
  // suggestion id, prefixed to avoid colliding with a same-id comment.
  const key = `suggestion:${suggestionId}`;
  state.spec.replyComposerCommentId = "";
  state.spec.replyDrafts.delete(key);
  await refreshSpecReviewState();
  setBanner("Reply added.", "success");
}

async function setSpecCommentStatus(commentId, action) {
  await fetchJson(`/api/spec-sessions/by-file/comments/${encodeURIComponent(commentId)}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file: state.spec.selectedPath,
      by: specCommentByInput.value || "human",
    }),
  });
  await refreshSpecReviewState();
  setBanner(action === "resolve" ? "Comment resolved." : "Comment reopened.", "success");
}

async function setSpecSuggestionStatus(suggestionId, action) {
  if (action !== "reopen") {
    state.spec.previewSuggestionId = "";
    state.spec.suggestionPreview = null;
    clearSpecSuggestionPreview();
  }
  await fetchJson(`/api/spec-sessions/by-file/suggestions/${encodeURIComponent(suggestionId)}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file: state.spec.selectedPath,
      by: specSuggestionByInput.value || specCommentByInput.value || "human",
    }),
  });
  await refreshSpecReviewState();
  setBanner(action === "accept" ? "Suggestion accepted." : action === "reopen" ? "Suggestion reopened." : "Suggestion dismissed.", "success");
}

async function previewSpecSuggestion(suggestionId) {
  if (state.spec.previewSuggestionId === suggestionId) {
    state.spec.previewSuggestionId = "";
    state.spec.suggestionPreview = null;
    clearSpecSuggestionPreview();
    renderSpecComments();
    setBanner("Suggestion preview hidden.", "success");
    return;
  }

  const result = await fetchJson(`/api/spec-sessions/by-file/suggestions/${encodeURIComponent(suggestionId)}/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file: state.spec.selectedPath,
    }),
  });
  state.spec.previewSuggestionId = suggestionId;
  state.spec.suggestionPreview = result.preview;
  renderSpecInlineSuggestionPreview(result.suggestion, result.preview);
  renderSpecComments();
  setBanner("Suggestion preview shown in the spec.", "success");
}

async function applySpecSuggestion(suggestionId) {
  await fetchJson(`/api/spec-sessions/by-file/suggestions/${encodeURIComponent(suggestionId)}/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file: state.spec.selectedPath,
      by: specSuggestionByInput.value || specCommentByInput.value || "human",
    }),
  });
  state.spec.previewSuggestionId = "";
  state.spec.suggestionPreview = null;
  clearSpecSuggestionPreview();
  await loadSpecSession(state.spec.selectedPath);
  setBanner("Suggestion applied.", "success");
}

async function rollbackSpecSuggestion(suggestionId) {
  await fetchJson(`/api/spec-sessions/by-file/suggestions/${encodeURIComponent(suggestionId)}/rollback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file: state.spec.selectedPath,
      by: specSuggestionByInput.value || specCommentByInput.value || "human",
    }),
  });
  state.spec.previewSuggestionId = "";
  state.spec.suggestionPreview = null;
  clearSpecSuggestionPreview();
  await loadSpecSession(state.spec.selectedPath);
  setBanner("Suggestion rolled back.", "success");
}

async function switchAppMode(nextMode) {
  state.appMode = nextMode;
  applyAppMode();
  if (nextMode === "spec") {
    try {
      await loadSpecSessions();
      syncRouteState({ replace: true });
    } catch (error) {
      setBanner(error.message, "error");
    }
    return;
  }

  syncWorkspaceChrome();
  syncRouteState({ replace: true });
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
  const repoChanged = route.repo && route.repo !== state.repoPath;
  const exitedSpecMode = state.appMode === "spec" && route.view !== "spec";
  if (route.repo) {
    state.repoPath = route.repo;
  }
  if (route.view === "spec") {
    state.appMode = "spec";
    state.spec.selectedPath = route.specFile || state.spec.selectedPath;
    applyAppMode();
    await loadSpecSessions({ loadSelected: Boolean(state.spec.selectedPath) });
    return;
  }

  state.appMode = "roadmap";
  applyAppMode();
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

  // If the URL points at a different repo than what state currently holds,
  // reload the workspace before reconciling selection. Without this, navigating
  // to a new #repo=... silently keeps showing the previous repo's data.
  // Same applies when leaving spec mode: spec sessions may have changed while
  // the user was in spec mode, so the badge counts in workspace.specSessionsByItemId
  // need a refresh.
  if (repoChanged || exitedSpecMode) {
    await loadWorkspace(route.itemId || "", { syncRoute: false });
    return;
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
    clearTransientBanner();

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
    clearTransientBanner();
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
  if (state.appMode === "spec") {
    void loadSpecSessions();
    return;
  }

  void loadWorkspace(state.selectedItemId, {
    forceReloadItem: Boolean(state.selectedItemId),
    replaceRoute: true,
  });
});

roadmapModeButton.addEventListener("click", () => {
  void switchAppMode("roadmap");
});

specModeButton.addEventListener("click", () => {
  void switchAppMode("spec");
});

specFilesToggleButton.addEventListener("click", () => {
  toggleSpecFilesPanel();
});

specGutterElement.addEventListener("pointerdown", beginSpecMarginResize);
window.addEventListener("pointermove", updateSpecMarginResize);
window.addEventListener("pointerup", endSpecMarginResize);
window.addEventListener("pointercancel", endSpecMarginResize);

// View / layer toggles
specViewSegButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    state.spec.viewMode = btn.dataset.specView === "read" ? "read" : "review";
    applyAppMode();
    if (state.spec.viewMode === "read") {
      // Read mode: pure spec, no review chrome.
      // - strip diff blocks (the periodic refresh is also guarded against
      //   re-inserting them in Read mode now)
      // - drop any "anchor hidden by diff" state so the original text
      //   shows; diff blocks are gone, the user wants the source
      // - drop the anchor underlines
      specFileContentElement.querySelectorAll(".spec-diff-block[data-spec-diff-suggestion-id]").forEach((el) => el.remove());
      specFileContentElement.querySelectorAll(".spec-anchor-hidden-by-diff").forEach((el) => {
        el.classList.remove("spec-anchor-hidden-by-diff");
      });
      undecorateSpecAnchors();
    } else {
      // Review mode: rebuild the underlines first, then renderSpecComments
      // re-inserts the diff blocks and re-marks the matching anchor spans.
      decorateSpecAnchors();
      renderSpecComments();
    }
  });
});

specLayerSegButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const layer = btn.dataset.specLayer;
    if (layer === "comments") state.spec.showComments = !state.spec.showComments;
    if (layer === "suggestions") state.spec.showSuggestions = !state.spec.showSuggestions;
    syncSpecToolbarChrome();
    // Order matters: decorate first so renderSpecComments → renderSpecDiffBlocks
    // can find live anchor spans to mark with .spec-anchor-hidden-by-diff.
    // If we decorated AFTER, the diff-block insertion would mark spans that
    // were then unwrapped by undecorateSpecAnchors, briefly flashing the
    // original sentence into view until the next render.
    decorateSpecAnchors();
    renderSpecComments();
  });
});

if (specResolvedToggleButton) {
  specResolvedToggleButton.addEventListener("click", () => {
    state.spec.showResolved = !state.spec.showResolved;
    syncSpecToolbarChrome();
    decorateSpecAnchors();
    renderSpecComments();
  });
}

if (specSidebarSearchInput) {
  specSidebarSearchInput.addEventListener("input", () => {
    state.spec.sidebarSearch = specSidebarSearchInput.value;
    renderSpecSessions();
  });
}

specCommentCancelButton.addEventListener("click", () => {
  hideSpecComposerForm();
  state.spec.selectedQuote = "";
  specCommentTextInput.value = "";
  specCommentAnchorInput.value = "";
  setSpecCommentAnchorMode("global");
});

// ── Participants facepile interactions ────────────────────────────────
// Click toggles the popover. Document click closes it (except clicks on
// the facepile or inside the popover). Esc closes it. The viewer's actor
// input is live-bound — typing in it updates the facepile in real time so
// they see "themselves" change name as they type.

if (specParticipantsFacepile) {
  specParticipantsFacepile.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleSpecParticipantsPopover();
  });
}

if (specParticipantsPopover) {
  // Clicks inside the popover should not close it (allows future interactive
  // children, e.g. filter-by-participant).
  specParticipantsPopover.addEventListener("click", (event) => {
    event.stopPropagation();
  });
}

document.addEventListener("click", (event) => {
  if (!specParticipantsPopover || specParticipantsPopover.hidden) return;
  if (specParticipantsFacepile?.contains(event.target)) return;
  if (specParticipantsPopover.contains(event.target)) return;
  toggleSpecParticipantsPopover(false);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && specParticipantsPopover && !specParticipantsPopover.hidden) {
    toggleSpecParticipantsPopover(false);
    specParticipantsFacepile?.focus();
  }
});

if (specCommentByInput) {
  specCommentByInput.addEventListener("input", () => {
    renderSpecParticipantsFacepile();
  });
}

specSuggestionCancelButton.addEventListener("click", () => {
  hideSpecComposerForm();
  state.spec.selectedQuote = "";
  specSuggestionAnchorInput.value = "";
  specSuggestionContentInput.value = "";
  specSuggestionRationaleInput.value = "";
  setSpecSuggestionAnchorMode("quote");
});

specCommentAnchorModeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setSpecCommentAnchorMode(button.dataset.commentAnchorMode);
    if (state.spec.commentAnchorMode === "quote" && state.spec.selectedQuote) {
      specCommentAnchorInput.value = state.spec.selectedQuote;
    }
    if (state.spec.commentAnchorMode !== "global") {
      specCommentAnchorInput.focus();
    }
  });
});

specSuggestionAnchorModeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setSpecSuggestionAnchorMode(button.dataset.suggestionAnchorMode);
    if (state.spec.suggestionAnchorMode === "quote" && state.spec.selectedQuote) {
      specSuggestionAnchorInput.value = state.spec.selectedQuote;
    }
    specSuggestionAnchorInput.focus();
  });
});

specFileContentElement.addEventListener("mouseup", () => {
  if (!showSpecToolbarForSelection()) {
    captureSpecSelectedQuote();
  }
});

specFileContentElement.addEventListener("keyup", () => {
  if (!showSpecToolbarForSelection()) {
    captureSpecSelectedQuote();
  }
});

// When the user deselects (collapsed range, click elsewhere, arrow keys),
// the floating Comment / Suggest toolbar should disappear with the
// selection. Without this it sits there pointing at nothing, with no way
// for the user to dismiss it short of opening a composer.
document.addEventListener("selectionchange", () => {
  if (specContextToolbarElement.hidden) return;
  const selection = window.getSelection();
  if (!selection) return;
  const collapsed = selection.rangeCount === 0 || selection.isCollapsed;
  if (collapsed) {
    state.spec.selectedQuote = "";
    hideSpecContextToolbar();
    return;
  }
  // Selection still alive but moved outside the spec body — hide too.
  const range = selection.getRangeAt(0);
  if (!specFileContentElement.contains(range.commonAncestorContainer)) {
    state.spec.selectedQuote = "";
    hideSpecContextToolbar();
  }
});

// The floating Comment / Suggest toolbar only appears on a real text
// selection. We deliberately do NOT pop it on hover/pointermove — that
// covered the text and felt over-eager. To add a comment without a
// selection, hover any block and click the "+" button that appears in
// the gutter (set up below).
specFileContentElement.addEventListener("mouseleave", (event) => {
  if (event.relatedTarget instanceof Node && specContextToolbarElement.contains(event.relatedTarget)) {
    return;
  }
  if (!state.spec.selectedQuote) {
    hideSpecContextToolbar();
  }
});

// ── Hover-to-add: gutter "+" button ───────────────────────────
// Discoverability: every block in the spec body becomes a comment
// target. On hover, a small "+" appears in the gutter at that block's
// vertical center; clicking opens the composer pre-anchored to the
// block. No selection required, no trailing button cluttering the
// margin, no toolbar following the cursor.
let specGutterAddButton = null;
let specGutterAddBlock = null;
function ensureSpecGutterAddButton() {
  if (specGutterAddButton) return specGutterAddButton;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "spec-gutter-add";
  btn.title = "Add a comment here";
  btn.setAttribute("aria-label", "Add a comment to this paragraph");
  btn.textContent = "+";
  btn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (specGutterAddBlock) openSpecComposerForBlock(specGutterAddBlock);
  });
  specGutterElement.appendChild(btn);
  specGutterAddButton = btn;
  return btn;
}
function hideSpecGutterAddButton() {
  if (!specGutterAddButton) return;
  specGutterAddButton.classList.remove("is-on");
  specGutterAddBlock = null;
}
specFileContentElement.addEventListener("mousemove", (event) => {
  if (state.spec.viewMode !== "review") {
    hideSpecGutterAddButton();
    return;
  }
  if (state.spec.commentComposerOpen || state.spec.suggestionComposerOpen) {
    hideSpecGutterAddButton();
    return;
  }
  // While the user has an active selection, the floating toolbar is the
  // right entry point — don't double up with the gutter button.
  if (state.spec.selectedQuote) {
    hideSpecGutterAddButton();
    return;
  }
  const target = event.target instanceof Element
    ? event.target.closest("h1, h2, h3, h4, h5, h6, p, li, pre, th, td")
    : null;
  if (!target || !specFileContentElement.contains(target) || !normalizeVisibleText(target.textContent)) {
    // The cursor is in body whitespace (padding, between blocks). Don't
    // hide the button — the user might be on their way to it. We hide
    // only on mouseleave from the body+gutter region.
    return;
  }
  const btn = ensureSpecGutterAddButton();
  const blockRect = target.getBoundingClientRect();
  const gutterRect = specGutterElement.getBoundingClientRect();
  const top = (blockRect.top + blockRect.height / 2) - gutterRect.top;
  btn.style.top = `${Math.max(0, top)}px`;
  btn.classList.add("is-on");
  specGutterAddBlock = target;
});
// Hide when the cursor leaves the body — UNLESS it's heading into the
// gutter (where the + button lives). The cursor crosses the body/gutter
// boundary on its way to the button; if we hide on that crossing, the
// user can never reach it. Spare anything inside the gutter, including
// gaps between gutter children before the cursor lands on the button.
specFileContentElement.addEventListener("mouseleave", (event) => {
  const related = event.relatedTarget;
  if (related instanceof Node && specGutterElement.contains(related)) {
    return;
  }
  hideSpecGutterAddButton();
});
// And when the cursor leaves the gutter without re-entering the body — the
// button lives in the gutter, so a cursor that crosses out of both should
// dismiss it.
specGutterElement.addEventListener("mouseleave", (event) => {
  const related = event.relatedTarget;
  if (related instanceof Node && specFileContentElement.contains(related)) {
    return;
  }
  hideSpecGutterAddButton();
});

specContextToolbarElement.addEventListener("click", (event) => {
  const action = event.target instanceof Element ? event.target.closest("[data-spec-context-action]") : null;
  if (!action) {
    return;
  }
  const quote = specContextToolbarElement.dataset.quote || state.spec.selectedQuote;
  hideSpecContextToolbar();
  openSpecComposer(action.dataset.specContextAction === "suggest" ? "suggestion" : "comment", quote);
});

specAttachForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const filePath = specAttachPathInput.value.trim();
  if (!filePath) {
    setBanner("Enter a file path to attach.", "error");
    return;
  }
  void attachSpecSession(filePath).catch((error) => {
    setBanner(error.message, "error");
  });
});

specSessionListElement.addEventListener("click", (event) => {
  const removeButton = event.target instanceof Element ? event.target.closest("[data-spec-session-remove]") : null;
  if (removeButton) {
    event.preventDefault();
    event.stopPropagation();
    void removeSpecSession(removeButton.dataset.specSessionRemove).catch((error) => {
      setBanner(error.message, "error");
    });
    return;
  }

  const target = event.target instanceof Element ? event.target.closest("[data-spec-session-path]") : null;
  if (!target) {
    return;
  }
  void loadSpecSession(target.dataset.specSessionPath).catch((error) => {
    setBanner(error.message, "error");
  });
});

specFileContentElement.addEventListener("click", (event) => {
  const removeButton = event.target instanceof Element ? event.target.closest("[data-spec-missing-remove]") : null;
  if (removeButton) {
    void removeSpecSession(removeButton.dataset.specMissingRemove).catch((error) => {
      setBanner(error.message, "error");
    });
    return;
  }
  // Clicking an anchored phrase in the body activates the first
  // visible card anchored to it. Without this, the underline was a
  // signal you couldn't act on from the body — the only way to
  // navigate from a phrase to its conversation was to scan the margin
  // for the matching card.
  const anchorSpan = event.target instanceof Element ? event.target.closest(".spec-anchor-quote") : null;
  if (!anchorSpan) return;
  const quote = normalizeVisibleText(anchorSpan.textContent || "");
  if (!quote) return;
  const ctx = state.spec.context;
  if (!ctx) return;
  // Look at suggestions first (they're more action-oriented). If an
  // anchored suggestion is currently visible, jump to its diff block;
  // otherwise activate the first comment with that anchor.
  const visibleSuggestions = (ctx.suggestions || []).filter((s) => {
    if (s.status === "pending" || s.status === "accepted") return state.spec.showSuggestions;
    return state.spec.showResolved && state.spec.showSuggestions;
  });
  const suggestion = visibleSuggestions.find((s) => s.anchor?.scope === "anchor" && normalizeVisibleText(s.anchor.quote) === quote);
  if (suggestion) {
    focusSpecSuggestionAnchor(suggestion.id);
    return;
  }
  const visibleComments = state.spec.showComments
    ? (ctx.comments || []).filter(commentMatchesFilter)
    : [];
  const comment = visibleComments.find((c) => c.anchor?.scope === "anchor" && normalizeVisibleText(c.anchor.quote) === quote);
  if (comment) {
    focusSpecCommentAnchor(comment.id);
  }
});

specCommentForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void addSpecComment().catch((error) => {
    setBanner(error.message, "error");
  });
});

specSuggestionForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void addSpecSuggestion().catch((error) => {
    setBanner(error.message, "error");
  });
});

specMarginElement.addEventListener("submit", (event) => {
  const formElement = event.target instanceof HTMLFormElement ? event.target : null;
  if (!formElement?.classList.contains("spec-card-reply-form")) {
    return;
  }
  event.preventDefault();
  const textarea = formElement.querySelector("textarea");
  const text = textarea?.value.trim() || "";
  if (!text) {
    setBanner("Reply text is required.", "error");
    return;
  }
  if (formElement.dataset.suggestionReplyId) {
    void replyToSpecSuggestion(formElement.dataset.suggestionReplyId, text).catch((error) => {
      setBanner(error.message, "error");
    });
    return;
  }
  void replyToSpecComment(formElement.dataset.commentId, text).catch((error) => {
    setBanner(error.message, "error");
  });
});

specMarginElement.addEventListener("input", (event) => {
  const textarea = event.target instanceof HTMLTextAreaElement ? event.target : null;
  const formElement = textarea?.closest(".spec-card-reply-form");
  if (!formElement) return;
  if (formElement.dataset.suggestionReplyId) {
    state.spec.replyDrafts.set(`suggestion:${formElement.dataset.suggestionReplyId}`, textarea.value);
    return;
  }
  if (formElement.dataset.commentId) {
    state.spec.replyDrafts.set(formElement.dataset.commentId, textarea.value);
  }
});

specMarginElement.addEventListener("click", (event) => {
  const marginAction = event.target instanceof Element ? event.target.closest("[data-spec-margin-action]") : null;
  if (marginAction) {
    event.preventDefault();
    if (marginAction.dataset.specMarginAction === "new-comment") {
      openSpecComposer("comment", "");
    }
    return;
  }
  const button = event.target instanceof Element ? event.target.closest("[data-comment-action]") : null;
  const commentCard = event.target instanceof Element ? event.target.closest("[data-comment-id]") : null;
  const replyForm = event.target instanceof Element ? event.target.closest(".spec-card-reply-form") : null;
  const suggestionButton = event.target instanceof Element ? event.target.closest("[data-suggestion-action]") : null;
  const suggestionCard = event.target instanceof Element ? event.target.closest("[data-suggestion-id]") : null;
  if (button || suggestionButton) {
    event.preventDefault();
    event.stopPropagation();
  }
  if (suggestionCard) {
    // If the click is inside the reply form on this card and not on
    // one of our explicit `data-suggestion-action` buttons, leave it
    // alone — the submit handler will pick it up. Otherwise we'd
    // re-render the margin mid-submit and detach the form.
    if (event.target instanceof Element && event.target.closest(".spec-card-reply-form") && !suggestionButton) {
      return;
    }
    if (!suggestionButton) {
      focusSpecSuggestionAnchor(suggestionCard.dataset.suggestionId);
      return;
    }
    if (suggestionButton.dataset.suggestionAction === "apply") {
      void applySpecSuggestion(suggestionCard.dataset.suggestionId).catch((error) => {
        setBanner(error.message, "error");
      });
      return;
    }
    if (suggestionButton.dataset.suggestionAction === "rollback") {
      void rollbackSpecSuggestion(suggestionCard.dataset.suggestionId).catch((error) => {
        setBanner(error.message, "error");
      });
      return;
    }
    if (suggestionButton.dataset.suggestionAction === "view-edit") {
      // The inline diff block in the body is the actual change. Scroll
      // it into view so the reader sees what the card is talking about.
      const diff = specFileContentElement.querySelector(`[data-spec-diff-suggestion-id="${CSS.escape(suggestionCard.dataset.suggestionId)}"]`);
      if (diff) {
        scrollSpecTargetIntoView(diff);
        diff.classList.add("is-spec-diff-pulse");
        window.setTimeout(() => diff.classList.remove("is-spec-diff-pulse"), 1400);
      }
      return;
    }
    if (suggestionButton.dataset.suggestionAction === "reply") {
      state.spec.replyComposerCommentId = `suggestion:${suggestionCard.dataset.suggestionId}`;
      renderSpecComments();
      // Focus the freshly-rendered textarea so the user can type immediately.
      const textarea = specMarginElement.querySelector(`.spec-card-reply-form[data-suggestion-reply-id="${CSS.escape(suggestionCard.dataset.suggestionId)}"] textarea`);
      textarea?.focus();
      return;
    }
    if (suggestionButton.dataset.suggestionAction === "cancel-reply") {
      const key = `suggestion:${suggestionCard.dataset.suggestionId}`;
      state.spec.replyComposerCommentId = "";
      state.spec.replyDrafts.delete(key);
      renderSpecComments();
      return;
    }
    void setSpecSuggestionStatus(suggestionCard.dataset.suggestionId, suggestionButton.dataset.suggestionAction).catch((error) => {
      setBanner(error.message, "error");
    });
    return;
  }

  if (!commentCard) {
    return;
  }

  if (replyForm && !button) {
    return;
  }

  if (!button) {
    focusSpecCommentAnchor(commentCard.dataset.commentId);
    return;
  }

  if (button.dataset.commentAction === "reply") {
    const commentId = commentCard.dataset.commentId;
    state.spec.replyComposerCommentId = commentId;
    renderSpecComments();
    focusActiveSpecReplyDraft();
    return;
  }

  if (button.dataset.commentAction === "cancel-reply") {
    state.spec.replyDrafts.delete(commentCard.dataset.commentId);
    state.spec.replyComposerCommentId = "";
    renderSpecComments();
    return;
  }

  if (button.dataset.commentAction === "toggle-resolved") {
    if (state.spec.expandedResolvedCommentIds.has(commentCard.dataset.commentId)) {
      state.spec.expandedResolvedCommentIds.delete(commentCard.dataset.commentId);
    } else {
      state.spec.expandedResolvedCommentIds.add(commentCard.dataset.commentId);
    }
    renderSpecComments();
    return;
  }

  void setSpecCommentStatus(commentCard.dataset.commentId, button.dataset.commentAction).catch((error) => {
    setBanner(error.message, "error");
  });
});

window.addEventListener("resize", () => {
  layoutSpecMargin();
});

statusBanner.addEventListener("click", (event) => {
  const button = event.target instanceof Element ? event.target.closest(".status-banner-dismiss") : null;
  if (!button) {
    return;
  }
  setBanner("");
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

// Cmd/Ctrl-Enter submits the spec composer from inside any of its inputs.
// Convention shared with GitHub / Slack / Linear for "send this".
function attachComposerShortcuts(form) {
  if (!form) return;
  form.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      if (typeof form.requestSubmit === "function") form.requestSubmit();
      else form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
    }
  });
}
attachComposerShortcuts(specCommentForm);
attachComposerShortcuts(specSuggestionForm);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.editorOverlayOpen && shouldUseEditorOverlay()) {
    closeEditorOverlay();
    return;
  }

  // Spec composer: Escape closes the comment/suggestion floating form.
  // Cmd/Ctrl-Enter inside the form submits it (matches the convention of
  // GitHub/Slack/etc. for sending text).
  if (event.key === "Escape" && (state.spec.commentComposerOpen || state.spec.suggestionComposerOpen)) {
    hideSpecComposerForm();
    state.spec.composerTarget = null;
    state.spec.commentAnchorMode = "global";
    state.spec.suggestionAnchorMode = "quote";
    // Don't leave a stale selectedQuote behind — it would suppress the
    // gutter "+" hover button on the next mousemove.
    state.spec.selectedQuote = "";
    return;
  }

  if (event.key !== "Escape" || !state.lensesExpanded) {
    return;
  }

  state.lensesExpanded = false;
  renderBoardChrome();
});

// Spec composer backdrop click: tapping the dimmed area outside the
// composer dismisses it, matching standard modal behavior.
document.addEventListener("click", (event) => {
  if (!state.spec.commentComposerOpen && !state.spec.suggestionComposerOpen) return;
  const target = event.target;
  if (!(target instanceof Element)) return;
  // If the click is inside either composer, ignore. The backdrop is
  // a `body::before` pseudo-element, so any click that doesn't reach
  // a real composer element is a backdrop click.
  if (target.closest(".spec-composer")) return;
  // Don't close when clicking buttons that just OPENED the composer
  // (the click reaches us before the composer state catches up).
  if (target.closest("[data-spec-margin-action='new-comment']")) return;
  if (target.closest("[data-spec-context-action]")) return;
  if (target.closest(".spec-gutter-add")) return;
  hideSpecComposerForm();
  state.spec.composerTarget = null;
  state.spec.selectedQuote = "";
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

openInSpecButton?.addEventListener("click", () => {
  void openCurrentItemAsSpecSession();
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

window.setInterval(() => {
  if (state.appMode !== "spec" || !state.spec.selectedPath) {
    return;
  }

  void refreshSpecReviewState().catch(() => {
    // Automatic refresh should never interrupt local reading or drafting.
  });
}, SPEC_REVIEW_REFRESH_MS);

resetEditor();
const initialRoute = readRouteState();
state.repoPath = initialRoute.repo || "";
if (state.repoPath && repoNameElement) {
  // Best-effort: extract the trailing path segment as a placeholder.
  // /api/workspace will overwrite with the canonical name when it loads.
  const segments = state.repoPath.replaceAll("\\", "/").split("/").filter(Boolean);
  const placeholderName = segments[segments.length - 1] || "";
  if (placeholderName) {
    repoNameElement.textContent = placeholderName;
    document.title = `Minimap — ${placeholderName}`;
  }
}
state.appMode = initialRoute.view === "spec" ? "spec" : "roadmap";
state.spec.selectedPath = initialRoute.specFile;
applyAppMode();
renderSpecCommentAnchorMode();
state.activeLens = initialRoute.lens;
state.boardLayout = initialRoute.layout;
state.editorMode = initialRoute.mode;
state.searchQuery = initialRoute.query;
state.activeFilters = initialRoute.filters;
state.filtersExpanded = Object.keys(initialRoute.filters).length > 0;
renderScopeChrome();
applyEditorMode();
void loadWorkspace(state.appMode === "spec" ? "" : (initialRoute.itemId || state.selectedItemId), {
  preferredLens: initialRoute.lens,
  preferredLayout: initialRoute.layout,
  preferredMode: initialRoute.mode,
  syncRoute: false,
}).then(() => {
  if (initialRoute.view === "spec") {
    void loadSpecSessions({ loadSelected: Boolean(initialRoute.specFile) });
    return;
  }

  if (initialRoute.itemId || initialRoute.mode !== "preview" || initialRoute.lens !== DEFAULT_LENS_KEY || initialRoute.layout !== DEFAULT_BOARD_LAYOUT || initialRoute.query || Object.keys(initialRoute.filters).length > 0) {
    void applyRouteStateFromLocation();
    return;
  }

  if (state.selectedItemId) {
    syncRouteState({ replace: true });
  }
});







// Test hook — exposes pure helpers for Playwright to verify in-browser
// without driving full UI flows. Kept minimal; only stable helpers go here.
window.__minimapSpec = Object.freeze({
  buildRenderedNormalizedMap,
  buildWhitespaceNormalizedMap,
  sourceQuoteForRenderedSelection: (renderedText, sourceContent) => {
    const previous = state.spec.content;
    state.spec.content = String(sourceContent || "");
    try {
      return sourceQuoteForRenderedSelection(renderedText);
    } finally {
      state.spec.content = previous;
    }
  },
  // Open the comment composer with a given rendered selection text —
  // equivalent to selecting in the doc and clicking the floating toolbar's
  // "Comment", but without depending on toolbar geometry which is flaky to
  // drive in tests.
  openCommentComposerWithSelection: (selectionText) => {
    const sourceQuote = sourceQuoteForRenderedSelection(String(selectionText || ""));
    state.spec.selectedQuote = sourceQuote;
    openSpecComposer("comment", sourceQuote);
  },
});
