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

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const staticRoot = path.join(__dirname, "ui");
const repoRoot = process.cwd();
const requestedPort = Number(process.env.PORT || 4312);
const maxPortAttempts = 20;
const repoName = path.basename(path.resolve(repoRoot));

const contentTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
]);

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

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

async function handleApi(request, response, pathname) {
  if (request.method === "GET" && pathname === "/health") {
    sendJson(response, 200, { ok: true });
    return true;
  }

  if (request.method === "GET" && pathname === "/api/workspace") {
    const workspace = await loadWorkspace(repoRoot);
    sendJson(response, 200, workspace);
    return true;
  }

  if (request.method === "POST" && pathname === "/api/setup/initialize") {
    const workspace = await initializeWorkspace(repoRoot);
    sendJson(response, 200, workspace);
    return true;
  }

  if (request.method === "POST" && pathname === "/api/board") {
    const rawBody = await readRequestBody(request);
    const body = parseJsonBody(rawBody);
    const workspace = await saveBoardByGroups(repoRoot, body.groups);
    sendJson(response, 200, workspace);
    return true;
  }

  if (request.method === "POST" && pathname === "/api/scope") {
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
    const item = await readItemById(repoRoot, decodeURIComponent(itemMatch[1]));
    sendJson(response, 200, item);
    return true;
  }

  if (itemMatch && request.method === "POST") {
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
    const handled = await handleApi(request, response, pathname);

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

    if (extension === ".html") {
      const html = file.replaceAll("__REPO_NAME__", escapeHtml(repoName));
      sendText(response, 200, html, contentType);
      return;
    }

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

listenOnAvailablePort(server, requestedPort)
  .then((boundPort) => {
    const fallbackNote = boundPort === requestedPort ? "" : ` (requested ${requestedPort})`;
    process.stdout.write(`Roadmap UI running at http://localhost:${boundPort}${fallbackNote}\n`);
  })
  .catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });




