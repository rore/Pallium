// package/minimap/ui/api.js
//
// Browser-native ES module. DOM-free, so it can be unit-tested under
// `node --test` with an injected fetch. All HTTP traffic for the UI flows
// through here; call sites use the named methods rather than building URLs
// or calling fetch directly.

const ROADMAP_PREFIXES = [
  "/api/workspace",
  "/api/worktree-workspace",
  "/api/worktree-sources",
  "/api/worktree-source-workspace",
  "/api/board",
  "/api/scope",
  "/api/items/",
  "/api/metadata-order",
  "/api/lenses/",
  "/api/setup/",
];

function isRoadmapEndpoint(url) {
  return ROADMAP_PREFIXES.some((prefix) => url.startsWith(prefix));
}

export function normalizeError(response, payload) {
  const e = new Error(payload?.error?.message || "Request failed.");
  e.code = payload?.error?.code || "request_failed";
  e.details = payload?.error?.details || null;
  e.statusCode = response.status;
  return e;
}

// `getRepo` is a function (not a string) so the caller can pass a live
// pointer at `state.repoPath`; api.js doesn't need to know about state.
export function createApi({ fetch: fetchImpl, getRepo, getSource } = {}) {
  const f = fetchImpl || (typeof globalThis.fetch === "function" ? globalThis.fetch.bind(globalThis) : null);
  if (!f) throw new Error("createApi: no fetch implementation available");
  const repo = typeof getRepo === "function" ? getRepo : () => "";
  const source = typeof getSource === "function" ? getSource : () => null;

  async function request(url, init = {}, { unbound = false, repoRoot = null } = {}) {
    const headers = new Headers(init.headers || {});
    const setRepoHeader = (value) => {
      if (/[^\x20-\x7e]/.test(value)) headers.set("X-Minimap-Repo-Encoded", encodeURIComponent(value));
      else headers.set("X-Minimap-Repo", value);
    };
    if (init.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json; charset=utf-8");
    }
    const selection = unbound ? null : source();
    if (selection?.mode === "across") {
      if (!selection.identity) throw new Error("Select one checkout before opening or changing an item.");
      const { repoRoot, sourceKey, git, roadmapBinding } = selection.identity;
      setRepoHeader(repoRoot);
      headers.set("X-Minimap-Source-Context", JSON.stringify({ repoRoot, sourceKey, git, roadmapBinding }).replace(/[\u007f-\uffff]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`));
      url = url.replace(/^\/api\//, "/api/source/");
    }
    const repoValue = repoRoot ?? repo();
    if (!selection && isRoadmapEndpoint(url) && repoValue) {
      setRepoHeader(repoValue);
    }
    const response = await f(url, { ...init, headers });
    let payload = null;
    try { payload = await response.json(); } catch {}
    if (!response.ok) throw normalizeError(response, payload);
    return payload;
  }

  function postJson(url, body) {
    return request(url, { method: "POST", body: JSON.stringify(body) });
  }

  function id(value) { return encodeURIComponent(value); }
  function pathParam(value) { return encodeURIComponent(value); }

  return {
    // Roadmap
    loadWorkspace: () => request("/api/workspace"),
    loadWorktreeWorkspace: ({ openedOnly = false } = {}) => request(`/api/worktree-workspace${openedOnly ? "?openedOnly=1" : ""}`, {}, { unbound: true }),
    discoverWorktreeSources: () => request("/api/worktree-sources", {}, { unbound: true }),
    loadSourceWorkspace: (identity) => request("/api/worktree-source-workspace", {
      headers: { "X-Minimap-Source-Context": JSON.stringify(identity).replace(/[\u007f-\uffff]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`) },
    }, { unbound: true, repoRoot: identity.repoRoot }),
    initializeWorkspace: () => request("/api/setup/initialize", { method: "POST" }),
    saveBoard: (groups, expectedRevision) => postJson("/api/board", { groups, expectedRevision }),
    reorderMetadata: (payload) => postJson("/api/metadata-order", payload),
    reorderLensGroup: (field, payload) => postJson(`/api/lenses/${id(field)}/order`, payload),
    saveScope: (scopeText, expectedRevision = null) => postJson("/api/scope", { scopeText, expectedRevision }),
    readItem: (itemId, options = {}) => request(`/api/items/${id(itemId)}`, options),
    readBoardParticipantCounts: ({ includeCompleted = false, ...options } = {}) => request(
      `/api/board/participant-counts${includeCompleted === true ? "?includeCompleted=1" : ""}`, options,
    ),
    readItemParticipants: (itemId, options = {}) => request(`/api/items/${id(itemId)}/participants`, options),
    saveItem: (itemId, payload) => postJson(`/api/items/${id(itemId)}`, payload),

    // Spec sessions — never carry the repo header
    listSessions: () => request("/api/spec-sessions"),
    attachSession: (file) => postJson("/api/spec-sessions/attach", { file }),
    getSessionByFile: (filePath) => request(`/api/spec-sessions/by-file?path=${pathParam(filePath)}`),
    getSessionContext: (filePath) => request(`/api/spec-sessions/by-file/context?path=${pathParam(filePath)}`),
    getSessionContent: (filePath) => request(`/api/spec-sessions/by-file/content?path=${pathParam(filePath)}`),
    removeSession: (filePath) => request(`/api/spec-sessions/by-file?path=${pathParam(filePath)}`, { method: "DELETE" }),
    moveSession: (from, to) => postJson("/api/spec-sessions/by-file/move", { from, to }),
    addComment: (file, payload) => postJson("/api/spec-sessions/by-file/comments", { file, ...payload }),
    addCommentReply: (file, commentId, payload) => postJson(`/api/spec-sessions/by-file/comments/${id(commentId)}/reply`, { file, ...payload }),
    setCommentStatus: (file, commentId, action, payload = {}) => postJson(`/api/spec-sessions/by-file/comments/${id(commentId)}/${action}`, { file, ...payload }),
    addSuggestion: (file, payload) => postJson("/api/spec-sessions/by-file/suggestions", { file, ...payload }),
    addSuggestionReply: (file, suggestionId, payload) => postJson(`/api/spec-sessions/by-file/suggestions/${id(suggestionId)}/reply`, { file, ...payload }),
    setSuggestionStatus: (file, suggestionId, action, payload = {}) => postJson(`/api/spec-sessions/by-file/suggestions/${id(suggestionId)}/${action}`, { file, ...payload }),
    previewSuggestion: (file, suggestionId) => postJson(`/api/spec-sessions/by-file/suggestions/${id(suggestionId)}/preview`, { file }),
    applySuggestion: (file, suggestionId, payload = {}) => postJson(`/api/spec-sessions/by-file/suggestions/${id(suggestionId)}/apply`, { file, ...payload }),
    rollbackSuggestion: (file, suggestionId, payload = {}) => postJson(`/api/spec-sessions/by-file/suggestions/${id(suggestionId)}/rollback`, { file, ...payload }),
  };
}
