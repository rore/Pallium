// package/minimap/ui/spec/composer.js
//
// Composer / form-handling and selection-toolbar logic for the spec
// subsystem. DOM-touching; covered by Playwright (`playwright/roadmap-ui.spec.js`).
//
// Initialized once via wireSpecComposer({ dom, state, api, helpers }) at
// startup. Internally references DOM via the captured `DOM` binding,
// state via `STATE`, network via `API`, and in-app utilities via `HELPERS`.

import { normalizeVisibleText } from "/spec/anchors.js";

let DOM, STATE, API, HELPERS;

export function wireSpecComposer(deps) {
  DOM = deps.dom;
  STATE = deps.state;
  API = deps.api;
  HELPERS = deps.helpers;
}

// ── Selection capture ──────────────────────────────────────────────────

export function getSpecSelectionText() {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
    return "";
  }

  const range = selection.getRangeAt(0);
  const container = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE
    ? range.commonAncestorContainer
    : range.commonAncestorContainer.parentElement;
  if (!container || !DOM.specFileContentElement.contains(container)) {
    return "";
  }

  return selection.toString().trim();
}

export function captureSpecSelectedQuote() {
  const selectedText = getSpecSelectionText();
  if (!selectedText) {
    STATE.spec.selectedQuote = "";
    STATE.spec.selectedQuoteLineRange = null;
    STATE.spec.selectedQuoteOffset = null;
    return;
  }
  // Count how many times the selected text appears in the rendered body
  // BEFORE the live selection's start. That gives us the occurrence index
  // (0-based) the user actually selected, which we then use to pick the
  // matching occurrence in the source map. Without this, indexOf in the
  // source map always picks the first match — wrong when the same phrase
  // appears more than once.
  const occurrenceIndex = renderedSelectionOccurrenceIndex(selectedText);
  const resolved = HELPERS.resolveSourceQuoteFromRendered(selectedText, occurrenceIndex);
  STATE.spec.selectedQuote = resolved.quote;
  STATE.spec.selectedQuoteLineRange = resolved.lineRange;
  STATE.spec.selectedQuoteOffset = resolved.quoteOffset;
}

// 0-based count of how many times `needle` appears in the rendered body
// before the live selection's start, matching whatever normalization the
// renderer uses on textContent. Returns 0 (treat as first occurrence) when
// there's no selection or no match in front of it. Whitespace is collapsed
// the same way normalizeAnchorWhitespace handles it so the count lines up
// with what the source-map matcher will see.
export function renderedSelectionOccurrenceIndex(needle) {
  const trimmedNeedle = HELPERS.normalizeAnchorWhitespace(needle);
  if (!trimmedNeedle) return 0;
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return 0;
  const range = selection.getRangeAt(0);
  if (!DOM.specFileContentElement.contains(range.startContainer)) return 0;

  // textContent up to the selection start.
  const beforeRange = document.createRange();
  beforeRange.selectNodeContents(DOM.specFileContentElement);
  beforeRange.setEnd(range.startContainer, range.startOffset);
  const before = HELPERS.normalizeAnchorWhitespace(beforeRange.toString());

  let count = 0;
  let cursor = before.indexOf(trimmedNeedle);
  while (cursor !== -1) {
    count += 1;
    cursor = before.indexOf(trimmedNeedle, cursor + 1);
  }
  return count;
}

// 0-based count of how many times `needle` appears in the rendered body
// before this block's start. Used to pick the right occurrence in the
// source map when the user opens the composer from the gutter `+` rather
// than via a live text selection (which uses renderedSelectionOccurrenceIndex).
function renderedBlockOccurrenceIndex(block, needle) {
  const trimmedNeedle = HELPERS.normalizeAnchorWhitespace(needle);
  if (!trimmedNeedle) return 0;
  if (!DOM.specFileContentElement.contains(block)) return 0;
  const beforeRange = document.createRange();
  beforeRange.selectNodeContents(DOM.specFileContentElement);
  beforeRange.setEndBefore(block);
  const before = HELPERS.normalizeAnchorWhitespace(beforeRange.toString());
  let count = 0;
  let cursor = before.indexOf(trimmedNeedle);
  while (cursor !== -1) {
    count += 1;
    cursor = before.indexOf(trimmedNeedle, cursor + 1);
  }
  return count;
}

// ── Anchor mode (form chrome) ──────────────────────────────────────────

export function specAnchorSummary(mode, value) {
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

export function setSpecCommentAnchorMode(mode) {
  STATE.spec.commentAnchorMode = HELPERS.SPEC_COMMENT_ANCHOR_MODES.has(mode) ? mode : "global";
  renderSpecCommentAnchorMode();
}

export function renderSpecCommentAnchorMode() {
  DOM.specCommentAnchorModeButtons.forEach((button) => {
    const active = button.dataset.commentAnchorMode === STATE.spec.commentAnchorMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });

  const globalMode = STATE.spec.commentAnchorMode === "global";
  DOM.specCommentGlobalInput.checked = globalMode;
  DOM.specCommentAnchorInput.closest("label").hidden = globalMode;
  DOM.specCommentAnchorSummaryElement.textContent = specAnchorSummary(STATE.spec.commentAnchorMode, DOM.specCommentAnchorInput.value);
  if (globalMode) {
    DOM.specCommentAnchorInput.value = "";
    return;
  }

  if (STATE.spec.commentAnchorMode === "section") {
    DOM.specCommentAnchorLabelElement.textContent = "Section";
    DOM.specCommentAnchorInput.placeholder = "Heading > Subheading";
    return;
  }

  DOM.specCommentAnchorLabelElement.textContent = "Quote";
  DOM.specCommentAnchorInput.placeholder = "Exact quote from the file";
}

export function setSpecSuggestionAnchorMode(mode) {
  STATE.spec.suggestionAnchorMode = HELPERS.SPEC_SUGGESTION_ANCHOR_MODES.has(mode) ? mode : "quote";
  renderSpecSuggestionAnchorMode();
}

export function renderSpecSuggestionAnchorMode() {
  DOM.specSuggestionAnchorModeButtons.forEach((button) => {
    const active = button.dataset.suggestionAnchorMode === STATE.spec.suggestionAnchorMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });

  if (STATE.spec.suggestionAnchorMode === "section") {
    DOM.specSuggestionAnchorLabelElement.textContent = "Section";
    DOM.specSuggestionAnchorInput.placeholder = "Heading > Subheading";
    DOM.specSuggestionAnchorSummaryElement.textContent = specAnchorSummary("section", DOM.specSuggestionAnchorInput.value);
    return;
  }

  DOM.specSuggestionAnchorLabelElement.textContent = "Quote";
  DOM.specSuggestionAnchorInput.placeholder = "Exact quote from the file";
  DOM.specSuggestionAnchorSummaryElement.textContent = specAnchorSummary("quote", DOM.specSuggestionAnchorInput.value);
}

// ── Block discovery & quote derivation ─────────────────────────────────

export function specBlockCandidates() {
  return Array.from(DOM.specFileContentElement.querySelectorAll("h1, h2, h3, h4, h5, h6, p, li, pre, th, td"));
}

export function quoteForSpecBlock(element) {
  const visibleText = normalizeVisibleText(element?.textContent || "");
  return visibleText ? HELPERS.sourceQuoteForRenderedSelection(visibleText) : "";
}

// ── Context toolbar (the floating Comment / Suggest buttons) ───────────

export function hideSpecContextToolbar() {
  DOM.specContextToolbarElement.hidden = true;
  DOM.specContextToolbarElement.dataset.quote = "";
}

export function showSpecContextToolbar(quote, rect) {
  if (!quote || !rect || !STATE.spec.context) {
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
  DOM.specContextToolbarElement.dataset.quote = quote;
  DOM.specContextToolbarElement.style.left = `${left}px`;
  DOM.specContextToolbarElement.style.top = `${top}px`;
  DOM.specContextToolbarElement.hidden = false;
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

export function showSpecToolbarForSelection() {
  captureSpecSelectedQuote();
  const rect = selectedSpecRangeRect();
  if (!STATE.spec.selectedQuote || !rect) {
    return false;
  }
  showSpecContextToolbar(STATE.spec.selectedQuote, rect);
  return true;
}

// ── Composer state (open / close, prefill) ─────────────────────────────

export function openSpecComposer(kind, quote = "") {
  const cleanQuote = quote.trim();
  // Preserve the captured line range when the caller is opening on the same
  // quote we just captured from a live DOM selection. Other entry points
  // (paragraph "+" gutter, programmatic) pass a quote that didn't come from
  // a tracked selection — drop the range so we don't smuggle a stale hint
  // onto an unrelated occurrence.
  if (cleanQuote !== STATE.spec.selectedQuote) {
    STATE.spec.selectedQuoteLineRange = null;
    STATE.spec.selectedQuoteOffset = null;
  }
  if (kind === "suggestion") {
    if (!cleanQuote) {
      HELPERS.setBanner("Select text or use a paragraph action to suggest an edit.", "error");
      return;
    }
    STATE.spec.selectedQuote = cleanQuote;
    STATE.spec.commentComposerOpen = false;
    STATE.spec.suggestionComposerOpen = true;
    DOM.specSuggestionAnchorInput.value = cleanQuote;
    setSpecSuggestionAnchorMode("quote");
    showSpecComposerForm("suggestion");
    DOM.specSuggestionContentInput.focus();
    return;
  }

  STATE.spec.selectedQuote = cleanQuote;
  STATE.spec.suggestionComposerOpen = false;
  STATE.spec.commentComposerOpen = true;
  if (cleanQuote) {
    DOM.specCommentAnchorInput.value = cleanQuote;
    setSpecCommentAnchorMode("quote");
  } else {
    // No selection → anchor to the document's first H1 if available.
    // The legacy `__file` (global) anchor is kept in the schema but no
    // longer surfaced as an authoring choice.
    const firstHeading = DOM.specFileContentElement.querySelector("h1, h2, h3");
    const headingText = firstHeading ? normalizeVisibleText(firstHeading.textContent) : "";
    if (headingText) {
      DOM.specCommentAnchorInput.value = headingText;
      setSpecCommentAnchorMode("section");
    } else {
      DOM.specCommentAnchorInput.value = "";
      setSpecCommentAnchorMode("global");
    }
  }
  showSpecComposerForm("comment");
  DOM.specCommentTextInput.focus();
}

// Open the comment composer pre-anchored to a specific block in the spec
// body. Used by the hover-to-add `+` button in the gutter — gives the
// user an obvious way to add a comment without having to first select
// text. Headings get a section anchor (matches what they'd get if they
// typed the heading by hand); paragraphs and list items get a quote
// anchor against the block's visible text.
export function openSpecComposerForBlock(block) {
  if (!block) return;
  const tag = (block.tagName || "").toLowerCase();
  STATE.spec.suggestionComposerOpen = false;
  STATE.spec.commentComposerOpen = true;
  if (tag.startsWith("h") && tag.length === 2) {
    // Headings: use a section anchor. No quote, no line-range hint.
    STATE.spec.selectedQuote = "";
    STATE.spec.selectedQuoteLineRange = null;
    STATE.spec.selectedQuoteOffset = null;
    const headingText = normalizeVisibleText(block.textContent);
    DOM.specCommentAnchorInput.value = headingText;
    setSpecCommentAnchorMode("section");
  } else {
    // Paragraphs / list items: capture both the quote AND its source line
    // range so a disambiguation hint travels with the submission. Without
    // this, a paragraph quote that happens to share text with another
    // location in the file (or that the user trims down to a shorter,
    // non-unique substring) would fail with anchor_ambiguous and the user
    // would have no way to recover.
    const visibleText = normalizeVisibleText(block.textContent || "");
    const occurrenceIndex = visibleText ? renderedBlockOccurrenceIndex(block, visibleText) : 0;
    const resolved = visibleText
      ? HELPERS.resolveSourceQuoteFromRendered(visibleText, occurrenceIndex)
      : { quote: "", lineRange: null, quoteOffset: null };
    STATE.spec.selectedQuote = resolved.quote;
    STATE.spec.selectedQuoteLineRange = resolved.lineRange;
    STATE.spec.selectedQuoteOffset = resolved.quoteOffset;
    if (resolved.quote) {
      DOM.specCommentAnchorInput.value = resolved.quote;
      setSpecCommentAnchorMode("quote");
    } else {
      DOM.specCommentAnchorInput.value = "";
      setSpecCommentAnchorMode("global");
    }
  }
  showSpecComposerForm("comment");
  DOM.specCommentTextInput.focus();
}

// Show the (hidden) composer form as a floating panel anchored to the file pane.
// It overlays the spec doc so it doesn't shift layout while open.
export function showSpecComposerForm(kind) {
  const form = kind === "suggestion" ? DOM.specSuggestionForm : DOM.specCommentForm;
  const other = kind === "suggestion" ? DOM.specCommentForm : DOM.specSuggestionForm;
  if (other) other.hidden = true;
  if (!form) return;
  form.hidden = false;
  // Position the form: center horizontally over the spec body, near the top.
  // (Keep CSS simple: it's `position: fixed` styled below.)
}

export function hideSpecComposerForm() {
  if (DOM.specCommentForm) DOM.specCommentForm.hidden = true;
  if (DOM.specSuggestionForm) DOM.specSuggestionForm.hidden = true;
  STATE.spec.commentComposerOpen = false;
  STATE.spec.suggestionComposerOpen = false;
}

// ── Suggestion lifecycle (preview / apply / rollback) ──────────────────

export async function previewSpecSuggestion(suggestionId) {
  if (STATE.spec.previewSuggestionId === suggestionId) {
    STATE.spec.previewSuggestionId = "";
    STATE.spec.suggestionPreview = null;
    HELPERS.clearSpecSuggestionPreview();
    HELPERS.renderSpecComments();
    HELPERS.setBanner("Suggestion preview hidden.", "success");
    return;
  }

  const result = await API.previewSuggestion(STATE.spec.selectedPath, suggestionId);
  STATE.spec.previewSuggestionId = suggestionId;
  STATE.spec.suggestionPreview = result.preview;
  HELPERS.renderSpecInlineSuggestionPreview(result.suggestion, result.preview);
  HELPERS.renderSpecComments();
  HELPERS.setBanner("Suggestion preview shown in the spec.", "success");
}

export async function applySpecSuggestion(suggestionId) {
  await API.applySuggestion(STATE.spec.selectedPath, suggestionId, {
    by: DOM.specSuggestionByInput.value || DOM.specCommentByInput.value || "human",
  });
  STATE.spec.previewSuggestionId = "";
  STATE.spec.suggestionPreview = null;
  HELPERS.clearSpecSuggestionPreview();
  await HELPERS.loadSpecSession(STATE.spec.selectedPath);
  HELPERS.setBanner("Suggestion applied.", "success");
}

export async function rollbackSpecSuggestion(suggestionId) {
  await API.rollbackSuggestion(STATE.spec.selectedPath, suggestionId, {
    by: DOM.specSuggestionByInput.value || DOM.specCommentByInput.value || "human",
  });
  STATE.spec.previewSuggestionId = "";
  STATE.spec.suggestionPreview = null;
  HELPERS.clearSpecSuggestionPreview();
  await HELPERS.loadSpecSession(STATE.spec.selectedPath);
  HELPERS.setBanner("Suggestion rolled back.", "success");
}
