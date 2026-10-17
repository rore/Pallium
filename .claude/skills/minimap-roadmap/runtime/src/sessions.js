import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { AppError } from "./roadmap.js";
import { assertSourceWriteGuard, assertSourceWritePath } from "./source-write-guard.js";

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
  // specs that mention something in prose AND inside a fenced code block,
  // or twice in a single paragraph), prefer the occurrence the caller
  // pointed at. We accept two complementary hints, in order of strength:
  //   1. quoteOffset — exact character offset in `text`. Picks the unique
  //      occurrence at that offset; if none match exactly, picks the one
  //      nearest in the file. Strongest hint, used when the UI mapped the
  //      live selection back to a specific source position.
  //   2. lineStart/lineEnd — a 1-based line range that brackets the user's
  //      selection. Filters occurrences to those rows; falls back to the
  //      ambiguous error when more than one row remains.
  // When there is exactly one occurrence neither hint matters.
  let occurrence;
  if (occurrences.length === 1) {
    occurrence = occurrences[0];
  } else {
    const hintOffset = Number.isInteger(options.quoteOffset) && options.quoteOffset >= 0
      ? options.quoteOffset
      : null;
    if (hintOffset !== null) {
      // Exact-offset match wins outright. Otherwise pick the closest — this
      // covers minor whitespace drift between the hint and the indexed match.
      const exact = occurrences.find((o) => o.offset === hintOffset);
      if (exact) {
        occurrence = exact;
      } else {
        let best = occurrences[0];
        let bestDelta = Math.abs(best.offset - hintOffset);
        for (let i = 1; i < occurrences.length; i += 1) {
          const delta = Math.abs(occurrences[i].offset - hintOffset);
          if (delta < bestDelta) {
            best = occurrences[i];
            bestDelta = delta;
          }
        }
        occurrence = best;
      }
    }
    if (!occurrence) {
      const hintStart = Number.isInteger(options.lineStart) ? options.lineStart : null;
      const hintEnd = Number.isInteger(options.lineEnd) ? options.lineEnd : hintStart;
      if (hintStart !== null) {
        const inRange = occurrences.filter((o) => o.lineStart >= hintStart && o.lineStart <= hintEnd);
        // Exactly one occurrence inside the hinted range — use it. Multiple
        // matches in range still fall through to the ambiguous error rather
        // than guessing (the offset hint above is the right tool for that).
        if (inRange.length === 1) {
          occurrence = inRange[0];
        }
      }
    }
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
    // Char offset of the resolved match in `text`. Captured so resolveTextAnchor
    // can prefer the same occurrence on re-resolve, even if the file content
    // shifts in ways that keep the line range the same but introduce another
    // copy of the quote on the same row.
    offset: occurrence.offset,
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

async function readJson(filePath, fallback, signal) {
  try {
    return JSON.parse(await fs.readFile(filePath, { encoding: "utf8", signal }));
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
      return fallback;
    }
    throw error;
  }
}

// Atomic single-file write. Bare fs.writeFile to the live target is NOT
// atomic on Windows: a preempted write, antivirus interception, or a second
// writer racing against the first can leave the file with a new (shorter)
// prefix followed by leftover bytes from the previous content past the new
// EOF — and the next read fails JSON parsing. This bit a real session
// (corrupted MINIMAP_HOME/session-index.json yielded HTTP 500 on attach).
//
// Same pattern as writeAllOrNothing for the multi-file case, kept inline so
// any single-file write goes through it without callers having to think.
async function renameWithRetry(from, to) {
  for (let attempt = 0; ; attempt += 1) {
    try { await assertSourceWriteGuard(); return await fs.rename(from, to); }
    catch (error) {
      if (process.platform !== "win32" || !["EPERM", "EACCES"].includes(error?.code) || attempt === 4) throw error;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  }
}
async function writeFileAtomic(filePath, content) {
  const tmp = `${filePath}.tmp-${process.pid}`;
  await fs.writeFile(tmp, content, "utf8");
  await renameWithRetry(tmp, filePath);
}

async function writeJson(filePath, value) {
  await writeFileAtomic(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

async function readJsonLines(filePath, signal) {
  const content = await fs.readFile(filePath, { encoding: "utf8", signal }).catch((error) => {
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
  await assertSourceWriteGuard();
  await fs.appendFile(filePath, `${JSON.stringify(value)}\n`, "utf8");
}

function serializeJsonLines(values) {
  const content = values.map((value) => JSON.stringify(value)).join("\n");
  return content ? `${content}\n` : "";
}

async function writeJsonLines(filePath, values) {
  await writeFileAtomic(filePath, serializeJsonLines(values));
}

function serializeJson(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

// Stage each entry before sequential same-directory renames. This is NOT
// multi-file atomic: a rename failure can commit a prefix. Suggestion
// apply/rollback use a journal to recover that prefix on the next session read.
async function writeAllOrNothing(entries) {
  const tmps = entries.map((e) => ({ ...e, tmp: `${e.path}.tmp-${process.pid}` }));
  for (const e of tmps) {
    await fs.writeFile(e.tmp, e.content, "utf8");
  }
  for (const e of tmps) {
    await renameWithRetry(e.tmp, e.path);
  }
}

const SUGGESTION_JOURNAL = "suggestion-transaction.json";
const SESSION_LOCK = "session-mutation.lock";

// Cross-process lock for CLI and server mutations. A dead owner can be
// reclaimed; a recycled PID is deliberately treated as busy, not stolen.
// ponytail: PID reuse, malformed locks, or a crash during reclaim need manual lock cleanup.
async function staleSessionLock(lockPath) {
  const raw = await fs.readFile(lockPath, "utf8").catch(() => null);
  if (raw === null) return false;
  let owner;
  try { owner = JSON.parse(raw); } catch {}
  if (!Number.isSafeInteger(owner?.pid) || owner.pid <= 0) return false;
  // Signal 0 only checks process existence; it does not stop the server.
  try { process.kill(owner.pid, 0); return false; }
  catch (error) { return error?.code === "ESRCH"; }
}

async function withSessionMutationLock(paths, work, signal) {
  const lockPath = path.join(paths.sessionDir, SESSION_LOCK);
  const reclaimPath = lockPath + ".reclaim";
  const token = crypto.randomUUID();
  const deadline = Date.now() + 10_000;
  while (true) {
    if (signal?.aborted) throw signal.reason;
    try {
      await fs.writeFile(lockPath, JSON.stringify({ pid: process.pid, token }), { flag: "wx" });
      if (!(await pathExists(reclaimPath))) break;
      await fs.unlink(lockPath);
    } catch (error) {
      if (!["EEXIST", "EPERM", "EACCES"].includes(error?.code)) throw error;
      if (error?.code === "EEXIST" && await staleSessionLock(lockPath)) {
        try {
          await fs.mkdir(reclaimPath);
          try {
            if (await staleSessionLock(lockPath)) {
              await fs.unlink(lockPath).catch((unlinkError) => {
                if (unlinkError?.code !== "ENOENT") throw unlinkError;
              });
            }
          } finally {
            await fs.rmdir(reclaimPath);
          }
        } catch (reclaimError) {
          if (reclaimError?.code !== "EEXIST") throw reclaimError;
        }
      }
    }
    if (Date.now() >= deadline) throw new AppError("Another session edit is still running.", 409, "session_busy");
    await new Promise((resolve, reject) => {
      const timer = setTimeout(done, 50);
      function done() { signal?.removeEventListener("abort", abort); resolve(); }
      function abort() { clearTimeout(timer); signal.removeEventListener("abort", abort); reject(signal.reason); }
      signal?.addEventListener("abort", abort, { once: true });
      if (signal?.aborted) abort();
    });
  }
  try {
    await assertSourceWriteGuard();
    return await work();
  } finally {
    try {
      if (JSON.parse(await fs.readFile(lockPath, "utf8")).token === token) await fs.unlink(lockPath);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
}

async function recoverSuggestionTransactionUnlocked(paths) {
  const journalPath = path.join(paths.sessionDir, SUGGESTION_JOURNAL);
  if (!(await pathExists(journalPath))) return false;

  let journal;
  try { journal = JSON.parse(await fs.readFile(journalPath, "utf8")); } catch {
    throw new AppError("Suggestion recovery record is damaged; inspect it before editing this session.", 409, "recovery_conflict");
  }
  const session = await readJson(paths.sessionJson, null);
  const allowed = new Set([paths.suggestionsJsonl, paths.commentsJsonl, paths.sessionJson, paths.eventsJsonl]);
  const required = [paths.suggestionsJsonl, paths.sessionJson, paths.eventsJsonl];
  const writes = Array.isArray(journal?.writes) ? journal.writes : [];
  const writePaths = writes.map((entry) => entry?.path);
  const validHash = (hash) => typeof hash === "string" && /^sha256:[0-9a-f]{64}$/.test(hash);
  if (!session || journal?.version !== 1 || journal.targetPath !== path.resolve(session.targetFile)
      || (journal.writePath !== undefined && (typeof journal.writePath !== "string" || !path.isAbsolute(journal.writePath)))
      || !validHash(journal.beforeHash) || !validHash(journal.afterHash)
      || writes.length < required.length || new Set(writePaths).size !== writes.length
      || required.some((entryPath) => !writePaths.includes(entryPath))
      || writes.some((entry) => !allowed.has(entry?.path)
        || typeof entry.content !== "string" || !validHash(entry.beforeHash))) {
    throw new AppError("Suggestion recovery record does not match this session.", 409, "recovery_conflict");
  }
  if (journal.writePath && await fs.realpath(journal.targetPath) !== journal.writePath) {
    throw new AppError("Attached target link changed during suggestion recovery.", 409, "recovery_conflict");
  }
  const targetHash = hashText((await readTextTarget(journal.targetPath)).text);
  if (targetHash !== journal.beforeHash && targetHash !== journal.afterHash) {
    throw new AppError("Target changed during suggestion recovery; no file was overwritten.", 409, "recovery_conflict");
  }
  for (const entry of journal.writes) {
    const actualHash = hashText(await fs.readFile(entry.path, "utf8"));
    if (actualHash !== entry.beforeHash && actualHash !== hashText(entry.content)) {
      throw new AppError("Session metadata changed during suggestion recovery; no file was overwritten.", 409, "recovery_conflict");
    }
    if (targetHash !== journal.afterHash && actualHash !== entry.beforeHash) {
      throw new AppError("Target was restored after metadata changed; inspect the recovery record.", 409, "recovery_conflict");
    }
  }
  if (targetHash === journal.afterHash) await writeAllOrNothing(journal.writes);
  await fs.unlink(journalPath);
  return true;
}

async function recoverSuggestionTransaction(paths, { signal, onMutation } = {}) {
  if (signal?.aborted) throw signal.reason;
  if (!(await pathExists(path.join(paths.sessionDir, SUGGESTION_JOURNAL)))) return false;
  const recovered = await withSessionMutationLock(paths, () => recoverSuggestionTransactionUnlocked(paths), signal);
  if (recovered) await onMutation?.();
  return recovered;
}

async function withSessionMutation(filePath, options, work) {
  const session = await getFileSession(filePath, options);
  const home = options.minimapHome || resolveMinimapHome(options.env || process.env, options.platform || process.platform);
  const paths = makeSessionPaths(home, session.id);
  return withSessionMutationLock(paths, async () => {
    const recovered = await recoverSuggestionTransactionUnlocked(paths);
    if (recovered) await options.onMutation?.();
    return work();
  });
}

async function commitSuggestionTransaction(paths, targetPath, beforeText, afterText, writes, event) {
  const journalPath = path.join(paths.sessionDir, SUGGESTION_JOURNAL);
  await assertSourceWritePath(targetPath);
  const writePath = await fs.realpath(targetPath);
  await assertSourceWritePath(writePath);
  const targetStat = await fs.stat(writePath);
  if (targetStat.nlink > 1) throw new AppError("Cannot atomically replace a multiply linked target.", 409, "conflict");
  const targetTmp = `${writePath}.tmp-${process.pid}-${crypto.randomUUID()}`;
  const allWrites = [...writes, {
    path: paths.eventsJsonl,
    content: `${await fs.readFile(paths.eventsJsonl, "utf8")}${JSON.stringify(event)}\n`,
  }];
  const entries = await Promise.all(allWrites.map(async (entry) => ({
    ...entry,
    beforeHash: hashText(await fs.readFile(entry.path, "utf8")),
  })));
  const journal = {
    version: 1,
    targetPath,
    writePath,
    beforeHash: hashText(beforeText),
    afterHash: hashText(afterText),
    writes: entries,
  };
  try {
    await fs.writeFile(targetTmp, afterText, { encoding: "utf8", flag: "wx", mode: targetStat.mode });
    await fs.chmod(targetTmp, targetStat.mode);
    await writeFileAtomic(journalPath, serializeJson(journal));
    const targetUnchanged = await fs.realpath(targetPath) === writePath
      && hashText((await readTextTarget(targetPath)).text) === journal.beforeHash;
    const metadataUnchanged = (await Promise.all(entries.map(async (entry) =>
      hashText(await fs.readFile(entry.path, "utf8")) === entry.beforeHash))).every(Boolean);
    if (!targetUnchanged || !metadataUnchanged) {
      throw new AppError("Target or session changed while applying the suggestion; no file was overwritten.", 409, "drift");
    }
    await renameWithRetry(targetTmp, writePath);
    await writeAllOrNothing(entries);
    await fs.unlink(journalPath);
  } finally {
    await fs.unlink(targetTmp).catch((error) => { if (error?.code !== "ENOENT") throw error; });
  }
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
      // Optional disambiguation hints for duplicate quotes. Only forwarded
      // when the caller passed positive integers; everything else is dropped
      // so we don't smuggle through a stale hint. quoteOffset is the
      // strongest disambiguator (exact char position); the line range is
      // the fallback when the UI couldn't compute an offset.
      quoteOffset: Number.isInteger(input.quoteOffset) && input.quoteOffset >= 0 ? input.quoteOffset : undefined,
      lineStart: Number.isInteger(input.lineStart) && input.lineStart > 0 ? input.lineStart : undefined,
      lineEnd: Number.isInteger(input.lineEnd) && input.lineEnd > 0 ? input.lineEnd : undefined,
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

async function refreshSessionMetadataForTarget(session, targetPath, timestamp, text) {
  const buffer = Buffer.from(text, "utf8");
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

export async function loadSessionIndex(minimapHome = resolveMinimapHome(), { signal } = {}) {
  const indexPath = path.join(minimapHome, SESSION_INDEX_FILE);
  const index = await readJson(indexPath, { version: SESSION_INDEX_VERSION, files: {} }, signal);
  return {
    version: SESSION_INDEX_VERSION,
    files: index?.files && typeof index.files === "object" && !Array.isArray(index.files) ? index.files : {},
  };
}

async function saveSessionIndex(minimapHome, index) {
  await assertSourceWriteGuard();
  await fs.mkdir(minimapHome, { recursive: true });
  await writeJson(path.join(minimapHome, SESSION_INDEX_FILE), {
    version: SESSION_INDEX_VERSION,
    files: index.files || {},
  });
}

async function ensureSessionFiles(paths) {
  await assertSourceWriteGuard();
  await fs.mkdir(paths.sessionDir, { recursive: true });
  for (const filePath of [paths.commentsJsonl, paths.suggestionsJsonl, paths.eventsJsonl]) {
    if (!(await pathExists(filePath))) {
      await assertSourceWriteGuard();
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

async function withSessionLifecycle(filePath, options, create, work) {
  const cwd = options.cwd || process.cwd();
  const platform = options.platform || process.platform;
  const home = options.minimapHome || resolveMinimapHome(options.env || process.env, platform);
  const targetPath = path.resolve(cwd, filePath);
  const fileKey = normalizeFileKey(targetPath, platform);
  const index = await loadSessionIndex(home);
  const sessionId = index.files[fileKey] || (create ? makeSessionId(fileKey, targetPath) : null);
  if (!sessionId) return work();
  const paths = makeSessionPaths(home, sessionId);
  if (create) { await assertSourceWriteGuard(); await fs.mkdir(paths.sessionDir, { recursive: true }); }
  return withSessionMutationLock(paths, async () => {
    const recovered = await recoverSuggestionTransactionUnlocked(paths);
    if (recovered) await options.onMutation?.();
    return work();
  });
}

async function attachFileSessionUnlocked(filePath, options = {}) {
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

async function moveFileSessionUnlocked(fromFilePath, toFilePath, options = {}) {
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
  const index = await loadSessionIndex(minimapHome, { signal: options.signal });
  const sessionId = index.files[fileKey];

  if (!sessionId) {
    throw new AppError(`No minimap session is attached for ${filePath}. Run: minimap attach ${filePath}`, 404, "not_found");
  }

  const paths = makeSessionPaths(minimapHome, sessionId);
  await recoverSuggestionTransaction(paths, { signal: options.signal, onMutation: options.onMutation });
  const session = await readJson(paths.sessionJson, null, options.signal);
  if (!session) {
    throw new AppError(`Session metadata is missing for ${filePath}.`, 404, "not_found");
  }

  return session;
}

async function removeFileSessionUnlocked(filePath, options = {}) {
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
  await assertSourceWriteGuard();
  await fs.rm(paths.sessionDir, { recursive: true, force: true });

  return {
    removed: true,
    session: session || {
      id: sessionId,
      targetFile: normalizeDisplayPath(targetPath),
    },
  };
}

export const attachFileSession = (filePath, options = {}) =>
  withSessionLifecycle(filePath, options, true, () => attachFileSessionUnlocked(filePath, options));
export const moveFileSession = (fromFilePath, toFilePath, options = {}) =>
  withSessionLifecycle(fromFilePath, options, false, () => moveFileSessionUnlocked(fromFilePath, toFilePath, options));
export const removeFileSession = (filePath, options = {}) =>
  withSessionLifecycle(filePath, options, false, () => removeFileSessionUnlocked(filePath, options));

async function addFileSessionCommentUnlocked(filePath, input = {}, options = {}) {
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

async function addFileSessionCommentReplyUnlocked(filePath, commentId, input = {}, options = {}) {
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

async function addFileSessionSuggestionReplyUnlocked(filePath, suggestionId, input = {}, options = {}) {
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

async function updateFileSessionCommentStatusUnlocked(filePath, commentId, status, input = {}, options = {}) {
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

async function addFileSessionSuggestionUnlocked(filePath, input = {}, options = {}) {
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

async function updateFileSessionSuggestionStatusUnlocked(filePath, suggestionId, status, input = {}, options = {}) {
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

// Did `candidate`'s anchor range overlap the span that the applied
// suggestion replaced? Used by the apply cascade to find OTHER comments
// and suggestions that pointed inside the same region — they should be
// re-anchored to the new replacement quote so the conversation thread
// stays connected to the spec at the location it lives.
//
// Three signals, in order of strength:
//   1. char-offset overlap when both sides have `offset` and a quote
//      length to define a range. Strongest — handles substring,
//      partial overlap, identical-quote-but-different-occurrence.
//   2. line-range overlap when at least one side lacks offset. Coarse
//      but correct: a comment on line 21 inside a replace that spans
//      lines 21-24 is the same region.
//   3. exact quote-string equality. Final fallback for legacy data
//      where neither offset nor line range is present (pre-2026-05).
//
// Returns true when `candidate` should be re-anchored. Excludes the
// suggestion that's GENERATING the cascade (its anchor is updated
// separately).
function anchorOverlapsReplacedSpan(candidate, replacedAnchor) {
  if (!candidate || candidate.scope !== "anchor") return false;
  if (!replacedAnchor || replacedAnchor.scope !== "anchor") return false;
  const replacedQuote = typeof replacedAnchor.quote === "string" ? replacedAnchor.quote : "";

  // 1. char-offset overlap
  const cOff = Number.isFinite(candidate.offset) ? candidate.offset : null;
  const rOff = Number.isFinite(replacedAnchor.offset) ? replacedAnchor.offset : null;
  const cQuote = typeof candidate.quote === "string" ? candidate.quote : "";
  if (cOff !== null && rOff !== null && replacedQuote.length > 0) {
    const cStart = cOff;
    const cEnd = cOff + cQuote.length;
    const rStart = rOff;
    const rEnd = rOff + replacedQuote.length;
    return cStart < rEnd && rStart < cEnd;
  }

  // 2. line-range overlap (defensive: works when comment.offset is missing)
  const cLineStart = Number.isFinite(candidate.lineStart) ? candidate.lineStart : null;
  const cLineEnd = Number.isFinite(candidate.lineEnd) ? candidate.lineEnd : cLineStart;
  const rLineStart = Number.isFinite(replacedAnchor.lineStart) ? replacedAnchor.lineStart : null;
  const rLineEnd = Number.isFinite(replacedAnchor.lineEnd) ? replacedAnchor.lineEnd : rLineStart;
  if (cLineStart !== null && rLineStart !== null) {
    return cLineStart <= rLineEnd && rLineStart <= cLineEnd;
  }

  // 3. exact quote-string equality (legacy fallback)
  return cQuote.length > 0 && cQuote === replacedQuote;
}

async function applyFileSessionSuggestionUnlocked(filePath, suggestionId, input = {}, options = {}) {
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
  // Also re-anchor any OTHER suggestions in the same file that pointed
  // inside the same region (e.g. a follow-up suggestion against the same
  // sentence, or one that targeted a substring of the replaced span).
  // Match by anchor-range overlap, not exact quote equality — see
  // anchorOverlapsReplacedSpan for the cascade.
  if (isReplaceSuggestion) {
    const replacedAnchor = suggestion.anchor;
    for (let i = 0; i < suggestions.length; i += 1) {
      if (i === index) continue;
      const other = suggestions[i];
      if (!anchorOverlapsReplacedSpan(other.anchor, replacedAnchor)) continue;
      suggestions[i] = {
        ...other,
        anchor: { ...other.anchor, ...updatedAnchor, quote: updatedAnchor.quote },
        anchorRewrittenAt: timestamp,
      };
    }
  }

  // And update comments anchored inside the replaced region. Same overlap
  // rule as the suggestion cascade — substring, partial, or identical
  // quote, on the same line range or at overlapping char offsets.
  const comments = await readJsonLines(paths.commentsJsonl);
  let commentsChanged = false;
  if (isReplaceSuggestion) {
    const replacedAnchor = suggestion.anchor;
    for (let i = 0; i < comments.length; i += 1) {
      const c = comments[i];
      if (!anchorOverlapsReplacedSpan(c.anchor, replacedAnchor)) continue;
      comments[i] = {
        ...c,
        anchor: { ...c.anchor, ...updatedAnchor, quote: updatedAnchor.quote },
        anchorRewrittenAt: timestamp,
      };
      commentsChanged = true;
    }
  }

  const refreshedSession = await refreshSessionMetadataForTarget(session, targetPath, timestamp, edit.nextText);
  // The journal lets the next session access finish an interrupted metadata
  // promotion only when the target still has this operation's exact content.
  const writes = [
    { path: paths.suggestionsJsonl, content: serializeJsonLines(suggestions) },
  ];
  if (commentsChanged) {
    writes.push({ path: paths.commentsJsonl, content: serializeJsonLines(comments) });
  }
  writes.push({ path: paths.sessionJson, content: serializeJson(refreshedSession) });
  await commitSuggestionTransaction(paths, targetPath, text, edit.nextText, writes, {
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
async function rollbackFileSessionSuggestionUnlocked(filePath, suggestionId, input = {}, options = {}) {
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
  let pendingComments;
  let commentsChanged = false;
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
      // Reverse the comment re-anchoring too. Defer the actual write so it
      // joins the transactional triple-write below.
      const comments = await readJsonLines(paths.commentsJsonl);
      for (let i = 0; i < comments.length; i += 1) {
        const c = comments[i];
        if (c.anchor?.scope !== "anchor" || c.anchor?.quote !== newQuote) continue;
        const restored = { ...c, anchor: { ...c.anchor, ...sharedAnchor, quote: oldQuote } };
        delete restored.anchorRewrittenAt;
        comments[i] = restored;
        commentsChanged = true;
      }
      if (commentsChanged) {
        pendingComments = comments;
      }
    }
  }

  const refreshedSession = await refreshSessionMetadataForTarget(session, targetPath, timestamp, nextText);
  // Recover an interruption by matching the target content, not by
  // restoring old bytes over a possible external edit.
  const writes = [
    { path: paths.suggestionsJsonl, content: serializeJsonLines(suggestions) },
  ];
  if (commentsChanged) {
    writes.push({ path: paths.commentsJsonl, content: serializeJsonLines(pendingComments) });
  }
  writes.push({ path: paths.sessionJson, content: serializeJson(refreshedSession) });
  await commitSuggestionTransaction(paths, targetPath, text, nextText, writes, {
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

const guardedSessionMutation = (work, optionsIndex) => async (...args) =>
  withSessionMutation(args[0], args[optionsIndex] || {}, () => work(...args));

export const addFileSessionComment = guardedSessionMutation(addFileSessionCommentUnlocked, 2);
export const addFileSessionCommentReply = guardedSessionMutation(addFileSessionCommentReplyUnlocked, 3);
export const addFileSessionSuggestionReply = guardedSessionMutation(addFileSessionSuggestionReplyUnlocked, 3);
export const updateFileSessionCommentStatus = guardedSessionMutation(updateFileSessionCommentStatusUnlocked, 4);
export const addFileSessionSuggestion = guardedSessionMutation(addFileSessionSuggestionUnlocked, 2);
export const updateFileSessionSuggestionStatus = guardedSessionMutation(updateFileSessionSuggestionStatusUnlocked, 4);
export const applyFileSessionSuggestion = guardedSessionMutation(applyFileSessionSuggestionUnlocked, 3);
export const rollbackFileSessionSuggestion = guardedSessionMutation(rollbackFileSessionSuggestionUnlocked, 3);

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
  const index = await loadSessionIndex(minimapHome, { signal: options.signal });
  const sessions = [];
  const targets = options.targetFiles === undefined ? null
    : new Set(options.targetFiles.map((file) => normalizeFileKey(file, options.platform || process.platform)));

  for (const [fileKey, sessionId] of Object.entries(index.files)) {
    if (options.signal?.aborted) throw options.signal.reason;
    if (targets && !targets.has(fileKey)) continue;
    const paths = makeSessionPaths(minimapHome, sessionId);
    let session;
    try {
      await recoverSuggestionTransaction(paths, { signal: options.signal, onMutation: options.onMutation });
      session = await readJson(paths.sessionJson, null, options.signal);
      if (!session) continue;
      // Keep counts out of the full context; one bad session must not hide others.
      const comments = await readJsonLines(paths.commentsJsonl, options.signal);
      const suggestions = await readJsonLines(paths.suggestionsJsonl, options.signal);
      session.counts = {
        openComments: comments.filter((c) => c.status !== "resolved").length,
        pendingSuggestions: suggestions.filter((s) => s.status === "pending" || s.status === "accepted").length,
      };
    } catch (error) {
      if (options.signal?.aborted) throw options.signal.reason || error;
      session = session || await readJson(paths.sessionJson, null).catch(() => null)
        || { id: sessionId, targetFile: normalizeDisplayPath(fileKey), title: path.basename(fileKey) };
      delete session.counts;
      session.availability = {
        status: "unavailable",
        code: error?.code || "unavailable",
        message: error?.message || "Session data is unavailable.",
      };
    }
    sessions.push(session);
  }
  return sessions.sort((left, right) => String(right.lastActiveAt || "").localeCompare(String(left.lastActiveAt || "")));
}
