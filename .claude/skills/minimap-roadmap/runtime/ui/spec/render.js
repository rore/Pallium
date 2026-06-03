// package/minimap/ui/spec/render.js
//
// Rendering, anchor decoration, and margin layout for the spec subsystem.
// DOM-touching; covered by Playwright (`playwright/roadmap-ui.spec.js`).
//
// Initialized once via wireSpecRender({ dom, state, api, helpers }) at
// startup. Internally references DOM via the captured `DOM` binding,
// state via `STATE`, network via `API`, and in-app utilities via `HELPERS`.

import { renderMarkdownToHtml } from "/markdown.js";
import {
  normalizeVisibleText,
  stripMarkdownSyntaxForUi,
  decodeLiteralEscapes,
} from "/spec/anchors.js";
import { buildSpecToc } from "/spec/toc.js";

let DOM, STATE, API, HELPERS;

export function wireSpecRender(deps) {
  DOM = deps.dom;
  STATE = deps.state;
  API = deps.api;
  HELPERS = deps.helpers;
}

// Local copy of the inline HTML escaper. Mirrors app.js's escapeHtml so
// this module stays self-contained at the module boundary (matches how
// markdown.js handles the same dependency).
function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// Render a comment / reply / rationale body as paragraph-broken HTML.
// Comments authored by agents often arrive with structure that we want to
// preserve in the rendered card:
//   - Real newlines → blank lines split paragraphs, single newlines become
//     <br> so numbered/bulleted lists stay readable.
//   - Literal "\n" / "\t" / "\r" escapes (some models emit the two-char
//     sequence instead of the actual control char) get decoded the same
//     conservative way the server decodes suggestion content. We reuse
//     decodeLiteralEscapes from anchors.js for this.
//   - All output is HTML-escaped before any of the above structural HTML
//     is added — no markdown parsing, no link rendering, no risk of
//     injection.
function formatCommentBodyHtml(value) {
  const decoded = decodeLiteralEscapes(String(value || ""));
  const trimmed = decoded.replace(/^\s+|\s+$/g, "");
  if (!trimmed) return "";
  // Split on a blank line (one or more in a row). Within each paragraph,
  // single newlines become <br> so lists / multi-line prose stay legible.
  const paragraphs = trimmed.split(/\r?\n\s*\r?\n+/);
  return paragraphs
    .map((para) => {
      const lines = para.split(/\r?\n/).map((line) => escapeHtml(line));
      return `<p>${lines.join("<br>")}</p>`;
    })
    .join("");
}

// ── Anchor target resolution ───────────────────────────────────────────

function headingElementForPath(headingPath = []) {
  if (!headingPath.length) {
    return null;
  }

  const headings = Array.from(DOM.specFileContentElement.querySelectorAll("h1, h2, h3, h4, h5, h6"));
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

// ── Line-based anchor lookup ───────────────────────────────────────────
//
// The markdown renderer stamps every top-level block (and list item, and
// table row) with `data-spec-source-line="N"` — a 1-based line number in
// the FULL spec file (frontmatter included; see render.js where we pass
// the frontmatter offset). On read, the server re-resolves each anchor
// and reports `anchorStatus.lineStart` against the same line space, so
// going line → element is exact and survives quote drift.
//
// We rebuild the line→element map once per render and cache it on STATE
// so the per-card lookup in indexSpecAnchors is O(1) instead of an
// O(blocks × cards) text scan.

export function rebuildSpecLineIndex() {
  const map = new Map();
  if (DOM.specFileContentElement) {
    const elements = DOM.specFileContentElement.querySelectorAll("[data-spec-source-line]");
    for (const el of elements) {
      const line = parseInt(el.dataset.specSourceLine, 10);
      if (!Number.isFinite(line) || line < 1) continue;
      // First write wins — multiple elements can share a line (e.g. a list
      // and its first <li>). The list item is more specific and renders
      // AFTER the list opening tag, so we'd overwrite the parent. To pin
      // to the OUTERMOST block, keep the first.
      if (!map.has(line)) map.set(line, el);
    }
  }
  STATE.spec.lineToElement = map;
}

export function elementForSourceLine(line) {
  if (!Number.isFinite(line) || line < 1) return null;
  const map = STATE.spec.lineToElement;
  if (!map || !map.size) return null;
  const exact = map.get(line);
  if (exact) return exact;
  // Anchors can target lines that have no block of their own (blank lines,
  // mid-paragraph lines, lines inside fenced code). Walk back to the
  // nearest block that opens at or before the requested line — that's
  // the block the line belongs to.
  for (let probe = line - 1; probe >= 1; probe -= 1) {
    const hit = map.get(probe);
    if (hit) return hit;
  }
  return null;
}

function blockElementForQuote(quote) {
  const normalizedQuote = normalizeVisibleText(quote);
  if (!normalizedQuote) {
    return null;
  }

  const candidates = HELPERS.specBlockCandidates();
  // 1. literal whitespace-normalized match — fastest and most precise
  const literal = candidates.find((element) => normalizeVisibleText(element.textContent).includes(normalizedQuote));
  if (literal) return literal;

  // 2. markdown-stripped fallback — the quote may include backticks or a
  // `### ` heading prefix that the rendered HTML's textContent doesn't,
  // or vice versa. Stripping both sides catches that drift.
  const strippedQuote = stripMarkdownSyntaxForUi(quote);
  if (strippedQuote) {
    const stripped = candidates.find((element) => stripMarkdownSyntaxForUi(element.textContent).includes(strippedQuote)) || null;
    if (stripped) return stripped;
  }

  // 3. multi-block fallback. The quote spans more than one rendered block
  // (e.g. a heading PLUS the code fence beneath it, or a section header
  // PLUS several paragraphs). Walk the quote's lines top-down and return
  // the first rendered block that contains any of them — this is the
  // "first line of the spanned region", which is where we want the card
  // pinned. Without this the card has no anchor and gets stacked at the
  // bottom of the margin like an orphan, even though the server's
  // anchorStatus is `resolved`.
  const lines = String(quote || "").split(/\r?\n/);
  for (const line of lines) {
    const normalizedLine = normalizeVisibleText(line);
    if (!normalizedLine) continue;
    const literalLine = candidates.find((element) => normalizeVisibleText(element.textContent).includes(normalizedLine));
    if (literalLine) return literalLine;
    const strippedLine = stripMarkdownSyntaxForUi(line);
    if (!strippedLine) continue;
    const strippedHit = candidates.find((element) => stripMarkdownSyntaxForUi(element.textContent).includes(strippedLine));
    if (strippedHit) return strippedHit;
  }

  return null;
}

export function anchorTargetElement(item) {
  const anchor = item?.anchor || {};
  if (anchor.scope === "global") {
    return DOM.specFileContentElement.firstElementChild;
  }
  // Server-resolved line is the most authoritative signal. anchorStatus is
  // recomputed on every read, so it tracks file edits the original anchor
  // text cannot. Fall through to the original anchor.lineStart so an
  // orphaned-but-on-an-existing-line card lands visually near where the
  // user wrote it instead of stacked at the bottom of the margin. The
  // orphan styling is set independently in the layout pass — placement
  // and "this anchor is gone" visibility are separate concerns. Final
  // fallback is the heading-or-quote text-matching path for legacy
  // anchors that have no line metadata at all.
  const status = item?.anchorStatus || {};
  const resolvedLine = (status.status === "resolved" && Number.isFinite(status.lineStart))
    ? status.lineStart
    : null;
  const originalLine = Number.isFinite(anchor.lineStart) ? anchor.lineStart : null;
  // Try the resolved line first (server's re-resolution against the current
  // file). If absent (orphaned, ambiguous, or pre-line-metadata anchor),
  // try the original lineStart — the location the user authored the anchor
  // against. Either gives us the right visual placement; only when both
  // miss do we fall through to slow text matching.
  const lineCandidate = resolvedLine !== null ? resolvedLine : originalLine;
  if (lineCandidate !== null) {
    const byLine = elementForSourceLine(lineCandidate);
    if (byLine) return byLine;
  }
  if (anchor.scope === "section") {
    return headingElementForPath(anchor.headingPath || []);
  }
  return blockElementForQuote(anchor.quote);
}

// ── Highlight & scroll ─────────────────────────────────────────────────

export function clearSpecAnchorHighlight() {
  if (STATE.spec.anchorHighlightTimer) {
    window.clearTimeout(STATE.spec.anchorHighlightTimer);
    STATE.spec.anchorHighlightTimer = null;
  }
  DOM.specFileContentElement.querySelectorAll(".is-spec-anchor-highlight").forEach((element) => {
    element.classList.remove("is-spec-anchor-highlight");
  });
}

export function clearSpecSuggestionPreview() {
  DOM.specFileContentElement.querySelectorAll("[data-spec-diff-preview-id]").forEach((element) => {
    element.remove();
  });
  DOM.specFileContentElement.querySelectorAll(".is-spec-suggestion-preview-anchor").forEach((element) => {
    element.classList.remove("is-spec-suggestion-preview-anchor");
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

export function scrollSpecTargetIntoView(target) {
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

// ── Anchor focus / jump ────────────────────────────────────────────────

export function focusSpecAnchorItem(item, activeKey) {
  if (!item) {
    return;
  }

  STATE.spec.activeAnchorCommentId = activeKey;
  clearSpecAnchorHighlight();
  renderSpecComments();

  if (item.anchorStatus?.status && item.anchorStatus.status !== "resolved") {
    // The anchor's quote/section is no longer in the file (often after a
    // suggestion was applied that rewrote the anchored text). Tell the
    // user calmly — this is expected, not an error condition.
    HELPERS.setBanner("The anchored text is no longer in the file — nothing to jump to.", "info");
    return;
  }

  const target = anchorTargetElement(item);
  if (!target) {
    HELPERS.setBanner("Could not find the anchored text in the rendered file.", "error");
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
  STATE.spec.anchorHighlightTimer = window.setTimeout(() => {
    pulseTarget.classList.remove(pulseClass);
    STATE.spec.anchorHighlightTimer = null;
  }, 1700);
  HELPERS.setBanner("");
}

export function renderSpecInlineSuggestionPreview(suggestion, preview) {
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

// ── Time / actor formatting ────────────────────────────────────────────

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
  const value = (DOM.specCommentByInput?.value || "").trim();
  return value || "human";
}

function collectSpecParticipants() {
  // Returns [{ name, count, isViewer }] sorted by count desc, name asc.
  // The viewer is always present (with isViewer:true). If the viewer has
  // also authored content, their count includes it.
  const counts = new Map();
  const ctx = STATE.spec?.context;
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

export function renderSpecParticipantsFacepile() {
  if (!DOM.specParticipantsFacepile) return;
  // Hide entirely when there is no spec session loaded.
  if (!STATE.spec?.context && !STATE.spec?.selectedPath) {
    DOM.specParticipantsFacepile.hidden = true;
    return;
  }
  DOM.specParticipantsFacepile.hidden = false;

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
  DOM.specParticipantsFacepile.querySelector(".spec-facepile-circles").innerHTML = circlesHtml;

  const overflowEl = DOM.specParticipantsFacepile.querySelector(".spec-facepile-overflow");
  if (overflow > 0) {
    overflowEl.textContent = `+${overflow}`;
    overflowEl.hidden = false;
  } else {
    overflowEl.hidden = true;
  }

  const label = DOM.specParticipantsFacepile.querySelector("[data-spec-participants-label]");
  if (label) {
    label.textContent = total === 1 ? "1 participant" : `${total} participants`;
  }

  // If the popover is open, refresh its contents in place so updates flow
  // through (e.g. a comment arrives while the popover is open).
  if (DOM.specParticipantsPopover && !DOM.specParticipantsPopover.hidden) {
    renderSpecParticipantsPopover(participants);
  }
}

export function renderSpecParticipantsPopover(participants = collectSpecParticipants()) {
  if (!DOM.specParticipantsPopover) return;
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
  DOM.specParticipantsPopover.innerHTML = `
    <div class="spec-popover-head">Participants <span class="spec-popover-count">${participants.length}</span></div>
    <ul class="spec-popover-list" role="list">${itemsHtml}</ul>
  `;
}

export function toggleSpecParticipantsPopover(forceState) {
  if (!DOM.specParticipantsFacepile || !DOM.specParticipantsPopover) return;
  const willOpen = typeof forceState === "boolean"
    ? forceState
    : DOM.specParticipantsPopover.hidden;
  if (willOpen) {
    renderSpecParticipantsPopover();
    DOM.specParticipantsPopover.hidden = false;
    DOM.specParticipantsFacepile.setAttribute("aria-expanded", "true");
  } else {
    DOM.specParticipantsPopover.hidden = true;
    DOM.specParticipantsFacepile.setAttribute("aria-expanded", "false");
  }
}

// ── Sessions list ──────────────────────────────────────────────────────

export function renderSpecSessions() {
  const sessions = STATE.spec.sessions;
  const search = STATE.spec.sidebarSearch.trim().toLowerCase();
  const filtered = !search
    ? sessions
    : sessions.filter((s) => (
        (s.title || "").toLowerCase().includes(search)
          || (s.relativePath || "").toLowerCase().includes(search)
          || (s.targetFile || "").toLowerCase().includes(search)
      ));

  if (!filtered.length) {
    DOM.specSessionListElement.innerHTML = sessions.length
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
      const active = HELPERS.sameSpecUiPath(session.targetFile, STATE.spec.selectedPath);
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

  DOM.specSessionListElement.innerHTML = html;
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
  const isActive = HELPERS.sameSpecUiPath(session.targetFile, STATE.spec.selectedPath) && STATE.spec.context;
  let open = 0, pending = 0, orphan = 0;
  if (isActive) {
    open = (STATE.spec.context.comments || []).filter((c) => c.status !== "resolved").length;
    pending = (STATE.spec.context.suggestions || []).filter((s) => s.status === "pending" || s.status === "accepted").length;
    orphan = [
      ...(STATE.spec.context.comments || []),
      ...(STATE.spec.context.suggestions || []),
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

// ── File body rendering ────────────────────────────────────────────────

export function renderSpecFile() {
  const context = STATE.spec.context;
  if (STATE.spec.loadError) {
    const session = STATE.spec.sessions.find((candidate) => candidate.targetFile === STATE.spec.selectedPath);
    const missingTarget = STATE.spec.loadError.code === "target_missing";
    DOM.specFileTitleElement.textContent = session?.title || "Missing file";
    DOM.specFileSubtitleElement.textContent = session?.relativePath || session?.targetFile || STATE.spec.selectedPath || "Attached file";
    DOM.specFileContentElement.className = "spec-body spec-body-error";
    DOM.specFileContentElement.innerHTML = `
      <div class="spec-file-error-card">
        <p class="spec-file-error-kicker">${missingTarget ? "File no longer exists" : "Could not load file"}</p>
        <h2>${escapeHtml(missingTarget ? "This attached file is missing." : "This session could not be loaded.")}</h2>
        <p>${escapeHtml(STATE.spec.loadError.message || "The file could not be loaded.")}</p>
        <button class="spec-toolbar-button" type="button" data-spec-missing-remove="${escapeHtml(STATE.spec.selectedPath)}">Remove session</button>
      </div>
    `;
    DOM.specMarginElement.innerHTML = "";
    if (DOM.specTocElement) {
      buildSpecToc({
        bodyEl: DOM.specFileContentElement,
        tocEl: DOM.specTocElement,
        listEl: DOM.specTocListElement,
      });
    }
    HELPERS.hideSpecContextToolbar();
    return;
  }

  if (!context) {
    DOM.specFileTitleElement.textContent = "File";
    DOM.specFileSubtitleElement.textContent = "";
    DOM.specFileContentElement.className = "spec-body spec-body-empty";
    DOM.specFileContentElement.textContent = "Choose or attach a spec session.";
    DOM.specMarginElement.innerHTML = "";
    if (DOM.specTocElement) {
      buildSpecToc({
        bodyEl: DOM.specFileContentElement,
        tocEl: DOM.specTocElement,
        listEl: DOM.specTocListElement,
      });
    }
    HELPERS.hideSpecContextToolbar();
    return;
  }

  DOM.specFileTitleElement.textContent = context.session.title || "File";
  DOM.specFileSubtitleElement.textContent = context.session.relativePath || context.session.targetFile;
  DOM.specFileContentElement.className = context.session.markdown ? "spec-body spec-body-markdown" : "spec-body spec-body-plain";
  if (context.session.markdown) {
    const frontmatter = HELPERS.parseLeadingFrontmatter(STATE.spec.content);
    const headerHtml = HELPERS.buildSpecDocHeaderHtml(frontmatter);
    // If the frontmatter has a title, mirror it into the toolbar slot so the
    // tab title and the doc heading agree. Roadmap items reach this branch.
    if (frontmatter && typeof frontmatter.title === "string" && frontmatter.title.trim()) {
      DOM.specFileTitleElement.textContent = frontmatter.title.trim();
    }
    // Body is rendered without the frontmatter so the renderer's local
    // line indices start at 1. The server reports anchor lines against
    // the FULL file (frontmatter included), so pass the number of lines
    // the frontmatter consumed as an offset — the rendered DOM blocks
    // then carry data-spec-source-line values that line up with the
    // server's anchor.lineStart / anchorStatus.lineStart.
    const body = HELPERS.stripLeadingFrontmatter(STATE.spec.content);
    const original = String(STATE.spec.content || "");
    const consumed = original.length - body.length;
    const frontmatterLineCount = consumed > 0 ? original.slice(0, consumed).split(/\r?\n/).length - 1 : 0;
    DOM.specFileContentElement.innerHTML = headerHtml + renderMarkdownToHtml(body, { emitLines: true, lineOffset: frontmatterLineCount });
  } else {
    DOM.specFileContentElement.innerHTML = `<pre><code>${escapeHtml(STATE.spec.content)}</code></pre>`;
  }

  // Wrap quote-anchored ranges so they're hoverable + clickable.
  decorateSpecAnchors();

  // Rebuild the "On this page" TOC against the freshly-rendered body.
  // Safe to call on every render — buildSpecToc tears down its own
  // observer first, so re-renders don't leak observers.
  buildSpecToc({
    bodyEl: DOM.specFileContentElement,
    tocEl: DOM.specTocElement,
    listEl: DOM.specTocListElement,
  });

  // Index every block that carries a source-line attribute so anchorTargetElement
  // can do an O(1) line lookup instead of re-doing text matching against the
  // anchor.quote on every render. Built once after the DOM is in place.
  rebuildSpecLineIndex();

  STATE.spec.selectedQuote = "";
  STATE.spec.selectedQuoteLineRange = null;
  STATE.spec.selectedQuoteOffset = null;
  STATE.spec.activeAnchorCommentId = "";
  clearSpecAnchorHighlight();
  HELPERS.hideSpecContextToolbar();
}

// ── Margin cards ───────────────────────────────────────────────────────

function commentMatchesFilter(comment) {
  // Resolved visibility now comes from showResolved; orphan-and-stale stay visible.
  if (STATE.spec.showResolved) {
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

export function captureSpecReplyDraft() {
  if (!STATE.spec.replyComposerCommentId) {
    return;
  }
  const textarea = DOM.specMarginElement.querySelector(`.spec-card-reply-form[data-comment-id="${CSS.escape(STATE.spec.replyComposerCommentId)}"] textarea`);
  if (textarea) {
    STATE.spec.replyDrafts.set(STATE.spec.replyComposerCommentId, textarea.value);
  }
}

export function focusActiveSpecReplyDraft() {
  if (!STATE.spec.replyComposerCommentId) {
    return;
  }
  const textarea = DOM.specMarginElement.querySelector(`.spec-card-reply-form[data-comment-id="${CSS.escape(STATE.spec.replyComposerCommentId)}"] textarea`);
  if (textarea) {
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  }
}

export function scrollSpecReviewCardIntoView(cardId, type = "comment") {
  const selector = type === "suggestion"
    ? `[data-suggestion-id="${CSS.escape(cardId)}"]`
    : `[data-comment-id="${CSS.escape(cardId)}"]`;
  const card = DOM.specMarginElement.querySelector(selector);
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
  if (!DOM.specFileContentElement) return map;
  const bodyTop = DOM.specFileContentElement.getBoundingClientRect().top + DOM.specFileContentElement.scrollTop;

  function pushAnchor(id, el) {
    if (!el || map.has(id)) return;
    const r = el.getBoundingClientRect();
    map.set(id, { el, top: r.top - bodyTop + DOM.specFileContentElement.scrollTop });
  }

  // File-level pin: top of body.
  pushAnchor("__file", DOM.specFileContentElement);

  for (const comment of STATE.spec.context?.comments || []) {
    const target = anchorTargetElement(comment);
    if (target) pushAnchor(`comment:${comment.id}`, target);
  }
  for (const suggestion of STATE.spec.context?.suggestions || []) {
    const diffEl = DOM.specFileContentElement.querySelector(`[data-spec-diff-suggestion-id="${CSS.escape(suggestion.id)}"]`);
    const target = (diffEl && diffEl.offsetParent !== null) ? diffEl : anchorTargetElement(suggestion);
    if (target) pushAnchor(`suggestion:${suggestion.id}`, target);
  }
  return map;
}

export function renderSpecComments() {
  if (!DOM.specMarginElement) return;
  const ctx = STATE.spec.context;
  HELPERS.syncSpecToolbarChrome();

  if (STATE.spec.loadError) {
    DOM.specMarginElement.innerHTML = '<p class="spec-margin-empty">Remove this stale session or restore the missing file to continue reviewing.</p>';
    closeAllComposers();
    return;
  }
  if (!ctx) {
    DOM.specMarginElement.innerHTML = '<p class="spec-margin-empty">Choose a spec session to review.</p>';
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
    return STATE.spec.showResolved;
  });
  const showComments = STATE.spec.showComments;
  const showSuggestions = STATE.spec.showSuggestions;

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
    DOM.specMarginElement.innerHTML = comments.length || suggestions.length
      ? '<p class="spec-margin-empty">No items match the current view.</p>'
      : '<p class="spec-margin-empty">Hover a paragraph and click the + in the gutter to add the first comment.</p>';
    layoutSpecMargin();
    return;
  }

  const html = items.map(({ kind, item }) => {
    return kind === "comment" ? renderMarginCommentCard(item) : renderMarginSuggestionCard(item);
  }).join("");
  DOM.specMarginElement.innerHTML = html;
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
  const collapsedResolved = isResolved && !STATE.spec.expandedResolvedCommentIds.has(comment.id);
  const isActive = STATE.spec.activeAnchorCommentId === comment.id;

  const replies = (comment.replies || []).map((reply) => `
    <div class="spec-card-reply">
      <span class="spec-card-reply-author ${actorColorClass(reply.by)}">${escapeHtml(formatActorLabel(reply.by))}</span>
      <div class="spec-card-text">${formatCommentBodyHtml(reply.text)}</div>
    </div>`).join("");

  const isReplying = STATE.spec.replyComposerCommentId === comment.id;
  const replyForm = isReplying ? `
    <form class="spec-card-reply-form" data-comment-id="${escapeHtml(comment.id)}">
      <textarea rows="2" placeholder="Reply">${escapeHtml(STATE.spec.replyDrafts.get(comment.id) || "")}</textarea>
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
        <div class="spec-card-text">${formatCommentBodyHtml(comment.text)}</div>
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
  const isActive = STATE.spec.activeAnchorCommentId === `suggestion:${suggestion.id}`;
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
  const isReplying = STATE.spec.replyComposerCommentId === replyKey;
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
         <div class="spec-card-field-text">${formatCommentBodyHtml(suggestion.rationale)}</div>
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
      <div class="spec-card-text">${formatCommentBodyHtml(reply.text)}</div>
    </div>`).join("");
  const replyForm = isReplying ? `
    <form class="spec-card-reply-form" data-suggestion-reply-id="${escapeHtml(suggestion.id)}">
      <textarea rows="2" placeholder="Reply">${escapeHtml(STATE.spec.replyDrafts.get(replyKey) || "")}</textarea>
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
  if (DOM.specCommentForm) DOM.specCommentForm.hidden = true;
  if (DOM.specSuggestionForm) DOM.specSuggestionForm.hidden = true;
}

// ── Diff blocks ────────────────────────────────────────────────────────

// Render the inline diff blocks for visible suggestions.  When the
// suggestions layer is off, we strip them.  Each diff block carries a
// data-spec-diff-suggestion-id so renderSpecComments can find them as
// anchor targets. We only remove blocks that are tied to a suggestion;
// preview-only blocks (data-spec-diff-preview-id) are left alone.
export function renderSpecDiffBlocks() {
  if (!DOM.specFileContentElement) return;
  // Remove only suggestion-tied diff blocks. Preview blocks survive.
  DOM.specFileContentElement.querySelectorAll(".spec-diff-block[data-spec-diff-suggestion-id]").forEach((el) => el.remove());
  // And clear any "anchor hidden because diff is showing" state.
  DOM.specFileContentElement.querySelectorAll(".spec-anchor-hidden-by-diff").forEach((el) => {
    el.classList.remove("spec-anchor-hidden-by-diff");
  });

  // Read mode shows the pure spec — no diffs, no anchor decorations. Bail
  // before reinserting, otherwise the periodic refresh would silently add
  // diffs back into a Read-mode body a few seconds after the user switched.
  if (STATE.spec.viewMode !== "review") return;
  if (!STATE.spec.showSuggestions) return;

  for (const suggestion of STATE.spec.context?.suggestions || []) {
    // Resolved suggestions (applied / rejected) only show their inline
    // diff when the user explicitly opts in via the Resolved toggle.
    if ((suggestion.status === "rejected" || suggestion.status === "applied") && !STATE.spec.showResolved) continue;
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

// ── Anchor decoration ──────────────────────────────────────────────────

// Wrap each unique quote-anchored substring in a hoverable span so the
// margin card can highlight it. Only items that would actually appear in
// the active margin get a body-level mark — if the only thing anchored
// to a phrase is hidden (e.g. resolved with the Resolved toggle off),
// the underline is hidden too. The body and the comment pane stay in
// sync: an underline always corresponds to a card you can click.
export function decorateSpecAnchors() {
  const ctx = STATE.spec.context;
  if (!ctx || !DOM.specFileContentElement) return;
  // Strip any anchor-quote spans from a previous pass before re-walking.
  // This lets the function be called when toggle state changes without
  // having to rebuild the whole body.
  undecorateSpecAnchors();

  // Read mode shows the spec without any review chrome — no anchor
  // underlines, no diff blocks, no margin cards. Skip decoration so the
  // periodic refresh can't silently re-add underlines a few seconds in.
  if (STATE.spec.viewMode !== "review") return;

  const visibleComments = (ctx.comments || []).filter(commentMatchesFilter);
  const visibleSuggestions = (ctx.suggestions || []).filter((s) => {
    if (s.status === "pending" || s.status === "accepted") return true;
    return STATE.spec.showResolved;
  });
  const layerComments = STATE.spec.showComments ? visibleComments : [];
  const layerSuggestions = STATE.spec.showSuggestions ? visibleSuggestions : [];

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

export function undecorateSpecAnchors() {
  if (!DOM.specFileContentElement) return;
  // Replace each anchor-quote span with its text content, merging
  // adjacent text nodes back together via normalize().
  const spans = DOM.specFileContentElement.querySelectorAll(".spec-anchor-quote");
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
  const walker = document.createTreeWalker(DOM.specFileContentElement, NodeFilter.SHOW_TEXT, {
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

// ── Margin layout ──────────────────────────────────────────────────────

// Place each margin card next to its anchor's y position; if cards
// would overlap, slide the lower one down. Also draws gutter dots.
// Orphaned cards (anchor no longer exists in the file) are stacked
// at the bottom so they don't collide with anchored cards.
// The trailing "+ comment" button is placed below the last card.
export function layoutSpecMargin() {
  if (!DOM.specMarginElement || !DOM.specGutterElement) return;
  if (STATE.spec.viewMode !== "review") return;

  const cards = Array.from(DOM.specMarginElement.querySelectorAll(".spec-margin-card"));
  const anchors = indexSpecAnchors();

  // Clear gutter dots (the hover-add button is kept; it's not a dot).
  DOM.specGutterElement.querySelectorAll(".spec-gutter-dot").forEach((el) => el.remove());

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
      DOM.specGutterElement.appendChild(dot);
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
  // Cards moved → boundary state may have flipped (active card is now first
  // or last in visual order). Refresh the prev/next disabled state.
  HELPERS.updateSpecNavButtons();
}
