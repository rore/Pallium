// package/minimap/ui/state.js
//
// Single state object + tiny pub/sub. DOM-free. Tested with `node --test`.
// app.js imports this once at startup, binds the value to a const, and
// continues to mutate it directly via `state.foo = ...`. The set/update/
// subscribe APIs are available for incremental migration of call sites.

function makeInitial() {
  return {
    appMode: "roadmap",
    repoPath: "",
    workspace: null,
    setupState: null,
    selectedItemId: null,
    currentItem: null,
    activeLens: "board",
    boardLayout: "list",
    dragItemId: null,
    dragColumnIndex: null,
    dragClickSuppressUntil: 0,
    lensesExpanded: false,
    searchQuery: "",
    activeFilters: {},
    filtersExpanded: false,
    collapsedGroups: new Set(),
    scopeCollapsed: false,
    scopeWidth: 272,
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
      selectedQuoteLineRange: null,
      selectedQuoteOffset: null,
      // Map<sourceLine, Element> rebuilt after each render pass so anchor
      // lookups can do an O(1) line→element lookup instead of re-doing
      // text matching for every margin card. Populated by
      // rebuildSpecLineIndex; consumed by anchorTargetElement.
      lineToElement: new Map(),
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
      filesCollapsed: false,
      bodyFrac: 0.66,
      resizingMargin: false,
      viewMode: "review",
      showComments: true,
      showSuggestions: true,
      showResolved: false,
      sidebarSearch: "",
      composerTarget: null,
      lastSeenContentHash: "",
      fileChangedDetected: false,
    },
  };
}

export function createState(initialOverrides = {}) {
  const value = makeInitial();
  // Shallow-merge top-level keys, then deep-merge the `spec` subtree if
  // overrides include one. Other nested objects (collapsedGroups, etc.) are
  // never overridden at startup.
  for (const [key, v] of Object.entries(initialOverrides)) {
    if (key === "spec" && v && typeof v === "object") {
      Object.assign(value.spec, v);
    } else {
      value[key] = v;
    }
  }

  const listeners = new Set();
  function notify() {
    for (const fn of listeners) fn(value);
  }

  return {
    get() { return value; },
    set(patch) { Object.assign(value, patch); notify(); },
    update(mutator) { mutator(value); notify(); },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  };
}
