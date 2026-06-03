// package/minimap/ui/api.js
//
// Browser-native ES module. DOM-free, so it can be unit-tested under
// `node --test` with an injected fetch. All HTTP traffic for the UI flows
// through here; call sites use the named methods rather than building URLs
// or calling fetch directly.

const ROADMAP_PREFIXES = [
  "/api/workspace",
  "/api/board",
  "/api/scope",
  "/api/items/",
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
export function createApi({ fetch: fetchImpl, getRepo } = {}) {
  const f = fetchImpl || (typeof globalThis.fetch === "function" ? globalThis.fetch.bind(globalThis) : null);
  if (!f) throw new Error("createApi: no fetch implementation available");
  const repo = typeof getRepo === "function" ? getRepo : () => "";

  async function request(url, init = {}) {
    const headers = new Headers(init.headers || {});
    if (init.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json; charset=utf-8");
    }
    const repoValue = repo();
    if (isRoadmapEndpoint(url) && repoValue) {
      headers.set("X-Minimap-Repo", repoValue);
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
    initializeWorkspace: () => request("/api/setup/initialize", { method: "POST" }),
    saveBoard: (groups) => postJson("/api/board", { groups }),
    saveScope: (scopeText) => postJson("/api/scope", { scopeText }),
    readItem: (itemId) => request(`/api/items/${id(itemId)}`),
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
