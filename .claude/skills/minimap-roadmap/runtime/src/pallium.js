import fs from "node:fs/promises";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const PAGE_SIZE = 50;
const MAX_PARTICIPANTS = 200;
const MAX_PAGE_BYTES = 128 * 1024;
const MAX_TOTAL_BYTES = 256 * 1024;
const LOOKUP_TIMEOUT_MS = 2000;
const CONTRACT = "relay-session-work-associations/v1";
const REFERENCE_CONTRACT = "minimap-roadmap-item/v1";
const WORK_REF_SECRET_RE = /(?:\bgh[pousr]_[A-Za-z0-9]{30,255}\b|\bxox(?:[abpr]-\d{6,20}-\d{6,20}-[A-Za-z0-9]{20,64}|[a-z]-[A-Za-z0-9-]{20,255})\b|\bsk-(?:(?:ant-api\d{2}|proj)-)?[A-Za-z0-9_-]{20,255}\b|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b)/i;
const REDACTABLE_SECRET_RE = /(?:Bearer\s+\S+|(?:PASSWORD|SECRET|TOKEN|KEY|AUTH)\s*=\s*\S+|-----BEGIN [A-Z ]+KEY-----.*?-----END[^\n]*|(?:mongodb|postgres|mysql|redis):\/\/\S+|(?:Authorization|Cookie):\s*.+)/is;

function containsSensitive(value) {
  return String(value).includes("[REDACTED") || WORK_REF_SECRET_RE.test(value) || REDACTABLE_SECRET_RE.test(value);
}

class LookupError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

function hasUnsafeUnicode(value) {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (
      code <= 0x1f
      || (code >= 0x7f && code <= 0x9f)
      || code === 0x2028
      || code === 0x2029
      || (code >= 0xd800 && code <= 0xdbff && (index + 1 >= value.length || value.charCodeAt(index + 1) < 0xdc00 || value.charCodeAt(index + 1) > 0xdfff))
      || (code >= 0xdc00 && code <= 0xdfff && (index === 0 || value.charCodeAt(index - 1) < 0xd800 || value.charCodeAt(index - 1) > 0xdbff))
    ) {
      return true;
    }
    if (code >= 0xd800 && code <= 0xdbff) index += 1;
  }
  return false;
}

function validateReadablePart(value, { local = false } = {}) {
  if (typeof value !== "string" || !value || hasUnsafeUnicode(value)) return false;
  if (/^[ \t\n\r\f\v]|[ \t\n\r\f\v]$/.test(value)) return false;
  if (Buffer.byteLength(value, "utf8") > 512) return false;
  if (local && [...value].length > 128) return false;
  if (containsSensitive(value)) return false;
  return true;
}

export function encodeReferencePart(value) {
  return encodeURIComponent(String(value).normalize("NFC")).replace(/[!'()*]/g, (character) => (
    "%" + character.charCodeAt(0).toString(16).toUpperCase()
  ));
}

function hasInvalidPathSegment(value) {
  return value.split("/").some((part) => !part || part === "." || part === "..");
}

export function canonicalGitRemote(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  const raw = value.trim();
  if (raw.includes("\\") || hasUnsafeUnicode(raw) || containsSensitive(raw)) return null;

  let host;
  let port = "";
  let remotePath;
  let scheme;

  const scp = raw.match(/^([^/@:]+)@([^/:]+):(.+)$/);
  if (scp) {
    if (/\s/.test(scp[1] + scp[2])) return null;
    scheme = "ssh";
    host = scp[2];
    remotePath = scp[3];
  } else {
    let parsed;
    try {
      const authority = raw.match(/^[A-Za-z][A-Za-z0-9+.-]*:\/\/([^/]+)/)?.[1] || "";
      const hostPort = authority.split("@").at(-1);
      if (
        !authority
        || [...authority].some((character) => character.charCodeAt(0) > 127)
        || authority.includes("%")
        || hostPort.endsWith(":")
      ) return null;
      const withoutAuthority = raw.replace(/^[A-Za-z][A-Za-z0-9+.-]*:\/\/[^/]*/, "");
      if (/%(?![0-9A-Fa-f]{2})/.test(withoutAuthority)) return null;
      const rawPath = withoutAuthority.split(/[?#]/, 1)[0];
      const decodedRawPath = decodeURIComponent(rawPath);
      if (hasInvalidPathSegment(decodedRawPath.replace(/^\/+|\/+$/g, ""))) return null;
      parsed = new URL(raw);
      const suffix = decodeURIComponent(
        [parsed.search.slice(1), parsed.hash.slice(1)].filter(Boolean).join("&"),
      );
      if (suffix && containsSensitive(suffix)) return null;
      const hasUserinfo = authority.includes("@");
      const rawUserinfo = hasUserinfo ? authority.slice(0, authority.lastIndexOf("@")) : "";
      if (parsed.password || (hasUserinfo && (!parsed.username || parsed.protocol !== "ssh:" || rawUserinfo.includes(":")))) return null;
      if (hasUserinfo && !/^[A-Za-z0-9._-]+$/.test(parsed.username)) return null;
    } catch {
      return null;
    }
    if (!["https:", "ssh:"].includes(parsed.protocol) || !parsed.hostname) return null;
    scheme = parsed.protocol.slice(0, -1);
    host = parsed.hostname;
    port = parsed.port;
    try {
      remotePath = decodeURIComponent(parsed.pathname);
    } catch {
      return null;
    }
  }

  const normalizedHost = String(host).toLowerCase();
  if (!normalizedHost || !/^[\x00-\x7f]+$/.test(normalizedHost) || normalizedHost.includes("%")) return null;
  if (port && (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535)) return null;
  const defaultPort = scheme === "ssh" ? "22" : "443";
  const authority = normalizedHost + (port && port !== defaultPort ? ":" + Number(port) : "");

  let normalizedPath = String(remotePath || "").normalize("NFC").replace(/^\/+|\/+$/g, "");
  if (normalizedPath.endsWith(".git")) normalizedPath = normalizedPath.slice(0, -4);
  if (!normalizedPath || hasInvalidPathSegment(normalizedPath) || containsSensitive(normalizedPath) || hasUnsafeUnicode(normalizedPath)) return null;
  if (normalizedHost === "github.com") normalizedPath = normalizedPath.toLowerCase();
  return "git:" + authority + "/" + normalizedPath;
}

function isIpv4Loopback(hostname) {
  const match = hostname.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  return Boolean(match) && Number(match[1]) === 127 && match.slice(1).every((part) => Number(part) <= 255);
}

export function isLoopbackHost(hostname) {
  const normalized = String(hostname || "").toLowerCase().replace(/^\[|\]$/g, "");
  return normalized === "localhost" || normalized === "::1" || isIpv4Loopback(normalized);
}

export function parsePalliumEndpoint(rawValue) {
  if (typeof rawValue !== "string" || !rawValue.trim()) {
    return { configured: false, endpoint: null };
  }
  try {
    const url = new URL(rawValue.trim());
    if (
      url.protocol !== "http:"
      || !isLoopbackHost(url.hostname)
      || url.username
      || url.password
      || url.search
      || url.hash
      || (url.pathname !== "" && url.pathname !== "/")
    ) {
      return { configured: true, endpoint: null };
    }
    return { configured: true, endpoint: url.origin };
  } catch {
    return { configured: true, endpoint: null };
  }
}

function normalizeRemoteAddress(value) {
  return String(value || "").toLowerCase().replace(/^::ffff:/, "");
}

export function isTrustedParticipantRequest(request) {
  if (!isLoopbackHost(normalizeRemoteAddress(request?.socket?.remoteAddress))) return false;
  const host = request?.headers?.host;
  if (typeof host !== "string" || !host) return false;
  let requestOrigin;
  try {
    const parsed = new URL("http://" + host);
    if (!isLoopbackHost(parsed.hostname)) return false;
    requestOrigin = parsed.origin;
  } catch {
    return false;
  }
  const origin = request?.headers?.origin;
  if (origin === undefined) return true;
  try {
    return new URL(origin).origin === requestOrigin;
  } catch {
    return false;
  }
}

async function runGit(args, cwd) {
  const result = await execFileAsync("git", args, {
    cwd,
    timeout: 2000,
    maxBuffer: 64 * 1024,
    windowsHide: true,
    shell: false,
  });
  return String(result.stdout || "").replace(/[\r\n]+$/, "");
}

function encodedRoadmapRoot(gitRoot, roadmapRoot) {
  const relative = path.relative(gitRoot, roadmapRoot);
  if (path.isAbsolute(relative) || relative === ".." || relative.startsWith(".." + path.sep)) return null;
  if (!relative) return ".";
  const parts = relative.split(/[\\/]/);
  if (parts.some((part) => !part || part === "." || part === "..")) return null;
  return parts.map(encodeReferencePart).join("/");
}

export async function resolveRoadmapItemReference(repoRoot, roadmapPath, itemId, options = {}) {
  const git = options.runGit || runGit;
  const realpath = options.realpath || fs.realpath;
  try {
    const gitRoot = await realpath(path.resolve(await git(["rev-parse", "--show-toplevel"], repoRoot)));
    const remote = await git(["remote", "get-url", "origin"], gitRoot);
    const repositoryRef = canonicalGitRemote(remote);
    if (!repositoryRef) return null;

    const roadmapRoot = await realpath(path.resolve(repoRoot, roadmapPath));
    const encodedRoot = encodedRoadmapRoot(gitRoot, roadmapRoot);
    if (encodedRoot === null) return null;

    const scopeRef = "roadmap:v1:" + repositoryRef + "#" + encodedRoot;
    const localRef = "item:v1:" + encodeReferencePart(itemId);
    if (!validateReadablePart(scopeRef) || !validateReadablePart(localRef, { local: true })) return null;

    return {
      contract: REFERENCE_CONTRACT,
      scope_ref: scopeRef,
      local_ref: localRef,
    };
  } catch {
    return null;
  }
}

function boundedString(value, maximum, optional = false) {
  if (value === null && optional) return null;
  if (typeof value !== "string" || !value || [...value].length > maximum || hasUnsafeUnicode(value)) {
    throw new LookupError("invalid-response");
  }
  return value;
}

function timestamp(value, optional = false) {
  const parsed = boundedString(value, 64, optional);
  if (parsed === null) return null;
  if (!Number.isFinite(Date.parse(parsed))) throw new LookupError("invalid-response");
  return parsed;
}

function validateParticipant(row, reference) {
  if (!row || typeof row !== "object" || Array.isArray(row)) throw new LookupError("invalid-response");
  const state = boundedString(row.state, 32);
  const lifecycle = boundedString(row.lifecycle, 32);
  const health = row.destination_health === null ? null : boundedString(row.destination_health, 32, true);
  if (!["active", "unreachable", "closed"].includes(state)) throw new LookupError("invalid-response");
  if (!["recent", "dormant", "closed"].includes(lifecycle)) throw new LookupError("invalid-response");
  if (health !== null && !["active", "unreachable"].includes(health)) throw new LookupError("invalid-response");
  if (!Number.isInteger(row.scope_generation) || row.scope_generation < 0) throw new LookupError("invalid-response");

  const association = row.association;
  if (!association || typeof association !== "object" || Array.isArray(association)) throw new LookupError("invalid-response");
  if (
    association.scope_ref !== reference.scope_ref
    || association.local_ref !== reference.local_ref
    || typeof association.work_ref !== "string"
    || !/^work:v1:[0-9a-f]{64}$/.test(association.work_ref)
    || !Array.isArray(association.origins)
    || association.origins.some((origin) => !["explicit", "structural"].includes(origin))
  ) {
    throw new LookupError("invalid-response");
  }

  return {
    endpoint_id: boundedString(row.endpoint_id, 128),
    runtime: boundedString(row.runtime, 64),
    session_ref: boundedString(row.session_ref, 255),
    container_ref: boundedString(row.container_ref, 512),
    title: row.title === null || row.title === undefined ? null : boundedString(row.title, 255),
    alias: row.alias === null || row.alias === undefined ? null : boundedString(row.alias, 32),
    state,
    lifecycle,
    destination_health: health,
    first_seen_at: timestamp(row.first_seen_at),
    last_seen_at: timestamp(row.last_seen_at),
    closed_at: row.closed_at === null || row.closed_at === undefined ? null : timestamp(row.closed_at),
    scope_generation: row.scope_generation,
    association: {
      work_ref: association.work_ref,
      scope_ref: association.scope_ref,
      local_ref: association.local_ref,
      origins: [...new Set(association.origins)],
      created_at: timestamp(association.created_at),
      updated_at: timestamp(association.updated_at),
    },
  };
}

async function readJsonBounded(response, pageLimit, remainingTotal) {
  const contentLength = Number(response.headers.get("content-length"));
  if (Number.isFinite(contentLength) && contentLength > Math.min(pageLimit, remainingTotal)) {
    throw new LookupError("over-limit");
  }
  if (!response.body?.getReader) throw new LookupError("invalid-response");

  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > pageLimit || size > remainingTotal) {
      await reader.cancel().catch(() => {});
      throw new LookupError("over-limit");
    }
    chunks.push(Buffer.from(value));
  }

  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks));
    return { payload: JSON.parse(text), size };
  } catch (error) {
    if (error instanceof LookupError) throw error;
    throw new LookupError("invalid-response");
  }
}

function safeResult(status, reference, participants = [], partial = false, refreshedAt = null) {
  return { status, reference, participants, partial, refreshedAt };
}

export async function lookupPalliumParticipants(config, reference, options = {}) {
  if (!config?.configured) return safeResult("disabled", reference);
  if (!reference) return safeResult("identity-unavailable", null);
  if (!config.endpoint) return safeResult("unsupported", reference);

  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const controller = new AbortController();
  const externalSignal = options.signal;
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, options.timeoutMs || LOOKUP_TIMEOUT_MS);
  const abortFromCaller = () => controller.abort();
  externalSignal?.addEventListener("abort", abortFromCaller, { once: true });

  const participants = [];
  let totalBytes = 0;
  let partial = false;
  let canonicalWorkRef = null;

  try {
    for (let offset = 0; offset < MAX_PARTICIPANTS; offset += PAGE_SIZE) {
      const url = new URL("/relay/work-refs/participants", config.endpoint);
      url.searchParams.set("scope_ref", reference.scope_ref);
      url.searchParams.set("local_ref", reference.local_ref);
      url.searchParams.set("offset", String(offset));
      url.searchParams.set("limit", String(PAGE_SIZE));
      url.searchParams.set("include_closed", "false");

      let response;
      try {
        response = await fetchImpl(url, { signal: controller.signal, redirect: "error" });
      } catch (error) {
        if (externalSignal?.aborted) throw error;
        if (timedOut) return safeResult("timeout", reference, [], false, new Date().toISOString());
        return safeResult("unreachable", reference, [], false, new Date().toISOString());
      }

      if ([404, 405, 501].includes(response.status)) {
        return safeResult("unsupported", reference, [], false, new Date().toISOString());
      }
      if (!response.ok) {
        return safeResult("unreachable", reference, [], false, new Date().toISOString());
      }

      const read = await readJsonBounded(
        response,
        options.maxPageBytes || MAX_PAGE_BYTES,
        (options.maxTotalBytes || MAX_TOTAL_BYTES) - totalBytes,
      );
      totalBytes += read.size;
      const page = read.payload;
      if (
        !page
        || page.contract !== CONTRACT
        || typeof page.work_ref !== "string"
        || !/^work:v1:[0-9a-f]{64}$/.test(page.work_ref)
        || (canonicalWorkRef !== null && page.work_ref !== canonicalWorkRef)
        || typeof page.history_guidance !== "string"
        || !page.history_guidance
        || [...page.history_guidance].length > 2000
        || hasUnsafeUnicode(page.history_guidance)
        || page.scope_ref !== reference.scope_ref
        || page.local_ref !== reference.local_ref
        || page.offset !== offset
        || page.limit !== PAGE_SIZE
        || !Array.isArray(page.participants)
        || page.participants.length > PAGE_SIZE
      ) {
        throw new LookupError("invalid-response");
      }

      canonicalWorkRef ||= page.work_ref;
      const rows = page.participants.map((row) => validateParticipant(row, reference));
      if (rows.some((row) => row.association.work_ref !== canonicalWorkRef)) {
        throw new LookupError("invalid-response");
      }
      participants.push(...rows);
      if (rows.length < PAGE_SIZE) {
        partial = false;
        break;
      }
      if (participants.length === MAX_PARTICIPANTS) partial = true;
    }
    return safeResult("ok", reference, participants, partial, new Date().toISOString());
  } catch (error) {
    if (externalSignal?.aborted) throw error;
    if (timedOut) return safeResult("timeout", reference, [], false, new Date().toISOString());
    const status = error instanceof LookupError ? error.code : "invalid-response";
    return safeResult(status, reference, [], false, new Date().toISOString());
  } finally {
    clearTimeout(timer);
    externalSignal?.removeEventListener("abort", abortFromCaller);
  }
}
