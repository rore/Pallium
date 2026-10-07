import { createApi } from "/api.js";
import { renderMarkdownToHtml } from "/markdown.js";
import {
  normalizeFilterValues,
  normalizeFilterMap,
  itemMatchesFilters,
  filterBoardItemIds,
  buildDerivedVisibleGroups,
} from "/filters.js";
import {
  buildWhitespaceNormalizedMap,
  buildRenderedNormalizedMap,
  sourceQuoteForRenderedSelection as specSourceQuoteForRenderedSelection,
  resolveSourceQuoteFromRendered as specResolveSourceQuoteFromRendered,
  nthOccurrence,
  computeLineRange,
  normalizeVisibleText,
  stripMarkdownSyntaxForUi,
  decodeLiteralEscapes,
} from "/spec/anchors.js";
import {
  anchorTargetElement,
  clearSpecAnchorHighlight,
  clearSpecSuggestionPreview,
  scrollSpecTargetIntoView,
  scrollSpecCardIntoView,
  focusSpecAnchorItem,
  renderSpecInlineSuggestionPreview,
  renderSpecParticipantsFacepile,
  renderSpecParticipantsPopover,
  toggleSpecParticipantsPopover,
  renderSpecSessions,
  renderSpecFile,
  captureSpecReplyDraft,
  focusActiveSpecReplyDraft,
  scrollSpecReviewCardIntoView,
  renderSpecComments,
  renderSpecDiffBlocks,
  decorateSpecAnchors,
  undecorateSpecAnchors,
  layoutSpecMargin,
} from "/spec/render.js";
import {
  getSpecSelectionText,
  captureSpecSelectedQuote,
  renderedSelectionOccurrenceIndex,
  specAnchorSummary,
  setSpecCommentAnchorMode,
  renderSpecCommentAnchorMode,
  setSpecSuggestionAnchorMode,
  renderSpecSuggestionAnchorMode,
  specBlockCandidates,
  quoteForSpecBlock,
  hideSpecContextToolbar,
  showSpecContextToolbar,
  showSpecToolbarForSelection,
  openSpecComposer,
  openSpecComposerForBlock,
  showSpecComposerForm,
  hideSpecComposerForm,
  previewSpecSuggestion,
  applySpecSuggestion,
  rollbackSpecSuggestion,
} from "/spec/composer.js";
import { initSpec } from "/spec/index.js";
import { detectSpecFileChange } from "/spec/file-change.js";
import { createState } from "/state.js";
import { projectWorktreeGroups, countDistinctWorktreeFeatures, versionDifferences } from "/worktrees.js";

const FIXED_SECTIONS = ["Summary", "Why", "In Scope", "Out of Scope", "Done When", "Notes"];
const SCOPE_STORAGE_KEY = "roadmap-ui.scope-collapsed";
const SCOPE_WIDTH_STORAGE_KEY = "roadmap-ui.scope-width";
const BOARD_WIDTH_STORAGE_KEY = "roadmap-ui.board-width";
const SPEC_FILES_COLLAPSED_STORAGE_KEY = "spec-sessions.files-collapsed";
// Stored as a fraction of the spec-doc width (e.g. 0.62 = body is 62% of the
// pane, margin gets the rest). Migrated from a legacy pixel-width key on read.
const SPEC_BODY_WIDTH_STORAGE_KEY = "spec-sessions.body-frac";
const LEGACY_SPEC_BODY_WIDTH_STORAGE_KEY = "spec-sessions.body-width";
const DEFAULT_SCOPE_WIDTH = 272;
const MIN_SCOPE_WIDTH = 240;
const MAX_SCOPE_WIDTH = 440;
const DEFAULT_BOARD_WIDTH = 500;
const MIN_BOARD_WIDTH = 320;
const MAX_BOARD_WIDTH = 900;
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

function loadStoredScopePreference() {
  try {
    return window.localStorage.getItem(SCOPE_STORAGE_KEY) === "true";
  } catch {
    return false;
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

function clampBoardWidth(width) {
  return Math.max(MIN_BOARD_WIDTH, Math.min(MAX_BOARD_WIDTH, Math.round(width)));
}

function loadStoredBoardWidth() {
  try {
    const value = Number(window.localStorage.getItem(BOARD_WIDTH_STORAGE_KEY));
    return Number.isFinite(value) && value > 0 ? clampBoardWidth(value) : DEFAULT_BOARD_WIDTH;
  } catch {
    return DEFAULT_BOARD_WIDTH;
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

const stateContainer = createState({
  scopeCollapsed: loadStoredScopePreference(),
  scopeWidth: loadStoredScopeWidth(),
  boardWidth: loadStoredBoardWidth(),
  itemLoadGeneration: 0,
  itemLoadController: null,
  itemParticipantsController: null,
  itemParticipants: null,
  spec: {
    filesCollapsed: loadStoredSpecFilesPreference(),
    bodyFrac: loadStoredSpecBodyFrac(),
  },
});
const state = stateContainer.get();
state.worktreeMode = "this";
state.worktreeData = null;
state.worktreeLoading = false;
state.sourceMenuData = null;
state.workspaceScope = null;
state.workspaceStale = false;
state.selectedSource = null;
state.pinnedSource = null;
state.boundRequired = false;
state.confirmedEditSource = null;
state.preferredVersions = new Map();

const api = createApi({
  getRepo: () => state.repoPath,
  getSource: () => state.worktreeMode === "across" || state.boundRequired
    ? { mode: "across", identity: state.worktreeMode === "across" ? state.selectedSource : state.pinnedSource } : null,
});
let boardParticipantCounts = new Map();
let boardParticipantStatus = "idle";
let boardParticipantPartial = false;
let boardParticipantGeneration = 0;
let boardParticipantController = null;
let boardParticipantIncludeCompleted = null;
let workspaceLoadGeneration = 0;
let sourceInventoryRequest = null;

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
const specTocElement = document.querySelector("#spec-toc");
const specTocListElement = document.querySelector("#spec-toc-list");
const specTocToggleElement = document.querySelector("[data-spec-toc-toggle]");
const specViewSegButtons = Array.from(document.querySelectorAll("[data-spec-view]"));
const specLayerSegButtons = Array.from(document.querySelectorAll("[data-spec-layer]"));
const specResolvedToggleButton = document.querySelector("#spec-resolved-toggle");
const specNavPrevButton = document.querySelector("#spec-nav-prev");
const specNavNextButton = document.querySelector("#spec-nav-next");
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
const boardSourceToggleButton = document.querySelector("#board-source-toggle");
const boardSourceMenuElement = document.querySelector("#board-source-menu");
const boardSourceStatusElement = document.querySelector("#board-source-status");
const boardSourceStatusSummaryElement = document.querySelector("#board-source-status-summary");
const boardSourceStatusDetailsElement = document.querySelector("#board-source-status-details");
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
const boardFocusMilestoneSelect = document.querySelector("#board-focus-milestone");
const boardFocusUnfinishedButton = document.querySelector("#board-focus-unfinished");
const boardFocusInPlayButton = document.querySelector("#board-focus-in-play");
const boardParticipantStatusElement = document.querySelector("#board-participant-status");
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
const boardEditorResizerElement = document.querySelector("#board-editor-resizer");
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
const editorSourceLabelElement = document.querySelector("#editor-source-label");
const editorSourceSummaryElement = document.querySelector("#editor-source-summary");
const editorSourceSelectElement = document.querySelector("#editor-source-select");
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
const itemParticipantsElement = document.querySelector("#item-participants");
const itemParticipantsStatusElement = document.querySelector("#item-participants-status");
const itemParticipantsRefreshButton = document.querySelector("#item-participants-refresh");
const itemParticipantsReferenceElement = document.querySelector("#item-participants-reference");
const itemParticipantsScopeElement = document.querySelector("#item-participants-scope");
const itemParticipantsLocalElement = document.querySelector("#item-participants-local");
const itemParticipantsCopyButton = document.querySelector("#item-participants-copy");
const itemParticipantsListElement = document.querySelector("#item-participants-list");
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

// Wire the spec subsystem in one call. initSpec aggregates wireSpecRender
// and wireSpecComposer so app.js doesn't have to know they're two modules.
// The DOM bag is the union of what each side needs; helpers likewise.
// Function decls referenced here are hoisted within this module, so they're
// safe to capture before they appear physically further down.
initSpec({
  dom: {
    // Render side
    specSessionListElement,
    specFileTitleElement,
    specFileSubtitleElement,
    specFileContentElement,
    specMarginElement,
    specTocElement,
    specTocListElement,
    specTocToggleElement,
    specGutterElement,
    specParticipantsFacepile,
    specParticipantsPopover,
    // Composer side (forms + toolbar)
    specContextToolbarElement,
    specCommentForm,
    specCommentByInput,
    specCommentKindInput,
    specCommentAnchorInput,
    specCommentAnchorLabelElement,
    specCommentAnchorSummaryElement,
    specCommentTextInput,
    specCommentGlobalInput,
    specCommentAnchorModeButtons,
    specSuggestionForm,
    specSuggestionByInput,
    specSuggestionKindInput,
    specSuggestionAnchorInput,
    specSuggestionAnchorLabelElement,
    specSuggestionAnchorSummaryElement,
    specSuggestionContentInput,
    specSuggestionRationaleInput,
    specSuggestionAnchorModeButtons,
  },
  state,
  api,
  helpers: {
    setBanner,
    clearTransientBanner,
    sameSpecUiPath,
    parseLeadingFrontmatter,
    buildSpecDocHeaderHtml,
    stripLeadingFrontmatter,
    hideSpecContextToolbar,
    specBlockCandidates,
    syncSpecToolbarChrome,
    updateSpecNavButtons,
    SPEC_COMMENT_ANCHOR_MODES,
    SPEC_SUGGESTION_ANCHOR_MODES,
    normalizeAnchorWhitespace,
    sourceQuoteForRenderedSelection,
    resolveSourceQuoteFromRendered,
    clearSpecSuggestionPreview,
    renderSpecComments,
    renderSpecInlineSuggestionPreview,
    loadSpecSession,
  },
});

function persistScopePreference() {
  try {
    window.localStorage.setItem(SCOPE_STORAGE_KEY, String(state.scopeCollapsed));
  } catch {
    // Ignore storage failures.
  }
}

function persistScopeWidth() {
  try {
    window.localStorage.setItem(SCOPE_WIDTH_STORAGE_KEY, String(state.scopeWidth));
  } catch {
    // Ignore storage failures.
  }
}

function persistBoardWidth() {
  try {
    window.localStorage.setItem(BOARD_WIDTH_STORAGE_KEY, String(state.boardWidth));
  } catch {
    // Ignore storage failures.
  }
}

function persistSpecFilesPreference() {
  try {
    window.localStorage.setItem(SPEC_FILES_COLLAPSED_STORAGE_KEY, String(state.spec.filesCollapsed));
  } catch {
    // Ignore storage failures.
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

function renderSpecFileChangedBanner() {
  // Sticky warning banner shown when the periodic poll detects that the
  // active spec file's contentHash on disk no longer matches the hash we
  // captured on the last full reload. The banner ships its own "Reload"
  // button that re-runs loadSpecSession (which restamps the hash and
  // clears the flag); the user can also dismiss the toast via the
  // standard ×, in which case the next poll re-renders it.
  if (!state.spec.fileChangedDetected || !state.spec.selectedPath) {
    return false;
  }
  statusBanner.hidden = false;
  statusBanner.dataset.tone = "warning";
  statusBanner.innerHTML = `
    <span class="status-banner-message">This file changed on disk.</span>
    <button class="status-banner-action" type="button" data-spec-action="reload-changed-file">Reload</button>
    <button class="status-banner-dismiss" type="button" aria-label="Dismiss status">&times;</button>
  `;
  return true;
}

function clearTransientBanner() {
  // Clears the status banner unless a sticky condition is active, in which
  // case re-renders the highest-precedence sticky banner. Spec file-changed
  // beats workspace warnings because it requires user action (reload) to
  // restore parity with disk; workspace warnings are informational.
  if (renderSpecFileChangedBanner()) {
    return;
  }
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

function worktreePreferenceKey(repoPath = state.repoPath) {
  return `roadmap-ui.worktree-mode:${String(repoPath || "").toLowerCase()}`;
}

function loadWorktreePreference(repoPath) {
  try { return window.localStorage.getItem(worktreePreferenceKey(repoPath)) === "across" ? "across" : "this"; }
  catch { return "this"; }
}

function saveWorktreePreference() {
  try { window.localStorage.setItem(worktreePreferenceKey(), state.worktreeMode); } catch {}
}

function pinnedSourceKey(repoPath = state.repoPath) {
  return `roadmap-ui.pinned-source:${String(repoPath || "").toLowerCase()}`;
}

function rememberPinnedSource(source) {
  state.pinnedSource = source;
  state.boundRequired = true;
  try { window.sessionStorage.setItem(pinnedSourceKey(source.repoRoot), JSON.stringify(source)); } catch {}
}

function restorePinnedSource(repoPath) {
  try { return JSON.parse(window.sessionStorage.getItem(pinnedSourceKey(repoPath)) || "null"); }
  catch { return null; }
}

function buildCombinedWorkspace(aggregate) {
  const base = aggregate.workspace;
  const boardGroups = projectWorktreeGroups(aggregate, { lens: "board" });
  const items = {};
  for (const group of boardGroups) {
    for (const item of group.items) if (!item.missing) items[item.id] = item;
  }
  return { ...base, boardGroups, items };
}

function renderBoardSourceControl() {
  if (!boardSourceToggleButton) return;
  boardSourceToggleButton.textContent = state.worktreeMode === "across" ? "Across worktrees ▾" : "This checkout ▾";
  const aggregate = state.worktreeData;
  const missing = aggregate?.coverage?.missingBoardRefs || [];
  const groups = state.workspace ? getVisibleBoardGroups() : [];
  const across = state.worktreeMode === "across";
  const total = across ? aggregate?.features?.length || 0 : getBoardItems().filter((item) => !item.missing).length;
  const shown = across ? countDistinctWorktreeFeatures(groups) : getVisibleBoardItemIds().length;
  const partial = Boolean(aggregate?.partial || state.workspaceStale || state.worktreeLoading);
  const partialLabel = aggregate?.provisional ? "Opened checkout only" : "Partial coverage";
  boardSourceStatusElement.hidden = !state.workspace;
  boardSourceStatusSummaryElement.innerHTML = `${escapeHtml(String(shown))}${isSearchActive() ? ` / ${total}` : ""} ${across ? "features" : "items"}${partial ? `<span class="coverage-partial">${escapeHtml(partialLabel)}</span>` : ""}${state.worktreeLoading ? '<span class="coverage-partial" role="status">Loading other worktrees…</span>' : ""}${state.workspaceStale ? '<span class="coverage-partial">Last-known view</span>' : ""}`;
  const placements = groups.reduce((count, group) => count + group.items.filter((item) => !item.missing).length, 0);
  const coverage = across ? `<p>${escapeHtml(String(aggregate?.coverage?.loaded || 0))} roadmap checkouts loaded; ${escapeHtml(String(aggregate?.excluded?.length || 0))} excluded. Feature counts cover loaded local worktrees only.</p><p>${escapeHtml(String(placements))} placements in ${groups.length} groups. A feature can appear in multiple groups when its versions differ.</p>` : `<p>${total} items on this checkout's board. ${escapeHtml(String(shown))} match the current view.</p>`;
  const exclusions = (aggregate?.excluded || []).map((entry) => `<li>${escapeHtml(`${entry.repoRoot}: ${sourceExclusionReason(entry)}`)}</li>`).join("");
  const missingRows = missing.slice(0, 20).map((entry) => `<li>${escapeHtml(`${sourceDisplayName(aggregate, entry.sourceKey)} · ${entry.group} / ${entry.itemId} (missing file)`)}</li>`).join("");
  const sessions = boardParticipantStatus === "ok" ? (boardParticipantPartial ? "Session information has partial coverage." : "Session information is available for the loaded items.") : "Session information is unavailable; status-based matches still apply.";
  const missingNotice = missingRows ? `<p>${missing.length} missing board references:</p><ul>${missingRows}</ul>${missing.length > 20 ? `<p>+${missing.length - 20} more</p>` : ""}` : "";
  boardSourceStatusDetailsElement.innerHTML = coverage
    + (aggregate?.provisional ? `<p>Only the opened checkout is shown. Other worktrees and session information ${state.worktreeLoading ? "are still loading" : "could not be loaded"}; feature totals and In play are incomplete.</p>` : state.worktreeLoading ? "<p>Updating worktrees. The previous board remains available until the refresh finishes.</p>" : "")
    + (state.workspaceStale ? "<p>The refresh failed. These are the last-known results; refresh before relying on coverage.</p>" : "")
    + (exclusions ? "<p>Excluded from the combined board:</p><ul>" + exclusions + "</ul>" : "")
    + missingNotice + `<p>${escapeHtml(sessions)}</p>`;
}

function sourceExclusionReason(entry) {
  if (entry.reason === "workspace-load-failed") return entry.message || "Roadmap workspace could not be loaded";
  return ({ "incompatible-roadmap-config": "Roadmap location differs from the opened checkout",
    "missing-or-unavailable": "Checkout path is missing or unreadable",
    prunable: "Git worktree is prunable", "source-limit": "Checkout limit reached",
    "different-common-git-dir": "Not part of this Git worktree family" })[entry.reason] || entry.reason;
}

function sourceDisplayName(aggregate, sourceKey) {
  const source = aggregate?.sources?.find((candidate) => candidate.sourceKey === sourceKey);
  if (!source) return "Unavailable checkout";
  const branch = source.git.branchRef?.replace(/^refs\/heads\//, "") || source.git.headCommit?.slice(0, 8) || "unknown branch";
  return `${source.label} · ${branch}`;
}

function closeBoardSourceMenu() {
  boardSourceMenuElement.hidden = true;
  boardSourceToggleButton.setAttribute("aria-expanded", "false");
}

function isOpenedSource(source) {
  const normalize = (value) => /^[a-z]:[\\/]/i.test(value || "") ? normalizeSpecUiPath(value) : String(value || "").replaceAll("\\", "/");
  return normalize(source.repoRoot) === normalize(state.repoPath);
}

function renderBoardSourceMenu(inventory) {
  const focusedChoice = boardSourceMenuElement.contains(document.activeElement)
    ? document.activeElement.closest("[data-source-choice]")?.dataset.sourceChoice : null;
  const current = state.worktreeMode;
  const thisSelected = current === "this" ? "true" : "false";
  const acrossSelected = current === "across" ? "true" : "false";
  const sources = inventory?.sources || [];
  const acrossDisabled = inventory && !inventory.loading && sources.length < 2 ? "disabled" : "";
  const choices = [
    `<button type="button" data-source-choice="this" aria-current="${thisSelected}">This checkout<small>${escapeHtml(state.repoPath || "current repo")}</small></button>`,
    `<button type="button" data-source-choice="across" aria-current="${acrossSelected}" ${acrossDisabled}>Across worktrees<small>${sources.length ? `${sources.length} discovered checkouts · roadmaps checked when opened` : "Combine readable local roadmaps"}</small></button>`,
    ...sources.filter((source) => !isOpenedSource(source))
      .map((source) => `<button type="button" data-source-choice="${escapeHtml(source.sourceKey)}">${escapeHtml(sourceDisplayName(inventory, source.sourceKey))}<small>${escapeHtml(source.repoRoot)}</small></button>`),
  ];
  const excluded = (inventory?.excluded || []).map((entry) => `<div class="board-source-badge">Unavailable: ${escapeHtml(`${entry.repoRoot.split(/[\\/]/).filter(Boolean).at(-1) || entry.repoRoot} · ${sourceExclusionReason(entry).slice(0, 160)}`)}</div>`).join("");
  const aggregate = state.worktreeMode === "across" ? state.worktreeData : null;
  const missing = aggregate?.coverage?.missingBoardRefs || [];
  const missingRows = missing.slice(0, 20).map((entry) => {
    return `<li>${escapeHtml(`${sourceDisplayName(aggregate, entry.sourceKey)} · ${entry.group} / ${entry.itemId}`)}</li>`;
  }).join("");
  const missingNotice = missing.length ? `<details class="board-source-missing"><summary>${missing.length} missing board ${missing.length === 1 ? "reference" : "references"}</summary><ul>${missingRows}</ul>${missing.length > 20 ? `<p>+${missing.length - 20} more</p>` : ""}</details>` : "";
  const status = inventory?.error ? "Discovery unavailable · showing last-known choices" : inventory?.loading ? "Checking local checkouts…" : inventory?.partial ? "Partial discovery · some checkouts are unavailable" : inventory?.unavailable ? "Worktree discovery unavailable" : "";
  boardSourceMenuElement.innerHTML = `${choices.join("")}${status ? `<p class="source-menu-status" role="status">${escapeHtml(status)}</p>` : ""}${excluded}${missingNotice}`;
  if (focusedChoice) [...boardSourceMenuElement.querySelectorAll("[data-source-choice]")]
    .find((button) => button.dataset.sourceChoice === focusedChoice)?.focus({ preventScroll: true });
}

async function refreshSourceInventory() {
  const repoPath = state.repoPath;
  const generation = workspaceLoadGeneration;
  if (sourceInventoryRequest?.repoPath === repoPath && sourceInventoryRequest.generation === generation) return sourceInventoryRequest.promise;
  const previous = state.sourceMenuData?.repoPath === repoPath ? state.sourceMenuData : null;
  state.sourceMenuData = { ...previous, repoPath, loading: true };
  renderBoardSourceMenu(state.sourceMenuData);
  const request = { repoPath, generation };
  sourceInventoryRequest = request;
  request.promise = (async () => {
    try {
      const inventory = await api.discoverWorktreeSources();
      if (repoPath !== state.repoPath || generation !== workspaceLoadGeneration) return;
      state.sourceMenuData = { ...inventory, repoPath, loading: false };
    } catch (error) {
      if (repoPath !== state.repoPath || generation !== workspaceLoadGeneration) return;
      state.sourceMenuData = { ...previous, repoPath, loading: false, error: error.message };
    } finally {
      if (sourceInventoryRequest === request) sourceInventoryRequest = null;
      if (repoPath === state.repoPath && generation === workspaceLoadGeneration && !boardSourceMenuElement.hidden) renderBoardSourceMenu(state.sourceMenuData);
    }
  })();
  return request.promise;
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

function applyLensRouteChoice(workspace, route) {
  const available = getAvailableLenses(workspace);
  const requested = String(route.lens || "").trim();
  workspace.warnings = workspace.warnings || [];
  if (route.lensSpecified) {
    workspace.warnings = workspace.warnings.filter((warning) => warning.code !== "unknown_url_lens");
  }

  if (route.lensSpecified && available.some((lens) => lens.key === requested)) {
    state.activeLens = requested;
    state.lensExplicit = true;
    return;
  }

  state.activeLens = normalizeLensKey(workspace.defaultLens, workspace);
  state.lensExplicit = false;
  if (route.lensSpecified) {
    workspace.warnings.push({
      code: "unknown_url_lens",
      lens: requested,
      message: `URL grouping "${requested || "(empty)"}" is unavailable. Showing ${getActiveLensDefinition(workspace)?.label || "Board"} instead.`,
    });
  }
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
  return state.inPlay || Boolean(state.searchQuery) || Object.keys(state.activeFilters).length > 0;
}

function itemMatchesCurrentFilters(itemId, workspace = state.workspace) {
  const item = getBoardItemById(itemId, workspace);
  return itemMatchesFilters(item, { searchQuery: state.searchQuery, activeFilters: state.activeFilters, inPlay: state.inPlay, participantCounts: boardParticipantCounts });
}

function getFilteredBoardItemIds(workspace = state.workspace) {
  if (state.worktreeMode === "across" && state.worktreeData) {
    return getVisibleBoardGroups(workspace).flatMap((group) => group.items.filter((item) => !item.missing).map((item) => item.id));
  }
  return filterBoardItemIds(workspace, { searchQuery: state.searchQuery, activeFilters: state.activeFilters, inPlay: state.inPlay, participantCounts: boardParticipantCounts });
}

function getVisibleBoardGroups(workspace = state.workspace) {
  if (!workspace) {
    return [];
  }
  if (state.worktreeMode === "across" && state.worktreeData) {
    const groups = projectWorktreeGroups(state.worktreeData, {
      lens: getActiveLensDefinition(workspace)?.key || DEFAULT_LENS_KEY,
      searchQuery: state.searchQuery,
      activeFilters: state.activeFilters,
      inPlay: state.inPlay,
      participantCounts: boardParticipantCounts,
      showEmptyGroups: !isSearchActive(),
    }).map((group, index) => ({ ...group, originalIndex: index, isDerived: group.kind === "derived", draggable: false }));
    for (const group of groups) for (const item of group.items) if (!item.missing) workspace.items[item.id] = item;
    return groups;
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

  return buildDerivedVisibleGroups(workspace, activeLens, {
    searchQuery: state.searchQuery,
    activeFilters: state.activeFilters,
    inPlay: state.inPlay,
    participantCounts: boardParticipantCounts,
    defaultLensKey: DEFAULT_LENS_KEY,
    unassignedKey: UNASSIGNED_GROUP_KEY,
    unassignedLabel: UNASSIGNED_GROUP_LABEL,
    showEmptyGroups: !isSearchActive() && Array.isArray(activeLens.values) && activeLens.values.length > 0,
  });
}

function getVisibleBoardItemIds(workspace = state.workspace) {
  return getVisibleBoardGroups(workspace).flatMap((group) => group.items.filter((item) => !item.missing).map((item) => item.id));
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
  if (state.worktreeMode === "across") return false;
  const lens = getActiveLensDefinition(workspace);
  return Boolean(lens && lens.kind === "derived" && lens.draggable && !state.boardEditMode);
}

function canDragItemsInColumnLayout(workspace = state.workspace) {
  if (state.worktreeMode === "across") return false;
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
  if (state.worktreeMode === "across") return false;
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
    if (normalizedValue === "in-progress" || normalizedValue === "active") {
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
  if (normalizedField === "priority" && /^\d+$/.test(String(value))) {
    return `<span class="${classes.join(" ")}" title="Priority ${escapeHtml(value)}">${escapeHtml(`P${value}`)}</span>`;
  }
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
  if (state.worktreeMode === "across" && state.worktreeData) {
    const groups = getVisibleBoardGroups();
    const shown = countDistinctWorktreeFeatures(groups);
    const total = state.worktreeData.features.length;
    const appearances = groups.reduce((count, group) => count + group.items.filter((item) => !item.missing).length, 0);
    workspaceSummaryElement.textContent = `${shown}${isSearchActive() ? ` / ${total}` : ""} features · ${appearances} appearances · ${groups.length} groups`;
    return;
  }
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

function sourceRef(source) {
  return source?.git?.branchRef || source?.git?.headCommit || "";
}

function rememberPreferredVersion(itemId, source) {
  state.preferredVersions.set(itemId, { sourceKey: source.sourceKey, gitRef: sourceRef(source) });
}

function readRouteState() {
  const rawHash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : "";
  const params = new URLSearchParams(rawHash);
  return {
    view: params.get("view") || "roadmap",
    specFile: params.get("file") || "",
    itemId: params.get("item") || "",
    sourceKey: params.get("source") || "",
    sourceRef: params.get("sourceRef") || "",
    mode: normalizeEditorMode(params.get("mode") || "preview"),
    lens: params.get("lens") || "",
    lensSpecified: params.has("lens"),
    layout: normalizeBoardLayout(params.get("layout") || DEFAULT_BOARD_LAYOUT),
    query: normalizeSearchQuery(params.get("q") || ""),
    inPlay: params.get("inPlay") === "1",
    filters: parseRouteFilters(params),
    repo: params.get("repo") || "",
    sources: params.get("sources") || "",
    bound: params.get("bound") === "1",
  };
}

function buildRouteHash(itemId = state.selectedItemId, mode = state.editorMode) {
  const params = new URLSearchParams();

  if (state.repoPath) {
    params.set("repo", state.repoPath);
  }
  if (state.worktreeMode === "across" || state.worktreeModeExplicit) {
    params.set("sources", state.worktreeMode);
  }
  if (state.worktreeMode === "this" && state.boundRequired) params.set("bound", "1");

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
    if (state.worktreeMode === "across" && state.selectedSource) {
      params.set("source", state.selectedSource.sourceKey);
      params.set("sourceRef", sourceRef(state.selectedSource));
    }
  }

  const normalizedMode = normalizeEditorMode(mode);
  if (persistSelectedItem && normalizedMode !== "preview") {
    params.set("mode", normalizedMode);
  }

  const lensKey = state.worktreeData?.provisional && state.lensExplicit ? state.activeLens : normalizeLensKey(state.activeLens);
  if (state.lensExplicit) {
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
  if (state.inPlay) params.set("inPlay", "1");

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
      state.lensExplicit = true;
      state.lensesExpanded = false;
      void syncVisibleSelection({ replaceRoute: true });
    });
  }
}

const FINISHED_STATUSES = new Set(["done", "shipped", "superseded", "cancelled", "canceled"]);

function getBoardFieldValues(field) {
  if (state.worktreeMode === "across" && state.worktreeData) {
    return Array.from(new Set(state.worktreeData.features.flatMap((feature) => feature.versions
      .flatMap((version) => normalizeFilterValues(version.summary.metadata?.[field])))))
      .sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
  }
  return Array.from(new Set(Object.values(state.workspace?.items || {})
    .flatMap((item) => normalizeFilterValues(item.metadata?.[field])))).sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
}

function getUnfinishedStatusValues() {
  return getBoardFieldValues("status").filter((status) => !FINISHED_STATUSES.has(status.toLowerCase()));
}

function isUnfinishedFocused() {
  const values = getUnfinishedStatusValues();
  const selected = state.activeFilters.status || [];
  return selected.length > 0 && (values.length > 0
    ? values.length === selected.length && values.every((value) => selected.includes(value))
    : selected.every((value) => !FINISHED_STATUSES.has(value.toLowerCase())));
}

function boardPresenceIncludesCompleted() {
  const statuses = state.activeFilters.status || [];
  return state.inPlay && (statuses.length === 0 || statuses.some((status) => FINISHED_STATUSES.has(status.trim().toLowerCase())));
}

function boardInPlayResultsIncomplete() {
  if (state.worktreeMode === "across") return state.inPlay && (boardParticipantStatus !== "ok" || boardParticipantPartial);
  return state.inPlay && (boardParticipantStatus !== "ok" || boardParticipantPartial
    || boardParticipantIncludeCompleted !== boardPresenceIncludesCompleted());
}

function renderBoardParticipantStatus() {
  if (!boardParticipantStatusElement) return;
  const status = boardParticipantStatus;
  const incomplete = boardInPlayResultsIncomplete();
  const message = incomplete ? `In play results incomplete: ${status === "loading" || status === "idle" ? "checking attached sessions…"
    : status === "ok" && boardParticipantPartial ? (state.worktreeMode === "across" ? "some checkout associations are ambiguous or outside coverage" : "session counts limited to 200 items")
    : status === "disabled" ? "session lookup disabled"
    : status === "unsupported" ? "session lookup needs a newer Pallium"
    : status === "server-unsupported" ? "completed session lookup needs a newer Minimap"
    : "session lookup unavailable"}`
    : status === "loading" ? "Updating session badges…"
    : status === "ok" && boardParticipantPartial ? (state.worktreeMode === "across" ? "Session badges have partial checkout coverage" : "Session badges limited to 200 items")
    : status === "unsupported" ? "Participant recency needs a newer Pallium"
    : ["disabled", "idle", "ok"].includes(status) ? ""
    : "Session badges unavailable";
  boardParticipantStatusElement.hidden = !message || state.appMode !== "roadmap" || !state.workspace;
  boardParticipantStatusElement.textContent = message;
  boardParticipantStatusElement.title = message;
  boardParticipantStatusElement.classList.toggle("is-incomplete", incomplete);
}

function renderSearchControls() {
  if (!boardSearchInput || !boardViewToggleButton || !boardFilterToggleButton || !boardFiltersElement || !boardClearFiltersButton) {
    return;
  }

  const facets = state.workspace?.availableFilters ?? [];
  const activeFilterKeys = Object.keys(state.activeFilters);
  const activeFilterCount = activeFilterKeys.length;
  const showFilters = facets.length > 0 && state.filtersExpanded;

  const milestones = getBoardFieldValues("milestone");
  const selectedMilestones = state.activeFilters.milestone || [];
  boardFocusMilestoneSelect.innerHTML = `<option value="">All milestones</option>${selectedMilestones.length > 1 ? '<option value="__multiple__">Multiple milestones</option>' : ""}${milestones.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("")}`;
  boardFocusMilestoneSelect.value = selectedMilestones.length > 1 ? "__multiple__" : (selectedMilestones[0] || "");
  boardFocusMilestoneSelect.title = selectedMilestones.length > 1 ? `${selectedMilestones.length} milestones selected` : (selectedMilestones[0] || "All milestones");
  boardFocusMilestoneSelect.disabled = milestones.length === 0 || state.boardEditMode;
  boardFocusUnfinishedButton.disabled = (getUnfinishedStatusValues().length === 0 && !isUnfinishedFocused()) || state.boardEditMode;
  boardFocusUnfinishedButton.setAttribute("aria-pressed", isUnfinishedFocused() ? "true" : "false");
  boardFocusUnfinishedButton.classList.toggle("is-active", isUnfinishedFocused());
  boardFocusInPlayButton.disabled = !state.workspace || state.boardEditMode;
  boardFocusInPlayButton.setAttribute("aria-pressed", state.inPlay ? "true" : "false");
  boardFocusInPlayButton.classList.toggle("is-active", state.inPlay);

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
          <button class="filter-chip${activeValues.has(value) ? " is-active" : ""}" data-filter-key="${escapeHtml(facet.key)}" data-filter-value="${escapeHtml(value)}" type="button" title="${escapeHtml(value)}" ${state.boardEditMode ? "disabled" : ""}>${escapeHtml(value)}</button>
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
  boardEditButton.hidden = setupMode || state.worktreeMode === "across" || state.boardEditMode || !boardLensActive || !listLayoutActive;
  boardSaveButton.hidden = setupMode || !state.boardEditMode;
  boardCancelButton.hidden = setupMode || !state.boardEditMode;
  boardControlsElement.hidden = setupMode;
  boardSaveButton.disabled = !state.boardDirty;
  renderBoardSourceControl();
  renderLayoutControls();
  renderSearchControls();
  renderBoardParticipantStatus();
}

function renderScopeChrome() {
  const setupMode = isSetupMode();
  const showResizer = !setupMode && !state.scopeCollapsed && isDesktopScopeLayout();

  layoutElement.dataset.scopeCollapsed = String(state.scopeCollapsed);
  layoutElement.style.setProperty("--scope-width", `${state.scopeWidth}px`);
  layoutElement.style.setProperty("--board-width", `${state.boardWidth}px`);
  const showBoardResizer = !setupMode && !isColumnsLayoutActive() && isDesktopScopeLayout();
  boardEditorResizerElement.hidden = !showBoardResizer;
  boardEditorResizerElement.setAttribute("aria-valuemin", String(MIN_BOARD_WIDTH));
  boardEditorResizerElement.setAttribute("aria-valuemax", String(MAX_BOARD_WIDTH));
  boardEditorResizerElement.setAttribute("aria-valuenow", String(state.boardWidth));
  scopePanelElement.classList.toggle("scope-collapsed", state.scopeCollapsed);
  scopePanelElement.classList.toggle("scope-editing", state.scopeEditMode);
  const opened = state.worktreeMode === "across" ? state.worktreeData?.sources?.[0] : null;
  scopeSubtitleElement.textContent = opened ? `From ${opened.label} · ${opened.git.branchRef?.replace(/^refs\/heads\//, "") || opened.git.headCommit.slice(0, 8)}` : "";
  scopeSubtitleElement.hidden = !opened;
  scopeEditButton.hidden = setupMode || state.worktreeMode === "across" || state.scopeEditMode || state.scopeCollapsed;
  scopeEditButton.disabled = !state.workspace;
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

function syncWorkspaceChrome({ preserveBoardControls = false } = {}) {
  const setupMode = isSetupMode();
  document.body.dataset.setupMode = String(setupMode);
  layoutElement.dataset.setupMode = String(setupMode);
  layoutElement.dataset.boardLayout = normalizeBoardLayout(state.boardLayout);
  updateDocumentTitle();
  updateWorkspaceSummary();
  if (preserveBoardControls) { renderBoardSourceControl(); renderBoardParticipantStatus(); }
  else renderBoardChrome();
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

function beginBoardEditorResize(event) {
  if (isColumnsLayoutActive() || !isDesktopScopeLayout()) {
    return;
  }

  event.preventDefault();
  const startX = event.clientX;
  const startWidth = state.boardWidth;

  function move(nextEvent) {
    state.boardWidth = clampBoardWidth(startWidth + nextEvent.clientX - startX);
    renderScopeChrome();
  }

  function stop() {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", stop);
    window.removeEventListener("pointercancel", stop);
    persistBoardWidth();
  }

  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", stop);
  window.addEventListener("pointercancel", stop);
}

function collapsedGroupKey(name) {
  return `${state.repoPath}\n${normalizeLensKey(state.activeLens)}\n${name}`;
}

function isGroupCollapsed(name) {
  const toggled = state.collapsedGroups.has(collapsedGroupKey(name));
  return state.worktreeMode === "across" && name.startsWith("unlisted:") ? !toggled : toggled;
}

function toggleGroup(name) {
  const key = collapsedGroupKey(name);
  if (state.collapsedGroups.has(key)) {
    state.collapsedGroups.delete(key);
  } else {
    state.collapsedGroups.add(key);
  }

  renderBoard();
}

function captureColumnScrollState() {
  const columns = boardGroupsElement.querySelector(".board-columns");
  for (const column of columns?.querySelectorAll(".board-column") || []) {
    const groupName = column.querySelector("[data-group-toggle]")?.dataset.groupToggle;
    const list = column.querySelector(".board-column-list");
    if (groupName && list && !list.hidden) {
      state.columnScrollTops.set(collapsedGroupKey(groupName), list.scrollTop);
    }
  }
  return columns?.scrollLeft || 0;
}

function restoreColumnScrollState(scrollLeft) {
  const columns = boardGroupsElement.querySelector(".board-columns");
  if (columns) columns.scrollLeft = scrollLeft;
  for (const column of columns?.querySelectorAll(".board-column") || []) {
    const groupName = column.querySelector("[data-group-toggle]")?.dataset.groupToggle;
    const list = column.querySelector(".board-column-list");
    const storedScrollTop = groupName ? state.columnScrollTops.get(collapsedGroupKey(groupName)) : null;
    if (list && storedScrollTop != null) list.scrollTop = storedScrollTop;
  }
}

function toggleColumn(name) {
  const scrollLeft = captureColumnScrollState();
  toggleGroup(name);
  restoreColumnScrollState(scrollLeft);

  const nextToggle = [...boardGroupsElement.querySelectorAll("[data-group-toggle]")]
    .find((button) => button.dataset.groupToggle === name);
  nextToggle?.focus({ preventScroll: true });
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
  const workspace = await api.saveBoard(groups, state.workspace?.boardRevision);

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
    const workspace = await api.saveBoard(state.boardDraft, state.workspace?.boardRevision);

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
  if (state.worktreeMode === "across") {
    fields.boardGroup.innerHTML = '<option value="">Choose one checkout to change board placement</option>';
    fields.boardGroup.disabled = true;
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
  for (const dropZone of boardGroupsElement.querySelectorAll("[data-lens-drop-value], [data-board-drop-group-index], [data-board-column-drop-index], [data-item-order-drop-id]")) {
    dropZone.classList.remove("is-drop-target");
    delete dropZone.dataset.orderDropPlacement;
  }
  for (const element of boardGroupsElement.querySelectorAll(".is-dragging")) {
    element.classList.remove("is-dragging");
  }
}

function buildBoardParticipantBadge(item) {
  if (!state.inPlay && FINISHED_STATUSES.has(String(getBadgeMetadata(item).status || "").trim().toLowerCase())) return "";
  const counts = boardParticipantCounts.get(item.featureKey || item.id);
  if (!counts) return "";
  return buildParticipantRecencyBadges(counts.recentParticipantCount, counts.dormantParticipantCount);
}

function buildParticipantRecencyBadges(recent, dormant, closed = 0) {
  return [["Recent", recent], ["Dormant", dormant], ["Closed", closed]].filter(([, count]) => count > 0).map(([label, count]) => {
    const title = label === "Recent"
      ? "Recent under Pallium's 24-hour session last-seen observation; session activity is not work on this feature, current execution, or staffing."
      : label === "Dormant" ? "Dormant under Pallium's session last-seen observation; dormant does not mean this item is completed."
      : "Closed session association; this does not mean this item is completed.";
    return `<span class="badge board-item-participants${label !== "Recent" ? " participant-dormant" : ""}" title="${escapeHtml(title)}" aria-label="${escapeHtml(`${label} ${count} associated session${count === 1 ? "" : "s"}. ${title}`)}">${label} ${count}</span>`;
  }).join(" ");
}

function syncBoardParticipantBadges() {
  for (const card of boardGroupsElement.querySelectorAll(".board-item[data-item-id], .board-column-card-main[data-item-dblopen]")) {
    const itemId = card.dataset.itemId || card.dataset.itemDblopen;
    const item = state.workspace?.items?.[itemId];
    if (!item) continue;
    const markup = buildBoardParticipantBadge(item);
    for (const row of card.querySelectorAll(".badge-row, .board-card-signals")) {
      for (const current of row.querySelectorAll(".board-item-participants")) current.remove();
      if (markup) row.insertAdjacentHTML("beforeend", markup);
    }
  }
}

function getBoardCardStatus(item) {
  const status = normalizeBadgeToken(getBadgeMetadata(item).status);
  if (status === "blocked") return "blocked";
  if (status === "active" || status === "in-progress") return "progress";
  return "";
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
  const metadata = getBadgeMetadata(item);
  const cardStatus = getBoardCardStatus(item);
  const numericPriority = /^\d+$/.test(String(metadata.priority ?? "")) ? renderBadge(metadata.priority, "priority") : "";
  const participantBadge = buildBoardParticipantBadge(item);
  const signalBadges = `${cardStatus ? renderBadge(metadata.status, "status") : ""}${numericPriority}${participantBadge}`;
  const statusSignal = `<span class="board-card-signals">${signalBadges}</span>`;
  const specLink = state.workspace?.specSessionsByItemId?.[item.id];
  const specBadge = specLink?.unavailable
    ? `<span class="board-item-spec-badge is-unavailable" title="Spec session unavailable" aria-label="Spec session unavailable">⚠</span>`
    : specLink
      ? `<span class="board-item-spec-badge" title="${escapeHtml(buildSpecBadgeTitle(specLink))}" aria-label="${escapeHtml(buildSpecBadgeTitle(specLink))}">💬 ${specLink.openComments}${specLink.pendingSuggestions > 0 ? ` · ✎ ${specLink.pendingSuggestions}` : ""}</span>`
      : "";
  const sourceLabels = item.matchingVersions?.map((version) => `${version.sourceContext.label}: ${version.repoRoot}`) || [];
  const sourceName = item.sourceVersion?.sourceContext;
  const sourceLabel = sourceName ? `${sourceName.label} · ${sourceName.git.branchRef?.replace(/^refs\/heads\//, "") || sourceName.git.headCommit.slice(0, 8)}` : "";
  const differingFields = [...new Set((item.conflicts || []).map((entry) => entry.field))];
  const sourceBadgeLabel = item.matchingVersions?.length > 1 ? `${item.matchingVersions.length} checkouts` : sourceLabel;
  const sourceBadge = item.sourceVersion && (item.matchingVersions?.length === 1 || differingFields.length)
    ? `<span class="board-source-badge" title="${escapeHtml(sourceLabels.join("\n"))}">${escapeHtml(sourceBadgeLabel)}</span>` : "";
  const conflictDetail = (item.conflicts || []).map((entry) => {
    const source = item.versions?.find((version) => version.sourceKey === entry.sourceKey)?.sourceContext;
    return `${source?.repoRoot || entry.sourceKey} · ${entry.field}: ${entry.value}`;
  }).join("\n");
  const conflictBadge = differingFields.length ? `<span class="board-source-badge board-source-conflict" role="note" title="${escapeHtml(conflictDetail)}" aria-label="${escapeHtml(conflictDetail)}">${escapeHtml(differingFields.filter((field) => field !== "revision").map((field) => `${humanizeFilterKey(field)} differs`).join(" · ") || "Versions differ")}</span>` : "";
  const feature = activeLensKey === "board" && item.featureKey
    ? state.worktreeData?.features.find((entry) => entry.key === item.featureKey) : null;
  const otherGroups = [...new Set((feature?.groups || []).filter((group) => group.kind === "board" && group.name !== item.sourceVersion?.group).map((group) => group.name))];
  const groupCue = otherGroups.length ? `<span class="board-source-badge" role="note" title="${escapeHtml(otherGroups.join("\n"))}">${escapeHtml(`Also in ${otherGroups[0]}${otherGroups.length > 1 ? ` +${otherGroups.length - 1}` : ""}`)}</span>` : "";

  return `
    <span class="board-item-top">
      <span class="board-item-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</span>
      ${metaHtml}
    </span>
    ${statusSignal}
    <span class="board-item-id">${escapeHtml(item.sourceVersion?.itemId || item.id)}</span>
    ${overview}
    <span class="badge-row">${renderBadges(item, activeLensKey, { cardMode: true })}${participantBadge}${specBadge}${sourceBadge}${conflictBadge}${groupCue}</span>
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
    const workspace = await api.saveBoard(groups, state.workspace?.boardRevision);

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
    const workspace = await api.saveBoard(groups, state.workspace?.boardRevision);

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
    await api.saveItem(itemId, {
      metadata: {
        [activeLens.key]: targetValue === UNASSIGNED_GROUP_KEY ? null : targetValue,
      },
      expectedRevision: state.workspace?.items?.[itemId]?.revision,
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

function canReorderRelative(itemId, anchorItemId) {
  return getBoardGroupIndexForItem(itemId) === getBoardGroupIndexForItem(anchorItemId);
}

function restoreOrderActionFocus(kind, key, placement) {
  const buttons = [...boardGroupsElement.querySelectorAll(kind === "item" ? "[data-item-id-order]" : "[data-move-lens-group]")]
    .filter((button) => (kind === "item" ? button.dataset.itemIdOrder : button.dataset.lensGroupValue) === key);
  const target = buttons.find((button) => button.dataset.placement === placement && !button.disabled)
    || buttons.find((button) => !button.disabled)
    || buttons[0];
  target?.focus({ preventScroll: true });
}

function bindItemOrderShortcuts() {
  for (const button of boardGroupsElement.querySelectorAll("[data-item-id-order]")) {
    button.addEventListener("keydown", (event) => {
      if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const placement = event.key === "ArrowUp" ? "before" : event.key === "ArrowDown" ? "after" : "";
      const anchorItemId = placement === "before" ? button.dataset.orderPreviousId : button.dataset.orderNextId;
      if (!placement || !anchorItemId) return;
      event.preventDefault();
      void persistMetadataOrder(button.dataset.itemIdOrder, anchorItemId, placement, button);
    });
  }
}

function bindItemOrderDropTargets() {
  const targets = [...boardGroupsElement.querySelectorAll("[data-item-order-drop-id]")];
  const targetsByItemId = new Map(targets.map((target) => [target.dataset.itemOrderDropId, target]));
  const getDropKind = (itemId, target) => {
    const source = targetsByItemId.get(itemId);
    if (!source) return "";
    if (itemId === target.dataset.itemOrderDropId) return "blocked";
    if (source.dataset.itemOrderGroupValue !== target.dataset.itemOrderGroupValue) {
      return target.dataset.itemOrderDropValue ? "move" : "blocked";
    }
    return canReorderRelative(itemId, target.dataset.itemOrderDropId) ? "order" : "blocked";
  };

  for (const target of targets) {
    target.addEventListener("dragover", (event) => {
      if (!state.dragItemId) return;
      const dropKind = getDropKind(state.dragItemId, target);
      if (!dropKind) return;
      event.stopPropagation();
      if (dropKind === "blocked") {
        if (event.dataTransfer) event.dataTransfer.dropEffect = "none";
        return;
      }
      event.preventDefault();
      const bounds = target.getBoundingClientRect();
      target.dataset.orderDropPlacement = dropKind === "move"
        ? "inside"
        : (event.clientY < bounds.top + (bounds.height / 2) ? "before" : "after");
      target.classList.add("is-drop-target");
      if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    });

    target.addEventListener("dragleave", (event) => {
      if (target.contains(event.relatedTarget)) return;
      target.classList.remove("is-drop-target");
      delete target.dataset.orderDropPlacement;
    });

    target.addEventListener("drop", (event) => {
      const itemId = event.dataTransfer?.getData("application/x-minimap-item-id")
        || event.dataTransfer?.getData("text/plain")
        || state.dragItemId
        || "";
      const dropKind = getDropKind(itemId, target);
      if (dropKind !== "move" && dropKind !== "order") return;
      event.preventDefault();
      event.stopPropagation();
      const bounds = target.getBoundingClientRect();
      const placement = event.clientY < bounds.top + (bounds.height / 2) ? "before" : "after";
      const anchorItemId = target.dataset.itemOrderDropId;
      const dropValue = target.dataset.itemOrderDropValue || "";
      state.dragClickSuppressUntil = Date.now() + 350;
      clearBoardDragState();
      if (dropKind === "move") {
        void persistDerivedLensMove(itemId, dropValue);
        return;
      }
      void persistMetadataOrder(itemId, anchorItemId, placement, null);
    });
  }
}

async function persistMetadataOrder(itemId, anchorItemId, placement, triggerButton) {
  const item = state.workspace?.items?.[itemId];
  if (!state.workspace || !item || !anchorItemId) return;

  const columnScrollLeft = captureColumnScrollState();
  setBanner("Updating shared item order...");
  try {
    const workspace = await api.reorderMetadata({
      itemId,
      anchorItemId,
      placement,
      expectedBoardRevision: state.workspace.boardRevision,
    });
    const restoreFocus = document.activeElement === triggerButton;
    state.workspace = workspace;
    syncWorkspaceChrome();
    renderBoard();
    restoreColumnScrollState(columnScrollLeft);
    if (restoreFocus) restoreOrderActionFocus("item", itemId, placement);
    setBanner("Shared item order saved.", "success");
  } catch (error) {
    setBanner(error.message, "error");
  }
}

async function persistLensGroupOrder(value, anchorValue, placement, triggerButton) {
  const lens = getActiveLensDefinition();
  if (!state.workspace || !lens || lens.kind !== "derived" || !value || !anchorValue) return;

  setBanner(`Updating ${lens.label.toLowerCase()} group order...`);
  try {
    const workspace = await api.reorderLensGroup(lens.key, {
      value,
      anchorValue,
      placement,
      expectedConfigRevision: state.workspace.configRevision,
    });
    const restoreFocus = document.activeElement === triggerButton;
    state.workspace = workspace;
    syncWorkspaceChrome();
    renderBoard();
    if (restoreFocus) restoreOrderActionFocus("group", value, placement);
    setBanner(`${lens.label} group order saved.`, "success");
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
  const allowItemReorder = state.worktreeMode !== "across" && activeLens?.kind === "derived";
  const metadataGroups = allowItemReorder && !isSearchActive()
    ? visibleGroups.filter((group) => activeLens.values.includes(group.groupKey))
    : [];

  if (visibleGroups.length === 0) {
    boardGroupsElement.innerHTML = `
      <div class="empty-state">
        <div>${boardInPlayResultsIncomplete() ? "No confirmed roadmap items match yet; In play results are incomplete." : "No roadmap items match the current view."}</div>
        <div class="board-empty-hint">Clear the query or filters to see the full board again.</div>
      </div>
    `;
    syncMobileNavigation();
    return;
  }

  const columnsHtml = visibleGroups.map((group) => {
    const collapseKey = state.worktreeMode === "across" ? group.groupKey : group.name;
    const collapsed = isGroupCollapsed(collapseKey);
    const dropAttributes = allowColumnDrag
      ? (boardGrouping
        ? `data-board-drop-group-index="${group.originalIndex}"`
        : (group.dropValue ? `data-lens-drop-value="${escapeHtml(group.dropValue)}"` : ""))
      : "";
    const reorderAttributes = allowColumnReorder ? `data-board-column-drop-index="${group.originalIndex}"` : "";

    const cardsHtml = group.items.map((item, itemIndex) => {
      if (isMissingBoardItem(item)) {
        return renderMissingBoardCardColumn(item);
      }
      const activeClass = item.id === state.selectedItemId && state.editorOverlayOpen ? " board-column-card-active" : "";
      const dragHandle = allowColumnDrag
        ? `<span class="board-column-card-drag" data-drag-item-id="${escapeHtml(item.id)}" draggable="true" aria-label="Move ${escapeHtml(item.title)}" title="Drag to move ${escapeHtml(item.title)}${allowItemReorder ? ". Keyboard: Alt+Up or Alt+Down." : ""}">::</span>`
        : "";
      const previous = group.items[itemIndex - 1];
      const next = group.items[itemIndex + 1];
      const canMoveUp = Boolean(previous && canReorderRelative(item.id, previous.id));
      const canMoveDown = Boolean(next && canReorderRelative(item.id, next.id));
      const orderAttributes = allowItemReorder
        ? `data-item-id-order="${escapeHtml(item.id)}" data-order-previous-id="${escapeHtml(canMoveUp ? previous.id : "")}" data-order-next-id="${escapeHtml(canMoveDown ? next.id : "")}" aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown" aria-description="Press Alt+ArrowUp or Alt+ArrowDown to reorder."`
        : "";
      const itemOrderDropAttributes = allowItemReorder
        ? `data-item-order-drop-id="${escapeHtml(item.id)}" data-item-order-group-value="${escapeHtml(group.groupKey)}" data-item-order-drop-value="${escapeHtml(group.dropValue || "")}"`
        : "";
      const placementAttributes = boardGrouping && allowColumnDrag
        ? `data-board-drop-group-index="${group.originalIndex}" data-board-drop-before-id="${escapeHtml(item.id)}"`
        : "";

      return `
        <article class="board-column-card${activeClass}${getBoardCardStatus(item) ? ` board-card-status-${getBoardCardStatus(item)}` : ""}${placementAttributes ? " board-column-dropzone" : ""}" title="${escapeHtml(item.title)}" ${placementAttributes} ${itemOrderDropAttributes}>
          <div class="board-column-card-main" data-item-dblopen="${escapeHtml(item.id)}" title="${escapeHtml(item.title)}">
            ${buildBoardCardBodyMarkup(item, activeLens?.key)}
          </div>
          <div class="board-column-card-actions">
            <button class="ghost-button board-column-card-open" data-item-open="${escapeHtml(item.id)}" type="button" aria-label="Open ${escapeHtml(item.title)}" ${orderAttributes}>Open</button>
            ${dragHandle}
          </div>
        </article>
      `;
    }).join("");

    return `
      <section class="board-column${collapsed ? " board-column-collapsed" : ""}${group.items.length >= 10 ? " board-column-dense" : ""}${allowColumnReorder ? " board-column-reorderable" : ""}${reorderAttributes ? " board-column-reorder-dropzone" : ""}" ${reorderAttributes}>
        <div class="board-column-header">
          <div class="board-column-heading">
            <button class="order-button board-column-collapse-toggle" data-group-toggle="${escapeHtml(collapseKey)}" type="button" aria-expanded="${collapsed ? "false" : "true"}" aria-label="${collapsed ? "Expand" : "Collapse"} ${escapeHtml(group.name)} column" title="${collapsed ? "Expand" : "Collapse"} ${escapeHtml(group.name)} column"><span aria-hidden="true">${collapsed ? "+" : "−"}</span></button>
            <span class="board-column-name" title="${escapeHtml(group.name)}">${escapeHtml(group.name)}</span>
            <span class="group-count">${group.items.length}</span>
          </div>
          ${allowColumnReorder
            ? `<button class="board-column-reorder-handle" data-drag-column-index="${group.originalIndex}" draggable="true" type="button" aria-label="Reorder ${escapeHtml(group.name)} column" title="Drag to reorder ${escapeHtml(group.name)}">::</button>`
            : (() => {
                const index = metadataGroups.indexOf(group);
                if (index < 0) return "";
                const previousGroup = metadataGroups[index - 1];
                const nextGroup = metadataGroups[index + 1];
                return `<div class="board-column-order-actions">
                  <button class="order-button" data-move-lens-group="up" data-lens-group-value="${escapeHtml(group.groupKey)}" data-lens-group-anchor="${escapeHtml(previousGroup?.groupKey || "")}" data-placement="before" type="button" aria-label="Move ${escapeHtml(group.name)} group left" ${previousGroup ? "" : "disabled"}>←</button>
                  <button class="order-button" data-move-lens-group="down" data-lens-group-value="${escapeHtml(group.groupKey)}" data-lens-group-anchor="${escapeHtml(nextGroup?.groupKey || "")}" data-placement="after" type="button" aria-label="Move ${escapeHtml(group.name)} group right" ${nextGroup ? "" : "disabled"}>→</button>
                </div>`;
              })()}
        </div>
        <div class="board-column-list${dropAttributes ? " board-column-dropzone" : ""}" ${collapsed ? "hidden" : ""} ${dropAttributes}>
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
  for (const button of boardGroupsElement.querySelectorAll("[data-group-toggle]")) {
    button.addEventListener("click", () => toggleColumn(button.dataset.groupToggle));
  }

  bindItemOrderShortcuts();
  bindItemOrderDropTargets();

  for (const button of boardGroupsElement.querySelectorAll("[data-move-lens-group]")) {
    button.addEventListener("click", () => {
      void persistLensGroupOrder(button.dataset.lensGroupValue, button.dataset.lensGroupAnchor, button.dataset.placement, button);
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
  const allowGroupReorder = state.worktreeMode !== "across" && activeLens?.key === DEFAULT_LENS_KEY && !filtered;
  const allowDerivedDrag = canDragItemsInActiveLens();

  if (visibleGroups.length === 0) {
    boardGroupsElement.innerHTML = `
      <div class="empty-state">
        <div>${boardInPlayResultsIncomplete() ? "No confirmed roadmap items match yet; In play results are incomplete." : "No roadmap items match the current view."}</div>
        <div class="board-empty-hint">Clear the query or filters to see the full board again.</div>
      </div>
    `;
    syncMobileNavigation();
    return;
  }

  const allowItemReorder = state.worktreeMode !== "across" && activeLens?.kind === "derived";
  const metadataGroups = allowItemReorder && !filtered
    ? visibleGroups.filter((group) => activeLens.values.includes(group.groupKey))
    : [];
  const restrictionHtml = allowItemReorder && state.workspace.boardGroups.length > 1
    ? '<div class="board-order-note">Priority moves stay inside each board.md group. Use one neutral Items group for full cross-lane ordering.</div>'
    : "";

  const html = visibleGroups.map((group) => {
    const collapseKey = state.worktreeMode === "across" ? group.groupKey : group.name;
    const collapsed = isGroupCollapsed(collapseKey);
    const items = group.items.map((item, itemIndex) => {
      if (isMissingBoardItem(item)) {
        return renderMissingBoardCardRead(item);
      }
      const active = item.id === state.selectedItemId ? " board-item-active" : "";
      const dragHandle = allowDerivedDrag
        ? `<span class="board-column-card-drag" data-drag-item-id="${escapeHtml(item.id)}" draggable="true" aria-label="Move ${escapeHtml(item.title)}" title="Drag to move ${escapeHtml(item.title)}${allowItemReorder ? ". Keyboard: Alt+Up or Alt+Down." : ""}">::</span>`
        : "";
      const previous = group.items[itemIndex - 1];
      const next = group.items[itemIndex + 1];
      const canMoveUp = Boolean(previous && canReorderRelative(item.id, previous.id));
      const canMoveDown = Boolean(next && canReorderRelative(item.id, next.id));
      const orderAttributes = allowItemReorder
        ? `data-item-id-order="${escapeHtml(item.id)}" data-order-previous-id="${escapeHtml(canMoveUp ? previous.id : "")}" data-order-next-id="${escapeHtml(canMoveDown ? next.id : "")}" aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown" aria-description="Press Alt+ArrowUp or Alt+ArrowDown to reorder."`
        : "";
      const itemOrderDropAttributes = allowItemReorder
        ? `data-item-order-drop-id="${escapeHtml(item.id)}" data-item-order-group-value="${escapeHtml(group.groupKey)}" data-item-order-drop-value="${escapeHtml(group.dropValue || "")}"`
        : "";
      return `
        <div class="board-item-row">
          <button class="board-item${active}${getBoardCardStatus(item) ? ` board-card-status-${getBoardCardStatus(item)}` : ""}" data-item-id="${escapeHtml(item.id)}" type="button" title="${escapeHtml(item.title)}" aria-label="Open ${escapeHtml(item.title)}" aria-pressed="${item.id === state.selectedItemId ? "true" : "false"}" ${orderAttributes} ${itemOrderDropAttributes}>
            ${buildBoardCardBodyMarkup(item, activeLens?.key, dragHandle)}
          </button>
        </div>
      `;
    }).join("");

    const metadataGroupIndex = metadataGroups.indexOf(group);
    const previousGroup = metadataGroups[metadataGroupIndex - 1];
    const nextGroup = metadataGroups[metadataGroupIndex + 1];
    const groupActions = allowGroupReorder
      ? `
          <div class="group-actions">
            <button class="order-button" data-move-group="up" data-group-index="${group.originalIndex}" type="button" ${(filtered || group.originalIndex === 0) ? "disabled" : ""}>Up</button>
            <button class="order-button" data-move-group="down" data-group-index="${group.originalIndex}" type="button" ${(filtered || group.originalIndex === state.workspace.boardGroups.length - 1) ? "disabled" : ""}>Down</button>
          </div>
        `
      : (metadataGroupIndex >= 0 ? `
          <div class="group-actions" aria-label="${escapeHtml(activeLens.label)} group order">
            <button class="order-button" data-move-lens-group="up" data-lens-group-value="${escapeHtml(group.groupKey)}" data-lens-group-anchor="${escapeHtml(previousGroup?.groupKey || "")}" data-placement="before" type="button" aria-label="Move ${escapeHtml(group.name)} group up" ${previousGroup ? "" : "disabled"}>Up</button>
            <button class="order-button" data-move-lens-group="down" data-lens-group-value="${escapeHtml(group.groupKey)}" data-lens-group-anchor="${escapeHtml(nextGroup?.groupKey || "")}" data-placement="after" type="button" aria-label="Move ${escapeHtml(group.name)} group down" ${nextGroup ? "" : "disabled"}>Down</button>
          </div>
        ` : "");

    return `
      <section class="board-group${collapsed ? " board-group-collapsed" : ""}${allowDerivedDrag && group.dropValue ? " board-group-droppable" : ""}" data-group-index="${group.originalIndex}">
        <div class="board-group-header">
          <button class="collapse-toggle${allowDerivedDrag && group.dropValue ? " board-group-dropzone" : ""}" data-group-toggle="${escapeHtml(collapseKey)}" type="button" aria-expanded="${collapsed ? "false" : "true"}" ${allowDerivedDrag && group.dropValue ? `data-lens-drop-value="${escapeHtml(group.dropValue)}"` : ""}>
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
  boardGroupsElement.innerHTML = restrictionHtml + html;
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

  bindItemOrderShortcuts();
  bindItemOrderDropTargets();

  for (const button of boardGroupsElement.querySelectorAll("[data-move-lens-group]")) {
    button.addEventListener("click", () => {
      void persistLensGroupOrder(button.dataset.lensGroupValue, button.dataset.lensGroupAnchor, button.dataset.placement, button);
    });
  }
  if (!allowDerivedDrag) {
    return;
  }

  for (const handle of boardGroupsElement.querySelectorAll("[data-drag-item-id]")) {
    handle.addEventListener("dragstart", (event) => {
      const itemId = handle.dataset.dragItemId || "";
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
      handle.classList.add("is-dragging");
      event.dataTransfer?.setData("text/plain", itemId);
      event.dataTransfer?.setData("application/x-minimap-item-id", itemId);
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
      }
    });

    handle.addEventListener("dragend", () => {
      handle.classList.remove("is-dragging");
      state.dragClickSuppressUntil = Date.now() + 350;
      if (!state.dragItemId || state.dragItemId === handle.dataset.dragItemId) {
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

function renderBoard(preserveInteraction = false) {
  if (!preserveInteraction) return renderBoardContents();
  const scrollLeft = captureColumnScrollState();
  const scrollTop = boardGroupsElement.scrollTop;
  const focused = document.activeElement;
  const focusedCard = focused?.closest(".board-item[data-item-id], .board-column-card-main[data-item-dblopen]");
  const focusedItemId = focusedCard?.dataset.itemId || focusedCard?.dataset.itemDblopen;
  const focusedOpenItemId = focused?.getAttribute("data-item-open");
  const focusedGroup = focused?.getAttribute("data-group-toggle");
  renderBoardContents();
  restoreColumnScrollState(scrollLeft);
  boardGroupsElement.scrollTop = scrollTop;
  if (focused && !focused.isConnected && document.activeElement === document.body) {
    const selector = focusedOpenItemId ? `[data-item-open="${CSS.escape(focusedOpenItemId)}"]`
      : focusedItemId ? `.board-item[data-item-id="${CSS.escape(focusedItemId)}"], .board-column-card-main[data-item-dblopen="${CSS.escape(focusedItemId)}"]`
      : focusedGroup ? `[data-group-toggle="${CSS.escape(focusedGroup)}"]` : "";
    if (selector) boardGroupsElement.querySelector(selector)?.focus({ preventScroll: true });
  }
}

function renderBoardContents() {
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

function isAbortError(error) {
  return error?.name === "AbortError";
}

function invalidateItemRequests() {
  state.itemLoadGeneration += 1;
  state.itemLoadController?.abort();
  state.itemParticipantsController?.abort();
  state.itemLoadController = null;
  state.itemParticipantsController = null;
  state.itemParticipants = null;
  renderItemParticipants();
}

function beginItemLoad(itemId) {
  invalidateItemRequests();
  const controller = new AbortController();
  state.itemLoadController = controller;
  return {
    generation: state.itemLoadGeneration,
    itemId,
    repoPath: state.repoPath,
    sourceKey: state.selectedSource?.sourceKey || null,
    controller,
  };
}

function itemIntentIsCurrent(intent, { requireSelected = false } = {}) {
  return Boolean(
    intent
    && intent.generation === state.itemLoadGeneration
    && intent.repoPath === state.repoPath
    && intent.sourceKey === (state.selectedSource?.sourceKey || null)
    && (!requireSelected || intent.itemId === state.selectedItemId)
  );
}

function participantStatusText(result) {
  if (!result) return "";
  if (result.status === "loading") return "Refreshing…";
  if (result.status === "ok") {
    const count = result.participants?.length || 0;
    return result.partial ? `${count}+` : (count === 1 ? "1 participant" : `${count} participants`);
  }
  return {
    "ambiguous-feature": "Association ambiguous",
    "identity-unavailable": "Reference unavailable",
    unsupported: "Pallium unsupported",
    unreachable: "Pallium unavailable",
    timeout: "Lookup timed out",
    "invalid-response": "Invalid response",
    "over-limit": "Response too large",
  }[result.status] || "Unavailable";
}

function formatParticipantTime(value) {
  if (!value) return "unknown";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "unknown";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function buildParticipantNameHtml(participant, name) {
  if (!participant.session_url) return escapeHtml(name);
  return `<a href="${escapeHtml(participant.session_url)}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHtml(`Open ${name} session in Pallium`)}" title="Open session in Pallium">${escapeHtml(name)}</a>`;
}

function renderItemParticipants() {
  if (!itemParticipantsElement) return;
  const result = state.itemParticipants;
  const quietlyHidden = !state.currentItem
    || !result
    || result.status === "disabled"
    || (result.status === "loading" && !result.reference);
  itemParticipantsElement.hidden = quietlyHidden;
  if (quietlyHidden) return;

  const hasParticipants = result.status === "ok" && result.participants?.length > 0;
  if (hasParticipants) {
    const participants = result.participants;
    itemParticipantsStatusElement.innerHTML = buildParticipantRecencyBadges(
      participants.filter((participant) => participant.lifecycle === "recent").length,
      participants.filter((participant) => participant.lifecycle === "dormant").length,
      participants.filter((participant) => participant.lifecycle === "closed").length,
    ) + (result.partial ? '<span class="badge" title="Counts describe only the displayed sessions; more may exist.">Partial</span>' : "");
  } else itemParticipantsStatusElement.textContent = participantStatusText(result);
  itemParticipantsRefreshButton.disabled = result.status === "loading";

  const reference = result.reference;
  itemParticipantsReferenceElement.hidden = !reference;
  itemParticipantsScopeElement.textContent = reference?.scope_ref || "";
  itemParticipantsLocalElement.textContent = reference?.local_ref || "";
  itemParticipantsCopyButton.disabled = !reference;

  if (result.status === "loading") {
    itemParticipantsListElement.innerHTML = '<p class="muted">Refreshing participant associations…</p>';
    return;
  }

  if (result.status !== "ok") {
    const messages = {
      "ambiguous-feature": "More than one distinct feature uses this ID across checkouts. Participant associations cannot be assigned safely to either feature.",
      "identity-unavailable": "This repository has no safe canonical Git origin, so Minimap cannot create an exact participant reference.",
      unsupported: "The configured local Pallium service does not support participant lookup.",
      unreachable: "The configured local Pallium service could not be reached.",
      timeout: "The participant lookup exceeded its overall time limit.",
      "invalid-response": "Pallium returned a response Minimap could not safely validate.",
      "over-limit": "The participant response exceeded Minimap's safety bounds.",
    };
    itemParticipantsListElement.innerHTML = `<p class="muted">${escapeHtml(messages[result.status] || "Participant lookup is unavailable.")}</p>`;
    return;
  }

  const participants = Array.isArray(result.participants) ? result.participants : [];
  if (participants.length === 0) {
    itemParticipantsListElement.innerHTML = '<p class="muted">No sessions are associated with this item.</p>';
    return;
  }

  const renderParticipant = (participant) => {
    const name = participant.alias || participant.title || participant.session_ref;
    const availability = [["Session", participant.state], ["Lifecycle", participant.lifecycle], ["Destination", participant.destination_health]].filter(([, value]) => Boolean(value));
    const origins = participant.association?.origins || [];

    return `
      <article class="item-participant" role="listitem">
        <div class="item-participant-heading">
          <strong>${buildParticipantNameHtml(participant, name)}</strong>
          <span class="badge">${escapeHtml(participant.runtime)}</span>
        </div>
        <div class="item-participant-reference-row"><span class="muted">Session</span><code>${escapeHtml(participant.session_ref)}</code></div>
        <div class="item-participant-reference-row"><span class="muted">Container</span><code>${escapeHtml(participant.container_ref)}</code></div>
        <div class="item-participant-badges">${availability.map(([label, value]) => `<span class="badge">${escapeHtml(label)}: ${escapeHtml(value)}</span>`).join("")}</div>
        <p class="muted item-participant-freshness" title="Last seen: ${escapeHtml(participant.last_seen_at)}; association updated: ${escapeHtml(participant.association?.updated_at || "")}">
          Session last seen ${escapeHtml(formatParticipantTime(participant.last_seen_at))} · association updated ${escapeHtml(formatParticipantTime(participant.association?.updated_at))}
          ${origins.length ? ` · ${escapeHtml(origins.join(", "))}` : ""}
        </p>
      </article>
    `;
  };
  const rows = ["recent", "dormant", "closed"].map((lifecycle) => {
    const group = participants.filter((participant) => participant.lifecycle === lifecycle);
    if (!group.length) return "";
    const label = lifecycle[0].toUpperCase() + lifecycle.slice(1);
    return `<section class="item-participant-group" role="listitem" aria-label="${label} sessions"><h4>${label}</h4><div class="item-participant-group-list" role="list">${group.map(renderParticipant).join("")}</div></section>`;
  }).join("");

  const guidance = '<p class="muted">Last seen measures session activity, not work on this feature or staffing. Dormant does not mean completed.</p>'
    + (state.worktreeMode === "across" ? '<p class="muted">Associations belong to the logical feature, not a specific checkout version.</p>' : '')
    + (participants.some((participant) => participant.session_url)
      ? '<p class="muted">Use a linked Pallium session to remove explicit associations; structural links update through their producer. Captured History is unchanged, but is not a complete participation record.</p>' : "");
  itemParticipantsListElement.innerHTML = (result.partial ? '<p class="muted">Showing up to 200 participants; more may exist. Counts describe only the displayed sessions.</p>' : "") + guidance + rows;
}

async function loadItemParticipants(itemId, generation = state.itemLoadGeneration) {
  const intent = { generation, itemId, repoPath: state.repoPath, sourceKey: state.selectedSource?.sourceKey || null };
  if (!itemIntentIsCurrent(intent, { requireSelected: true })) return;

  if (state.worktreeData?.provisional) {
    state.itemParticipantsController?.abort();
    state.itemParticipants = { status: "loading", reference: null, participants: [], partial: true, itemId };
    renderItemParticipants();
    return;
  }

  if (state.worktreeMode === "across") {
    const featureKey = state.workspace?.items?.[itemId]?.featureKey;
    const feature = state.worktreeData?.features?.find((entry) => entry.key === featureKey);
    if (feature && state.worktreeData.features.filter((entry) => entry.id.normalize("NFC") === feature.id.normalize("NFC")).length > 1) {
      state.itemParticipants = { status: "ambiguous-feature", participants: [], itemId };
      renderItemParticipants();
      return;
    }
  }

  state.itemParticipantsController?.abort();
  const controller = new AbortController();
  state.itemParticipantsController = controller;
  const previous = state.itemParticipants?.itemId === itemId ? state.itemParticipants : null;
  state.itemParticipants = {
    status: "loading",
    reference: previous?.reference || null,
    participants: previous?.participants || [],
    partial: previous?.partial || false,
    refreshedAt: previous?.refreshedAt || null,
    itemId,
  };
  renderItemParticipants();

  try {
    const actualItemId = state.worktreeMode === "across" ? state.currentItem?.metadata?.id : itemId;
    const result = await api.readItemParticipants(actualItemId, { signal: controller.signal });
    if (!itemIntentIsCurrent(intent, { requireSelected: true }) || controller.signal.aborted) return;
    state.itemParticipants = { ...result, itemId };
    renderItemParticipants();
  } catch (error) {
    if (isAbortError(error) || controller.signal.aborted || !itemIntentIsCurrent(intent, { requireSelected: true })) return;
    state.itemParticipants = {
      status: "invalid-response",
      reference: previous?.reference || null,
      participants: [],
      partial: false,
      refreshedAt: null,
      itemId,
    };
    renderItemParticipants();
  } finally {
    if (state.itemParticipantsController === controller) state.itemParticipantsController = null;
  }
}

function resetEditor() {
  invalidateItemRequests();
  state.currentItem = null;
  state.confirmedEditSource = null;
  editorSourceLabelElement.hidden = true;
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

function positionEditorSourceMenu() {
  editorSourceSelectElement.style.maxWidth = "";
  editorSourceSelectElement.style.maxHeight = "";
  if (!editorSourceLabelElement.open || getComputedStyle(editorSourceSelectElement).position === "static") return;
  const panel = editorPanelElement.getBoundingClientRect();
  const menu = editorSourceSelectElement.getBoundingClientRect();
  editorSourceSelectElement.style.maxWidth = `${Math.max(0, panel.right - menu.left - 12)}px`;
  editorSourceSelectElement.style.maxHeight = `${Math.max(0, Math.min(window.innerHeight * 0.6, panel.bottom - menu.top - 12))}px`;
}

function renderEditorSourceSelect() {
  const card = state.worktreeMode === "across"
    ? getVisibleBoardGroups().flatMap((group) => group.items).find((item) => item.id === state.selectedItemId)
      || state.workspace?.items?.[state.selectedItemId] : null;
  const feature = card ? state.worktreeData?.features?.find((entry) => entry.key === card.featureKey) : null;
  const versions = feature ? [...new Map(feature.versions.map((version) => [version.sourceKey, version])).values()] : [];
  editorSourceLabelElement.hidden = state.worktreeMode !== "across" || versions.length === 0;
  const matchingSources = new Set(card?.matchingVersions?.map((version) => version.sourceKey) || []);
  const selected = versions.find((version) => version.sourceKey === state.selectedSource?.sourceKey) || versions[0];
  const branchName = (version) => version?.sourceContext.git.branchRef?.replace(/^refs\/heads\//, "") || version?.sourceContext.git.headCommit.slice(0, 8) || "Unavailable checkout";
  editorSourceSummaryElement.textContent = `${versions.length === 1 ? "Checkout" : `${versions.length} versions`} · ${branchName(selected)}`;
  editorSourceSummaryElement.title = branchName(selected);
  editorSourceSelectElement.innerHTML = versions.map((version) => {
    const active = version.sourceKey === selected?.sourceKey;
    const differences = versionDifferences(version, selected);
    const label = active ? "Selected version" : differences.length ? differences.join(" · ") : "Same content and metadata";
    return `<div class="editor-source-choice"><button type="button" data-editor-source="${escapeHtml(version.sourceKey)}" aria-pressed="${active}"><strong>${escapeHtml(branchName(version))}</strong><span class="editor-source-meta">${renderBadge(version.summary.status || "unknown", "status")}${matchingSources.has(version.sourceKey) ? "" : " filtered out"}</span><span class="editor-source-difference${differences.length ? " board-source-conflict" : ""}">${escapeHtml(label)}</span></button><details class="editor-source-path"><summary>Checkout path</summary><small>${escapeHtml(version.repoRoot)}</small></details></div>`;
  }).join("");
  positionEditorSourceMenu();
}

function renderItem(item) {
  state.currentItem = item;
  state.dirtyStructured = false;
  state.dirtyRaw = false;
  editorTitleElement.textContent = item.metadata.title;
  editorSubtitleElement.textContent = item.filePath;
  renderEditorSourceSelect();
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

// State-aware wrappers around the pure helpers in spec/anchors.js. The pure
// versions take `sourceContent` explicitly; these bind it to state.spec.content
// so existing call sites stay unchanged.
function sourceQuoteForRenderedSelection(selectionText) {
  return specSourceQuoteForRenderedSelection(selectionText, state.spec.content);
}

function resolveSourceQuoteFromRendered(selectionText, occurrenceIndex = 0) {
  return specResolveSourceQuoteFromRendered(selectionText, state.spec.content, occurrenceIndex);
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

  // Make the suggestion card visible first — for nav-button jumps the
  // card may be off-screen, and even for diff-present suggestions the
  // card sits in the same scroll container so a card scroll keeps the
  // active card in view.
  scrollSpecCardIntoView(`suggestion:${suggestionId}`);

  const diff = specFileContentElement.querySelector(
    `[data-spec-diff-suggestion-id="${CSS.escape(suggestionId)}"]`,
  );
  if (diff) {
    scrollSpecTargetIntoView(diff);
    diff.classList.remove("is-spec-diff-pulse");
    void diff.offsetWidth;
    diff.classList.add("is-spec-diff-pulse");
    window.setTimeout(() => diff.classList.remove("is-spec-diff-pulse"), 1500);
    clearTransientBanner();
    return;
  }

  // No diff in the body (resolved suggestion, Resolved toggle off, or
  // orphaned). Fall back to the anchor jump and the regular reasons.
  focusSpecAnchorItem(suggestion, `suggestion:${suggestionId}`);
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
  boardSourceToggleButton.closest(".board-source-control").hidden = specMode;
  if (specMode) closeBoardSourceMenu();
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
// (Implementation moved to spec/render.js; toggleSpecParticipantsPopover and
// renderSpecParticipantsFacepile are imported.)

function syncSpecToolbarChrome() {
  const ctx = state.spec.context;
  const comments = ctx?.comments || [];
  const suggestions = ctx?.suggestions || [];
  // Counts reflect what's actually rendered in the margin given the
  // current Resolved toggle — match the predicates in renderSpecComments
  // (commentMatchesFilter for comments; pending/accepted always visible
  // for suggestions, applied/rejected only when showResolved is on) so
  // the chip never overcounts hidden cards. When showResolved is off,
  // resolved items are not currently visible so they don't tick the
  // count; toggling Resolved on flips them back into the tally.
  const showResolved = state.spec.showResolved;
  const visibleComments = showResolved
    ? comments.length
    : comments.filter((c) => c.status !== "resolved").length;
  const visibleSuggestions = showResolved
    ? suggestions.length
    : suggestions.filter((s) => s.status === "pending" || s.status === "accepted").length;
  document.querySelectorAll('[data-spec-count="comments"]').forEach((el) => { el.textContent = visibleComments; });
  document.querySelectorAll('[data-spec-count="suggestions"]').forEach((el) => { el.textContent = visibleSuggestions; });
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
  updateSpecNavButtons();
}

// Visible cards in the order the reader sees them down the margin column.
// Re-sorted by visual top because layoutSpecMargin shuffles cards to align
// with their anchor positions in the body — DOM order is the insertion
// order (comments then suggestions), not the reading order. Orphan cards
// at the bottom land last, which matches their visual position too.
function visibleSpecMarginCards() {
  if (!specMarginElement) return [];
  const cards = Array.from(specMarginElement.querySelectorAll(".spec-margin-card"));
  return cards
    .map((card) => ({ card, top: card.getBoundingClientRect().top }))
    .sort((a, b) => a.top - b.top)
    .map(({ card }) => card);
}

function activeSpecCardKey() {
  return state.spec.activeAnchorCommentId || "";
}

function specCardKey(card) {
  if (card.dataset.suggestionId) return `suggestion:${card.dataset.suggestionId}`;
  return card.dataset.commentId || "";
}

// Step to the previous or next visible card and trigger the same code path
// a click on the card would. `direction` is -1 (prev) or +1 (next).
// When nothing is active yet, prev jumps to the LAST card and next to the
// FIRST so the buttons always do something on first press.
function navigateSpecMarginCard(direction) {
  const cards = visibleSpecMarginCards();
  if (cards.length === 0) return;

  const activeKey = activeSpecCardKey();
  let index = cards.findIndex((card) => specCardKey(card) === activeKey);
  if (index === -1) {
    index = direction > 0 ? -1 : cards.length;
  }
  const next = index + direction;
  if (next < 0 || next >= cards.length) return;

  const target = cards[next];
  if (target.dataset.suggestionId) {
    focusSpecSuggestionAnchor(target.dataset.suggestionId);
  } else if (target.dataset.commentId) {
    focusSpecCommentAnchor(target.dataset.commentId);
  }
}

// Reflect the prev/next button enabled state. Called from the toolbar
// state-render path AND from layoutSpecMargin (so re-flowing cards updates
// the boundary state without a full re-render).
function updateSpecNavButtons() {
  if (!specNavPrevButton || !specNavNextButton) return;
  const isReview = state.spec.viewMode === "review";
  if (!isReview) {
    specNavPrevButton.disabled = true;
    specNavNextButton.disabled = true;
    return;
  }
  const cards = visibleSpecMarginCards();
  if (cards.length === 0) {
    specNavPrevButton.disabled = true;
    specNavNextButton.disabled = true;
    return;
  }
  const activeKey = activeSpecCardKey();
  const index = cards.findIndex((card) => specCardKey(card) === activeKey);
  // Nothing active → both directions are usable (we'll jump to first/last).
  if (index === -1) {
    specNavPrevButton.disabled = false;
    specNavNextButton.disabled = false;
    return;
  }
  specNavPrevButton.disabled = index <= 0;
  specNavNextButton.disabled = index >= cards.length - 1;
}


async function loadSpecSessions(options = {}) {
  const payload = await api.listSessions();
  state.spec.sessions = payload.sessions || [];
  if (state.spec.selectedPath && !state.spec.sessions.some((session) => sameSpecUiPath(session.targetFile, state.spec.selectedPath))) {
    state.spec.selectedPath = "";
    state.spec.context = null;
    state.spec.content = "";
    state.spec.lastSeenContentHash = "";
    state.spec.fileChangedDetected = false;
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
    context = await api.getSessionContext(filePath);
    content = await api.getSessionContent(filePath);
  } catch (error) {
    state.spec.context = null;
    state.spec.content = "";
    state.spec.lastSeenContentHash = "";
    state.spec.fileChangedDetected = false;
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
  state.spec.lastSeenContentHash = context?.session?.contentHash || "";
  state.spec.fileChangedDetected = false;
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

  await api.removeSession(filePath);

  state.spec.sessions = state.spec.sessions.filter((candidate) => !sameSpecUiPath(candidate.targetFile, filePath));
  if (sameSpecUiPath(state.spec.selectedPath, filePath)) {
    state.spec.selectedPath = state.spec.sessions[0]?.targetFile || "";
    state.spec.context = null;
    state.spec.content = "";
    state.spec.lastSeenContentHash = "";
    state.spec.fileChangedDetected = false;
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

  const context = await api.getSessionContext(state.spec.selectedPath);
  state.spec.context = context;
  // Compare BEFORE rendering so the new flag is in scope when the banner
  // predicate runs below. The hash watermark is only ever advanced by full
  // reloads (loadSpecSession); the periodic poll just observes.
  const freshHash = context?.session?.contentHash || "";
  if (detectSpecFileChange(state.spec.lastSeenContentHash, freshHash)) {
    state.spec.fileChangedDetected = true;
  }
  renderSpecComments();
  syncSpecToolbarChrome();
  renderSpecFileChangedBanner();

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
  const result = await api.attachSession(filePath);
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
    // Disambiguation hints: forward the captured line range AND char offset
    // when the input value still looks like the live selection that produced
    // them. Exact equality is the strongest signal; a substring match also
    // counts — the user may have trimmed the prefilled paragraph quote down
    // to a shorter, common phrase, and the original line range/offset still
    // bracket the trimmed quote, so the server can disambiguate.
    // A typed value that ISN'T a substring of selectedQuote is something
    // the user wrote from scratch — we drop both hints there.
    if (state.spec.selectedQuote
        && (anchorValue === state.spec.selectedQuote || state.spec.selectedQuote.includes(anchorValue))) {
      if (state.spec.selectedQuoteLineRange) {
        body.lineStart = state.spec.selectedQuoteLineRange.lineStart;
        body.lineEnd = state.spec.selectedQuoteLineRange.lineEnd;
      }
      if (Number.isInteger(state.spec.selectedQuoteOffset)) {
        body.quoteOffset = state.spec.selectedQuoteOffset;
      }
    }
  }

  await api.addComment(body.file, body);
  // Form visibility is driven by `form.hidden`, not the state flag — flipping
  // commentComposerOpen alone leaves the form on screen. Use hideSpecComposerForm
  // to actually take it down, mirroring the cancel/escape paths.
  hideSpecComposerForm();
  state.spec.composerTarget = null;
  state.spec.selectedQuote = "";
  state.spec.selectedQuoteLineRange = null;
  state.spec.selectedQuoteOffset = null;
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
    // Same hint plumbing as comments — see addSpecComment for the rationale
    // on guarding by anchorValue === selectedQuote.
    if (state.spec.selectedQuote && anchorValue === state.spec.selectedQuote) {
      if (state.spec.selectedQuoteLineRange) {
        body.lineStart = state.spec.selectedQuoteLineRange.lineStart;
        body.lineEnd = state.spec.selectedQuoteLineRange.lineEnd;
      }
      if (Number.isInteger(state.spec.selectedQuoteOffset)) {
        body.quoteOffset = state.spec.selectedQuoteOffset;
      }
    }
  }

  await api.addSuggestion(body.file, body);
  hideSpecComposerForm();
  state.spec.composerTarget = null;
  state.spec.selectedQuote = "";
  state.spec.selectedQuoteLineRange = null;
  state.spec.selectedQuoteOffset = null;
  setSpecSuggestionAnchorMode("quote");
  specSuggestionAnchorInput.value = "";
  specSuggestionContentInput.value = "";
  specSuggestionRationaleInput.value = "";
  await refreshSpecReviewState();
  setBanner("Suggestion added.", "success");
}

async function replyToSpecComment(commentId, text) {
  await api.addCommentReply(state.spec.selectedPath, commentId, {
    by: specCommentByInput.value || "human",
    text,
  });
  state.spec.replyComposerCommentId = "";
  state.spec.replyDrafts.delete(commentId);
  await refreshSpecReviewState();
  scrollSpecReviewCardIntoView(commentId);
  setBanner("Reply added.", "success");
}

async function replyToSpecSuggestion(suggestionId, text) {
  await api.addSuggestionReply(state.spec.selectedPath, suggestionId, {
    by: specSuggestionByInput.value || specCommentByInput.value || "human",
    text,
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
  await api.setCommentStatus(state.spec.selectedPath, commentId, action, {
    by: specCommentByInput.value || "human",
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
  await api.setSuggestionStatus(state.spec.selectedPath, suggestionId, action, {
    by: specSuggestionByInput.value || specCommentByInput.value || "human",
  });
  await refreshSpecReviewState();
  setBanner(action === "accept" ? "Suggestion accepted." : action === "reopen" ? "Suggestion reopened." : "Suggestion dismissed.", "success");
}

async function switchAppMode(nextMode) {
  state.appMode = nextMode;
  applyAppMode();
  if (nextMode === "spec") {
    invalidateBoardPresence();
    try {
      await loadSpecSessions();
      syncRouteState({ replace: true });
    } catch (error) {
      setBanner(error.message, "error");
    }
    return;
  }

  syncWorkspaceChrome();
  renderBoard();
  syncRouteState({ replace: true });
  void refreshBoardPresence();
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
  if (options.refreshPresence !== false && boardParticipantIncludeCompleted !== boardPresenceIncludesCompleted()) void refreshBoardPresence();
  const visibleItemIds = getVisibleBoardItemIds();
  const preferredItemId = options.preferredItemId || "";
  const pendingPresenceItemId = state.inPlay && ["idle", "loading"].includes(boardParticipantStatus)
    && preferredItemId && state.workspace?.items?.[preferredItemId] ? preferredItemId : "";
  const useOverlay = shouldUseEditorOverlay();

  syncWorkspaceChrome({ preserveBoardControls: options.preserveBoardControls });
  renderBoard(options.preserveBoardControls === true);
  if (state.currentItem && state.worktreeMode === "across") renderEditorSourceSelect();

  if (options.preserveDirtyItem && state.currentItem && hasUnsavedCurrentItemChanges()) {
    if (options.syncRoute !== false) syncRouteState({ replace: options.replaceRoute !== false });
    return;
  }

  if (visibleItemIds.length === 0 && !pendingPresenceItemId) {
    resetEditor();
    if (options.syncRoute !== false) {
      syncRouteState({ replace: options.replaceRoute !== false });
    }
    return;
  }

  const nextItemId = [preferredItemId, state.selectedItemId, visibleItemIds[0]].find((itemId) => itemId && (itemId === pendingPresenceItemId || visibleItemIds.includes(itemId))) || visibleItemIds[0];
  const shouldShowItem = !useOverlay || state.editorOverlayOpen || Boolean(preferredItemId) || options.forceReloadItem === true;

  if (!shouldShowItem) {
    if (useOverlay) {
      resetEditor();
      syncWorkspaceChrome({ preserveBoardControls: options.preserveBoardControls });
      renderBoard(options.preserveBoardControls === true);
    } else if (state.selectedItemId && !visibleItemIds.includes(state.selectedItemId)) {
      resetEditor();
      syncWorkspaceChrome({ preserveBoardControls: options.preserveBoardControls });
      renderBoard(options.preserveBoardControls === true);
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
      preserveDirtyItem: options.preserveDirtyItem,
      preserveBoardControls: options.preserveBoardControls,
    });
    return;
  }

  if (useOverlay) {
    state.editorOverlayOpen = true;
    syncWorkspaceChrome({ preserveBoardControls: options.preserveBoardControls });
    renderBoard(options.preserveBoardControls === true);
  }

  if (options.syncRoute !== false) {
    syncRouteState({ replace: options.replaceRoute !== false });
  }
}

async function applyRouteStateFromLocation() {
  if ((hasUnsavedCurrentItemChanges() || state.boardDirty || state.scopeDirty)
    && window.location.hash !== buildRouteHash()
    && !window.confirm("Discard unsaved item, board, or scope changes before navigating?")) {
    syncRouteState({ replace: true });
    return;
  }
  const route = readRouteState();
  if (route.itemId && route.sourceKey && route.sources === "across") {
    state.preferredVersions.set(route.itemId, { sourceKey: route.sourceKey, gitRef: route.sourceRef });
  }
  const repoChanged = route.repo && route.repo !== state.repoPath;
  const requestedWorktreeMode = route.sources === "across" ? "across" : route.sources === "this" ? "this" : loadWorktreePreference(route.repo || state.repoPath);
  const worktreeModeChanged = requestedWorktreeMode !== state.worktreeMode;
  const boundChanged = (requestedWorktreeMode === "this" && route.bound) !== state.boundRequired;
  const exitedSpecMode = state.appMode === "spec" && route.view !== "spec";
  if (route.repo) {
    state.repoPath = route.repo;
  }
  state.worktreeMode = requestedWorktreeMode;
  state.worktreeModeExplicit = Boolean(route.sources);
  state.boundRequired = requestedWorktreeMode === "this" && route.bound;
  state.pinnedSource = state.boundRequired ? restorePinnedSource(state.repoPath) : null;
  if (route.view === "spec") {
    invalidateBoardPresence();
    state.appMode = "spec";
    state.spec.selectedPath = route.specFile || state.spec.selectedPath;
    applyAppMode();
    await loadSpecSessions({ loadSelected: Boolean(state.spec.selectedPath) });
    return;
  }

  state.appMode = "roadmap";
  applyAppMode();
  if (!repoChanged && state.workspace) {
    applyLensRouteChoice(state.workspace, route);
  }
  state.boardLayout = normalizeBoardLayout(route.layout);
  state.editorOverlayOpen = route.layout === "columns" && Boolean(route.itemId);
  state.searchQuery = route.query;
  state.inPlay = route.inPlay;
  state.activeFilters = route.filters;
  state.filtersExpanded = Object.keys(route.filters).length > 0;

  const nextMode = state.worktreeMode === "across" ? "preview" : normalizeEditorMode(route.mode);
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
  if (repoChanged || exitedSpecMode || worktreeModeChanged || boundChanged) {
    closeBoardSourceMenu();
    await loadWorkspace(route.itemId || "", {
      syncRoute: false,
      preferredLens: route.lens,
      routeLensSpecified: route.lensSpecified,
      preferredLayout: route.layout,
    });
    return;
  }

  clearTransientBanner();
  await syncVisibleSelection({
    preferredItemId: route.itemId || state.selectedItemId,
    replaceRoute: true,
    forceReloadItem: Boolean(route.sourceKey && (route.sourceKey !== state.selectedSource?.sourceKey
      || (route.sourceRef && route.sourceRef !== sourceRef(state.selectedSource)))),
  });
}
function boardPresenceIsVisible() {
  return document.visibilityState === "visible"
    && state.appMode === "roadmap"
    && state.worktreeMode !== "across"
    && Boolean(state.workspace)
    && !state.boardEditMode
    && !state.dragItemId
    && state.dragColumnIndex === null;
}

function invalidateBoardPresence({ keepCounts = false } = {}) {
  boardParticipantController?.abort();
  boardParticipantController = null;
  boardParticipantGeneration += 1;
  // Across counts belong to the workspace snapshot, not the visibility poller.
  // Preserve them while paused; a repo/source change still discards them.
  if (state.worktreeMode === "across" && state.workspaceScope?.mode === "across"
    && state.workspaceScope.repoPath === state.repoPath) return;
  if (!keepCounts) boardParticipantCounts = new Map();
  boardParticipantIncludeCompleted = null;
  boardParticipantStatus = "idle";
  boardParticipantPartial = false;
  renderBoardParticipantStatus();
  if (state.workspace && state.appMode === "roadmap") syncBoardParticipantBadges();
}

async function refreshBoardPresence() {
  if (!boardPresenceIsVisible()) return;
  const includeCompleted = boardPresenceIncludesCompleted();
  if (boardParticipantIncludeCompleted !== includeCompleted) {
    invalidateBoardPresence({ keepCounts: true });
    boardParticipantIncludeCompleted = includeCompleted;
    boardParticipantStatus = "loading";
    renderBoardParticipantStatus();
  }
  if (boardParticipantController) return;
  const controller = new AbortController();
  const generation = boardParticipantGeneration;
  const repoPath = state.repoPath;
  const worktreeMode = state.worktreeMode;
  boardParticipantController = controller;
  if (boardParticipantStatus === "idle") {
    boardParticipantStatus = "loading";
    renderBoardParticipantStatus();
  }
  try {
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(5_000)]);
    let result = await api.readBoardParticipantCounts({ signal, includeCompleted });
    if (includeCompleted && result.status === "ok" && result.includeCompleted !== true) {
      result = { status: "server-unsupported", counts: [] };
    }
    if (generation !== boardParticipantGeneration || repoPath !== state.repoPath || worktreeMode !== state.worktreeMode || !boardPresenceIsVisible()) return;
    if (result.status === "ok") {
      const keyName = worktreeMode === "across" ? "featureKey" : "itemId";
      const knownKeys = worktreeMode === "across"
        ? new Set(state.worktreeData?.features?.map((feature) => feature.key) || [])
        : new Set(Object.keys(state.workspace.items || {}));
      if (!Array.isArray(result.counts) || result.counts.length > 200
        || (result.counts.length > 0 && (result.recentSeconds !== 86400 || typeof result.asOf !== "string"
        || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/.test(result.asOf)
        || !Number.isFinite(Date.parse(result.asOf))))
        || result.counts.some((row) =>
        !row || typeof row[keyName] !== "string" || !knownKeys.has(row[keyName])
        || [row.participantCount, row.recentParticipantCount, row.dormantParticipantCount].some((count) => !Number.isSafeInteger(count) || count < 0)
        || row.recentParticipantCount + row.dormantParticipantCount !== row.participantCount
      ) || new Set(result.counts.map((row) => row[keyName])).size !== result.counts.length) {
        throw new Error("Invalid board participant counts.");
      }
      boardParticipantCounts = new Map(result.counts.map((row) => [row[keyName], row]));
    } else {
      boardParticipantCounts = new Map();
    }
    boardParticipantStatus = result.status;
    boardParticipantPartial = result.status === "ok" && result.partial === true;
    await syncBoardPresenceView();
    renderBoardParticipantStatus();
  } catch (error) {
    if (controller.signal.aborted || generation !== boardParticipantGeneration || repoPath !== state.repoPath || worktreeMode !== state.worktreeMode) return;
    boardParticipantCounts = new Map();
    boardParticipantStatus = "unavailable";
    boardParticipantPartial = false;
    await syncBoardPresenceView();
    renderBoardParticipantStatus();
  } finally {
    if (boardParticipantController === controller) boardParticipantController = null;
  }
}

async function syncBoardPresenceView() {
  if (!state.inPlay) {
    syncBoardParticipantBadges();
    renderBoardSourceControl();
    return;
  }
  await syncVisibleSelection({ replaceRoute: true, preserveDirtyItem: true, preserveBoardControls: true });
}

async function loadWorkspace(preferredItemId = state.selectedItemId, options = {}) {
  const generation = ++workspaceLoadGeneration;
  const repoPath = state.repoPath;
  const worktreeMode = state.worktreeMode;
  const stillCurrent = () => generation === workspaceLoadGeneration && repoPath === state.repoPath && worktreeMode === state.worktreeMode;
  const sameScope = state.workspaceScope?.repoPath === repoPath && state.workspaceScope?.mode === worktreeMode
    && (!state.boundRequired || (state.workspaceScope.sourceKey === state.pinnedSource?.sourceKey
      && state.workspaceScope.sourceRef === sourceRef(state.pinnedSource)));
  const preserveDirtyItem = Boolean(options.preserveDirtyItem && state.currentItem && hasUnsavedCurrentItemChanges());
  const draftSource = preserveDirtyItem ? state.selectedSource : null;
  const originalSelection = state.selectedItemId;
  let presented = sameScope;
  if (!sameScope || worktreeMode !== "across") {
    invalidateItemRequests();
    invalidateBoardPresence();
  }
  const initialItemGeneration = state.itemLoadGeneration;
  state.worktreeLoading = worktreeMode === "across";
  if (!sameScope) {
    state.workspace = null;
    state.worktreeData = null;
    state.workspaceScope = null;
    state.currentItem = null;
    state.setupState = null;
    syncWorkspaceChrome();
    workspaceSummaryElement.textContent = "Opening checkout…";
    boardGroupsElement.innerHTML = '<div class="empty-state" role="status">Opening checkout…</div>';
    editorTitleElement.textContent = "Opening checkout…";
    editorSubtitleElement.textContent = "";
    renderPreview();
    renderEditorChrome();
  } else {
    renderBoardSourceControl();
  }

  const present = async (aggregate, sourceWorkspace = null, workspace = sourceWorkspace?.workspace) => {
    if (aggregate && !aggregate.workspace) throw new Error(aggregate.unavailable?.message || "This checkout has no readable roadmap workspace.");
    workspace = aggregate ? buildCombinedWorkspace(aggregate) : workspace;
    if (!stillCurrent()) return;
    const reconcile = worktreeMode === "across" && presented;
    const retainUnfinished = reconcile && isUnfinishedFocused();
    const keepEditor = reconcile && (state.currentItem || state.itemLoadController);
    resetAncillaryEditModes();
    state.setupState = null;
    state.workspaceStale = false;
    if (sourceWorkspace) rememberPinnedSource(sourceWorkspace.source);
    state.worktreeData = aggregate;
    state.selectedSource = (keepEditor ? state.selectedSource : draftSource) || aggregate?.sources?.[0] || sourceWorkspace?.source || state.pinnedSource || null;
    state.workspace = workspace;
    const unfinishedStatuses = retainUnfinished ? getUnfinishedStatusValues() : [];
    if (unfinishedStatuses.length) state.activeFilters = normalizeFilterMap({ ...state.activeFilters, status: unfinishedStatuses });
    state.workspaceScope = { repoPath, mode: worktreeMode, sourceKey: state.pinnedSource?.sourceKey, sourceRef: sourceRef(state.pinnedSource) };
    if (aggregate) {
      const presence = aggregate.participantCounts;
      const known = new Set(aggregate.features.map((feature) => feature.key));
      const counts = presence?.status === "ok" && Array.isArray(presence.counts)
        && presence.counts.every((row) => known.has(row.featureKey)
          && [row.participantCount, row.recentParticipantCount, row.dormantParticipantCount].every((value) => Number.isSafeInteger(value) && value >= 0))
        ? presence.counts : [];
      boardParticipantCounts = new Map(counts.map((row) => [row.featureKey, row]));
      boardParticipantStatus = presence?.status || "unavailable";
      boardParticipantPartial = Boolean(presence?.partial || (presence?.status === "ok" && counts.length !== (presence.counts?.length || 0)));
      boardParticipantIncludeCompleted = true;
    }
    if (reconcile) {
      if (state.lensExplicit) applyLensRouteChoice(workspace, { lens: state.activeLens, lensSpecified: true });
      else state.activeLens = normalizeLensKey(state.activeLens, workspace);
    } else if (aggregate?.provisional && options.routeLensSpecified) {
      // A requested grouping may exist only in worktrees that have not loaded yet.
      state.activeLens = options.preferredLens || DEFAULT_LENS_KEY;
      state.lensExplicit = true;
    } else if (Object.hasOwn(options, "routeLensSpecified")) {
      applyLensRouteChoice(workspace, {
        lens: options.preferredLens,
        lensSpecified: options.routeLensSpecified,
      });
    } else {
      state.activeLens = normalizeLensKey(options.preferredLens ?? state.activeLens, workspace);
    }
    if (!reconcile) state.boardLayout = normalizeBoardLayout(options.preferredLayout ?? state.boardLayout);
    if (!preserveDirtyItem && !keepEditor) state.editorMode = worktreeMode === "across" ? "preview" : normalizeEditorMode(options.preferredMode ?? state.editorMode);
    roadmapPathElement.textContent = workspace.roadmapPath;
    renderScope();
    clearTransientBanner();

    const desiredItemId = reconcile ? state.selectedItemId || (state.itemLoadGeneration === initialItemGeneration ? preferredItemId : "") : preferredItemId;
    const desiredSource = state.preferredVersions.get(desiredItemId);
    const deferSelection = aggregate?.provisional && desiredItemId
      && (!workspace.items[desiredItemId] || desiredSource && !aggregate.sources.some((source) => source.sourceKey === desiredSource.sourceKey));
    presented = true;
    if (reconcile) {
      const focused = document.activeElement;
      const filterKey = focused?.getAttribute("data-filter-key");
      const filterValue = focused?.getAttribute("data-filter-value");
      const lensKey = focused?.getAttribute("data-lens-key");
      renderSearchControls();
      if (focused && !focused.isConnected) {
        const selector = filterKey ? `[data-filter-key="${CSS.escape(filterKey)}"][data-filter-value="${CSS.escape(filterValue)}"]`
          : lensKey ? `[data-lens-key="${CSS.escape(lensKey)}"]` : "";
        if (selector) document.querySelector(selector)?.focus({ preventScroll: true });
      }
    }
    if (deferSelection || reconcile && state.itemLoadController) {
      syncWorkspaceChrome({ preserveBoardControls: reconcile });
      renderBoard(reconcile);
      if (state.currentItem) renderEditorSourceSelect();
      return;
    }
    const fallbackItemId = shouldUseEditorOverlay() ? "" : (getFirstVisibleBoardItemId(workspace) || getFirstBoardItemId(workspace));
    await syncVisibleSelection({
      preferredItemId: reconcile || worktreeMode === "across" ? desiredItemId : desiredItemId && workspace.items?.[desiredItemId] ? desiredItemId : fallbackItemId,
      syncRoute: aggregate?.provisional ? false : options.syncRoute,
      replaceRoute: options.replaceRoute,
      forceReloadItem: reconcile ? options.forceReloadItem === true && state.selectedItemId === originalSelection : options.forceReloadItem === true || Boolean(preferredItemId),
      preserveDirtyItem: preserveDirtyItem || reconcile && hasUnsavedCurrentItemChanges(),
      preserveBoardControls: reconcile,
      refreshPresence: false,
    });
    if (stillCurrent() && aggregate && !aggregate.provisional && state.currentItem && !state.itemLoadController) void loadItemParticipants(state.selectedItemId);
    if (stillCurrent()) void refreshBoardPresence();
  };

  try {
    if (worktreeMode === "across" && !options.aggregate) {
      // Render one guarded checkout while the full scan continues; no background service or cache.
      const completed = api.loadWorktreeWorkspace().then((aggregate) => ({ aggregate }), (error) => ({ error }));
      const opened = !sameScope ? api.loadWorktreeWorkspace({ openedOnly: true }).then((aggregate) => ({ aggregate, opened: true }), (error) => ({ error, opened: true })) : null;
      const first = opened ? await Promise.race([completed, opened]) : await completed;
      if (!stillCurrent()) return;
      if (first.opened && !first.error && first.aggregate?.workspace) await present(first.aggregate);
      const result = first.opened ? await completed : first;
      if (!stillCurrent()) return;
      if (result.error) {
        if (!first.opened && opened) {
          const fallback = await opened;
          if (!stillCurrent()) return;
          if (!fallback.error && fallback.aggregate?.workspace) await present(fallback.aggregate);
        }
        throw result.error;
      }
      state.worktreeLoading = false;
      await present(result.aggregate);
    } else {
      const sourceWorkspace = options.sourceCandidate ? await api.loadSourceWorkspace(options.sourceCandidate) : null;
      const workspace = options.aggregate ? null : sourceWorkspace?.workspace || await api.loadWorkspace();
      if (!stillCurrent()) return;
      state.worktreeLoading = false;
      await present(options.aggregate || null, sourceWorkspace, workspace);
    }
  } catch (error) {
    if (!stillCurrent()) return;
    state.worktreeLoading = false;
    if (state.workspace && (sameScope || state.worktreeData?.provisional)) {
      state.workspaceStale = true;
      if (state.worktreeData?.provisional) {
        boardParticipantStatus = "unavailable";
        renderBoardParticipantStatus();
      }
      renderBoardSourceControl();
      setBanner(`Refresh failed. Showing the last-known view. ${error.message}`, "error");
      return;
    }
    state.workspace = null;
    state.worktreeData = null;
    state.workspaceScope = null;
    state.workspaceStale = false;
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
  const previousItem = state.currentItem;
  const previousItemId = state.selectedItemId;
  if (options.mode) {
    state.editorMode = normalizeEditorMode(options.mode);
  }
  if (typeof options.openOverlay === "boolean") {
    state.editorOverlayOpen = options.openOverlay;
  }
  const card = state.worktreeMode === "across"
    ? getVisibleBoardGroups().flatMap((group) => group.items).find((item) => item.id === itemId) || state.workspace?.items?.[itemId]
    : null;
  const feature = card ? state.worktreeData?.features?.find((entry) => entry.key === card.featureKey) : null;
  const preferredSource = state.preferredVersions.get(itemId);
  let version = feature?.versions.find((entry) => entry.sourceKey === preferredSource?.sourceKey);
  if (state.worktreeMode === "across" && preferredSource
    && (!version || (preferredSource.gitRef && sourceRef(version.sourceContext) !== preferredSource.gitRef))) {
    setBanner("The selected checkout version changed or is unavailable.", "error");
    if (!window.confirm("The selected checkout version changed or is unavailable. Open the board's current version instead?")) return;
    state.preferredVersions.delete(itemId);
    version = null;
  }
  version ||= card?.sourceVersion;
  if (state.worktreeMode === "across" && !version) {
    setBanner("This item source is no longer available. Refresh the combined board.", "error");
    return;
  }
  if (version) state.selectedSource = version.sourceContext;
  const intent = beginItemLoad(itemId);

  try {
    const item = await api.readItem(version?.itemId || itemId, { signal: intent.controller.signal });
    if (!itemIntentIsCurrent(intent) || intent.controller.signal.aborted) return;
    if (options.preserveDirtyItem && (state.currentItem !== previousItem || state.selectedItemId !== previousItemId || hasUnsavedCurrentItemChanges())) return;
    state.confirmedEditSource = null;
    state.selectedItemId = itemId;
    renderItem(item);
    applyEditorMode();
    syncWorkspaceChrome({ preserveBoardControls: options.preserveBoardControls });
    if (rerenderBoard) {
      renderBoard(options.preserveBoardControls === true);
    }
    if (options.syncRoute !== false) {
      syncRouteState({ replace: options.replaceRoute === true });
    }
    clearTransientBanner();
    void loadItemParticipants(itemId, intent.generation);
  } catch (error) {
    if (!isAbortError(error) && itemIntentIsCurrent(intent)) setBanner(error.message, "error");
  } finally {
    if (state.itemLoadController === intent.controller) state.itemLoadController = null;
  }
}
async function openBoardItemPreview(itemId) {
  if (!itemId) {
    return;
  }

  const useOverlay = shouldUseEditorOverlay();
  if (itemId === state.selectedItemId && state.currentItem) {
    state.editorOverlayOpen = useOverlay;
    void loadItemParticipants(itemId);
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
    await api.initializeWorkspace();
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
  if (state.worktreeMode === "across" && nextMode !== "preview" && state.currentItem
    && (state.confirmedEditSource?.itemId !== state.selectedItemId
      || state.confirmedEditSource?.sourceKey !== state.selectedSource?.sourceKey)) {
    if (!state.selectedSource || !window.confirm(`Edit only ${state.selectedSource.repoRoot}? Other checkout versions will not change.`)) return;
    state.confirmedEditSource = { itemId: state.selectedItemId, sourceKey: state.selectedSource.sourceKey };
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
  if (state.worktreeMode === "across" && (state.confirmedEditSource?.itemId !== state.selectedItemId
    || state.confirmedEditSource?.sourceKey !== state.selectedSource?.sourceKey)) {
    setBanner("Choose and confirm one checkout before editing this feature.", "error");
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
    const actualItemId = state.worktreeMode === "across" ? state.currentItem?.metadata?.id : state.selectedItemId;

    const savedItemId = state.selectedItemId;
    const savedSourceKey = state.selectedSource?.sourceKey;
    const savedMode = state.editorMode;
    const savedItem = await api.saveItem(actualItemId, { ...payload, expectedRevision: state.currentItem?.revision });
    if (state.selectedItemId === savedItemId && state.selectedSource?.sourceKey === savedSourceKey) {
      const currentPayload = savedMode === "raw" ? { rawText: rawTextElement.value } : collectPayload();
      if (state.editorMode === savedMode && JSON.stringify(currentPayload) === JSON.stringify(payload)) renderItem(savedItem);
      else state.currentItem.revision = savedItem.revision;
    }
    if (state.worktreeMode === "across" && state.selectedSource) {
      rememberPreferredVersion(state.selectedItemId, state.selectedSource);
    }

    if (state.worktreeMode !== "across" && state.editorMode === "structured" && Number.isInteger(nextBoardGroupIndex) && nextBoardGroupIndex >= 0 && nextBoardGroupIndex !== currentBoardGroupIndex) {
      const groups = buildBoardGroupsWithMovedItem(state.selectedItemId, nextBoardGroupIndex);
      if (groups) {
        await api.saveBoard(groups, state.workspace?.boardRevision);
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
    const workspace = await api.saveScope(state.scopeDraft, state.workspace?.scopeRevision);

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
  if (state.boardDirty || state.scopeDirty) {
    setBanner("Save or discard the board or scope draft before refreshing.", "error");
    return;
  }

  const options = {
    forceReloadItem: Boolean(state.selectedItemId),
    replaceRoute: true,
    preserveDirtyItem: true,
  };
  if (state.boundRequired && !state.pinnedSource) {
    const repoPath = state.repoPath;
    const generation = workspaceLoadGeneration;
    const worktreeMode = state.worktreeMode;
    const stillCurrent = () => repoPath === state.repoPath && generation === workspaceLoadGeneration
      && worktreeMode === state.worktreeMode && state.boundRequired && !state.pinnedSource;
    void api.discoverWorktreeSources().then((inventory) => {
      if (!stillCurrent()) return;
      const sourceCandidate = inventory.sources.find(isOpenedSource);
      if (!sourceCandidate) throw new Error("This checkout is unavailable. Reopen the source menu to choose a checkout.");
      return loadWorkspace(state.selectedItemId, { ...options, sourceCandidate });
    }).catch((error) => { if (stillCurrent()) setBanner(error.message, "error"); });
    return;
  }
  void loadWorkspace(state.selectedItemId, options);
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

if (specNavPrevButton) {
  specNavPrevButton.addEventListener("click", () => navigateSpecMarginCard(-1));
}
if (specNavNextButton) {
  specNavNextButton.addEventListener("click", () => navigateSpecMarginCard(1));
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
  state.spec.selectedQuoteLineRange = null;
  state.spec.selectedQuoteOffset = null;
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
  state.spec.selectedQuoteLineRange = null;
  state.spec.selectedQuoteOffset = null;
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
  // Once a composer is open, the captured quote+range are committed — don't
  // wipe them when the selection collapses (which it does as soon as the
  // user clicks into the form's textarea). Just hide the floating toolbar.
  const composerOpen = state.spec.commentComposerOpen || state.spec.suggestionComposerOpen;
  if (collapsed) {
    if (!composerOpen) {
      state.spec.selectedQuote = "";
      state.spec.selectedQuoteLineRange = null;
  state.spec.selectedQuoteOffset = null;
    state.spec.selectedQuoteOffset = null;
    }
    hideSpecContextToolbar();
    return;
  }
  // Selection still alive but moved outside the spec body — hide too.
  const range = selection.getRangeAt(0);
  if (!specFileContentElement.contains(range.commonAncestorContainer)) {
    if (!composerOpen) {
      state.spec.selectedQuote = "";
      state.spec.selectedQuoteLineRange = null;
  state.spec.selectedQuoteOffset = null;
    state.spec.selectedQuoteOffset = null;
    }
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
  const target = event.target instanceof Element ? event.target : null;
  if (!target) {
    return;
  }
  const reloadBtn = target.closest('[data-spec-action="reload-changed-file"]');
  if (reloadBtn) {
    if (state.spec.selectedPath) {
      void loadSpecSession(state.spec.selectedPath).catch((error) => {
        setBanner(error?.message || "Could not reload spec.", "error");
      });
    }
    return;
  }
  if (target.closest(".status-banner-dismiss")) {
    setBanner("");
  }
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
boardEditorResizerElement.addEventListener("pointerdown", beginBoardEditorResize);

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
    state.spec.selectedQuoteLineRange = null;
  state.spec.selectedQuoteOffset = null;
    state.spec.selectedQuoteOffset = null;
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
  state.spec.selectedQuoteLineRange = null;
  state.spec.selectedQuoteOffset = null;
});

boardFocusMilestoneSelect.addEventListener("change", () => {
  if (state.boardEditMode) return;
  const nextFilters = normalizeFilterMap({ ...state.activeFilters });
  if (boardFocusMilestoneSelect.value) nextFilters.milestone = [boardFocusMilestoneSelect.value];
  else delete nextFilters.milestone;
  state.activeFilters = normalizeFilterMap(nextFilters);
  void syncVisibleSelection({ replaceRoute: true });
});

boardFocusUnfinishedButton.addEventListener("click", () => {
  if (state.boardEditMode) return;
  const nextFilters = normalizeFilterMap({ ...state.activeFilters });
  if (isUnfinishedFocused()) delete nextFilters.status;
  else nextFilters.status = getUnfinishedStatusValues();
  state.activeFilters = normalizeFilterMap(nextFilters);
  void syncVisibleSelection({ replaceRoute: true });
});

boardFocusInPlayButton.addEventListener("click", () => {
  if (!state.workspace || state.boardEditMode) return;
  state.inPlay = !state.inPlay;
  void syncVisibleSelection({ replaceRoute: true, preserveDirtyItem: true });
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

boardSourceToggleButton.addEventListener("click", () => {
  if (!boardSourceMenuElement.hidden) { closeBoardSourceMenu(); return; }
  const cached = state.sourceMenuData?.repoPath === state.repoPath ? state.sourceMenuData : null;
  renderBoardSourceMenu(cached);
  boardSourceMenuElement.hidden = false;
  boardSourceToggleButton.setAttribute("aria-expanded", "true");
  void refreshSourceInventory();
});

boardSourceMenuElement.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-source-choice]");
  if (!button) return;
  const choice = button.dataset.sourceChoice;
  const choiceRepoPath = state.repoPath;
  const choiceGeneration = workspaceLoadGeneration;
  const choiceMode = state.worktreeMode;
  const choiceBoundRequired = state.boundRequired;
  if ((choice === "this" && state.worktreeMode === "this" && state.workspace && !state.workspaceStale)
    || (choice === "across" && state.worktreeMode === "across")) { closeBoardSourceMenu(); return; }
  if ((hasUnsavedCurrentItemChanges() || state.boardDirty || state.scopeDirty)
    && !window.confirm("Discard unsaved item, board, or scope changes before switching checkouts?")) return;
  closeBoardSourceMenu();
  if (choice === "across") {
    state.worktreeMode = "across";
    state.pinnedSource = null;
    state.boundRequired = false;
    state.worktreeModeExplicit = true;
    saveWorktreePreference();
    resetEditor();
    await loadWorkspace("", { replaceRoute: true });
  } else {
    if (choice === "this") await refreshSourceInventory();
    if (choiceRepoPath !== state.repoPath || choiceGeneration !== workspaceLoadGeneration || choiceMode !== state.worktreeMode || choiceBoundRequired !== state.boundRequired) return;
    const inventory = state.sourceMenuData?.repoPath === state.repoPath ? state.sourceMenuData : null;
    const selected = choice === "this"
      ? inventory?.sources?.find(isOpenedSource) || state.worktreeData?.sources?.[0]
      : inventory?.sources?.find((source) => source.sourceKey === choice);
    if (!selected) { setBanner("This checkout choice is unavailable. Reopen the source menu to refresh it.", "error"); return; }
    if (selected) state.repoPath = selected.repoRoot;
    state.worktreeMode = "this";
    state.worktreeModeExplicit = true;
    state.boundRequired = true;
    state.pinnedSource = null;
    state.selectedSource = null;
    saveWorktreePreference();
    resetEditor();
    await loadWorkspace("", { sourceCandidate: selected, replaceRoute: true });
  }
  renderBoardSourceControl();
});

document.addEventListener("click", (event) => {
  if (!boardSourceMenuElement.hidden && !event.target.closest(".board-source-control")) closeBoardSourceMenu();
});
boardSourceMenuElement.addEventListener("keydown", (event) => {
  if (event.key === "Escape") { closeBoardSourceMenu(); boardSourceToggleButton.focus(); }
});

boardClearFiltersButton.addEventListener("click", () => {
  state.searchQuery = "";
  state.inPlay = false;
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

itemParticipantsRefreshButton?.addEventListener("click", () => {
  if (state.selectedItemId) void loadItemParticipants(state.selectedItemId);
});

itemParticipantsCopyButton?.addEventListener("click", () => {
  const reference = state.itemParticipants?.reference;
  if (!reference) return;
  void navigator.clipboard.writeText(`scope_ref: ${reference.scope_ref}\nlocal_ref: ${reference.local_ref}`).then(() => {
    setBanner("Participant reference copied.", "success");
  }).catch(() => {
    setBanner("Could not copy the participant reference.", "error");
  });
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

editorSourceSelectElement.addEventListener("click", (event) => {
  const button = event.target.closest("[data-editor-source]");
  if (!button || button.getAttribute("aria-pressed") === "true") return;
  const itemId = state.selectedItemId;
  if (!itemId) return;
  if (hasUnsavedCurrentItemChanges() && !window.confirm("Discard unsaved changes before opening another checkout version?")) {
    return;
  }
  const selected = state.worktreeData?.sources.find((source) => source.sourceKey === button.dataset.editorSource);
  if (selected) rememberPreferredVersion(itemId, selected);
  state.confirmedEditSource = null;
  editorSourceLabelElement.open = false;
  void loadItem(itemId, true, { mode: "preview", openOverlay: state.editorOverlayOpen });
});

window.addEventListener("hashchange", () => {
  void applyRouteStateFromLocation();
});

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") invalidateBoardPresence();
  else void refreshBoardPresence();
});
window.setInterval(() => {
  if (boardPresenceIsVisible()) void refreshBoardPresence();
}, 30_000);

window.addEventListener("resize", () => {
  if (state.lensesExpanded) {
    positionLensControls();
  }
  positionEditorSourceMenu();
});
editorSourceLabelElement.addEventListener("toggle", positionEditorSourceMenu);
new ResizeObserver(positionEditorSourceMenu).observe(editorPanelElement);

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
state.worktreeMode = initialRoute.sources === "across" ? "across" : initialRoute.sources === "this" ? "this" : loadWorktreePreference(state.repoPath);
state.worktreeModeExplicit = Boolean(initialRoute.sources);
if (initialRoute.sources === "across" && initialRoute.itemId && initialRoute.sourceKey) {
  state.preferredVersions.set(initialRoute.itemId, { sourceKey: initialRoute.sourceKey, gitRef: initialRoute.sourceRef });
}
state.boundRequired = state.worktreeMode === "this" && initialRoute.bound;
state.pinnedSource = state.boundRequired ? restorePinnedSource(state.repoPath) : null;
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
state.activeLens = initialRoute.lens || DEFAULT_LENS_KEY;
state.lensExplicit = initialRoute.lensSpecified;
state.boardLayout = initialRoute.layout;
state.editorMode = state.worktreeMode === "across" ? "preview" : initialRoute.mode;
state.searchQuery = initialRoute.query;
state.inPlay = initialRoute.inPlay;
state.activeFilters = initialRoute.filters;
state.filtersExpanded = Object.keys(initialRoute.filters).length > 0;
renderScopeChrome();
applyEditorMode();
const initialWorkspaceLoad = loadWorkspace(state.appMode === "spec" ? "" : (initialRoute.itemId || state.selectedItemId), {
  preferredLens: initialRoute.lens,
  routeLensSpecified: initialRoute.lensSpecified,
  preferredLayout: initialRoute.layout,
  syncRoute: false,
});
const initialWorkspaceGeneration = workspaceLoadGeneration;
void initialWorkspaceLoad.then(() => {
  if (workspaceLoadGeneration !== initialWorkspaceGeneration) return;
  if (initialRoute.view === "spec") {
    void loadSpecSessions({ loadSelected: Boolean(initialRoute.specFile) });
    return;
  }

  if (state.worktreeMode === "across") {
    // The progressive load already applied the route and retained newer view intent.
    syncRouteState({ replace: true });
    return;
  }

  if (initialRoute.itemId || initialRoute.mode !== "preview" || initialRoute.lensSpecified || initialRoute.layout !== DEFAULT_BOARD_LAYOUT || initialRoute.query || initialRoute.inPlay || Object.keys(initialRoute.filters).length > 0) {
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
  // Read-only snapshot of spec state used by Playwright tests to verify what
  // the live-selection capture path stored in state. Returning a frozen copy
  // keeps consumers from mutating internals.
  getSpecStateSnapshot: () => Object.freeze({
    selectedQuote: state.spec.selectedQuote,
    selectedQuoteLineRange: state.spec.selectedQuoteLineRange
      ? { ...state.spec.selectedQuoteLineRange }
      : null,
    selectedQuoteOffset: state.spec.selectedQuoteOffset,
    commentComposerOpen: state.spec.commentComposerOpen,
    suggestionComposerOpen: state.spec.suggestionComposerOpen,
  }),
  rerenderSpecDocument: renderSpecFile,
  buildRenderedNormalizedMap,
  buildWhitespaceNormalizedMap,
  sourceQuoteForRenderedSelection: (renderedText, sourceContent) => {
    return specSourceQuoteForRenderedSelection(renderedText, sourceContent || state.spec.content);
  },
  // Same as the above, but exposes the line range too so tests can verify
  // the disambiguation hint we'd send for a given rendered selection.
  resolveSourceQuoteFromRendered: (renderedText, sourceContent) => {
    return specResolveSourceQuoteFromRendered(renderedText, sourceContent || state.spec.content);
  },
  // Open the comment composer with a given rendered selection text —
  // equivalent to selecting in the doc and clicking the floating toolbar's
  // "Comment", but without depending on toolbar geometry which is flaky to
  // drive in tests. Mirrors the captureSpecSelectedQuote path so the line
  // range hint travels with the quote when the form is submitted.
  openCommentComposerWithSelection: (selectionText) => {
    const occurrenceIndex = renderedSelectionOccurrenceIndex(String(selectionText || ""));
    const resolved = resolveSourceQuoteFromRendered(String(selectionText || ""), occurrenceIndex);
    state.spec.selectedQuote = resolved.quote;
    state.spec.selectedQuoteLineRange = resolved.lineRange;
    state.spec.selectedQuoteOffset = resolved.quoteOffset;
    openSpecComposer("comment", resolved.quote);
  },
  // Open the comment composer anchored to a specific block element — what
  // the gutter "+" button does when the user hovers a paragraph and clicks.
  // Lets tests exercise the paragraph-anchored path (and its line-range hint
  // capture) without depending on hover-button geometry.
  openCommentComposerForBlock: (block) => {
    openSpecComposerForBlock(block);
  },
});
