import http from "node:http";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  AppError,
  initializeWorkspace,
  loadWorkspace,
  readItemById,
  reorderLensField,
  reorderMetadataItem,
  saveBoardByGroups,
  saveItemById,
  saveScopeText,
} from "./src/roadmap.js";
import { loadWorktreeAggregate } from "./src/worktree-aggregate.js";
import { discoverWorktreeSources } from "./src/worktree-sources.js";
import { selectWorktreeParticipantCandidates } from "./src/worktree-presence.js";
import { requirePathInSource, requireRoadmapInSource, verifySourceContext } from "./src/source-bound.js";
import { withSourceWriteGuard } from "./src/source-write-guard.js";
import {
  addFileSessionSuggestion,
  addFileSessionSuggestionReply,
  addFileSessionComment,
  addFileSessionCommentReply,
  attachFileSession,
  getFileSessionContext,
  getFileSessionFileContent,
  getFileSession,
  applyFileSessionSuggestion,
  rollbackFileSessionSuggestion,
  listFileSessions,
  moveFileSession,
  previewFileSessionSuggestion,
  removeFileSession,
  updateFileSessionSuggestionStatus,
  updateFileSessionCommentStatus,
} from "./src/sessions.js";
import { readServerRegistry, writeServerRegistry, deleteServerRegistry, readRuntimeIdentity } from "./src/server-registry.js";
import { matchRoute } from "./src/router.js";
import { createLifecycleLog, lifecycleError } from "./src/server-lifecycle-log.js";
import {
  isTrustedLocalRequest,
  lookupPalliumParticipantCounts,
  lookupPalliumParticipants,
  parsePalliumConfig,
  palliumConfigId,
  resolveRoadmapItemReferences,
  resolveRoadmapItemReference,
} from "./src/pallium.js";

// Re-exported so test/server-router.test.js can import the matcher without
// booting the HTTP server here. (server.js still auto-starts on import — that
// is how the launcher scripts run it.)
export { matchRoute };

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const launchMode = process.send ? "ipc-detached-restart"
  : path.basename(process.argv[1] || "") === "start-server.mjs" ? "foreground-start" : "direct";
let lifecycleLog = createLifecycleLog({ sourcePath: __filename, launchMode });
process.on("uncaughtExceptionMonitor", (error, origin) => {
  try { lifecycleLog("fatal", { origin, error: lifecycleError(error, __dirname) }); } catch {}
});
process.once("exit", (code) => lifecycleLog("exit", { code }));
const staticRoot = path.join(__dirname, "ui");
const cwdFallback = process.cwd();
const requestedPort = Number(process.env.PORT || 4312);
lifecycleLog("startup", { port: Number.isInteger(requestedPort) ? requestedPort : null });
const maxPortAttempts = 20;
const LOCAL_SERVER_HOST = "127.0.0.1";
const palliumConfig = parsePalliumConfig(
  process.env.MINIMAP_PALLIUM_ENDPOINT,
  process.env.MINIMAP_PALLIUM_DASHBOARD_ENDPOINT,
);

const runtimeIdentity = await readRuntimeIdentity(__filename);
const serverVersion = runtimeIdentity.version;
lifecycleLog = createLifecycleLog({ ...runtimeIdentity, launchMode });

// Set when /api/shutdown has been observed once; prevents a second concurrent
// caller from scheduling a duplicate shutdown() (which would race process.exit
// against the second response being flushed).
let shuttingDown = false;
let restartAcknowledged = false;
if (process.send) {
  process.on("message", (message) => {
    if (message?.type === "minimap-ready-ack") restartAcknowledged = true;
  });
  process.once("disconnect", () => {
    if (!restartAcknowledged && !shuttingDown) {
      shuttingDown = true;
      void shutdown("RESTART_PARENT_DISCONNECTED");
    }
  });
}

async function clearOwnRegistry() {
  try {
    if ((await readServerRegistry())?.pid === process.pid) await deleteServerRegistry();
  } catch (error) {
    lifecycleLog("registry-cleanup-failed", { error: lifecycleError(error, __dirname) });
    throw error;
  }
}

const contentTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml; charset=utf-8"],
]);

function sendJson(response, statusCode, payload) {
  response.writeHead(statusCode, { "Content-Type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(payload));
}

function sendText(response, statusCode, payload, contentType) {
  response.writeHead(statusCode, { "Content-Type": contentType });
  response.end(payload);
}

async function readRequestBody(request) {
  const chunks = [];

  for await (const chunk of request) {
    chunks.push(chunk);
  }

  return Buffer.concat(chunks).toString("utf8");
}

function getStaticFilePath(urlPathname) {
  const requestedPath = urlPathname === "/" ? "/index.html" : urlPathname;
  const normalized = path.normalize(requestedPath).replace(/^([.][.][/\\])+/, "");
  const resolved = path.join(staticRoot, normalized);
  const staticBase = `${staticRoot}${path.sep}`;

  if (!resolved.startsWith(staticBase) && resolved !== path.join(staticRoot, "index.html")) {
    return null;
  }

  return resolved;
}

function parseJsonBody(rawBody) {
  try {
    return JSON.parse(rawBody || "{}");
  } catch {
    throw new AppError("Request body must be valid JSON.", 400, "bad_request");
  }
}

function requireQueryParam(requestUrl, name) {
  const value = requestUrl.searchParams.get(name);
  if (!value || value.trim() === "") {
    throw new AppError(`Missing required query parameter "${name}".`, 400, "bad_request");
  }
  return value;
}

async function withJsonBody(request) {
  const raw = await readRequestBody(request);
  if (request.boundRepoRoot) await validateBoundRequest(request);
  const body = parseJsonBody(raw);
  if (request.boundSpecRepo) {
    request.boundBodyPaths = ["file", "from", "to"].filter((key) => Object.hasOwn(body, key)).map((key) => body[key]);
    for (const candidate of request.boundBodyPaths) await requirePathInSource(request.boundSpecRepo, candidate);
  }
  return body;
}

async function validateBoundRequest(request) {
  await verifySourceContext(request.boundRepoRoot, request.boundExpected);
  if (request.boundSpecRepo) {
    if (request.boundUrl.searchParams.has("path")) {
      await requirePathInSource(request.boundRepoRoot, request.boundUrl.searchParams.get("path"));
    }
    for (const candidate of request.boundBodyPaths || []) await requirePathInSource(request.boundRepoRoot, candidate);
    return;
  }
  const roadmap = await requireRoadmapInSource(request.boundRepoRoot);
  const expectedPath = request.boundExpected.roadmapBinding?.resolvedPath;
  const actualPath = roadmap.resolvedPath;
  const samePath = typeof expectedPath === "string" && path.isAbsolute(expectedPath)
    && (process.platform === "win32"
      ? path.normalize(expectedPath).toLowerCase() === path.normalize(actualPath).toLowerCase()
      : path.normalize(expectedPath) === path.normalize(actualPath));
  if (request.boundExpected.roadmapBinding?.roadmapPath !== roadmap.roadmapPath
    || !samePath) {
    throw new AppError("Roadmap location changed. Reload this source before continuing.", 409, "source_changed");
  }
}

function requireFileFromBody(body, message) {
  if (typeof body.file !== "string" || body.file.trim() === "") {
    throw new AppError(message, 400, "bad_request");
  }
  return body.file;
}

async function resolveRoadmapRepo(request) {
  if (request.boundRepoRoot) return request.boundRepoRoot;
  const encodedRepo = request.headers["x-minimap-repo-encoded"];
  let headerRepo = request.headers["x-minimap-repo"];
  if (encodedRepo !== undefined) {
    if (typeof encodedRepo !== "string" || headerRepo !== undefined) {
      throw new AppError("Invalid repo path headers.", 400, "bad_request");
    }
    try { headerRepo = decodeURIComponent(encodedRepo); }
    catch { throw new AppError("Invalid encoded repo path.", 400, "bad_request"); }
  }
  const candidate = (typeof headerRepo === "string" && headerRepo.trim()) || cwdFallback;
  const resolved = path.resolve(candidate);
  try {
    const stat = await fs.stat(resolved);
    if (!stat.isDirectory()) {
      throw new AppError(`Repo path is not a directory: ${resolved}`, 400, "bad_request");
    }
  } catch (error) {
    if (error instanceof AppError) throw error;
    if (error && error.code === "ENOENT") {
      throw new AppError(`Repo path does not exist: ${resolved}`, 400, "bad_request");
    }
    throw error;
  }
  return resolved;
}

// Cross-link spec sessions to roadmap items in the active repo. The roadmap
// workspace gets a side-channel map keyed on item.id so the UI can render
// "this item has 3 open comments" badges without a second request. Sessions
// whose targetFile lies outside the active repo are intentionally ignored —
// we only surface links the user can act on from this workspace view.
async function buildSpecSessionsByItemId(repoRoot, workspace) {
  let sessions;
  try {
    sessions = await listFileSessions();
  } catch {
    return {};
  }

  const sessionsByPath = new Map();
  for (const session of sessions) {
    if (session && typeof session.targetFile === "string") {
      sessionsByPath.set(session.targetFile, session);
    }
  }

  const linked = {};
  // workspace.items is the full id-keyed map; boardGroups items are summaries
  // without filePath. The full map covers both board items AND off-board ones.
  for (const item of Object.values(workspace.items ?? {})) {
    if (!item.filePath) continue;
    // item.filePath is already absolute (raw from itemRecord). Forward-slash
    // it to match how listFileSessions normalizes targetFile.
    const absolute = path.resolve(item.filePath).replace(/\\/g, "/");
    const session = sessionsByPath.get(absolute);
    if (!session) continue;
    linked[item.id] = session.availability?.status === "unavailable"
      ? { sessionId: session.id, targetFile: session.targetFile, unavailable: true }
      : {
          sessionId: session.id,
          targetFile: session.targetFile,
          openComments: session.counts.openComments,
          pendingSuggestions: session.counts.pendingSuggestions,
        };
  }
  return linked;
}

// ---------------------------------------------------------------------------
// Route handlers. Each handler has signature (request, response, ctx) where
// ctx = { url, params }. params is the array of regex captures (if any).
// ---------------------------------------------------------------------------

async function handleHealth(request, response) {
  sendJson(response, 200, { ok: true, runtime: runtimeIdentity, pid: process.pid, participants: {
    mode: palliumConfig.endpoint ? "enabled" : "disabled",
    links: palliumConfig.dashboardEndpoint ? "enabled" : "disabled",
    configId: palliumConfigId(palliumConfig),
  } });
}

async function handleShutdown(request, response) {
  const expectedPid = request.headers["x-minimap-instance-pid"] ?? null;
  if (expectedPid !== null && expectedPid !== String(process.pid)) {
    sendJson(response, 409, { error: "server_instance_mismatch" });
    return;
  }

  // Cross-platform graceful shutdown. On Windows, child_process.kill() does
  // not deliver SIGTERM/SIGINT to the JS event loop, so a signal-based stop
  // from another process is unreliable. POST /api/shutdown works everywhere
  // because it's plain HTTP and runs on the same code path as the signal
  // handler. We send the response first, then exit on the next tick so the
  // client sees a clean 200 before the socket closes.
  sendJson(response, 200, { shuttingDown: true });
  if (!shuttingDown) {
    shuttingDown = true;
    response.on("finish", () => {
      // Defer one tick so the kernel has flushed the response.
      setImmediate(() => { void shutdown("SHUTDOWN_API"); });
    });
  }
}

async function handleSpecAttach(request, response) {
  const body = await withJsonBody(request);
  const file = requireFileFromBody(body, "Spec-session attach requires a file path.");
  const result = await attachFileSession(file, { cwd: cwdFallback });
  sendJson(response, 200, result);
}

async function handleListSpecSessions(request, response) {
  let sessions = await listFileSessions();
  if (request.boundSpecRepo) {
    const scoped = await Promise.all(sessions.map(async (session) => {
      try { await requirePathInSource(request.boundSpecRepo, session.targetFile); return session; }
      catch { return null; }
    }));
    sessions = scoped.filter(Boolean);
  }
  sendJson(response, 200, { sessions });
}

async function handleGetSpecSession(request, response, ctx) {
  const file = requireQueryParam(ctx.url, "path");
  const session = await getFileSession(file, { cwd: cwdFallback });
  sendJson(response, 200, { session });
}

async function handleGetSpecContext(request, response, ctx) {
  const file = requireQueryParam(ctx.url, "path");
  const context = await getFileSessionContext(file, { cwd: cwdFallback });
  sendJson(response, 200, context);
}

async function handleGetSpecContent(request, response, ctx) {
  const file = requireQueryParam(ctx.url, "path");
  const content = await getFileSessionFileContent(file, { cwd: cwdFallback });
  sendJson(response, 200, content);
}

async function handleRemoveSpecSession(request, response, ctx) {
  const file = requireQueryParam(ctx.url, "path");
  const result = await removeFileSession(file, { cwd: cwdFallback });
  sendJson(response, 200, result);
}

async function handleMoveSpecSession(request, response) {
  const body = await withJsonBody(request);

  if (typeof body.from !== "string" || body.from.trim() === "" || typeof body.to !== "string" || body.to.trim() === "") {
    throw new AppError("Spec-session move requires from and to file paths.", 400, "bad_request");
  }

  const result = await moveFileSession(body.from, body.to, { cwd: cwdFallback });
  sendJson(response, 200, result);
}

async function handleAddComment(request, response) {
  const body = await withJsonBody(request);
  const file = requireFileFromBody(body, "Comment creation requires a file path.");
  const result = await addFileSessionComment(file, body, { cwd: cwdFallback });
  sendJson(response, 200, result);
}

async function handleCommentReply(request, response, ctx) {
  const body = await withJsonBody(request);
  const file = requireFileFromBody(body, "Comment reply requires a file path.");
  const result = await addFileSessionCommentReply(file, decodeURIComponent(ctx.params[0]), body, { cwd: cwdFallback });
  sendJson(response, 200, result);
}

async function handleSuggestionReply(request, response, ctx) {
  const body = await withJsonBody(request);
  const file = requireFileFromBody(body, "Suggestion reply requires a file path.");
  const result = await addFileSessionSuggestionReply(file, decodeURIComponent(ctx.params[0]), body, { cwd: cwdFallback });
  sendJson(response, 200, result);
}

async function handleCommentStatus(request, response, ctx) {
  const body = await withJsonBody(request);
  const file = requireFileFromBody(body, "Comment status update requires a file path.");
  const status = ctx.params[1] === "resolve" ? "resolved" : "open";
  const result = await updateFileSessionCommentStatus(file, decodeURIComponent(ctx.params[0]), status, body, { cwd: cwdFallback });
  sendJson(response, 200, result);
}

async function handleAddSuggestion(request, response) {
  const body = await withJsonBody(request);
  const file = requireFileFromBody(body, "Suggestion creation requires a file path.");
  const result = await addFileSessionSuggestion(file, body, { cwd: cwdFallback });
  sendJson(response, 200, result);
}

async function handleSuggestionStatus(request, response, ctx) {
  const body = await withJsonBody(request);
  const file = requireFileFromBody(body, "Suggestion status update requires a file path.");
  const statusByAction = {
    accept: "accepted",
    reject: "rejected",
    reopen: "pending",
  };
  const status = statusByAction[ctx.params[1]];
  const result = await updateFileSessionSuggestionStatus(file, decodeURIComponent(ctx.params[0]), status, body, { cwd: cwdFallback });
  sendJson(response, 200, result);
}

async function handleSuggestionPreviewApply(request, response, ctx) {
  const body = await withJsonBody(request);
  const file = requireFileFromBody(body, "Suggestion preview/apply/rollback requires a file path.");
  const suggestionId = decodeURIComponent(ctx.params[0]);
  const action = ctx.params[1];
  let result;
  if (action === "apply") {
    result = await applyFileSessionSuggestion(file, suggestionId, body, { cwd: cwdFallback });
  } else if (action === "rollback") {
    result = await rollbackFileSessionSuggestion(file, suggestionId, body, { cwd: cwdFallback });
  } else {
    result = await previewFileSessionSuggestion(file, suggestionId, { cwd: cwdFallback });
  }
  sendJson(response, 200, result);
}

async function handleWorkspace(request, response) {
  const repoRoot = await resolveRoadmapRepo(request);
  const workspace = await loadWorkspace(repoRoot);
  workspace.specSessionsByItemId = await buildSpecSessionsByItemId(repoRoot, workspace);
  sendJson(response, 200, workspace);
}

async function handleWorktreeSources(request, response) {
  const repoRoot = await resolveRoadmapRepo(request);
  sendJson(response, 200, await discoverWorktreeSources(repoRoot));
}

async function handleWorktreeSourceWorkspace(request, response) {
  const rawContext = request.headers["x-minimap-source-context"];
  if (typeof rawContext !== "string" || !rawContext) {
    throw new AppError("Source context is required.", 400, "source_context_required");
  }
  let expected;
  try { expected = JSON.parse(rawContext); }
  catch { throw new AppError("Invalid source context.", 400, "bad_request"); }
  if (!expected || typeof expected !== "object" || Array.isArray(expected)) {
    throw new AppError("Invalid source context.", 400, "bad_request");
  }
  if (expected.roadmapBinding !== undefined && (!expected.roadmapBinding
    || typeof expected.roadmapBinding !== "object" || Array.isArray(expected.roadmapBinding)
    || typeof expected.roadmapBinding.roadmapPath !== "string"
    || typeof expected.roadmapBinding.resolvedPath !== "string"
    || !path.isAbsolute(expected.roadmapBinding.resolvedPath))) {
    throw new AppError("Invalid source context.", 400, "bad_request");
  }

  const repoRoot = await resolveRoadmapRepo(request);
  await verifySourceContext(repoRoot, expected);
  const roadmap = await requireRoadmapInSource(repoRoot);
  const workspace = await loadWorkspace(repoRoot);
  workspace.specSessionsByItemId = await buildSpecSessionsByItemId(repoRoot, workspace);

  const source = await verifySourceContext(repoRoot, expected);
  const currentRoadmap = await requireRoadmapInSource(repoRoot);
  const samePath = (left, right) => typeof left === "string" && typeof right === "string"
    && path.isAbsolute(left) && path.isAbsolute(right)
    && (process.platform === "win32"
      ? path.normalize(left).toLowerCase() === path.normalize(right).toLowerCase()
      : path.normalize(left) === path.normalize(right));
  if (roadmap.roadmapPath !== workspace.roadmapPath || !samePath(roadmap.resolvedPath, workspace.resolvedPath)
    || roadmap.roadmapPath !== currentRoadmap.roadmapPath || !samePath(roadmap.resolvedPath, currentRoadmap.resolvedPath)
    || (expected.roadmapBinding && (expected.roadmapBinding.roadmapPath !== roadmap.roadmapPath
      || !samePath(expected.roadmapBinding.resolvedPath, roadmap.resolvedPath)))) {
    throw new AppError("Roadmap location changed. Reload this source before continuing.", 409, "source_changed");
  }
  sendJson(response, 200, { source: { ...source, roadmapBinding: {
    roadmapPath: roadmap.roadmapPath, resolvedPath: roadmap.resolvedPath,
  } }, workspace });
}

async function handleWorktreeWorkspace(request, response) {
  const repoRoot = await resolveRoadmapRepo(request);
  const openedOnlyValues = new URL(request.url, "http://localhost").searchParams.getAll("openedOnly");
  if (openedOnlyValues.length > 1 || (openedOnlyValues.length && openedOnlyValues[0] !== "1")) {
    throw new AppError("Invalid openedOnly query parameter.", 400, "bad_request");
  }
  const openedOnly = openedOnlyValues.length === 1;
  const aggregate = await loadWorktreeAggregate(repoRoot, { openedOnly });
  aggregate.participantCounts = openedOnly
    ? { status: "loading", counts: [], partial: true, includeCompleted: true }
    : await lookupWorktreeParticipantCounts(request, response, repoRoot, aggregate);
  if (!response.destroyed) sendJson(response, 200, aggregate);
}

async function lookupWorktreeParticipantCounts(request, response, repoRoot, aggregate) {
  if (!palliumConfig.configured) {
    return { status: "disabled", counts: [], partial: Boolean(aggregate.partial), includeCompleted: true };
  }
  if (!aggregate.workspace) {
    return { status: "identity-unavailable", counts: [], partial: true, includeCompleted: true };
  }
  const candidates = selectWorktreeParticipantCandidates(aggregate, { includeCompleted: true });
  const partial = candidates.partial || candidates.ambiguous.length > 0;
  if (!candidates.features.length) {
    return { status: "ok", counts: [], partial, includeCompleted: true };
  }
  const references = await resolveRoadmapItemReferences(repoRoot, aggregate.workspace.roadmapPath, candidates.features.map((feature) => feature.id));
  if (!references) {
    return { status: "identity-unavailable", counts: [], partial: true, includeCompleted: true };
  }
  const controller = new AbortController();
  const abort = () => controller.abort();
  request.once("aborted", abort);
  response.once("close", abort);
  try {
    const result = await lookupPalliumParticipantCounts(palliumConfig, references, { signal: controller.signal });
    return {
      status: result.status,
      counts: result.status === "ok" ? result.counts.map((row, index) => ({
        featureKey: candidates.features[index].key, participantCount: row.participant_count,
        recentParticipantCount: row.recent_participant_count, dormantParticipantCount: row.dormant_participant_count,
      })) : [],
      partial,
      ...(result.status === "ok" ? { asOf: result.asOf, recentSeconds: result.recentSeconds } : {}),
      includeCompleted: true,
    };
  } catch (error) {
    if (!controller.signal.aborted) throw error;
    return { status: "unavailable", counts: [], partial: true, includeCompleted: true };
  } finally {
    request.off("aborted", abort);
    response.off("close", abort);
  }
}

async function handleInitialize(request, response) {
  const repoRoot = await resolveRoadmapRepo(request);
  const workspace = await initializeWorkspace(repoRoot);
  sendJson(response, 200, workspace);
}

async function handleBoard(request, response) {
  const repoRoot = await resolveRoadmapRepo(request);
  const body = await withJsonBody(request);
  if (request.boundRepoRoot && typeof body.expectedRevision !== "string") {
    throw new AppError("Bound board update requires expectedRevision.", 400, "revision_required");
  }
  const workspace = await saveBoardByGroups(repoRoot, body.groups, body.expectedRevision);
  sendJson(response, 200, workspace);
}

async function handleMetadataOrder(request, response) {
  const repoRoot = await resolveRoadmapRepo(request);
  const body = await withJsonBody(request);
  const workspace = await reorderMetadataItem(repoRoot, body);
  sendJson(response, 200, workspace);
}

async function handleLensOrder(request, response, ctx) {
  const repoRoot = await resolveRoadmapRepo(request);
  const body = await withJsonBody(request);
  const workspace = await reorderLensField(repoRoot, decodeURIComponent(ctx.params[0]), body);
  sendJson(response, 200, workspace);
}
async function handleScope(request, response) {
  const repoRoot = await resolveRoadmapRepo(request);
  const body = await withJsonBody(request);

  if (typeof body.scopeText !== "string") {
    throw new AppError("Scope update must provide scopeText.", 400, "bad_request");
  }
  if (request.boundRepoRoot && typeof body.expectedRevision !== "string") {
    throw new AppError("Bound scope update requires expectedRevision.", 400, "revision_required");
  }

  const workspace = await saveScopeText(repoRoot, body.scopeText, body.expectedRevision ?? null);
  sendJson(response, 200, workspace);
}

async function handleItemParticipants(request, response, ctx) {
  if (!palliumConfig.configured) {
    sendJson(response, 200, await lookupPalliumParticipants(palliumConfig, null));
    return;
  }

  const repoRoot = await resolveRoadmapRepo(request);
  const id = decodeURIComponent(ctx.params[0]);
  const item = await readItemById(repoRoot, id);
  const workspace = await loadWorkspace(repoRoot);
  const reference = await resolveRoadmapItemReference(repoRoot, workspace.roadmapPath, item.id);
  const controller = new AbortController();
  const abort = () => controller.abort();
  request.once("aborted", abort);
  response.once("close", abort);

  try {
    const result = await lookupPalliumParticipants(palliumConfig, reference, { signal: controller.signal });
    if (!response.destroyed) sendJson(response, 200, result);
  } catch (error) {
    if (!controller.signal.aborted) throw error;
  } finally {
    request.off("aborted", abort);
    response.off("close", abort);
  }
}

async function handleBoardParticipantCounts(request, response, ctx) {
  const includeCompletedValues = ctx.url.searchParams.getAll("includeCompleted");
  if (includeCompletedValues.length > 1 || includeCompletedValues.some((value) => !["0", "1"].includes(value))) {
    throw new AppError("includeCompleted must be 0 or 1 and appear at most once.", 400, "bad_request");
  }
  const includeCompleted = includeCompletedValues[0] === "1";
  if (!palliumConfig.configured) {
    sendJson(response, 200, { status: "disabled", counts: [], partial: false });
    return;
  }
  const controller = new AbortController();
  const abort = () => controller.abort();
  request.once("aborted", abort);
  response.once("close", abort);
  try {
    const repoRoot = await resolveRoadmapRepo(request);
    const workspace = await loadWorkspace(repoRoot);
    const boardIds = [];
    const seen = new Set();
    for (const group of workspace.boardGroups || []) {
      for (const item of group.items || []) {
        const fullItem = workspace.items?.[item?.id];
        const status = String(fullItem?.status || "").trim().toLowerCase();
        if (
          item?.missing || !fullItem || seen.has(item.id)
          || (!includeCompleted && ["done", "shipped", "superseded", "cancelled", "canceled"].includes(status))
        ) continue;
        seen.add(item.id);
        boardIds.push(item.id);
      }
    }
    const partial = boardIds.length > 200;
    const itemIds = boardIds.slice(0, 200);
    if (!itemIds.length) {
      if (!response.destroyed) sendJson(response, 200, {
        status: "ok", counts: [], partial, ...(includeCompleted ? { includeCompleted: true } : {}),
      });
      return;
    }
    const references = await resolveRoadmapItemReferences(repoRoot, workspace.roadmapPath, itemIds);
    if (references === null) {
      if (!response.destroyed) sendJson(response, 200, { status: "identity-unavailable", counts: [], partial });
      return;
    }
    const result = await lookupPalliumParticipantCounts(palliumConfig, references, { signal: controller.signal });
    if (!response.destroyed) {
      const counts = result.status === "ok"
        ? result.counts.map((row, index) => ({
          itemId: itemIds[index], participantCount: row.participant_count,
          recentParticipantCount: row.recent_participant_count, dormantParticipantCount: row.dormant_participant_count,
        }))
        : [];
      sendJson(response, 200, {
        status: result.status, counts, partial,
        ...(result.status === "ok" ? { asOf: result.asOf, recentSeconds: result.recentSeconds } : {}),
        ...(result.status === "ok" && includeCompleted ? { includeCompleted: true } : {}),
      });
    }
  } catch (error) {
    if (!controller.signal.aborted) throw error;
  } finally {
    request.off("aborted", abort);
    response.off("close", abort);
  }
}
async function handleGetItem(request, response, ctx) {
  const repoRoot = await resolveRoadmapRepo(request);
  const item = await readItemById(repoRoot, decodeURIComponent(ctx.params[0]));
  sendJson(response, 200, item);
}

async function handleSaveItem(request, response, ctx) {
  const repoRoot = await resolveRoadmapRepo(request);
  const id = decodeURIComponent(ctx.params[0]);
  const body = await withJsonBody(request);
  if (request.boundRepoRoot && typeof body.expectedRevision !== "string") {
    throw new AppError("Bound item update requires expectedRevision.", 400, "revision_required");
  }

  if (body.id && body.id !== id) {
    throw new AppError("Item id in request body must match the URL.", 400, "bad_request");
  }

  const item = await saveItemById(repoRoot, id, body);
  sendJson(response, 200, item);
}

// Route ORDER matches the original if/else chain. Some patterns overlap
// (e.g. /comments/:id/reply vs /comments/:id/resolve), so the more specific
// patterns must come first. Keep this list in declaration order.
const routes = [
  { method: "GET",    pattern: /^\/health$/, handler: handleHealth },
  { method: "POST",   pattern: /^\/api\/shutdown$/, handler: handleShutdown },
  { method: "GET",    pattern: /^\/api\/worktree-sources$/, handler: handleWorktreeSources },
  { method: "GET",    pattern: /^\/api\/worktree-source-workspace$/, handler: handleWorktreeSourceWorkspace },
  { method: "GET",    pattern: /^\/api\/worktree-workspace$/, handler: handleWorktreeWorkspace },
  { method: "POST",   pattern: /^\/api\/spec-sessions\/attach$/, handler: handleSpecAttach },
  { method: "GET",    pattern: /^\/api\/spec-sessions$/, handler: handleListSpecSessions },
  { method: "GET",    pattern: /^\/api\/spec-sessions\/by-file$/, handler: handleGetSpecSession },
  { method: "GET",    pattern: /^\/api\/spec-sessions\/by-file\/context$/, handler: handleGetSpecContext },
  { method: "GET",    pattern: /^\/api\/spec-sessions\/by-file\/content$/, handler: handleGetSpecContent },
  { method: "DELETE", pattern: /^\/api\/spec-sessions\/by-file$/, handler: handleRemoveSpecSession },
  { method: "DELETE", pattern: /^\/api\/spec-sessions\/by-file\/context$/, handler: handleRemoveSpecSession },
  { method: "POST",   pattern: /^\/api\/spec-sessions\/by-file\/move$/, handler: handleMoveSpecSession },
  { method: "POST",   pattern: /^\/api\/spec-sessions\/by-file\/comments$/, handler: handleAddComment },
  { method: "POST",   pattern: /^\/api\/spec-sessions\/by-file\/comments\/([^/]+)\/reply$/, handler: handleCommentReply },
  { method: "POST",   pattern: /^\/api\/spec-sessions\/by-file\/suggestions\/([^/]+)\/reply$/, handler: handleSuggestionReply },
  { method: "POST",   pattern: /^\/api\/spec-sessions\/by-file\/comments\/([^/]+)\/(resolve|reopen)$/, handler: handleCommentStatus },
  { method: "POST",   pattern: /^\/api\/spec-sessions\/by-file\/suggestions$/, handler: handleAddSuggestion },
  { method: "POST",   pattern: /^\/api\/spec-sessions\/by-file\/suggestions\/([^/]+)\/(accept|reject|reopen)$/, handler: handleSuggestionStatus },
  { method: "POST",   pattern: /^\/api\/spec-sessions\/by-file\/suggestions\/([^/]+)\/(preview|apply|rollback)$/, handler: handleSuggestionPreviewApply },
  { method: "GET",    pattern: /^\/api\/workspace$/, handler: handleWorkspace },
  { method: "POST",   pattern: /^\/api\/setup\/initialize$/, handler: handleInitialize },
  { method: "POST",   pattern: /^\/api\/board$/, handler: handleBoard },
  { method: "POST",   pattern: /^\/api\/metadata-order$/, handler: handleMetadataOrder },
  { method: "POST",   pattern: /^\/api\/lenses\/([^/]+)\/order$/, handler: handleLensOrder },
  { method: "POST",   pattern: /^\/api\/scope$/, handler: handleScope },
  { method: "GET",    pattern: /^\/api\/board\/participant-counts$/, handler: handleBoardParticipantCounts },
  { method: "GET",    pattern: /^\/api\/items\/([^/]+)\/participants$/, handler: handleItemParticipants },
  { method: "GET",    pattern: /^\/api\/items\/([^/]+)$/, handler: handleGetItem },
  { method: "POST",   pattern: /^\/api\/items\/([^/]+)$/, handler: handleSaveItem },
];

async function handleApi(request, response, requestUrl) {
  const bound = requestUrl.pathname.startsWith("/api/source/");
  const routedUrl = bound ? new URL(requestUrl) : requestUrl;
  if (bound) routedUrl.pathname = requestUrl.pathname.replace(/^\/api\/source\//, "/api/");
  const match = matchRoute(routes, request.method, routedUrl.pathname);
  if (!match) return false;
  if (!isTrustedLocalRequest(request)) {
    throw new AppError("Minimap API is available only from this local origin.", 403, "forbidden");
  }
  if (bound) {
    if (["/api/shutdown", "/api/worktree-workspace", "/api/setup/initialize"].includes(routedUrl.pathname)) {
      throw new AppError("Route cannot be source-bound.", 400, "bad_request");
    }
    const rawContext = request.headers["x-minimap-source-context"];
    if (typeof rawContext !== "string" || !rawContext) {
      throw new AppError("Source context is required.", 400, "source_context_required");
    }
    let expected;
    try { expected = JSON.parse(rawContext); }
    catch { throw new AppError("Invalid source context.", 400, "bad_request"); }
    const repoRoot = await resolveRoadmapRepo(request);
    request.boundRepoRoot = repoRoot;
    request.boundExpected = expected;
    request.boundSpecRepo = routedUrl.pathname.startsWith("/api/spec-sessions") ? repoRoot : null;
    request.boundUrl = routedUrl;
    await validateBoundRequest(request);
  }
  if (bound) await withSourceWriteGuard(() => validateBoundRequest(request),
    () => match.handler(request, response, { url: routedUrl, params: match.params }),
    (candidate) => requirePathInSource(request.boundRepoRoot, candidate));
  else await match.handler(request, response, { url: routedUrl, params: match.params });
  return true;
}

async function requestListener(request, response) {
  const requestUrl = new URL(request.url || "/", "http://localhost");
  const pathname = requestUrl.pathname;

  try {
    const handled = await handleApi(request, response, requestUrl);

    if (handled) {
      return;
    }

    if (request.method !== "GET") {
      sendJson(response, 405, { error: { code: "method_not_allowed", message: "Method not allowed." } });
      return;
    }

    const filePath = getStaticFilePath(pathname);

    if (!filePath) {
      sendJson(response, 404, { error: { code: "not_found", message: "Not found." } });
      return;
    }

    let file;

    try {
      file = await fs.readFile(filePath, "utf8");
    } catch (error) {
      if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
        sendJson(response, 404, { error: { code: "not_found", message: "Not found." } });
        return;
      }
      throw error;
    }

    const extension = path.extname(filePath);
    const contentType = contentTypes.get(extension) || "application/octet-stream";

    // Static HTML is served as-is. Repo name is fetched client-side from /api/workspace.
    sendText(response, 200, file, contentType);
  } catch (error) {
    if (error instanceof AppError) {
      sendJson(response, error.statusCode, {
        error: {
          code: error.code,
          message: error.message,
          details: error.details ?? null,
        },
      });
      return;
    }

    sendJson(response, 500, {
      error: {
        code: "internal_error",
        message: "Unexpected server error.",
      },
    });
  }
}

function listenOnce(server, port) {
  return new Promise((resolve, reject) => {
    const onListening = () => {
      server.off("error", onError);
      resolve();
    };
    const onError = (error) => {
      server.off("listening", onListening);
      reject(error);
    };

    server.once("listening", onListening);
    server.once("error", onError);
    server.listen(port, LOCAL_SERVER_HOST);
  });
}

async function listenOnAvailablePort(server, startingPort) {
  let port = startingPort;

  for (let attempt = 0; attempt < maxPortAttempts; attempt += 1) {
    try {
      await listenOnce(server, port);
      return port;
    } catch (error) {
      if (error && typeof error === "object" && "code" in error && error.code === "EADDRINUSE") {
        port += 1;
        continue;
      }

      throw error;
    }
  }

  throw new Error(`Could not find a free port after trying ${maxPortAttempts} ports starting at ${startingPort}.`);
}

const server = http.createServer(requestListener);

const noFallback = process.env.MINIMAP_NO_PORT_FALLBACK === "1";

async function startServer() {
  try {
    let boundPort;
    if (noFallback) {
      await listenOnce(server, requestedPort);
      boundPort = requestedPort;
    } else {
      boundPort = await listenOnAvailablePort(server, requestedPort);
    }
    const fallbackNote = boundPort === requestedPort ? "" : ` (requested ${requestedPort})`;
    await writeServerRegistry({
      pid: process.pid,
      port: boundPort,
      startedAt: new Date().toISOString(),
      version: serverVersion,
      participantMode: palliumConfig.endpoint ? "enabled" : "disabled",
      participantConfigId: palliumConfigId(palliumConfig),
    });
    lifecycleLog("started", { port: boundPort });
    process.send?.({ type: "minimap-ready", pid: process.pid, port: boundPort });
    process.stdout.write(`Minimap running at http://localhost:${boundPort}${fallbackNote}\n`);
  } catch (error) {
    lifecycleLog("startup-failed", { error: lifecycleError(error, __dirname) });
    if (error && error.code === "EADDRINUSE" && noFallback) {
      // The launcher will re-probe.
      throw error;
    }
    try { await clearOwnRegistry(); } catch {}
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}

async function shutdown(signal) {
  lifecycleLog("shutdown", { reason: signal });
  try {
    await clearOwnRegistry();
  } catch (error) {
    process.stderr.write(`Registry cleanup failed: ${error.message}\n`);
  }
  process.exit(signal === "SIGINT" ? 130 : 0);
}

// Graceful shutdown handlers. On Linux/Mac, SIGTERM and SIGINT both reach this
// handler. On Windows, terminal Ctrl-C is delivered as SIGINT (works); but
// child_process.kill() bypasses signal delivery via TerminateProcess() (does
// not work — registry cleanup relies on probeRunningServer's /health check
// to detect stale entries on the next launch).
process.once("SIGTERM", () => shutdown("SIGTERM"));
process.once("SIGINT", () => shutdown("SIGINT"));

await startServer();
