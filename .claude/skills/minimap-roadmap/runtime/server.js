import http from "node:http";
import { createHash } from "node:crypto";
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
import { discoverWorktreeSources, readWorktreeIdentity } from "./src/worktree-sources.js";
import { selectBoardParticipantCandidates, selectWorktreeParticipantCandidates } from "./src/worktree-presence.js";
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
import { createRoadmapSnapshotCoordinator } from "./src/roadmap-snapshots.js";
import { createRelatedWorkScanner, readIndexedRecord, workflowConfigFingerprint } from "./src/related-work.js";
import { compactWorktreePayload, expandWorktreePayload } from "./ui/worktree-payload.js";
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
const roadmapSnapshots = createRoadmapSnapshotCoordinator();
const relatedWorkSnapshots = createRoadmapSnapshotCoordinator({ limits: { jobTimeoutMs: 10_000, maxBytes: 16 * 1024 * 1024 } });
const scanRelatedWork = createRelatedWorkScanner();
const relatedWorkLastGood = new Map();

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

function sendJson(response, statusCode, payload, serialized = false) {
  if (response.invalidateRoadmapSnapshots) {
    roadmapSnapshots.invalidateAll();
    response.invalidateRoadmapSnapshots = false;
  }
  response.writeHead(statusCode, { "Content-Type": "application/json; charset=utf-8" });
  response.end(serialized ? payload : JSON.stringify(payload));
}

function requestAbortSignal(request, response) {
  if (request.minimapReadBudget) return request.minimapReadBudget;
  const controller = new AbortController();
  const abort = () => {
    if (!response.writableEnded) controller.abort(new DOMException("Request disconnected.", "AbortError"));
  };
  request.once("aborted", abort);
  response.once("close", abort);
  const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(30_000)]);
  const budget = { signal, cleanup: () => {
    request.off("aborted", abort);
    response.off("close", abort);
    if (request.minimapReadBudget === budget) delete request.minimapReadBudget;
  } };
  request.minimapReadBudget = budget;
  return budget;
}

function snapshotAppError(error, signal) {
  if (error instanceof AppError) return error;
  if (error?.status === 503 || error?.status === 409) {
    return new AppError(error.message, error.status, error.code || "snapshot_unavailable");
  }
  if (signal?.reason?.name === "TimeoutError" || (signal?.aborted && error?.name === "AbortError")) {
    return new AppError("Snapshot request exceeded its 30-second budget.", 503, "snapshot_unavailable");
  }
  return error;
}

function canonicalPath(value) {
  const root = path.resolve(value);
  return process.platform === "win32" ? root.toLowerCase() : root;
}

function samePath(left, right) {
  return canonicalPath(left) === canonicalPath(right);
}

function sameSourceIdentity(left, right) {
  return Boolean(left && right && samePath(left.repoRoot, right.repoRoot)
    && left.sourceKey === right.sourceKey && JSON.stringify(left.git) === JSON.stringify(right.git));
}

function snapshotKey(repoRoot, mode) {
  const root = canonicalPath(repoRoot);
  return `${process.platform === "win32" ? root.toLowerCase() : root}\0${mode}`;
}

async function captureAdmissionEvidence(repoRoot, gitRoot, git, resolvedPath, signal) {
  const statValue = async (file) => {
    if (signal?.aborted) throw signal.reason;
    try {
      const stat = await fs.stat(file, { signal });
      return [stat.dev, stat.ino, stat.birthtimeMs, stat.size, stat.mtimeMs, stat.ctimeMs];
    } catch (error) {
      if (error?.code === "ENOENT") return null;
      throw error;
    }
  };
  const root = await fs.realpath(repoRoot);
  const gitFilesystemRoot = gitRoot ? await fs.realpath(gitRoot) : root;
  const gitEntry = path.join(gitFilesystemRoot, ".git");
  let gitEntryStat = null, gitEntryText = null;
  let actualGitDir = null;
  try {
    const entry = await fs.lstat(gitEntry, { signal });
    gitEntryStat = [entry.dev, entry.ino, entry.birthtimeMs, entry.size, entry.mtimeMs, entry.ctimeMs];
    if (entry.isFile()) {
      gitEntryText = await fs.readFile(gitEntry, { encoding: "utf8", signal });
      const target = gitEntryText.match(/^gitdir:\s*(.+)\s*$/im)?.[1];
      if (!target) return null;
      actualGitDir = await fs.realpath(path.resolve(gitFilesystemRoot, target));
    } else actualGitDir = await fs.realpath(gitEntry);
    if (git && !samePath(actualGitDir, git.gitDir)) return null;
    if (gitRoot && !git) return null;
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    if (git) return null;
    if (gitRoot) return null;
  }

  let gitEvidence = null;
  if (git || actualGitDir) {
    const gitDir = git?.gitDir || actualGitDir;
    const commonDir = git?.commonDir || gitDir;
    const head = await fs.readFile(path.join(gitDir, "HEAD"), { encoding: "utf8", signal });
    const commonDirPath = path.join(gitDir, "commondir");
    let commonDirText = null;
    try {
      commonDirText = await fs.readFile(commonDirPath, { encoding: "utf8", signal });
      if (!samePath(path.resolve(gitDir, commonDirText.trim()), commonDir)) return null;
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      if (!samePath(gitDir, commonDir)) return null;
    }
    gitEvidence = { gitDir: canonicalPath(gitDir), commonDir: canonicalPath(commonDir),
      gitDirStat: await statValue(gitDir), commonDirStat: await statValue(commonDir), head,
      gitEntryStat, gitEntryText, commonDirText };
  }

  const configPath = path.join(root, "roadmap.config.json");
  let config = null;
  try { config = createHash("sha256").update(await fs.readFile(configPath, { signal })).digest("hex"); }
  catch (error) { if (error?.code !== "ENOENT") throw error; }
  const bindingRoot = await fs.realpath(resolvedPath);
  return { root: canonicalPath(root), rootStat: await statValue(root),
    gitRoot: gitRoot ? canonicalPath(gitFilesystemRoot) : null, gitRootStat: gitRoot ? await statValue(gitFilesystemRoot) : null,
    git: gitEvidence,
    config, configStat: await statValue(configPath), bindingRoot: canonicalPath(bindingRoot),
    bindingStat: await statValue(bindingRoot) };
}

async function captureSourceAdmission(repoRoot, roadmapBinding, identity, signal) {
  const currentBinding = await requireRoadmapInSource(repoRoot, { signal });
  if (currentBinding.roadmapPath !== roadmapBinding.roadmapPath
    || !samePath(currentBinding.resolvedPath, roadmapBinding.resolvedPath)) return null;
  const git = identity?.git || null;
  const gitRoot = identity?.repoRoot || null;
  const evidence = await captureAdmissionEvidence(repoRoot, gitRoot, git, currentBinding.resolvedPath, signal);
  if (!evidence) return null;
  if (!identity && !evidence.git) return null;
  if (git) {
    const expectedHead = git.branchRef ? `ref: ${git.branchRef}` : git.headCommit;
    if (evidence.git.head.trim() !== expectedHead) return null;
  }
  return { repoRoot: canonicalPath(repoRoot), gitRoot: gitRoot ? canonicalPath(gitRoot) : null,
    sourceKey: identity?.sourceKey || null, git,
    roadmapPath: currentBinding.roadmapPath, resolvedPath: canonicalPath(currentBinding.resolvedPath), evidence };
}

async function admitSource(expected, signal) {
  const binding = await requireRoadmapInSource(expected.repoRoot, { signal });
  if (binding.roadmapPath !== expected.roadmapPath || !samePath(binding.resolvedPath, expected.resolvedPath)) return false;
  const evidence = await captureAdmissionEvidence(expected.repoRoot, expected.gitRoot, expected.git, binding.resolvedPath, signal);
  return Boolean(evidence && JSON.stringify(expected.evidence) === JSON.stringify(evidence));
}

function sameWorkspaceRevision(left, right) {
  if (!left || !right || left.configRevision !== right.configRevision
    || left.boardRevision !== right.boardRevision || left.scopeRevision !== right.scopeRevision
    || !samePath(left.resolvedPath, right.resolvedPath)) return false;
  const leftItems = Object.values(left.items || {}), rightItems = Object.values(right.items || {});
  if (leftItems.length !== rightItems.length) return false;
  const byId = new Map(rightItems.map((item) => [item.id, item]));
  return leftItems.every((item) => {
    const other = byId.get(item.id);
    return other && item.revision === other.revision && samePath(item.filePath, other.filePath);
  });
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

async function validateBoundRequest(request, { signal } = {}) {
  await verifySourceContext(request.boundRepoRoot, request.boundExpected, { signal });
  if (request.boundSpecRepo) {
    if (request.boundUrl.searchParams.has("path")) {
      await requirePathInSource(request.boundRepoRoot, request.boundUrl.searchParams.get("path"), { signal });
    }
    for (const candidate of request.boundBodyPaths || []) await requirePathInSource(request.boundRepoRoot, candidate, { signal });
    return;
  }
  const roadmap = await requireRoadmapInSource(request.boundRepoRoot, { signal });
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
function compactSpecSession(session) {
  return session.availability?.status === "unavailable"
    ? { sessionId: session.id, targetFile: session.targetFile, unavailable: true }
    : { sessionId: session.id, targetFile: session.targetFile,
      openComments: session.counts.openComments, pendingSuggestions: session.counts.pendingSuggestions };
}

async function readSpecSessions(targetFiles, { signal, onMutation } = {}) {
  let sessions;
  try { sessions = await listFileSessions({ targetFiles, signal, onMutation }); }
  catch (error) { if (signal?.aborted) throw signal.reason || error; return new Map(); }
  return new Map(sessions.filter((session) => typeof session?.targetFile === "string")
    .map((session) => [path.resolve(session.targetFile).replace(/\\/g, "/"), compactSpecSession(session)]));
}

async function buildSpecSessionsByItemId(repoRoot, workspace, options = {}) {
  let sessions;
  try {
    sessions = await listFileSessions({ targetFiles: Object.values(workspace.items ?? {}).map((item) => item.filePath).filter(Boolean), ...options });
  } catch (error) {
    if (options.signal?.aborted) throw options.signal.reason || error;
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
    linked[item.id] = compactSpecSession(session);
  }
  return linked;
}

async function attachAggregateSpecSessions(aggregate, options = {}) {
  const versions = (aggregate.features || []).flatMap((feature) => feature.versions || []);
  const sessions = await readSpecSessions(versions.map((version) => version.summary.filePath).filter(Boolean), options);
  for (const version of versions) {
    const file = version.summary.filePath;
    if (!file) continue;
    const session = sessions.get(path.resolve(file).replace(/\\/g, "/"));
    if (session) version.summary.specSession = session;
  }
}

async function buildObservationManifest(repoRoot, workspace, aggregate, signal) {
  const modes = {};
  for (const includeCompleted of [false, true]) {
    if (signal?.aborted) throw signal.reason;
    const key = includeCompleted ? "completed" : "unfinished";
    const board = aggregate ? null : selectBoardParticipantCandidates(workspace, { includeCompleted });
    const selected = aggregate
      ? selectWorktreeParticipantCandidates(aggregate, { includeCompleted })
      : { features: board.ids.map((id) => ({ key: id, id })), partial: board.partial, ambiguous: [] };
    const partial = selected.partial || selected.ambiguous.length > 0;
    if (!workspace) { modes[key] = { status: "identity-unavailable", counts: [], partial: true }; continue; }
    if (!palliumConfig.configured) { modes[key] = { status: "disabled", counts: [], partial }; continue; }
    const ids = selected.features.map((feature) => feature.id);
    const references = ids.length
      ? await resolveRoadmapItemReferences(repoRoot, workspace.roadmapPath, ids, { signal })
      : [];
    if (references === null) { modes[key] = { status: "identity-unavailable", counts: [], partial: true }; continue; }
    modes[key] = { status: "ok", partial, counts: selected.features.map((feature, index) => ({
      ...(aggregate ? { featureKey: feature.key } : { itemId: feature.id }), reference: references[index],
    })) };
  }
  return modes;
}

async function handleBoardObservations(request, response, ctx) {
  const snapshots = ctx.url.searchParams.getAll("snapshot");
  const includeCompletedValues = ctx.url.searchParams.getAll("includeCompleted");
  if (snapshots.length !== 1 || !snapshots[0]
    || includeCompletedValues.length > 1 || includeCompletedValues.some((value) => !["0", "1"].includes(value))) {
    throw new AppError("Invalid snapshot observation query.", 400, "bad_request");
  }
  const { signal, cleanup } = requestAbortSignal(request, response);
  const generation = roadmapSnapshots.generation();
  try {
    const repoRoot = await resolveRoadmapRepo(request);
    const manifestModes = ["this", "opened", "across"];
    const manifestMode = manifestModes.find((mode) => roadmapSnapshots.getManifest(snapshots[0], snapshotKey(repoRoot, mode)));
    const manifest = manifestMode && roadmapSnapshots.getManifest(snapshots[0], snapshotKey(repoRoot, manifestMode));
    const sameRepo = manifest && samePath(manifest.openedRepo, repoRoot);
    if (!manifest || !sameRepo || !["this", "across"].includes(manifest.mode)) {
      throw new AppError("Snapshot is no longer available for this checkout.", 409, "snapshot_expired");
    }
    const mode = manifest.observation[includeCompletedValues[0] === "1" ? "completed" : "unfinished"];
    let result;
    if (!mode || mode.status !== "ok") result = { status: mode?.status || "identity-unavailable", counts: [], partial: Boolean(mode?.partial), includeCompleted: includeCompletedValues[0] === "1" };
    else if (!mode.counts.length) result = { status: "ok", counts: [], partial: mode.partial,
      includeCompleted: includeCompletedValues[0] === "1" };
    else {
      const provider = await lookupPalliumParticipantCounts(palliumConfig, mode.counts.map((entry) => entry.reference), { signal });
      result = { status: provider.status,
        counts: provider.status === "ok" ? provider.counts.map((row, index) => ({
          [manifest.mode === "across" ? "featureKey" : "itemId"]: mode.counts[index][manifest.mode === "across" ? "featureKey" : "itemId"],
          participantCount: row.participant_count, recentParticipantCount: row.recent_participant_count,
          dormantParticipantCount: row.dormant_participant_count,
        })) : [], partial: mode.partial,
        ...(provider.status === "ok" ? { asOf: provider.asOf, recentSeconds: provider.recentSeconds } : {}),
        includeCompleted: includeCompletedValues[0] === "1" };
    }
    if (signal.aborted) return;
    if (generation !== roadmapSnapshots.generation()
      || !roadmapSnapshots.getManifest(snapshots[0], snapshotKey(repoRoot, manifestMode))) {
      throw new AppError("Snapshot changed while observations were loading.", 409, "snapshot_invalidated");
    }
    sendJson(response, 200, result);
  } catch (error) { if (!response.destroyed) throw snapshotAppError(error, signal); }
  finally { cleanup(); }
}

async function readThisSnapshot(repoRoot, { signal, cached = false } = {}) {
  return roadmapSnapshots.read({ key: snapshotKey(repoRoot, "this"), cached, signal,
    load: async ({ signal: scanSignal }) => {
      const identity = await readWorktreeIdentity(repoRoot, { signal: scanSignal });
      const workspace = await loadWorkspace(repoRoot, { signal: scanSignal });
      workspace.specSessionsByItemId = await buildSpecSessionsByItemId(repoRoot, workspace, {
        signal: scanSignal, onMutation: () => roadmapSnapshots.invalidateAll(),
      });
      const observation = await buildObservationManifest(repoRoot, workspace, null, scanSignal);
      const finalWorkspace = await loadWorkspace(repoRoot, { signal: scanSignal });
      if (!sameWorkspaceRevision(workspace, finalWorkspace)) {
        throw new AppError("Roadmap files changed while the snapshot was loading.", 409, "snapshot_invalidated");
      }
      const finalIdentity = await readWorktreeIdentity(repoRoot, { signal: scanSignal });
      if ((identity && !finalIdentity) || (!identity && finalIdentity)) {
        throw new AppError("Checkout identity is unavailable.", 503, "snapshot_unavailable");
      }
      if (identity && !sameSourceIdentity(identity, finalIdentity)) {
        throw new AppError("Roadmap source changed while the snapshot was loading.", 409, "snapshot_invalidated");
      }
      const admission = await captureSourceAdmission(repoRoot, workspace, finalIdentity, scanSignal);
      if (!admission && finalIdentity) throw new AppError("Roadmap source changed while the snapshot was loading.", 409, "snapshot_invalidated");
      return { value: workspace, manifest: { openedRepo: canonicalPath(repoRoot), mode: "this", observation }, admission };
    },
    admit: async (admission, { signal: admitSignal }) => {
      if (!admission) return false;
      return admitSource(admission, admitSignal);
    },
  });
}

async function readParticipantWorkspace(repoRoot, { signal } = {}) {
  return roadmapSnapshots.read({ key: snapshotKey(repoRoot, "participants"), retain: false, signal,
    load: async ({ signal: scanSignal }) => {
      const identity = await readWorktreeIdentity(repoRoot, { signal: scanSignal });
      const workspace = await loadWorkspace(repoRoot, { signal: scanSignal });
      const finalIdentity = await readWorktreeIdentity(repoRoot, { signal: scanSignal });
      if ((identity && !finalIdentity) || (!identity && finalIdentity)) {
        throw new AppError("Checkout identity is unavailable.", 503, "snapshot_unavailable");
      }
      if (identity && !sameSourceIdentity(identity, finalIdentity)) {
        throw new AppError("Roadmap source changed while participants were loading.", 409, "snapshot_invalidated");
      }
      return { value: workspace };
    },
  });
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
  const result = await attachFileSession(file, sessionReadOptions());
  sendJson(response, 200, result);
}

function sessionReadOptions() {
  return { cwd: cwdFallback, onMutation: () => roadmapSnapshots.invalidateAll() };
}

async function handleListSpecSessions(request, response) {
  let sessions = await listFileSessions(sessionReadOptions());
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
  const session = await getFileSession(file, sessionReadOptions());
  sendJson(response, 200, { session });
}

async function handleGetSpecContext(request, response, ctx) {
  const file = requireQueryParam(ctx.url, "path");
  const context = await getFileSessionContext(file, sessionReadOptions());
  sendJson(response, 200, context);
}

async function handleGetSpecContent(request, response, ctx) {
  const file = requireQueryParam(ctx.url, "path");
  const content = await getFileSessionFileContent(file, sessionReadOptions());
  sendJson(response, 200, content);
}

async function handleRemoveSpecSession(request, response, ctx) {
  const file = requireQueryParam(ctx.url, "path");
  const result = await removeFileSession(file, sessionReadOptions());
  sendJson(response, 200, result);
}

async function handleMoveSpecSession(request, response) {
  const body = await withJsonBody(request);

  if (typeof body.from !== "string" || body.from.trim() === "" || typeof body.to !== "string" || body.to.trim() === "") {
    throw new AppError("Spec-session move requires from and to file paths.", 400, "bad_request");
  }

  const result = await moveFileSession(body.from, body.to, sessionReadOptions());
  sendJson(response, 200, result);
}

async function handleAddComment(request, response) {
  const body = await withJsonBody(request);
  const file = requireFileFromBody(body, "Comment creation requires a file path.");
  const result = await addFileSessionComment(file, body, sessionReadOptions());
  sendJson(response, 200, result);
}

async function handleCommentReply(request, response, ctx) {
  const body = await withJsonBody(request);
  const file = requireFileFromBody(body, "Comment reply requires a file path.");
  const result = await addFileSessionCommentReply(file, decodeURIComponent(ctx.params[0]), body, sessionReadOptions());
  sendJson(response, 200, result);
}

async function handleSuggestionReply(request, response, ctx) {
  const body = await withJsonBody(request);
  const file = requireFileFromBody(body, "Suggestion reply requires a file path.");
  const result = await addFileSessionSuggestionReply(file, decodeURIComponent(ctx.params[0]), body, sessionReadOptions());
  sendJson(response, 200, result);
}

async function handleCommentStatus(request, response, ctx) {
  const body = await withJsonBody(request);
  const file = requireFileFromBody(body, "Comment status update requires a file path.");
  const status = ctx.params[1] === "resolve" ? "resolved" : "open";
  const result = await updateFileSessionCommentStatus(file, decodeURIComponent(ctx.params[0]), status, body, sessionReadOptions());
  sendJson(response, 200, result);
}

async function handleAddSuggestion(request, response) {
  const body = await withJsonBody(request);
  const file = requireFileFromBody(body, "Suggestion creation requires a file path.");
  const result = await addFileSessionSuggestion(file, body, sessionReadOptions());
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
  const result = await updateFileSessionSuggestionStatus(file, decodeURIComponent(ctx.params[0]), status, body, sessionReadOptions());
  sendJson(response, 200, result);
}

async function handleSuggestionPreviewApply(request, response, ctx) {
  const body = await withJsonBody(request);
  const file = requireFileFromBody(body, "Suggestion preview/apply/rollback requires a file path.");
  const suggestionId = decodeURIComponent(ctx.params[0]);
  const action = ctx.params[1];
  const options = sessionReadOptions();
  let result;
  if (action === "apply") {
    result = await applyFileSessionSuggestion(file, suggestionId, body, options);
  } else if (action === "rollback") {
    result = await rollbackFileSessionSuggestion(file, suggestionId, body, options);
  } else {
    result = await previewFileSessionSuggestion(file, suggestionId, options);
  }
  sendJson(response, 200, result);
}

async function handleWorkspace(request, response) {
  const values = new URL(request.url, "http://localhost").searchParams.getAll("cached");
  if (values.length > 1 || values.some((value) => value !== "1")) throw new AppError("cached must be 1 and appear at most once.", 400, "bad_request");
  const { signal, cleanup } = requestAbortSignal(request, response);
  try {
    const repoRoot = await resolveRoadmapRepo(request);
    const loaded = await readThisSnapshot(repoRoot, { signal, cached: values.length === 1 });
    if (signal.aborted) return;
    if (loaded.generation !== roadmapSnapshots.generation()) throw new AppError("Snapshot changed while the request was in progress.", 409, "snapshot_invalidated");
    loaded.value.snapshot = loaded.snapshot;
    sendJson(response, 200, loaded.value);
  } catch (error) {
    if (!response.destroyed) throw snapshotAppError(error, signal);
  } finally { cleanup(); }
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

  const { signal, cleanup } = requestAbortSignal(request, response);
  try {
  const repoRoot = await resolveRoadmapRepo(request);
  await verifySourceContext(repoRoot, expected, { signal });
  const roadmap = await requireRoadmapInSource(repoRoot, { signal });
  const snapshot = await readThisSnapshot(repoRoot, { signal });
  const workspace = snapshot.value;
  workspace.snapshot = snapshot.snapshot;

  const source = await verifySourceContext(repoRoot, expected, { signal });
  const currentRoadmap = await requireRoadmapInSource(repoRoot, { signal });
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
  if (snapshot.generation !== roadmapSnapshots.generation()) throw new AppError("Snapshot changed while the request was in progress.", 409, "snapshot_invalidated");
  sendJson(response, 200, { source: { ...source, roadmapBinding: {
    roadmapPath: roadmap.roadmapPath, resolvedPath: roadmap.resolvedPath,
  } }, workspace });
  } catch (error) { if (!response.destroyed) throw snapshotAppError(error, signal); }
  finally { cleanup(); }
}

async function handleWorktreeWorkspace(request, response) {
  const openedOnlyValues = new URL(request.url, "http://localhost").searchParams.getAll("openedOnly");
  const cachedValues = new URL(request.url, "http://localhost").searchParams.getAll("cached");
  const participantValues = new URL(request.url, "http://localhost").searchParams.getAll("participants");
  const compactValues = new URL(request.url, "http://localhost").searchParams.getAll("compact");
  if (openedOnlyValues.length > 1 || (openedOnlyValues.length && openedOnlyValues[0] !== "1")) {
    throw new AppError("Invalid openedOnly query parameter.", 400, "bad_request");
  }
  if (cachedValues.length > 1 || cachedValues.some((value) => value !== "1")
    || participantValues.length > 1 || participantValues.some((value) => value !== "0")
    || compactValues.length > 1 || compactValues.some((value) => value !== "1")) {
    throw new AppError("Invalid worktree snapshot query parameter.", 400, "bad_request");
  }
  const openedOnly = openedOnlyValues.length === 1;
  const cached = cachedValues.length === 1;
  const participants = participantValues.length === 0;
  const compact = compactValues.length === 1;
  const mode = openedOnly ? "opened" : "across";
  const { signal, cleanup } = requestAbortSignal(request, response);
  try {
    const repoRoot = await resolveRoadmapRepo(request);
    const key = snapshotKey(repoRoot, mode);
    const loaded = await roadmapSnapshots.read({ key, cached, signal, priority: openedOnly,
      load: async ({ signal: scanSignal }) => {
        const aggregate = await loadWorktreeAggregate(repoRoot, { openedOnly, signal: scanSignal });
        await attachAggregateSpecSessions(aggregate, { signal: scanSignal,
          onMutation: () => roadmapSnapshots.invalidateAll() });
        const sources = new Map();
        const sourceChecks = aggregate.snapshotChecks || [];
        for (const check of sourceChecks) {
          const source = (aggregate.sources || []).find((entry) => entry.sourceKey === check.sourceKey);
          if (!source) continue;
          const binding = source.roadmapBinding || check.workspace;
          const finalWorkspace = await loadWorkspace(source.repoRoot, { signal: scanSignal });
          if (!sameWorkspaceRevision(check.workspace, finalWorkspace)) {
            throw new AppError("Roadmap files changed while the snapshot was loading.", 409, "snapshot_invalidated");
          }
          const finalIdentity = await readWorktreeIdentity(source.repoRoot, { signal: scanSignal });
          if (!finalIdentity) throw new AppError("Checkout identity is unavailable.", 503, "snapshot_unavailable");
          if (!sameSourceIdentity(source, finalIdentity)) {
            throw new AppError("Roadmap source changed while the snapshot was loading.", 409, "snapshot_invalidated");
          }
          const admission = await captureSourceAdmission(source.repoRoot, binding, finalIdentity, scanSignal);
          if (!admission || !sameSourceIdentity(source, admission)) {
            throw new AppError("Roadmap source changed while the snapshot was loading.", 409, "snapshot_invalidated");
          }
          sources.set(source.sourceKey, admission);
        }
        const manifest = await buildObservationManifest(repoRoot, aggregate.workspace, openedOnly ? null : aggregate, scanSignal);
        return { value: compactWorktreePayload(aggregate), manifest: { openedRepo: canonicalPath(repoRoot), mode: openedOnly ? "this" : "across", observation: manifest },
          admission: sourceChecks.length === (aggregate.sources || []).length && sourceChecks.length
            ? [...sources.values()] : [null] };
      },
      admit: async (admissions, { signal: admitSignal }) => {
        if (!Array.isArray(admissions) || !admissions.length) return false;
        for (const expected of admissions) {
          if (!expected) return false;
          if (!await admitSource(expected, admitSignal)) return false;
        }
        return true;
      },
    });
    if (signal.aborted) return;
    if (loaded.generation !== roadmapSnapshots.generation()) throw new AppError("Snapshot changed while the request was in progress.", 409, "snapshot_invalidated");
    if (compact && !participants) {
      // The retained object is already serialized; only its freshness metadata changes.
      if (!response.destroyed) sendJson(response, 200,
        `${loaded.valueJson.slice(0, -1)},"snapshot":${JSON.stringify(loaded.snapshot)}}`, true);
      return;
    }
    if (!compact) loaded.value = expandWorktreePayload(loaded.value);
    loaded.value.snapshot = loaded.snapshot;
    if (participants) loaded.value.participantCounts = openedOnly
      ? { status: "loading", counts: [], partial: true, includeCompleted: true }
      : await lookupWorktreeParticipantCounts(request, response, repoRoot, loaded.value, mode);
    if (loaded.generation !== roadmapSnapshots.generation()) throw new AppError("Snapshot changed while the request was in progress.", 409, "snapshot_invalidated");
    if (!response.destroyed) sendJson(response, 200, loaded.value);
  } catch (error) {
    if (!response.destroyed) throw snapshotAppError(error, signal);
  } finally { cleanup(); }
}

async function lookupWorktreeParticipantCounts(request, response, repoRoot, aggregate, mode) {
  if (!palliumConfig.configured) {
    return { status: "disabled", counts: [], partial: Boolean(aggregate.partial), includeCompleted: true };
  }
  if (!aggregate.workspace) {
    return { status: "identity-unavailable", counts: [], partial: true, includeCompleted: true };
  }
  const manifest = roadmapSnapshots.getManifest(aggregate.snapshot?.id, snapshotKey(repoRoot, mode));
  const observation = manifest?.observation?.completed;
  if (!observation) return { status: "identity-unavailable", counts: [], partial: true, includeCompleted: true };
  if (observation.status !== "ok") return { status: observation.status, counts: [], partial: observation.partial, includeCompleted: true };
  const controller = new AbortController();
  const abort = () => controller.abort();
  request.once("aborted", abort);
  response.once("close", abort);
  try {
    const result = await lookupPalliumParticipantCounts(palliumConfig, observation.counts.map((entry) => entry.reference), { signal: controller.signal });
    return {
      status: result.status,
      counts: result.status === "ok" ? result.counts.map((row, index) => ({
        featureKey: observation.counts[index].featureKey, participantCount: row.participant_count,
        recentParticipantCount: row.recent_participant_count, dormantParticipantCount: row.dormant_participant_count,
      })) : [],
      partial: observation.partial,
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

  const { signal, cleanup } = requestAbortSignal(request, response);
  try {
    const repoRoot = await resolveRoadmapRepo(request);
    const id = decodeURIComponent(ctx.params[0]);
    const snapshot = await readParticipantWorkspace(repoRoot, { signal });
    const workspace = snapshot.value;
    if (!Object.hasOwn(workspace.items, id)) throw new AppError(`Item "${id}" was not found.`, 404, "not_found");
    const reference = await resolveRoadmapItemReference(repoRoot, workspace.roadmapPath, id, { signal });
    const result = await lookupPalliumParticipants(palliumConfig, reference, { signal });
    if (snapshot.generation !== roadmapSnapshots.generation()) throw new AppError("Snapshot changed while the request was in progress.", 409, "snapshot_invalidated");
    if (!response.destroyed) sendJson(response, 200, result);
  } catch (error) {
    if (!response.destroyed && (!signal.aborted || signal.reason?.name === "TimeoutError")) {
      throw snapshotAppError(error, signal);
    }
  } finally { cleanup(); }
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
  const { signal, cleanup } = requestAbortSignal(request, response);
  try {
    const repoRoot = await resolveRoadmapRepo(request);
    const snapshot = await readParticipantWorkspace(repoRoot, { signal });
    if (snapshot.generation !== roadmapSnapshots.generation()) throw new AppError("Snapshot changed while the request was in progress.", 409, "snapshot_invalidated");
    const observations = await buildObservationManifest(repoRoot, snapshot.value, null, signal);
    const observation = observations[includeCompleted ? "completed" : "unfinished"];
    if (!observation || observation.status !== "ok") {
      if (!response.destroyed) sendJson(response, 200, { status: observation?.status || "identity-unavailable", counts: [], partial: Boolean(observation?.partial), ...(includeCompleted ? { includeCompleted: true } : {}) });
      return;
    }
    const result = observation.counts.length
      ? await lookupPalliumParticipantCounts(palliumConfig, observation.counts.map((entry) => entry.reference), { signal })
      : { status: "ok", counts: [] };
    if (!response.destroyed) {
      if (snapshot.generation !== roadmapSnapshots.generation()) throw new AppError("Snapshot changed while the request was in progress.", 409, "snapshot_invalidated");
      const counts = result.status === "ok"
        ? result.counts.map((row, index) => ({
          itemId: observation.counts[index].itemId, participantCount: row.participant_count,
          recentParticipantCount: row.recent_participant_count, dormantParticipantCount: row.dormant_participant_count,
        }))
        : [];
      sendJson(response, 200, {
        status: result.status, counts, partial: observation.partial,
        ...(result.status === "ok" ? { asOf: result.asOf, recentSeconds: result.recentSeconds } : {}),
        ...(result.status === "ok" && includeCompleted ? { includeCompleted: true } : {}),
      });
    }
  } catch (error) {
    if (!response.destroyed && (!signal.aborted || signal.reason?.name === "TimeoutError")) {
      throw snapshotAppError(error, signal);
    }
  } finally { cleanup(); }
}
async function handleGetItem(request, response, ctx) {
  const repoRoot = await resolveRoadmapRepo(request);
  const item = await readItemById(repoRoot, decodeURIComponent(ctx.params[0]));
  sendJson(response, 200, item);
}

async function handleRelatedWork(request, response, ctx) {
  const { signal, cleanup } = requestAbortSignal(request, response);
  try {
    const repoRoot = await resolveRoadmapRepo(request);
    const itemId = decodeURIComponent(ctx.params[0]);
    await readItemById(repoRoot, itemId);
    const [source, roadmap] = await Promise.all([
      readWorktreeIdentity(repoRoot, { signal }), requireRoadmapInSource(repoRoot, { signal }),
    ]);
    if (!source) return sendJson(response, 200, { status: "unavailable", reason: "source_identity_unavailable", records: [] });
    const reference = await resolveRoadmapItemReference(repoRoot, roadmap.roadmapPath, itemId, { signal });
    if (!reference) return sendJson(response, 200, { status: "unavailable", reason: "reference_identity_unavailable", records: [] });
    const configHash = await workflowConfigFingerprint(repoRoot, { signal });
    const key = JSON.stringify([repoRoot, source.sourceKey, source.git.headCommit, roadmap.resolvedPath, roadmap.configRevision, configHash]);
    const requested = ctx.url.searchParams.get("generation");
    let generation;
    let index;
    if (requested) {
      index = relatedWorkSnapshots.getManifest(requested, key);
      if (!index) throw new AppError("Related work changed. Restart from the first page.", 409, "related_work_changed");
      generation = requested;
    } else {
      try {
        const read = await relatedWorkSnapshots.read({ key, cached: ctx.url.searchParams.get("fresh") !== "1",
          admit: () => true, signal, load: async ({ signal: scanSignal }) => {
          const value = await scanRelatedWork(repoRoot, { signal: scanSignal, sourceCommit: source.git.headCommit });
          if (await workflowConfigFingerprint(repoRoot, { signal: scanSignal }) !== configHash
            || (value.configHash && value.configHash !== configHash)) {
            throw new AppError("Workflow configuration changed during scan.", 409, "source_changed");
          }
          const [actual, currentRoadmap] = await Promise.all([
            readWorktreeIdentity(repoRoot, { signal: scanSignal }), requireRoadmapInSource(repoRoot, { signal: scanSignal }),
          ]);
          if (actual?.sourceKey !== source.sourceKey || actual?.git.headCommit !== source.git.headCommit
            || currentRoadmap.resolvedPath !== roadmap.resolvedPath || currentRoadmap.configRevision !== roadmap.configRevision) {
            throw new AppError("Checkout or roadmap changed during related-work scan.", 409, "source_changed");
          }
          if (value.status === "partial" && relatedWorkSnapshots.getManifest(relatedWorkLastGood.get(key)?.id, key)) {
            throw new AppError("Related-work scan has partial coverage.", 503, "related_work_partial", value.coverage);
          }
          return { value, manifest: value };
        } });
        index = read.value;
        generation = read.snapshot.id;
        if (read.snapshot.stale) index = { ...index, status: "stale", reason: "validation_due", staleSince: read.snapshot.validatedAt };
        if (index.status === "ok" && relatedWorkLastGood.get(key)?.id !== generation) {
          relatedWorkLastGood.delete(key);
          relatedWorkLastGood.set(key, { id: generation, validatedAt: read.snapshot.validatedAt });
          if (relatedWorkLastGood.size > 16) relatedWorkLastGood.delete(relatedWorkLastGood.keys().next().value);
        }
      } catch (error) {
        if (signal.aborted || error.code === "source_changed" || error.code === "snapshot_invalidated") throw error;
        const previous = relatedWorkLastGood.get(key);
        index = previous && relatedWorkSnapshots.getManifest(previous.id, key);
        if (!index) throw error;
        generation = previous.id;
        previous.failure = { reason: error.code || error.message, coverage: error.details || index.coverage };
      }
    }
    const failed = relatedWorkLastGood.get(key);
    if (failed?.id === generation && failed.failure) index = { ...index, status: "stale", ...failed.failure, staleSince: failed.validatedAt };
    const matched = index.records.filter((record) => record.sources.some((entry) => entry.provider === "minimap"
      && entry.scope_ref === reference.scope_ref && entry.local_ref === reference.local_ref));
    if (ctx.url.searchParams.has("record")) {
      const record = matched.find((entry) => entry.id === ctx.url.searchParams.get("record"));
      if (!record) throw new AppError("Record is not in this index.", 404, "record_not_indexed");
      const content = await readIndexedRecord(repoRoot, record, index.taskPath, { signal });
      if (content === null) throw new AppError("Record changed. Refresh related work.", 409, "related_work_changed");
      const [openedSource, openedRoadmap, openedConfig] = await Promise.all([
        readWorktreeIdentity(repoRoot, { signal }), requireRoadmapInSource(repoRoot, { signal }), workflowConfigFingerprint(repoRoot, { signal }),
      ]);
      if (openedSource?.sourceKey !== source.sourceKey || openedSource?.git.headCommit !== source.git.headCommit
        || openedRoadmap.resolvedPath !== roadmap.resolvedPath || openedRoadmap.configRevision !== roadmap.configRevision
        || openedConfig !== configHash) throw new AppError("Source changed. Refresh related work.", 409, "related_work_changed");
      return sendJson(response, 200, { id: record.id, title: record.title, recordedState: record.recordedState, content });
    }
    const rawOffset = ctx.url.searchParams.get("offset") || "0";
    if (!/^(0|[1-9]\d*)$/.test(rawOffset) || Number(rawOffset) > matched.length) throw new AppError("Invalid related-work page.", 400, "bad_request");
    const offset = Number(rawOffset);
    const records = matched.slice(offset, offset + 20).map(({ sources, hash, path, ...record }) => record);
    const [servedSource, servedRoadmap, servedConfig] = await Promise.all([
      readWorktreeIdentity(repoRoot, { signal }), requireRoadmapInSource(repoRoot, { signal }), workflowConfigFingerprint(repoRoot, { signal }),
    ]);
    if (servedSource?.sourceKey !== source.sourceKey || servedSource?.git.headCommit !== source.git.headCommit
      || servedRoadmap.resolvedPath !== roadmap.resolvedPath || servedRoadmap.configRevision !== roadmap.configRevision
      || servedConfig !== configHash) throw new AppError("Source changed. Restart related work.", 409, "related_work_changed");
    sendJson(response, 200, { status: index.status, reason: index.reason || null, coverage: index.coverage,
      staleSince: index.staleSince || null,
      records, total: matched.length, generation, nextOffset: offset + records.length < matched.length ? offset + records.length : null,
      source: { repoRoot, sourceKey: source.sourceKey, headCommit: source.git.headCommit } });
  } finally { cleanup(); }
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
  { method: "GET",    pattern: /^\/api\/board\/observations$/, handler: handleBoardObservations },
  { method: "GET",    pattern: /^\/api\/items\/([^/]+)\/participants$/, handler: handleItemParticipants },
  { method: "GET",    pattern: /^\/api\/items\/([^/]+)\/related-work$/, handler: handleRelatedWork },
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
  const readBudget = bound && routedUrl.pathname === "/api/source/workspace"
    ? requestAbortSignal(request, response) : null;
  try {
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
    await validateBoundRequest(request, readBudget ? { signal: readBudget.signal } : undefined);
  }
  const invalidatesSnapshot = ["POST", "DELETE"].includes(request.method)
    && routedUrl.pathname !== "/api/shutdown"
    && !/^\/api\/spec-sessions\/by-file\/suggestions\/[^/]+\/preview$/.test(routedUrl.pathname);
  if (invalidatesSnapshot) response.invalidateRoadmapSnapshots = true;
  try {
    if (bound) await withSourceWriteGuard(() => validateBoundRequest(request, readBudget ? { signal: readBudget.signal } : undefined),
      () => match.handler(request, response, { url: routedUrl, params: match.params }),
      (candidate) => requirePathInSource(request.boundRepoRoot, candidate));
    else await match.handler(request, response, { url: routedUrl, params: match.params });
    if (response.invalidateRoadmapSnapshots) {
      roadmapSnapshots.invalidateAll();
      response.invalidateRoadmapSnapshots = false;
    }
  } catch (error) {
    response.invalidateRoadmapSnapshots = false;
    throw error;
  }
  return true;
  } finally { readBudget?.cleanup(); }
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
