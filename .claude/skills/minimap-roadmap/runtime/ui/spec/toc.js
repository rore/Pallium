// package/minimap/ui/spec/toc.js
//
// "On this page" table of contents for the spec workbench.
// Builds a link list from the rendered .spec-body DOM, tracks the
// active section with a single IntersectionObserver, and persists
// collapsed state to localStorage. No framework; pure browser APIs.
//
// Initialized via wireSpecToc({ dom, helpers }) at startup.
// Re-render entry point is buildSpecToc({ bodyEl, tocEl, listEl }),
// called from spec/render.js after the body is rebuilt.

// Convert a heading's textContent into a stable, unique HTML id slug.
// `taken` is a Set of slugs already used in this rebuild — pass it so
// duplicate headings get -2, -3, … suffixes deterministically.
//
// Rules (kept simple on purpose):
//   - lowercase
//   - drop ASCII punctuation; collapse whitespace and dashes
//   - keep non-ASCII letters as-is (HTML ids allow them)
//   - empty result falls back to "section"
//   - mutate `taken` with the chosen slug so the caller's loop stays correct
export function slugifyHeadingId(text, taken) {
  const base = String(text || "")
    .toLowerCase()
    // strip ASCII punctuation but keep letters/digits/underscores from any script
    .replace(/[!"#$%&'()*+,./:;<=>?@\[\\\]^`{|}~]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");

  const seed = base || "section";
  if (!taken.has(seed)) {
    taken.add(seed);
    return seed;
  }
  for (let n = 2; ; n += 1) {
    const candidate = `${seed}-${n}`;
    if (!taken.has(candidate)) {
      taken.add(candidate);
      return candidate;
    }
  }
}

// Collapse runs of any whitespace (including newlines from rendered HTML)
// to single spaces, then trim. Used for both id-slug input and display text.
function normalizeHeadingText(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

// Turn a list of heading elements into the model the renderer consumes.
// Each entry: { level, id, text }. Existing ids are kept; missing ids are
// generated via slugifyHeadingId() and assigned via opts.assignId so the
// pure function stays unit-testable with non-DOM stand-ins.
export function buildSpecTocModel(headings, opts) {
  const assignId = opts && opts.assignId;
  const taken = new Set();
  // Pre-seed `taken` with existing ids so generated slugs don't collide.
  for (const h of headings) {
    if (h && h.id) taken.add(h.id);
  }
  const out = [];
  for (const h of headings) {
    if (!h || !h.tagName) continue;
    const tag = String(h.tagName).toUpperCase();
    if (tag !== "H2" && tag !== "H3") continue;
    const level = Number(tag.slice(1));
    const text = normalizeHeadingText(h.textContent);
    let id = h.id;
    if (!id) {
      id = slugifyHeadingId(text, taken);
      if (typeof assignId === "function") {
        assignId(h, id);
      }
    }
    out.push({ level, id, text });
  }
  return out;
}

// HTML escape — local copy so the module has no extra imports. Mirrors the
// escapeHtml in render.js / app.js. Kept private (not exported) so each
// module's escaper boundary stays explicit.
function escapeTocHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// Render the model as a flat <li><a> list. H3 entries get .is-sub so CSS
// can indent them with padding-left — we keep the DOM flat so the active-
// link logic doesn't have to walk a tree.
function renderTocList(listEl, model) {
  if (!listEl) return;
  if (!model.length) {
    listEl.innerHTML = "";
    return;
  }
  const html = model
    .map((entry) => {
      // class is a literal ternary; the rest goes through escapeTocHtml so the
      // lint in test/ui-lint-html-escape.test.js can verify safety inline.
      return `<li><a class="${entry.level === 3 ? "spec-toc-link is-sub" : "spec-toc-link"}" href="#${escapeTocHtml(entry.id)}" title="${escapeTocHtml(entry.text)}" data-spec-toc-target="${escapeTocHtml(entry.id)}">${escapeTocHtml(entry.text)}</a></li>`;
    })
    .join("");
  listEl.innerHTML = html;
}

// Module-scoped IntersectionObserver — torn down and rebuilt on every
// buildSpecToc() call so it always observes the current heading set.
let activeObserver = null;
let activeHeadings = []; // refs to the currently-observed heading elements

function teardownObserver() {
  if (activeObserver) {
    activeObserver.disconnect();
    activeObserver = null;
  }
  activeHeadings = [];
}

// Pick the heading whose top is the closest non-positive number — i.e. the
// last one we've scrolled past. Falls back to the first heading.
//
// Reference frame: we use the SCROLL container's top, not the body's. The
// body grows much taller than the scroll viewport, so its
// getBoundingClientRect().top is far above the visible area once you've
// scrolled. The scroll container (.spec-doc) is the right ruler — its top
// matches what the user perceives as "the top of the visible doc".
function pickActiveHeading(scrollEl) {
  if (!activeHeadings.length) return null;
  // A small offset so a heading just barely below the top still counts as
  // "active" — feels more natural than waiting until it crosses the exact
  // pixel edge.
  const ACTIVATION_OFFSET = 24;
  const refTop = (scrollEl ? scrollEl.getBoundingClientRect().top : 0) + ACTIVATION_OFFSET;
  let chosen = activeHeadings[0];
  let chosenDelta = -Infinity;
  for (const h of activeHeadings) {
    const delta = h.getBoundingClientRect().top - refTop;
    if (delta <= 0 && delta > chosenDelta) {
      chosenDelta = delta;
      chosen = h;
    }
  }
  return chosen;
}

function setActiveLink(listEl, headingId) {
  if (!listEl) return;
  const links = listEl.querySelectorAll(".spec-toc-link");
  links.forEach((a) => {
    const isActive = a.dataset.specTocTarget === headingId;
    a.classList.toggle("is-active", isActive);
  });
}

// Walk up from el until we find an ancestor that scrolls (overflow auto/scroll
// with content taller than its box). Returns null if nothing scrolls — in that
// case the document/viewport is the implicit scroller.
function findScrollAncestor(el) {
  let node = el && el.parentElement;
  while (node && node !== document.body) {
    const style = window.getComputedStyle(node);
    if (/(auto|scroll|overlay)/.test(style.overflowY) && node.scrollHeight > node.clientHeight) {
      return node;
    }
    node = node.parentElement;
  }
  return null;
}

// Module-level scroll-listener bookkeeping so we can detach it on rebuild.
let activeScrollEl = null;
let activeScrollHandler = null;
let activeScrollRafId = 0;

function detachScrollHandler() {
  if (activeScrollEl && activeScrollHandler) {
    activeScrollEl.removeEventListener("scroll", activeScrollHandler);
  }
  if (activeScrollRafId) {
    cancelAnimationFrame(activeScrollRafId);
    activeScrollRafId = 0;
  }
  activeScrollEl = null;
  activeScrollHandler = null;
}

// Public entry point — called from render.js after .spec-body re-renders.
// Walks h2/h3 in order, assigns missing ids, fills the list, sets up the
// active-section observer.
export function buildSpecToc({ bodyEl, tocEl, listEl }) {
  if (!bodyEl || !tocEl || !listEl) return;

  teardownObserver();
  detachScrollHandler();

  // Only count headings that belong to the rendered spec body — skip
  // headings inside error/empty cards (e.g. <h2> inside .spec-file-error-card),
  // which would otherwise pollute the TOC with non-document content.
  const headings = Array.from(bodyEl.querySelectorAll("h2, h3")).filter(
    (h) => !h.closest(".spec-file-error-card"),
  );
  const model = buildSpecTocModel(headings, {
    assignId: (el, slug) => { el.id = slug; },
  });
  renderTocList(listEl, model);

  // Keep the heading element refs we'll observe (h2/h3 only, after id
  // assignment so they're addressable).
  activeHeadings = headings.filter((h) => /^H[23]$/.test(h.tagName));

  // Empty-doc state: collapse the panel and disable the toggle until
  // headings reappear (e.g. while editing a doc).
  if (!model.length) {
    tocEl.dataset.empty = "true";
    return;
  }
  tocEl.dataset.empty = "false";

  // The actual scroll container — usually .spec-doc, which has its own
  // overflow-y. The IntersectionObserver only fires on viewport boundary
  // crossings, but the user scrolls inside the container, not the viewport,
  // so we ALSO listen to the container's scroll event. The observer is
  // still useful for the initial paint and for layout shifts.
  const scrollEl = findScrollAncestor(bodyEl);

  activeObserver = new IntersectionObserver(
    () => {
      const chosen = pickActiveHeading(scrollEl);
      if (chosen && chosen.id) setActiveLink(listEl, chosen.id);
    },
    {
      // root: the scroll container if we found one — falls back to the
      // viewport. threshold [0, 1] = fire on edge crossings only.
      root: scrollEl || null,
      threshold: [0, 1],
    },
  );
  activeHeadings.forEach((h) => activeObserver.observe(h));

  // Scroll listener on the actual scroll container. requestAnimationFrame-
  // throttled so we don't recompute on every scroll event (which can fire
  // dozens of times a second on a fast wheel). The rafId is module-scoped
  // so detachScrollHandler() can cancel a pending frame from a previous
  // build before its callback runs against stale state.
  if (scrollEl) {
    activeScrollHandler = () => {
      if (activeScrollRafId) return;
      activeScrollRafId = requestAnimationFrame(() => {
        activeScrollRafId = 0;
        const chosen = pickActiveHeading(scrollEl);
        if (chosen && chosen.id) setActiveLink(listEl, chosen.id);
      });
    };
    activeScrollEl = scrollEl;
    scrollEl.addEventListener("scroll", activeScrollHandler, { passive: true });
  }

  // Initial paint — make sure something is highlighted before the user scrolls.
  const initial = pickActiveHeading(scrollEl);
  if (initial && initial.id) setActiveLink(listEl, initial.id);
}

// localStorage key for collapsed state. String "true" / "false".
const TOC_COLLAPSED_KEY = "minimap.spec.toc.collapsed";

function readPersistedCollapsed() {
  try {
    return localStorage.getItem(TOC_COLLAPSED_KEY) === "true";
  } catch (_err) {
    // Some embeds (sandboxed iframes) throw on localStorage access. Default
    // to expanded — same fallback the sessions sidebar uses.
    return false;
  }
}

function writePersistedCollapsed(value) {
  try {
    localStorage.setItem(TOC_COLLAPSED_KEY, value ? "true" : "false");
  } catch (_err) {
    // Silently ignore — the dataset attribute on the element is the
    // session-level source of truth for the rest of the page.
  }
}

function applyCollapsedState(tocEl, toggleEl, collapsed) {
  if (!tocEl) return;
  tocEl.dataset.collapsed = collapsed ? "true" : "false";
  if (toggleEl) {
    toggleEl.setAttribute("aria-expanded", collapsed ? "false" : "true");
    toggleEl.setAttribute(
      "aria-label",
      collapsed ? "Expand table of contents" : "Collapse table of contents",
    );
    // Flip the chevron glyph to match.
    const glyph = toggleEl.querySelector("[aria-hidden]");
    if (glyph) glyph.textContent = collapsed ? "›" : "‹";
  }
}

// One-shot wiring — called from initSpec at startup. Captures references,
// installs click handlers for the toggle and for in-list anchor jumps,
// and applies the persisted collapse state.
export function wireSpecToc({ dom }) {
  const tocEl = dom.specTocElement || null;
  const listEl = dom.specTocListElement || null;
  const toggleEl = dom.specTocToggleElement || null;
  if (!tocEl || !listEl) return;

  // Apply persisted collapse state before first render so the layout
  // doesn't briefly flash expanded then snap closed.
  applyCollapsedState(tocEl, toggleEl, readPersistedCollapsed());

  if (toggleEl) {
    toggleEl.addEventListener("click", () => {
      const next = tocEl.dataset.collapsed !== "true";
      applyCollapsedState(tocEl, toggleEl, next);
      writePersistedCollapsed(next);
    });
  }

  // Click delegation: capture clicks on TOC anchors and smooth-scroll the
  // matching heading into view. We DO NOT update the URL hash — this app's
  // hash is a query-style routing string (`#repo=...&view=spec&file=...`),
  // not a section fragment, so writing `#section-id` would clobber the
  // route. If shareable section deep-links are needed later, they should
  // ride on a dedicated route param (e.g. &section=...), not the bare hash.
  listEl.addEventListener("click", (event) => {
    const link = event.target.closest("a.spec-toc-link");
    if (!link) return;
    const id = link.dataset.specTocTarget;
    if (!id) return;
    const target = document.getElementById(id);
    if (!target) return;
    event.preventDefault();
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}
