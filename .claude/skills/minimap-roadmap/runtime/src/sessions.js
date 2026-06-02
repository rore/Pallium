import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { AppError } from "./roadmap.js";

const SESSION_INDEX_FILE = "session-index.json";
const SESSION_INDEX_VERSION = 1;
const EMPTY_JSONL = "";
const TEXT_EXTENSIONS = new Set([".md", ".mdx", ".txt", ".rst", ".adoc"]);
const MARKDOWN_EXTENSIONS = new Set([".md", ".mdx"]);
const COMMENT_KINDS = new Set([
  "instruction",
  "concern",
  "question",
  "evidence",
  "disagreement",
  "confirmation",
  "recommendation",
  "conclusion",
]);
const COMMENT_STATUSES = new Set(["open", "resolved", "accepted", "rejected", "deferred", "stale"]);
const SUGGESTION_KINDS = new Set(["replace", "insert_after", "delete"]);
const SUGGESTION_STATUSES = new Set(["pending", "accepted", "rejected", "applied", "stale"]);

function nowIso() {
  return new Date().toISOString();
}

function normalizeSlashes(value) {
  return String(value || "").replaceAll("\\", "/");
}

function normalizeFileKey(filePath, platform = process.platform) {
  const normalized = normalizeSlashes(path.resolve(filePath));
  return platform === "win32" ? normalized.toLowerCase() : normalized;
}

function shortHash(value) {
  return crypto.createHash("sha256").update(value).digest("hex").slice(0, 8);
}

function hashContent(buffer) {
  return `sha256:${crypto.createHash("sha256").update(buffer).digest("hex")}`;
}

function hashText(value) {
  return `sha256:${crypto.createHash("sha256").update(String(value)).digest("hex")}`;
}

function detectLineEnding(text) {
  return String(text).includes("\r\n") ? "\r\n" : "\n";
}

// Decode literal backslash escapes (\n, \r, \t, \\) in suggestion content.
// Authors — particularly LLMs — sometimes emit `\n` as a two-character literal
// instead of a real newline. Without decoding, applying such a suggestion
// would write the literal backslash-n into the file. We decode conservatively:
// only the four common escapes.
function decodeLiteralEscapes(value) {
  if (typeof value !== "string" || value.indexOf("\\") === -1) return String(value || "");
  return value.replace(/\\([nrt\\])/g, (_, ch) => {
    if (ch === "n") return "\n";
    if (ch === "r") return "\r";
    if (ch === "t") return "\t";
    return "\\";
  });
}

function normalizeSuggestionContent(content, lineEnding) {
  return decodeLiteralEscapes(content).replace(/\r\n|\r|\n/g, lineEnding);
}

function slugifyBasename(filePath) {
  const parsed = path.parse(filePath);
  const source = parsed.name || parsed.base || "file";
  const slug = source
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "file";
}

function makeSessionId(fileKey, filePath) {
  return `${slugifyBasename(filePath)}-${shortHash(fileKey)}`;
}

function normalizeDisplayPath(value) {
  return normalizeSlashes(path.resolve(value));
}

function isKnownTextExtension(filePath) {
  const extension = path.extname(filePath).toLowerCase();
  return TEXT_EXTENSIONS.has(extension) || extension === "";
}

function detectFileKind(filePath) {
  const extension = path.extname(filePath).toLowerCase();
  if (MARKDOWN_EXTENSIONS.has(extension)) {
    return { kind: "markdown", markdown: true };
  }
  return { kind: "text", markdown: false };
}

function looksBinary(buffer) {
  if (buffer.includes(0)) {
    return true;
  }

  const sample = buffer.subarray(0, Math.min(buffer.length, 4096));
  if (sample.length === 0) {
    return false;
  }

  let controlCount = 0;
  for (const byte of sample) {
    if (byte === 9 || byte === 10 || byte === 13) {
      continue;
    }
    if (byte < 32) {
      controlCount += 1;
    }
  }

  return controlCount / sample.length > 0.05;
}

function splitLinesPreserveText(text) {
  return String(text).split(/\r?\n/);
}

function stripClosingHeadingHashes(title) {
  return title.replace(/\s+#+\s*$/, "").trim();
}

export function parseMarkdownOutline(text) {
  const lines = splitLinesPreserveText(text);
  const outline = [];
  const headingStack = [];
  let inFence = false;

  lines.forEach((line, index) => {
    if (/^\s*(```|~~~)/.test(line)) {
      inFence = !inFence;
      return;
    }

    if (inFence) {
      return;
    }

    const match = line.match(/^(#{1,6})\s+(.+?)\s*$/);
    if (!match) {
      return;
    }

    const level = match[1].length;
    const title = stripClosingHeadingHashes(match[2]);
    if (!title) {
      return;
    }

    headingStack.length = level - 1;
    headingStack[level - 1] = title;
    const headingPath = headingStack.filter(Boolean);

    outline.push({
      level,
      title,
      headingPath,
      lineStart: index + 1,
    });
  });

  return outline;
}

function lineRangeForOffset(text, offset, length) {
  const before = text.slice(0, offset);
  const selected = text.slice(offset, offset + length);
  const lineStart = before.split(/\r?\n/).length;
  const lineEnd = lineStart + selected.split(/\r?\n/).length - 1;
  return { lineStart, lineEnd };
}

function lineTextForRange(text, lineStart, lineEnd) {
  const lines = splitLinesPreserveText(text);
  return lines.slice(lineStart - 1, lineEnd).join("\n");
}

function headingPathForLine(text, lineNumber) {
  const outline = parseMarkdownOutline(text);
  let current = [];

  for (const heading of outline) {
    if (heading.lineStart > lineNumber) {
      break;
    }
    current = heading.headingPath;
  }

  return current;
}

// Strip markdown syntax characters that often disappear when text is
// extracted from a rendered view, copy-pasted across editors, or escaped by
// a shell. This is intentionally conservative: it removes only inline
// markers (backticks, asterisks, underscores, leading heading hashes) and
// normalizes whitespace. It does NOT touch link/image syntax or fenced
// code blocks — those would change semantics.
function stripMarkdownSyntax(value) {
  return String(value || "")
    .replace(/^#{1,6}\s+/gm, "")     // strip `### ` heading prefixes
    .replace(/[`*_]/g, "")           // strip inline code/bold/italic markers
    .replace(/\s+/g, " ")
    .trim();
}

function findQuoteOccurrences(text, quote) {
  if (!quote) {
    return [];
  }

  const occurrences = [];
  let offset = text.indexOf(quote);

  while (offset !== -1) {
    occurrences.push({
      offset,
      ...lineRangeForOffset(text, offset, quote.length),
    });
    offset = text.indexOf(quote, offset + Math.max(quote.length, 1));
  }

  if (occurrences.length > 0) {
    return occurrences;
  }

  // Literal search missed. Retry with markdown syntax stripped from both
  // sides — catches the common case where the quote was captured from a
  // rendered view (no backticks, no `### ` prefix) but the file has them,
  // or vice versa. We map the stripped match back to a line range using
  // the strippedQuote's location in a strippedText copy and then use the
  // first non-empty line in the original text whose stripped form contains
  // the stripped quote. This is approximate but lets the anchor resolve.
  const strippedQuote = stripMarkdownSyntax(quote);
  if (!strippedQuote) {
    return [];
  }

  const lines = text.split(/\r?\n/);
  const fallback = [];
  let lineOffset = 0;
  for (let i = 0; i < lines.length; i += 1) {
    const stripped = stripMarkdownSyntax(lines[i]);
    if (stripped && stripped.includes(strippedQuote)) {
      fallback.push({
        offset: lineOffset,
        lineStart: i + 1,
        lineEnd: i + 1,
        approximate: true,
      });
    }
    lineOffset += lines[i].length + 1; // +1 for the newline
  }
  return fallback;
}

function sameHeadingPath(left = [], right = []) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

// Loose comparator: case-insensitive, Unicode NFC-normalized, with em-dashes
// and en-dashes folded to hyphens. Catches the common typography drift you
// see when a heading title was retyped (or PowerShell normalized it). Used
// only as a fallback when strict equality misses.
function normalizeHeadingValue(value) {
  return String(value || "")
    .normalize("NFC")
    .replace(/[—–]/g, "-")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function sameHeadingPathLoose(left = [], right = []) {
  if (left.length !== right.length) return false;
  for (let i = 0; i < left.length; i += 1) {
    if (normalizeHeadingValue(left[i]) !== normalizeHeadingValue(right[i])) return false;
  }
  return true;
}

function endsWithHeadingPath(haystack = [], suffix = []) {
  if (suffix.length === 0 || suffix.length > haystack.length) return false;
  const offset = haystack.length - suffix.length;
  for (let i = 0; i < suffix.length; i += 1) {
    if (normalizeHeadingValue(haystack[offset + i]) !== normalizeHeadingValue(suffix[i])) return false;
  }
  return true;
}

// Resolve a heading anchor through a tolerance cascade:
//   1. exact full-path match
//   2. exact full-path match with Unicode/case normalization
//   3. unique suffix match (the user gave a tail of the canonical path)
//   4. unique leaf match (the user gave just the heading title)
// Returns the matched outline entry, or { ambiguous: candidates } when more
// than one outline entry matches at a tier (we surface that distinctly so
// callers can tell "no match" from "too many matches").
function resolveHeadingAnchor(outline, headingPath) {
  if (!Array.isArray(headingPath) || headingPath.length === 0) return null;

  const exact = outline.find((heading) => sameHeadingPath(heading.headingPath, headingPath));
  if (exact) return { match: exact };

  const loose = outline.filter((heading) => sameHeadingPathLoose(heading.headingPath, headingPath));
  if (loose.length === 1) return { match: loose[0] };
  if (loose.length > 1) return { ambiguous: loose };

  const suffix = outline.filter((heading) => endsWithHeadingPath(heading.headingPath, headingPath));
  if (suffix.length === 1) return { match: suffix[0] };
  if (suffix.length > 1) return { ambiguous: suffix };

  if (headingPath.length === 1) {
    const leafTarget = normalizeHeadingValue(headingPath[0]);
    const leaf = outline.filter((heading) => normalizeHeadingValue(heading.title) === leafTarget);
    if (leaf.length === 1) return { match: leaf[0] };
    if (leaf.length > 1) return { ambiguous: leaf };
  }

  return null;
}

export function createTextAnchor(text, options = {}) {
  const quote = String(options.quote || "");
  if (!quote) {
    throw new AppError("Text anchors require a quote.", 400, "bad_request");
  }

  const occurrences = findQuoteOccurrences(text, quote);
  if (occurrences.length === 0) {
    throw new AppError("Text anchor quote must match exactly one location.", 422, "anchor_orphaned");
  }

  // Disambiguation: when the same phrase appears more than once (common in
  // specs that mention something in prose AND inside a fenced code block),
  // prefer the occurrence whose lineStart matches the caller's hint. The
  // hint is optional — if absent or no occurrence matches, we keep the
  // existing strict-uniqueness behavior so old callers see the same error.
  // When there is exactly one occurrence the hint is irrelevant.
  let occurrence;
  if (occurrences.length === 1) {
    occurrence = occurrences[0];
  } else {
    const hint = Number.isInteger(options.lineStart) ? options.lineStart : null;
    occurrence = hint !== null ? occurrences.find((o) => o.lineStart === hint) : null;
    if (!occurrence) {
      throw new AppError("Text anchor quote must match exactly one location.", 422, "anchor_ambiguous");
    }
  }

  const headingPath = Array.isArray(options.headingPath) ? options.headingPath : headingPathForLine(text, occurrence.lineStart);

  return {
    scope: "anchor",
    quote,
    headingPath,
    lineStart: occurrence.lineStart,
    lineEnd: occurrence.lineEnd,
    selectedHash: hashText(quote),
    fileHash: options.fileHash || hashText(text),
  };
}

export function resolveTextAnchor(text, anchor = {}) {
  if (anchor.scope === "global") {
    return { status: "resolved", strategy: "global" };
  }

  if (anchor.scope === "section") {
    const resolution = resolveHeadingAnchor(parseMarkdownOutline(text), anchor.headingPath || []);
    if (resolution?.match) {
      return {
        status: "resolved",
        strategy: "heading_path",
        lineStart: resolution.match.lineStart,
        lineEnd: resolution.match.lineStart,
        // The canonical full path of the matched heading. May differ from
        // the input when the user passed a leaf-only or suffix path.
        headingPath: resolution.match.headingPath,
      };
    }
    if (resolution?.ambiguous) {
      return {
        status: "orphaned",
        strategy: "heading_path",
        ambiguous: resolution.ambiguous.map((heading) => heading.headingPath),
      };
    }
    return { status: "orphaned", strategy: "heading_path" };
  }

  const quote = String(anchor.quote || "");
  if (!quote) {
    return { status: "orphaned", strategy: "missing_quote" };
  }

  if (anchor.lineStart && anchor.lineEnd) {
    const currentRangeText = lineTextForRange(text, anchor.lineStart, anchor.lineEnd);
    if (currentRangeText.includes(quote) && (!anchor.selectedHash || anchor.selectedHash === hashText(quote))) {
      return {
        status: "resolved",
        strategy: "line_range",
        lineStart: anchor.lineStart,
        lineEnd: anchor.lineEnd,
      };
    }
  }

  const occurrences = findQuoteOccurrences(text, quote);
  if (occurrences.length === 0) {
    return { status: "orphaned", strategy: "quote" };
  }

  const headingMatches = occurrences.filter((occurrence) => sameHeadingPath(headingPathForLine(text, occurrence.lineStart), anchor.headingPath || []));
  if (headingMatches.length === 1) {
    return {
      status: "resolved",
      strategy: "heading_quote",
      lineStart: headingMatches[0].lineStart,
      lineEnd: headingMatches[0].lineEnd,
    };
  }
  if (headingMatches.length > 1) {
    return { status: "ambiguous", strategy: "heading_quote" };
  }

  if (occurrences.length === 1) {
    return {
      status: "resolved",
      strategy: "quote",
      lineStart: occurrences[0].lineStart,
      lineEnd: occurrences[0].lineEnd,
    };
  }

  return { status: "ambiguous", strategy: "quote" };
}

async function readTextTarget(filePath) {
  const buffer = await fs.readFile(filePath).catch((error) => {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
      throw new AppError(`Attached file no longer exists: ${normalizeDisplayPath(filePath)}`, 404, "target_missing");
    }
    throw error;
  });
  if (!isKnownTextExtension(filePath) && looksBinary(buffer)) {
    throw new AppError("Attached file must be a text file.", 422, "invalid_target");
  }
  if (looksBinary(buffer)) {
    throw new AppError("Attached file must be a text file.", 422, "invalid_target");
  }

  const text = buffer.toString("utf8");
  if (text.includes("\uFFFD")) {
    throw new AppError("Attached file must be valid UTF-8 text.", 422, "invalid_target");
  }

  return { buffer, text };
}

async function pathExists(targetPath) {
  try {
    await fs.access(targetPath);
    return true;
  } catch {
    return false;
  }
}

async function findRepoRoot(startPath) {
  let current = path.dirname(path.resolve(startPath));

  while (true) {
    const gitPath = path.join(current, ".git");
    if (await pathExists(gitPath)) {
      return current;
    }

    const parent = path.dirname(current);
    if (parent === current) {
      return null;
    }
    current = parent;
  }
}

async function resolveGitDir(repoRoot) {
  const gitPath = path.join(repoRoot, ".git");
  const stat = await fs.stat(gitPath);
  if (stat.isDirectory()) {
    return gitPath;
  }

  const content = await fs.readFile(gitPath, "utf8");
  const match = content.match(/^gitdir:\s*(.+)\s*$/i);
  if (!match) {
    return null;
  }

  return path.resolve(repoRoot, match[1]);
}

async function readGitHead(repoRoot) {
  if (!repoRoot) {
    return "";
  }

  try {
    const gitDir = await resolveGitDir(repoRoot);
    if (!gitDir) {
      return "";
    }

    const head = (await fs.readFile(path.join(gitDir, "HEAD"), "utf8")).trim();
    if (!head.startsWith("ref:")) {
      return head;
    }

    const refPath = head.slice("ref:".length).trim();
    return (await fs.readFile(path.join(gitDir, refPath), "utf8")).trim();
  } catch {
    return "";
  }
}

function normalizeRepoRelativePath(repoRoot, targetPath) {
  if (!repoRoot) {
    return "";
  }
  return normalizeSlashes(path.relative(repoRoot, targetPath));
}

function makeSessionPaths(minimapHome, sessionId) {
  const sessionDir = path.join(minimapHome, "sessions", sessionId);
  return {
    sessionDir,
    sessionJson: path.join(sessionDir, "session.json"),
    commentsJsonl: path.join(sessionDir, "comments.jsonl"),
    suggestionsJsonl: path.join(sessionDir, "suggestions.jsonl"),
    eventsJsonl: path.join(sessionDir, "events.jsonl"),
  };
}

async function readJson(filePath, fallback) {
  try {
    return JSON.parse(await fs.readFile(filePath, "utf8"));
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
      return fallback;
    }
    throw error;
  }
}

async function writeJson(filePath, value) {
  await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function readJsonLines(filePath) {
  const content = await fs.readFile(filePath, "utf8").catch((error) => {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
      return "";
    }
    throw error;
  });

  return content
    .split(/\r?\n/)
    .filter((line) => line.trim() !== "")
    .map((line) => JSON.parse(line));
}

async function appendJsonLine(filePath, value) {
  await fs.appendFile(filePath, `${JSON.stringify(value)}\n`, "utf8");
}

async function writeJsonLines(filePath, values) {
  const content = values.map((value) => JSON.stringify(value)).join("\n");
  await fs.writeFile(filePath, content ? `${content}\n` : "", "utf8");
}

function nextCommentId(comments) {
  return `cmt_${String(comments.length + 1).padStart(6, "0")}`;
}

function nextSuggestionId(suggestions) {
  return `sug_${String(suggestions.length + 1).padStart(6, "0")}`;
}

function nextReplyId(comment) {
  const replies = Array.isArray(comment.replies) ? comment.replies : [];
  return `rpl_${String(replies.length + 1).padStart(6, "0")}`;
}

function requireNonEmptyString(value, message) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new AppError(message, 400, "bad_request");
  }
  return value.trim();
}

function requireNonBlankString(value, message) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new AppError(message, 400, "bad_request");
  }
  return value;
}

function validateCommentKind(kind) {
  const normalized = requireNonEmptyString(kind, "Comment kind is required.");
  if (!COMMENT_KINDS.has(normalized)) {
    throw new AppError(`Unsupported comment kind: ${normalized}`, 400, "bad_request");
  }
  return normalized;
}

function validateCommentStatus(status) {
  const normalized = requireNonEmptyString(status, "Comment status is required.");
  if (!COMMENT_STATUSES.has(normalized)) {
    throw new AppError(`Unsupported comment status: ${normalized}`, 400, "bad_request");
  }
  return normalized;
}

function validateSuggestionKind(kind) {
  const normalized = requireNonEmptyString(kind, "Suggestion kind is required.");
  if (!SUGGESTION_KINDS.has(normalized)) {
    throw new AppError(`Unsupported suggestion kind: ${normalized}`, 400, "bad_request");
  }
  return normalized;
}

function validateSuggestionStatus(status) {
  const normalized = requireNonEmptyString(status, "Suggestion status is required.");
  if (!SUGGESTION_STATUSES.has(normalized)) {
    throw new AppError(`Unsupported suggestion status: ${normalized}`, 400, "bad_request");
  }
  return normalized;
}

function makeCommentAnchor(text, input) {
  const scope = typeof input.scope === "string" && input.scope.trim() ? input.scope.trim() : "";
  if (scope === "global") {
    return { scope: "global" };
  }

  if (scope === "section") {
    if (!Array.isArray(input.headingPath) || input.headingPath.length === 0 || input.headingPath.some((part) => typeof part !== "string" || part.trim() === "")) {
      throw new AppError("Section comments require a headingPath.", 400, "bad_request");
    }
    const anchor = {
      scope: "section",
      headingPath: input.headingPath.map((part) => part.trim()),
    };
    const resolved = resolveTextAnchor(text, anchor);
    if (resolved.status !== "resolved") {
      if (Array.isArray(resolved.ambiguous) && resolved.ambiguous.length > 1) {
        const rendered = resolved.ambiguous.map((path) => path.join(" > ")).join("; ");
        throw new AppError(`Section anchor matched multiple headings: ${rendered}. Pass the full heading path.`, 422, "anchor_ambiguous");
      }
      throw new AppError("Section anchor could not be resolved.", 422, "anchor_orphaned");
    }
    // Store the canonical full path (the user may have passed a leaf-only or
    // suffix path; we resolve to the unambiguous one once on creation so future
    // resolves are stable).
    if (Array.isArray(resolved.headingPath) && resolved.headingPath.length > 0) {
      anchor.headingPath = resolved.headingPath;
    }
    return anchor;
  }

  const quote = typeof input.quote === "string" ? input.quote : "";
  if (quote.trim() !== "") {
    return createTextAnchor(text, {
      quote,
      headingPath: Array.isArray(input.headingPath) ? input.headingPath : undefined,
      // Optional disambiguation hint for duplicate quotes. Only forwarded
      // when the caller passed a positive integer line number; everything
      // else is dropped so we don't smuggle through a stale hint.
      lineStart: Number.isInteger(input.lineStart) && input.lineStart > 0 ? input.lineStart : undefined,
    });
  }

  throw new AppError("Comments require scope=global, scope=section with headingPath, or quote.", 400, "bad_request");
}

function makeSuggestionAnchor(text, input) {
  const anchor = makeCommentAnchor(text, input);
  if (anchor.scope === "global") {
    throw new AppError("Suggestions require a section or quote anchor.", 400, "bad_request");
  }
  return anchor;
}

function withAnchorStatus(comment, text) {
  return {
    ...comment,
    anchorStatus: resolveTextAnchor(text, comment.anchor),
  };
}

function withSuggestionAnchorStatus(suggestion, text) {
  return {
    ...suggestion,
    anchorStatus: resolveTextAnchor(text, suggestion.anchor),
  };
}

async function loadCommentState(filePath, options) {
  const session = await getFileSession(filePath, options);
  const minimapHome = options.minimapHome || resolveMinimapHome(options.env || process.env, options.platform || process.platform);
  const paths = makeSessionPaths(minimapHome, session.id);
  await ensureSessionFiles(paths);
  const targetPath = path.resolve(session.targetFile);
  const { text } = await readTextTarget(targetPath);
  const comments = await readJsonLines(paths.commentsJsonl);
  return { session, paths, text, comments };
}

async function loadSuggestionState(filePath, options) {
  const session = await getFileSession(filePath, options);
  const minimapHome = options.minimapHome || resolveMinimapHome(options.env || process.env, options.platform || process.platform);
  const paths = makeSessionPaths(minimapHome, session.id);
  await ensureSessionFiles(paths);
  const targetPath = path.resolve(session.targetFile);
  const { text } = await readTextTarget(targetPath);
  const suggestions = await readJsonLines(paths.suggestionsJsonl);
  return { session, paths, text, suggestions };
}

function findCommentIndex(comments, commentId) {
  return comments.findIndex((comment) => comment.id === commentId);
}

function findSuggestionIndex(suggestions, suggestionId) {
  return suggestions.findIndex((suggestion) => suggestion.id === suggestionId);
}

async function saveCommentMutation(paths, session, comments, timestamp) {
  await writeJsonLines(paths.commentsJsonl, comments);
  await writeJson(paths.sessionJson, {
    ...session,
    lastActiveAt: timestamp,
  });
}

async function saveSuggestionMutation(paths, session, suggestions, timestamp) {
  await writeJsonLines(paths.suggestionsJsonl, suggestions);
  await writeJson(paths.sessionJson, {
    ...session,
    lastActiveAt: timestamp,
  });
}

async function refreshSessionMetadataForTarget(session, targetPath, timestamp) {
  const { buffer } = await readTextTarget(targetPath);
  return {
    ...session,
    lastActiveAt: timestamp,
    ...(await buildTargetMetadata(targetPath, buffer)),
  };
}

async function appendSessionEvent(paths, event) {
  await appendJsonLine(paths.eventsJsonl, event);
}

export function resolveMinimapHome(env = process.env, platform = process.platform) {
  if (env.MINIMAP_HOME && env.MINIMAP_HOME.trim()) {
    return path.resolve(env.MINIMAP_HOME);
  }

  if (platform === "win32") {
    const localAppData = env.LOCALAPPDATA && env.LOCALAPPDATA.trim()
      ? env.LOCALAPPDATA
      : path.join(os.homedir(), "AppData", "Local");
    return path.join(localAppData, "minimap");
  }

  return path.join(os.homedir(), ".minimap");
}

export async function loadSessionIndex(minimapHome = resolveMinimapHome()) {
  const indexPath = path.join(minimapHome, SESSION_INDEX_FILE);
  const index = await readJson(indexPath, { version: SESSION_INDEX_VERSION, files: {} });
  return {
    version: SESSION_INDEX_VERSION,
    files: index?.files && typeof index.files === "object" && !Array.isArray(index.files) ? index.files : {},
  };
}

async function saveSessionIndex(minimapHome, index) {
  await fs.mkdir(minimapHome, { recursive: true });
  await writeJson(path.join(minimapHome, SESSION_INDEX_FILE), {
    version: SESSION_INDEX_VERSION,
    files: index.files || {},
  });
}

async function ensureSessionFiles(paths) {
  await fs.mkdir(paths.sessionDir, { recursive: true });
  for (const filePath of [paths.commentsJsonl, paths.suggestionsJsonl, paths.eventsJsonl]) {
    if (!(await pathExists(filePath))) {
      await fs.writeFile(filePath, EMPTY_JSONL, "utf8");
    }
  }
}

async function readValidTarget(targetPath, sourcePathForMessage) {
  const stat = await fs.stat(targetPath).catch((error) => {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
      throw new AppError(`Attached file was not found: ${sourcePathForMessage}`, 404, "not_found");
    }
    throw error;
  });

  if (!stat.isFile()) {
    throw new AppError("Attached target must be a file.", 422, "invalid_target");
  }

  return readTextTarget(targetPath);
}

async function buildTargetMetadata(targetPath, contentBuffer) {
  const repoRoot = await findRepoRoot(targetPath);
  const fileKind = detectFileKind(targetPath);
  return {
    targetFile: normalizeDisplayPath(targetPath),
    title: path.basename(targetPath),
    repoRoot: repoRoot ? normalizeDisplayPath(repoRoot) : "",
    relativePath: repoRoot ? normalizeRepoRelativePath(repoRoot, targetPath) : "",
    contentHash: hashContent(contentBuffer),
    gitHead: await readGitHead(repoRoot),
    fileKind: fileKind.kind,
    markdown: fileKind.markdown,
  };
}

export async function attachFileSession(filePath, options = {}) {
  const cwd = options.cwd || process.cwd();
  const minimapHome = options.minimapHome || resolveMinimapHome(options.env || process.env, options.platform || process.platform);
  const targetPath = path.resolve(cwd, filePath);
  const { buffer } = await readValidTarget(targetPath, filePath);
  const fileKey = normalizeFileKey(targetPath, options.platform || process.platform);
  const index = await loadSessionIndex(minimapHome);
  const existingSessionId = index.files[fileKey];
  const sessionId = existingSessionId || makeSessionId(fileKey, targetPath);
  const paths = makeSessionPaths(minimapHome, sessionId);
  const existing = existingSessionId ? await readJson(paths.sessionJson, null) : null;
  const timestamp = nowIso();
  const metadata = await buildTargetMetadata(targetPath, buffer);
  const session = {
    id: sessionId,
    createdAt: existing?.createdAt || timestamp,
    lastActiveAt: timestamp,
    ...metadata,
  };

  await ensureSessionFiles(paths);
  await writeJson(paths.sessionJson, session);

  if (!existingSessionId) {
    index.files[fileKey] = sessionId;
    await saveSessionIndex(minimapHome, index);
  }

  return {
    created: !existingSessionId,
    session,
  };
}

export async function moveFileSession(fromFilePath, toFilePath, options = {}) {
  const cwd = options.cwd || process.cwd();
  const platform = options.platform || process.platform;
  const minimapHome = options.minimapHome || resolveMinimapHome(options.env || process.env, platform);
  const fromTargetPath = path.resolve(cwd, fromFilePath);
  const toTargetPath = path.resolve(cwd, toFilePath);
  const fromFileKey = normalizeFileKey(fromTargetPath, platform);
  const toFileKey = normalizeFileKey(toTargetPath, platform);
  const index = await loadSessionIndex(minimapHome);
  const sessionId = index.files[fromFileKey];

  if (!sessionId) {
    throw new AppError(`No minimap session is attached for ${fromFilePath}. Run: minimap attach ${fromFilePath}`, 404, "not_found");
  }

  const conflictingSessionId = index.files[toFileKey];
  if (conflictingSessionId && conflictingSessionId !== sessionId) {
    throw new AppError(`A different minimap session is already attached for ${toFilePath}.`, 409, "conflict");
  }

  const { buffer } = await readValidTarget(toTargetPath, toFilePath);
  const paths = makeSessionPaths(minimapHome, sessionId);
  const existing = await readJson(paths.sessionJson, null);

  if (!existing) {
    throw new AppError(`Session metadata is missing for ${fromFilePath}.`, 404, "not_found");
  }

  const session = {
    ...existing,
    lastActiveAt: nowIso(),
    ...(await buildTargetMetadata(toTargetPath, buffer)),
  };

  await ensureSessionFiles(paths);
  await writeJson(paths.sessionJson, session);

  if (fromFileKey !== toFileKey) {
    delete index.files[fromFileKey];
  }
  index.files[toFileKey] = sessionId;
  await saveSessionIndex(minimapHome, index);

  return { session };
}

export async function getFileSession(filePath, options = {}) {
  const cwd = options.cwd || process.cwd();
  const minimapHome = options.minimapHome || resolveMinimapHome(options.env || process.env, options.platform || process.platform);
  const targetPath = path.resolve(cwd, filePath);
  const fileKey = normalizeFileKey(targetPath, options.platform || process.platform);
  const index = await loadSessionIndex(minimapHome);
  const sessionId = index.files[fileKey];

  if (!sessionId) {
    throw new AppError(`No minimap session is attached for ${filePath}. Run: minimap attach ${filePath}`, 404, "not_found");
  }

  const paths = makeSessionPaths(minimapHome, sessionId);
  const session = await readJson(paths.sessionJson, null);
  if (!session) {
    throw new AppError(`Session metadata is missing for ${filePath}.`, 404, "not_found");
  }

  return session;
}

export async function removeFileSession(filePath, options = {}) {
  const cwd = options.cwd || process.cwd();
  const minimapHome = options.minimapHome || resolveMinimapHome(options.env || process.env, options.platform || process.platform);
  const targetPath = path.resolve(cwd, filePath);
  const fileKey = normalizeFileKey(targetPath, options.platform || process.platform);
  const index = await loadSessionIndex(minimapHome);
  const sessionId = index.files[fileKey];

  if (!sessionId) {
    throw new AppError(`No minimap session is attached for ${filePath}.`, 404, "not_found");
  }

  const paths = makeSessionPaths(minimapHome, sessionId);
  const session = await readJson(paths.sessionJson, null);
  delete index.files[fileKey];
  await saveSessionIndex(minimapHome, index);
  await fs.rm(paths.sessionDir, { recursive: true, force: true });

  return {
    removed: true,
    session: session || {
      id: sessionId,
      targetFile: normalizeDisplayPath(targetPath),
    },
  };
}

export async function addFileSessionComment(filePath, input = {}, options = {}) {
  const { session, paths, text, comments } = await loadCommentState(filePath, options);
  const timestamp = nowIso();
  const comment = {
    id: nextCommentId(comments),
    by: requireNonEmptyString(input.by, "Comment actor is required."),
    kind: validateCommentKind(input.kind),
    status: "open",
    anchor: makeCommentAnchor(text, input),
    text: requireNonEmptyString(input.text, "Comment text is required."),
    confidence: typeof input.confidence === "string" && input.confidence.trim() ? input.confidence.trim() : "",
    createdAt: timestamp,
    updatedAt: timestamp,
    replies: [],
  };

  await appendJsonLine(paths.commentsJsonl, comment);
  await writeJson(paths.sessionJson, {
    ...session,
    lastActiveAt: timestamp,
  });

  return {
    comment: withAnchorStatus(comment, text),
  };
}

export async function addFileSessionCommentReply(filePath, commentId, input = {}, options = {}) {
  const { session, paths, text, comments } = await loadCommentState(filePath, options);
  const index = findCommentIndex(comments, commentId);

  if (index === -1) {
    throw new AppError(`Comment was not found: ${commentId}`, 404, "not_found");
  }

  const timestamp = nowIso();
  const comment = {
    ...comments[index],
    replies: Array.isArray(comments[index].replies) ? [...comments[index].replies] : [],
    updatedAt: timestamp,
  };
  comment.replies.push({
    id: nextReplyId(comment),
    by: requireNonEmptyString(input.by, "Reply actor is required."),
    text: requireNonEmptyString(input.text, "Reply text is required."),
    createdAt: timestamp,
  });
  comments[index] = comment;

  await saveCommentMutation(paths, session, comments, timestamp);

  return {
    comment: withAnchorStatus(comment, text),
  };
}

export async function addFileSessionSuggestionReply(filePath, suggestionId, input = {}, options = {}) {
  const { session, paths, text, suggestions } = await loadSuggestionState(filePath, options);
  const index = findSuggestionIndex(suggestions, suggestionId);

  if (index === -1) {
    throw new AppError(`Suggestion was not found: ${suggestionId}`, 404, "not_found");
  }

  const timestamp = nowIso();
  const suggestion = {
    ...suggestions[index],
    replies: Array.isArray(suggestions[index].replies) ? [...suggestions[index].replies] : [],
    updatedAt: timestamp,
  };
  suggestion.replies.push({
    id: nextReplyId(suggestion),
    by: requireNonEmptyString(input.by, "Reply actor is required."),
    text: requireNonEmptyString(input.text, "Reply text is required."),
    createdAt: timestamp,
  });
  suggestions[index] = suggestion;

  await saveSuggestionMutation(paths, session, suggestions, timestamp);

  return {
    suggestion: withSuggestionAnchorStatus(suggestion, text),
  };
}

export async function updateFileSessionCommentStatus(filePath, commentId, status, input = {}, options = {}) {
  const { session, paths, text, comments } = await loadCommentState(filePath, options);
  const index = findCommentIndex(comments, commentId);

  if (index === -1) {
    throw new AppError(`Comment was not found: ${commentId}`, 404, "not_found");
  }

  const timestamp = nowIso();
  const comment = {
    ...comments[index],
    status: validateCommentStatus(status),
    statusBy: requireNonEmptyString(input.by, "Status actor is required."),
    updatedAt: timestamp,
  };
  comments[index] = comment;

  await saveCommentMutation(paths, session, comments, timestamp);

  return {
    comment: withAnchorStatus(comment, text),
  };
}

export async function addFileSessionSuggestion(filePath, input = {}, options = {}) {
  const { session, paths, text, suggestions } = await loadSuggestionState(filePath, options);
  const timestamp = nowIso();
  const kind = validateSuggestionKind(input.kind);
  const suggestion = {
    id: nextSuggestionId(suggestions),
    by: requireNonEmptyString(input.by, "Suggestion actor is required."),
    kind,
    status: "pending",
    anchor: makeSuggestionAnchor(text, input),
    content: kind === "delete" ? String(input.content || "") : requireNonBlankString(input.content, "Suggestion content is required."),
    rationale: typeof input.rationale === "string" ? input.rationale.trim() : "",
    confidence: typeof input.confidence === "string" ? input.confidence.trim() : "",
    createdAt: timestamp,
    updatedAt: timestamp,
    replies: [],
  };

  await appendJsonLine(paths.suggestionsJsonl, suggestion);
  await writeJson(paths.sessionJson, {
    ...session,
    lastActiveAt: timestamp,
  });

  return {
    suggestion: withSuggestionAnchorStatus(suggestion, text),
  };
}

export async function updateFileSessionSuggestionStatus(filePath, suggestionId, status, input = {}, options = {}) {
  const { session, paths, text, suggestions } = await loadSuggestionState(filePath, options);
  const index = findSuggestionIndex(suggestions, suggestionId);

  if (index === -1) {
    throw new AppError(`Suggestion was not found: ${suggestionId}`, 404, "not_found");
  }

  const timestamp = nowIso();
  const previousStatus = suggestions[index].status;
  const suggestion = {
    ...suggestions[index],
    status: validateSuggestionStatus(status),
    updatedAt: timestamp,
    statusBy: requireNonEmptyString(input.by, "Suggestion status actor is required."),
  };
  suggestions[index] = suggestion;
  await saveSuggestionMutation(paths, session, suggestions, timestamp);
  await appendSessionEvent(paths, {
    type: "suggestion_status_updated",
    suggestionId,
    fromStatus: previousStatus,
    toStatus: suggestion.status,
    by: suggestion.statusBy,
    createdAt: timestamp,
  });

  return {
    suggestion: withSuggestionAnchorStatus(suggestion, text),
  };
}

function findQuoteRangeForSuggestion(text, suggestion, resolved) {
  const quote = String(suggestion.anchor?.quote || "");
  if (!quote) {
    throw new AppError("Suggestion preview requires a quote anchor for this edit.", 422, "unsupported_suggestion_anchor");
  }

  const matches = findQuoteOccurrences(text, quote).filter((occurrence) => (
    !resolved.lineStart || (occurrence.lineStart === resolved.lineStart && occurrence.lineEnd === resolved.lineEnd)
  ));

  if (matches.length !== 1) {
    throw new AppError("Suggestion anchor no longer resolves to one quote.", 422, matches.length === 0 ? "anchor_orphaned" : "anchor_ambiguous");
  }

  return {
    start: matches[0].offset,
    end: matches[0].offset + quote.length,
    before: quote,
  };
}

function headingLineRangeForSuggestion(text, suggestion, resolved) {
  if (suggestion.anchor?.scope !== "section" || !resolved.lineStart) {
    throw new AppError("Suggestion preview requires a quote anchor for this edit.", 422, "unsupported_suggestion_anchor");
  }

  const lines = splitLinesPreserveText(text);
  const lineEnding = detectLineEnding(text);
  const previousLines = lines.slice(0, resolved.lineStart - 1);
  const start = previousLines.length === 0 ? 0 : previousLines.join(lineEnding).length + lineEnding.length;
  const lineText = lines[resolved.lineStart - 1] || "";
  return {
    start,
    end: start + lineText.length,
    before: lineText,
  };
}

function buildSuggestionEdit(text, suggestion) {
  const resolved = resolveTextAnchor(text, suggestion.anchor);
  if (resolved.status !== "resolved") {
    throw new AppError(`Suggestion anchor is ${resolved.status}.`, 422, resolved.status === "ambiguous" ? "anchor_ambiguous" : "anchor_orphaned");
  }

  if (suggestion.anchor?.scope === "section" && suggestion.kind !== "insert_after") {
    throw new AppError("Only insert_after is supported for section suggestions.", 422, "unsupported_suggestion_anchor");
  }

  const content = normalizeSuggestionContent(suggestion.content, detectLineEnding(text));
  const range = suggestion.anchor?.scope === "section"
    ? headingLineRangeForSuggestion(text, suggestion, resolved)
    : findQuoteRangeForSuggestion(text, suggestion, resolved);

  if (suggestion.kind === "replace") {
    return {
      resolved,
      before: range.before,
      after: content,
      nextText: `${text.slice(0, range.start)}${content}${text.slice(range.end)}`,
    };
  }

  if (suggestion.kind === "delete") {
    return {
      resolved,
      before: range.before,
      after: "",
      nextText: `${text.slice(0, range.start)}${text.slice(range.end)}`,
    };
  }

  if (suggestion.kind === "insert_after") {
    return {
      resolved,
      before: "",
      after: content,
      nextText: `${text.slice(0, range.end)}${content}${text.slice(range.end)}`,
    };
  }

  throw new AppError(`Unsupported suggestion kind: ${suggestion.kind}`, 400, "bad_request");
}

function buildSuggestionDiff(before, after) {
  const beforeLines = splitLinesPreserveText(before);
  const afterLines = splitLinesPreserveText(after);
  return [
    ...beforeLines.filter((line) => line !== "").map((line) => `-${line}`),
    ...afterLines.filter((line) => line !== "").map((line) => `+${line}`),
  ].join("\n");
}

export async function previewFileSessionSuggestion(filePath, suggestionId, options = {}) {
  const { text, suggestions } = await loadSuggestionState(filePath, options);
  const index = findSuggestionIndex(suggestions, suggestionId);

  if (index === -1) {
    throw new AppError(`Suggestion was not found: ${suggestionId}`, 404, "not_found");
  }

  const suggestion = suggestions[index];
  const edit = buildSuggestionEdit(text, suggestion);

  return {
    suggestion: withSuggestionAnchorStatus(suggestion, text),
    preview: {
      kind: suggestion.kind,
      before: edit.before,
      after: edit.after,
      diff: buildSuggestionDiff(edit.before, edit.after),
      anchorStatus: edit.resolved,
      willChange: edit.nextText !== text,
    },
  };
}

export async function applyFileSessionSuggestion(filePath, suggestionId, input = {}, options = {}) {
  const { session, paths, text, suggestions } = await loadSuggestionState(filePath, options);
  const index = findSuggestionIndex(suggestions, suggestionId);

  if (index === -1) {
    throw new AppError(`Suggestion was not found: ${suggestionId}`, 404, "not_found");
  }

  const actor = requireNonEmptyString(input.by, "Suggestion apply actor is required.");
  const suggestion = suggestions[index];
  if (suggestion.status === "applied") {
    throw new AppError(`Suggestion is already applied: ${suggestionId}`, 409, "conflict");
  }
  if (suggestion.status === "rejected" || suggestion.status === "stale") {
    throw new AppError(`Suggestion cannot be applied from status ${suggestion.status}: ${suggestionId}`, 409, "conflict");
  }

  const edit = buildSuggestionEdit(text, suggestion);
  const timestamp = nowIso();
  const targetPath = path.resolve(session.targetFile);
  const beforeHash = hashText(text);
  const afterHash = hashText(edit.nextText);

  await fs.writeFile(targetPath, edit.nextText, "utf8");

  // Re-anchor logic for `replace`:
  //   The original quote no longer exists in the file — it's been replaced
  //   by `edit.after`. Without re-anchoring, the applied suggestion would
  //   show as orphaned even though it succeeded, and any other comments or
  //   suggestions anchored to the same old quote would also go orphan.
  //   Repoint them to the new content so the conversation stays connected
  //   to the spec at the location it lives.
  //
  //   `delete` and `insert_after` don't need this:
  //   - delete: the text is genuinely gone; orphan is the right state.
  //   - insert_after: anchor wasn't modified.
  const isReplaceSuggestion = suggestion.kind === "replace"
    && suggestion.anchor?.scope === "anchor"
    && typeof suggestion.anchor?.quote === "string"
    && typeof edit.after === "string"
    && edit.after.length > 0;

  let updatedAnchor = suggestion.anchor;
  if (isReplaceSuggestion) {
    const newQuote = edit.after;
    const occurrences = findQuoteOccurrences(edit.nextText, newQuote);
    if (occurrences.length === 1) {
      updatedAnchor = {
        ...suggestion.anchor,
        quote: newQuote,
        lineStart: occurrences[0].lineStart,
        lineEnd: occurrences[0].lineEnd,
        selectedHash: hashText(newQuote),
        fileHash: afterHash,
      };
    }
  }

  const appliedSuggestion = {
    ...suggestion,
    status: "applied",
    statusBy: actor,
    appliedBy: actor,
    appliedAt: timestamp,
    updatedAt: timestamp,
    anchor: updatedAnchor,
    // Snapshot the pre-apply anchor so a future rollback can find the
    // original quote and revert the change. Re-anchoring overwrites
    // `anchor.quote`, so without this we'd lose the only reference to
    // what was there before.
    originalAnchor: suggestion.anchor,
    beforeHash,
    afterHash,
  };
  suggestions[index] = appliedSuggestion;
  // Also re-anchor any OTHER suggestions in the same file that were anchored
  // to the same old quote (e.g. a follow-up suggestion against the same
  // sentence). Match by exact quote string under the same scope.
  if (isReplaceSuggestion) {
    const oldQuote = suggestion.anchor.quote;
    for (let i = 0; i < suggestions.length; i += 1) {
      if (i === index) continue;
      const other = suggestions[i];
      if (other.anchor?.scope !== "anchor" || other.anchor?.quote !== oldQuote) continue;
      suggestions[i] = {
        ...other,
        anchor: { ...other.anchor, ...updatedAnchor, quote: updatedAnchor.quote },
        anchorRewrittenAt: timestamp,
      };
    }
  }

  // And update comments anchored to the same quote.
  const comments = await readJsonLines(paths.commentsJsonl);
  let commentsChanged = false;
  if (isReplaceSuggestion) {
    const oldQuote = suggestion.anchor.quote;
    for (let i = 0; i < comments.length; i += 1) {
      const c = comments[i];
      if (c.anchor?.scope !== "anchor" || c.anchor?.quote !== oldQuote) continue;
      comments[i] = {
        ...c,
        anchor: { ...c.anchor, ...updatedAnchor, quote: updatedAnchor.quote },
        anchorRewrittenAt: timestamp,
      };
      commentsChanged = true;
    }
  }

  const refreshedSession = await refreshSessionMetadataForTarget(session, targetPath, timestamp);
  await writeJsonLines(paths.suggestionsJsonl, suggestions);
  if (commentsChanged) {
    await writeJsonLines(paths.commentsJsonl, comments);
  }
  await writeJson(paths.sessionJson, refreshedSession);
  await appendSessionEvent(paths, {
    type: "suggestion_applied",
    suggestionId,
    by: actor,
    beforeHash,
    afterHash,
    createdAt: timestamp,
  });

  return {
    suggestion: withSuggestionAnchorStatus(appliedSuggestion, edit.nextText),
    preview: {
      kind: suggestion.kind,
      before: edit.before,
      after: edit.after,
      diff: buildSuggestionDiff(edit.before, edit.after),
      anchorStatus: edit.resolved,
      willChange: edit.nextText !== text,
    },
  };
}

// Rollback an applied suggestion: revert the file to its pre-apply state
// for that suggestion's specific edit, restore the anchor to its original
// quote, and put the suggestion back into `pending` status. Refuses if the
// file has drifted (something else edited it since apply) — manual cleanup
// is safer than a guessed rollback in that case.
export async function rollbackFileSessionSuggestion(filePath, suggestionId, input = {}, options = {}) {
  const { session, paths, text, suggestions } = await loadSuggestionState(filePath, options);
  const index = findSuggestionIndex(suggestions, suggestionId);

  if (index === -1) {
    throw new AppError(`Suggestion was not found: ${suggestionId}`, 404, "not_found");
  }

  const actor = requireNonEmptyString(input.by, "Suggestion rollback actor is required.");
  const suggestion = suggestions[index];
  if (suggestion.status !== "applied") {
    throw new AppError(`Only applied suggestions can be rolled back (status: ${suggestion.status}).`, 409, "conflict");
  }

  // Refuse to roll back if the file has changed since this suggestion
  // was applied — we'd otherwise reintroduce stale content over later
  // edits. The user can always manually undo their own further edits
  // first and try rollback again.
  const currentHash = hashText(text);
  if (suggestion.afterHash && suggestion.afterHash !== currentHash) {
    throw new AppError(
      "File has changed since this suggestion was applied; rollback would clobber later edits.",
      409,
      "drift",
    );
  }

  const originalAnchor = suggestion.originalAnchor;
  if (!originalAnchor) {
    throw new AppError(
      "This applied suggestion has no rollback record (likely from before the rollback feature). Edit the file by hand to undo.",
      409,
      "no_rollback_record",
    );
  }

  // Compute the inverse edit. For each kind we need to find what was
  // written and replace it with what was there before.
  const timestamp = nowIso();
  let nextText = text;

  if (suggestion.kind === "replace") {
    // Forward apply replaced originalAnchor.quote with suggestion.content.
    // Inverse: find suggestion.content (the new text) and put back originalAnchor.quote.
    const occurrences = findQuoteOccurrences(text, suggestion.content || "");
    if (occurrences.length !== 1) {
      throw new AppError("Could not unambiguously locate the applied content to roll back.", 422, "rollback_ambiguous");
    }
    const occ = occurrences[0];
    const start = occ.offset;
    const end = start + (suggestion.content || "").length;
    nextText = text.slice(0, start) + (originalAnchor.quote || "") + text.slice(end);
  } else if (suggestion.kind === "insert_after") {
    // Forward apply inserted normalized content right after the anchor's quote.
    const eol = detectLineEnding(text);
    const insertion = normalizeSuggestionContent(suggestion.content, eol);
    // The anchor quote is still in place — find it, then strip the
    // insertion that immediately follows.
    const anchorOccurrences = findQuoteOccurrences(text, originalAnchor.quote || "");
    if (anchorOccurrences.length !== 1) {
      throw new AppError("Could not locate the anchor for rollback.", 422, "rollback_ambiguous");
    }
    const anchorOcc = anchorOccurrences[0];
    const anchorEnd = anchorOcc.offset + (originalAnchor.quote || "").length;
    if (text.slice(anchorEnd, anchorEnd + insertion.length) !== insertion) {
      throw new AppError("File content past the anchor doesn't match the inserted text — rollback aborted.", 422, "rollback_mismatch");
    }
    nextText = text.slice(0, anchorEnd) + text.slice(anchorEnd + insertion.length);
  } else if (suggestion.kind === "delete") {
    // Forward apply removed originalAnchor.quote. Inverse: re-insert it
    // at the closest plausible position. The file now has a gap where
    // the deletion happened — we can't reliably know exactly where it
    // was without a line snapshot. Refuse for now.
    throw new AppError("Rolling back a delete isn't supported yet — re-add the text by hand.", 422, "rollback_unsupported");
  } else {
    throw new AppError(`Rollback not supported for kind: ${suggestion.kind}`, 422, "rollback_unsupported");
  }

  const targetPath = path.resolve(session.targetFile);
  await fs.writeFile(targetPath, nextText, "utf8");
  const newAfterHash = hashText(nextText);

  const restoredSuggestion = {
    ...suggestion,
    status: "pending",
    statusBy: actor,
    updatedAt: timestamp,
    anchor: originalAnchor,
  };
  // Strip apply metadata so subsequent applies start clean.
  delete restoredSuggestion.appliedBy;
  delete restoredSuggestion.appliedAt;
  delete restoredSuggestion.beforeHash;
  delete restoredSuggestion.afterHash;
  delete restoredSuggestion.originalAnchor;
  suggestions[index] = restoredSuggestion;

  // Reverse the sibling re-anchoring that apply did. Anything currently
  // anchored to the new content (suggestion.anchor.quote, post-apply)
  // moves back to the original quote.
  if (suggestion.kind === "replace") {
    const newQuote = suggestion.anchor?.quote;
    const oldQuote = originalAnchor.quote;
    if (newQuote && newQuote !== oldQuote) {
      const restoredOccurrences = findQuoteOccurrences(nextText, oldQuote);
      const sharedAnchor = restoredOccurrences.length === 1
        ? {
          ...originalAnchor,
          lineStart: restoredOccurrences[0].lineStart,
          lineEnd: restoredOccurrences[0].lineEnd,
          selectedHash: hashText(oldQuote),
          fileHash: newAfterHash,
        }
        : originalAnchor;
      for (let i = 0; i < suggestions.length; i += 1) {
        if (i === index) continue;
        const other = suggestions[i];
        if (other.anchor?.scope !== "anchor" || other.anchor?.quote !== newQuote) continue;
        const restored = { ...other, anchor: { ...other.anchor, ...sharedAnchor, quote: oldQuote } };
        delete restored.anchorRewrittenAt;
        suggestions[i] = restored;
      }
      // Reverse the comment re-anchoring too.
      const comments = await readJsonLines(paths.commentsJsonl);
      let commentsChanged = false;
      for (let i = 0; i < comments.length; i += 1) {
        const c = comments[i];
        if (c.anchor?.scope !== "anchor" || c.anchor?.quote !== newQuote) continue;
        const restored = { ...c, anchor: { ...c.anchor, ...sharedAnchor, quote: oldQuote } };
        delete restored.anchorRewrittenAt;
        comments[i] = restored;
        commentsChanged = true;
      }
      if (commentsChanged) {
        await writeJsonLines(paths.commentsJsonl, comments);
      }
    }
  }

  const refreshedSession = await refreshSessionMetadataForTarget(session, targetPath, timestamp);
  await writeJsonLines(paths.suggestionsJsonl, suggestions);
  await writeJson(paths.sessionJson, refreshedSession);
  await appendSessionEvent(paths, {
    type: "suggestion_rolled_back",
    suggestionId,
    by: actor,
    fromHash: currentHash,
    toHash: newAfterHash,
    createdAt: timestamp,
  });

  return {
    suggestion: withSuggestionAnchorStatus(restoredSuggestion, nextText),
  };
}

export async function getFileSessionContext(filePath, options = {}) {
  const session = await getFileSession(filePath, options);
  const minimapHome = options.minimapHome || resolveMinimapHome(options.env || process.env, options.platform || process.platform);
  const paths = makeSessionPaths(minimapHome, session.id);
  const targetPath = path.resolve(session.targetFile);
  const { buffer, text } = await readTextTarget(targetPath);
  const currentMetadata = await buildTargetMetadata(targetPath, buffer);
  const comments = (await readJsonLines(paths.commentsJsonl)).map((comment) => withAnchorStatus(comment, text));
  const suggestions = (await readJsonLines(paths.suggestionsJsonl)).map((suggestion) => withSuggestionAnchorStatus(suggestion, text));

  return {
    session: {
      ...session,
      ...currentMetadata,
    },
    outline: currentMetadata.markdown ? parseMarkdownOutline(text) : [],
    comments,
    suggestions,
  };
}

export async function getFileSessionFileContent(filePath, options = {}) {
  const context = await getFileSessionContext(filePath, options);
  const targetPath = path.resolve(context.session.targetFile);
  const { text } = await readTextTarget(targetPath);

  return {
    session: context.session,
    outline: context.outline,
    content: text,
  };
}

export async function listFileSessions(options = {}) {
  const minimapHome = options.minimapHome || resolveMinimapHome(options.env || process.env, options.platform || process.platform);
  const index = await loadSessionIndex(minimapHome);
  const sessions = [];

  for (const sessionId of Object.values(index.files)) {
    const paths = makeSessionPaths(minimapHome, sessionId);
    const session = await readJson(paths.sessionJson, null);
    if (!session) continue;
    // Tally counts so the file list can show per-file pulse dots without
    // having to load each session's full context. Cheap: just reads two
    // JSONL files and counts statuses.
    try {
      const comments = await readJsonLines(paths.commentsJsonl);
      const suggestions = await readJsonLines(paths.suggestionsJsonl);
      session.counts = {
        openComments: comments.filter((c) => c.status !== "resolved").length,
        pendingSuggestions: suggestions.filter((s) => s.status === "pending" || s.status === "accepted").length,
      };
    } catch {
      session.counts = { openComments: 0, pendingSuggestions: 0 };
    }
    sessions.push(session);
  }

  return sessions.sort((left, right) => String(right.lastActiveAt || "").localeCompare(String(left.lastActiveAt || "")));
}
