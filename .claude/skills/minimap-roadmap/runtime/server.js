import http from "node:http";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  AppError,
  initializeWorkspace,
  loadWorkspace,
  readItemById,
  saveBoardByGroups,
  saveItemById,
  saveScopeText,
} from "./src/roadmap.js";
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
import { writeServerRegistry, deleteServerRegistry } from "./src/server-registry.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const staticRoot = path.join(__dirname, "ui");
const cwdFallback = process.cwd();
const requestedPort = Number(process.env.PORT || 4312);
const maxPortAttempts = 20;

const packageJsonPath = path.join(__dirname, "package.json");
const serverVersion = JSON.parse(await fs.readFile(packageJsonPath, "utf8")).version || "0.0.0";

// Set when /api/shutdown has been observed once; prevents a second concurrent
// caller from scheduling a duplicate shutdown() (which would race process.exit
// against the second response being flushed).
let shuttingDown = false;

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

async function resolveRoadmapRepo(request) {
  const headerRepo = request.headers["x-minimap-repo"];
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
    linked[item.id] = {
      sessionId: session.id,
      targetFile: session.targetFile,
      openComments: session.counts?.openComments ?? 0,
      pendingSuggestions: session.counts?.pendingSuggestions ?? 0,
    };
  }
  return linked;
}

async function handleApi(request, response, requestUrl) {
  const pathname = requestUrl.pathname;

  if (request.method === "GET" && pathname === "/health") {
    sendJson(response, 200, { ok: true });
    return true;
  }

  if (request.method === "POST" && pathname === "/api/shutdown") {
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
    return true;
  }

  if (request.method === "POST" && pathname === "/api/spec-sessions/attach") {
    const rawBody = await readRequestBody(request);
    const body = parseJsonBody(rawBody);

    if (typeof body.file !== "string" || body.file.trim() === "") {
      throw new AppError("Spec-session attach requires a file path.", 400, "bad_request");
    }

    const result = await attachFileSession(body.file, { cwd: cwdFallback });
    sendJson(response, 200, result);
    return true;
  }

  if (request.method === "GET" && pathname === "/api/spec-sessions") {
    const sessions = await listFileSessions();
    sendJson(response, 200, { sessions });
    return true;
  }

  if (request.method === "GET" && pathname === "/api/spec-sessions/by-file") {
    const file = requireQueryParam(requestUrl, "path");
    const session = await getFileSession(file, { cwd: cwdFallback });
    sendJson(response, 200, { session });
    return true;
  }

  if (request.method === "GET" && pathname === "/api/spec-sessions/by-file/context") {
    const file = requireQueryParam(requestUrl, "path");
    const context = await getFileSessionContext(file, { cwd: cwdFallback });
    sendJson(response, 200, context);
    return true;
  }

  if (request.method === "GET" && pathname === "/api/spec-sessions/by-file/content") {
    const file = requireQueryParam(requestUrl, "path");
    const content = await getFileSessionFileContent(file, { cwd: cwdFallback });
    sendJson(response, 200, content);
    return true;
  }

  if (request.method === "DELETE" && (pathname === "/api/spec-sessions/by-file" || pathname === "/api/spec-sessions/by-file/context")) {
    const file = requireQueryParam(requestUrl, "path");
    const result = await removeFileSession(file, { cwd: cwdFallback });
    sendJson(response, 200, result);
    return true;
  }

  if (request.method === "POST" && pathname === "/api/spec-sessions/by-file/move") {
    const rawBody = await readRequestBody(request);
    const body = parseJsonBody(rawBody);

    if (typeof body.from !== "string" || body.from.trim() === "" || typeof body.to !== "string" || body.to.trim() === "") {
      throw new AppError("Spec-session move requires from and to file paths.", 400, "bad_request");
    }

    const result = await moveFileSession(body.from, body.to, { cwd: cwdFallback });
    sendJson(response, 200, result);
    return true;
  }

  if (request.method === "POST" && pathname === "/api/spec-sessions/by-file/comments") {
    const rawBody = await readRequestBody(request);
    const body = parseJsonBody(rawBody);

    if (typeof body.file !== "string" || body.file.trim() === "") {
      throw new AppError("Comment creation requires a file path.", 400, "bad_request");
    }

    const result = await addFileSessionComment(body.file, body, { cwd: cwdFallback });
    sendJson(response, 200, result);
    return true;
  }

  const commentReplyMatch = pathname.match(/^\/api\/spec-sessions\/by-file\/comments\/([^/]+)\/reply$/);
  if (request.method === "POST" && commentReplyMatch) {
    const rawBody = await readRequestBody(request);
    const body = parseJsonBody(rawBody);

    if (typeof body.file !== "string" || body.file.trim() === "") {
      throw new AppError("Comment reply requires a file path.", 400, "bad_request");
    }

    const result = await addFileSessionCommentReply(body.file, decodeURIComponent(commentReplyMatch[1]), body, { cwd: cwdFallback });
    sendJson(response, 200, result);
    return true;
  }

  const suggestionReplyMatch = pathname.match(/^\/api\/spec-sessions\/by-file\/suggestions\/([^/]+)\/reply$/);
  if (request.method === "POST" && suggestionReplyMatch) {
    const rawBody = await readRequestBody(request);
    const body = parseJsonBody(rawBody);

    if (typeof body.file !== "string" || body.file.trim() === "") {
      throw new AppError("Suggestion reply requires a file path.", 400, "bad_request");
    }

    const result = await addFileSessionSuggestionReply(body.file, decodeURIComponent(suggestionReplyMatch[1]), body, { cwd: cwdFallback });
    sendJson(response, 200, result);
    return true;
  }

  const commentStatusMatch = pathname.match(/^\/api\/spec-sessions\/by-file\/comments\/([^/]+)\/(resolve|reopen)$/);
  if (request.method === "POST" && commentStatusMatch) {
    const rawBody = await readRequestBody(request);
    const body = parseJsonBody(rawBody);

    if (typeof body.file !== "string" || body.file.trim() === "") {
      throw new AppError("Comment status update requires a file path.", 400, "bad_request");
    }

    const status = commentStatusMatch[2] === "resolve" ? "resolved" : "open";
    const result = await updateFileSessionCommentStatus(body.file, decodeURIComponent(commentStatusMatch[1]), status, body, { cwd: cwdFallback });
    sendJson(response, 200, result);
    return true;
  }

  if (request.method === "POST" && pathname === "/api/spec-sessions/by-file/suggestions") {
    const rawBody = await readRequestBody(request);
    const body = parseJsonBody(rawBody);

    if (typeof body.file !== "string" || body.file.trim() === "") {
      throw new AppError("Suggestion creation requires a file path.", 400, "bad_request");
    }

    const result = await addFileSessionSuggestion(body.file, body, { cwd: cwdFallback });
    sendJson(response, 200, result);
    return true;
  }

  const suggestionStatusMatch = pathname.match(/^\/api\/spec-sessions\/by-file\/suggestions\/([^/]+)\/(accept|reject|reopen)$/);
  if (request.method === "POST" && suggestionStatusMatch) {
    const rawBody = await readRequestBody(request);
    const body = parseJsonBody(rawBody);

    if (typeof body.file !== "string" || body.file.trim() === "") {
      throw new AppError("Suggestion status update requires a file path.", 400, "bad_request");
    }

    const statusByAction = {
      accept: "accepted",
      reject: "rejected",
      reopen: "pending",
    };
    const status = statusByAction[suggestionStatusMatch[2]];
    const result = await updateFileSessionSuggestionStatus(body.file, decodeURIComponent(suggestionStatusMatch[1]), status, body, { cwd: cwdFallback });
    sendJson(response, 200, result);
    return true;
  }

  const suggestionPreviewApplyMatch = pathname.match(/^\/api\/spec-sessions\/by-file\/suggestions\/([^/]+)\/(preview|apply|rollback)$/);
  if (request.method === "POST" && suggestionPreviewApplyMatch) {
    const rawBody = await readRequestBody(request);
    const body = parseJsonBody(rawBody);

    if (typeof body.file !== "string" || body.file.trim() === "") {
      throw new AppError("Suggestion preview/apply/rollback requires a file path.", 400, "bad_request");
    }

    const suggestionId = decodeURIComponent(suggestionPreviewApplyMatch[1]);
    const action = suggestionPreviewApplyMatch[2];
    let result;
    if (action === "apply") {
      result = await applyFileSessionSuggestion(body.file, suggestionId, body, { cwd: cwdFallback });
    } else if (action === "rollback") {
      result = await rollbackFileSessionSuggestion(body.file, suggestionId, body, { cwd: cwdFallback });
    } else {
      result = await previewFileSessionSuggestion(body.file, suggestionId, { cwd: cwdFallback });
    }
    sendJson(response, 200, result);
    return true;
  }

  if (request.method === "GET" && pathname === "/api/workspace") {
    const repoRoot = await resolveRoadmapRepo(request);
    const workspace = await loadWorkspace(repoRoot);
    workspace.specSessionsByItemId = await buildSpecSessionsByItemId(repoRoot, workspace);
    sendJson(response, 200, workspace);
    return true;
  }

  if (request.method === "POST" && pathname === "/api/setup/initialize") {
    const repoRoot = await resolveRoadmapRepo(request);
    const workspace = await initializeWorkspace(repoRoot);
    sendJson(response, 200, workspace);
    return true;
  }

  if (request.method === "POST" && pathname === "/api/board") {
    const repoRoot = await resolveRoadmapRepo(request);
    const rawBody = await readRequestBody(request);
    const body = parseJsonBody(rawBody);
    const workspace = await saveBoardByGroups(repoRoot, body.groups);
    sendJson(response, 200, workspace);
    return true;
  }

  if (request.method === "POST" && pathname === "/api/scope") {
    const repoRoot = await resolveRoadmapRepo(request);
    const rawBody = await readRequestBody(request);
    const body = parseJsonBody(rawBody);

    if (typeof body.scopeText !== "string") {
      throw new AppError("Scope update must provide scopeText.", 400, "bad_request");
    }

    const workspace = await saveScopeText(repoRoot, body.scopeText);
    sendJson(response, 200, workspace);
    return true;
  }

  const itemMatch = pathname.match(/^\/api\/items\/([^/]+)$/);

  if (itemMatch && request.method === "GET") {
    const repoRoot = await resolveRoadmapRepo(request);
    const item = await readItemById(repoRoot, decodeURIComponent(itemMatch[1]));
    sendJson(response, 200, item);
    return true;
  }

  if (itemMatch && request.method === "POST") {
    const repoRoot = await resolveRoadmapRepo(request);
    const id = decodeURIComponent(itemMatch[1]);
    const rawBody = await readRequestBody(request);
    const body = parseJsonBody(rawBody);

    if (body.id && body.id !== id) {
      throw new AppError("Item id in request body must match the URL.", 400, "bad_request");
    }

    const item = await saveItemById(repoRoot, id, body);
    sendJson(response, 200, item);
    return true;
  }

  return false;
}

async function requestListener(request, response) {
  const requestUrl = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
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
    server.listen(port);
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
    });
    process.stdout.write(`Minimap running at http://localhost:${boundPort}${fallbackNote}\n`);
  } catch (error) {
    if (error && error.code === "EADDRINUSE" && noFallback) {
      // The launcher will re-probe.
      throw error;
    }
    try { await deleteServerRegistry(); } catch {}
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}

async function shutdown(signal) {
  try {
    await deleteServerRegistry();
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
