#!/usr/bin/env node
import { AppError } from "./src/roadmap.js";
import {
  addFileSessionSuggestion,
  addFileSessionComment,
  addFileSessionCommentReply,
  applyFileSessionSuggestion,
  attachFileSession,
  getFileSessionContext,
  listFileSessions,
  moveFileSession,
  previewFileSessionSuggestion,
  updateFileSessionSuggestionStatus,
  updateFileSessionCommentStatus,
} from "./src/sessions.js";

function printJson(value) {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

function parseFlags(args) {
  const flags = new Set();
  const positional = [];

  for (const arg of args) {
    if (arg.startsWith("--")) {
      flags.add(arg);
    } else {
      positional.push(arg);
    }
  }

  return { flags, positional };
}

function usage() {
  return `Usage:
  minimap attach <file> [--json]
  minimap context <file> --json [--summary] [--filter <open|resolved|all>]
  minimap comment add <file> --by <actor> --kind <kind> --text <text> [--global|--heading <path>|--quote <text>] [--json]
                                                                              # for duplicate quotes, add: --line-start N --line-end N  OR  --quote-offset N
  minimap comment add <file> --json-stdin [--json]   # body: {by, kind, text, scope?, headingPath?, quote?, quoteOffset?, lineStart?, lineEnd?, confidence?}
  minimap comment reply <file> <comment-id> --by <actor> --text <text> [--json]
  minimap comment reply <file> <comment-id> --json-stdin [--json]   # body: {by, text}
  minimap comment resolve <file> <comment-id> --by <actor> [--json]
  minimap comment reopen <file> <comment-id> --by <actor> [--json]
  minimap suggest add <file> --by <actor> --kind <replace|insert_after|delete> --quote <text> --content <text> [--rationale <text>] [--json]
                                                                              # for duplicate quotes, add: --line-start N --line-end N  OR  --quote-offset N
  minimap suggest add <file> --json-stdin [--json]   # body: {by, kind, content, rationale?, scope?, headingPath?, quote?, quoteOffset?, lineStart?, lineEnd?, confidence?}
  minimap suggest accept <file> <suggestion-id> --by <actor> [--json]
  minimap suggest reject <file> <suggestion-id> --by <actor> [--json]
  minimap suggest preview <file> <suggestion-id> [--json]
  minimap suggest apply <file> <suggestion-id> --by <actor> [--json]
  minimap session list [--json]
  minimap session move <from-file> <to-file> [--json]

For multi-line markdown content (backticks, em-dashes, apostrophes, embedded newlines),
use --json-stdin and pipe the JSON body on stdin. Avoids every shell's quoting rules.
For HTTP-direct use, see references/http.md.
`;
}

function requireFile(positional, command) {
  const file = positional[0];
  if (!file) {
    throw new AppError(`${command} requires a file path.`, 400, "bad_request");
  }
  return file;
}

function valueAfter(args, flag) {
  const index = args.indexOf(flag);
  if (index === -1) {
    return "";
  }
  return args[index + 1] || "";
}

// Parse an optional non-negative integer from `--flag N`. Returns undefined
// when the flag is absent OR the value isn't strictly a non-negative decimal
// integer, so the caller can spread the result without smuggling a stray
// NaN/string into the server's anchor disambiguation logic.
//
// `Number.parseInt` alone is too lenient for this job: it accepts trailing
// junk (`"3abc"` → 3), decimals (`"3.7"` → 3), scientific notation (`"1e3"` →
// 1, NOT 1000), `0x` prefixes, and leading whitespace. Each of those would
// silently anchor at the wrong line. We require a pure decimal integer
// upfront and only then call `parseInt`.
//
// Server enforces stricter bounds (`>0` for lineStart/lineEnd, `>=0` for
// quoteOffset) at sessions.js:763-765, where a hint that fails the check is
// dropped and the cascade falls through to the ambiguous-error path. We
// permit `0` here for all three flags and let the server own per-field
// validation; on the wire the result is identical.
function intFlag(args, flag) {
  const raw = valueAfter(args, flag);
  if (raw === "") {
    return undefined;
  }
  if (!/^\d+$/.test(raw)) {
    process.stderr.write(`[minimap] ${flag}: ignoring non-integer value ${JSON.stringify(raw)}\n`);
    return undefined;
  }
  const parsed = Number.parseInt(raw, 10);
  return Number.isInteger(parsed) ? parsed : undefined;
}

// Read all of stdin as a UTF-8 string. Used by --json-stdin, which lets the
// agent pipe a single JSON body in one shell turn instead of escaping every
// backtick, em-dash, and newline at the command line.
async function readStdin() {
  return new Promise((resolve, reject) => {
    const chunks = [];
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => chunks.push(chunk));
    process.stdin.on("end", () => resolve(chunks.join("")));
    process.stdin.on("error", reject);
  });
}

// Decode a JSON body from stdin. Loud failure on malformed JSON is the
// whole point — the HTTP API will silently strip raw newlines from string
// values and corrupt the data, so doing JSON.parse here gives the agent a
// clear error to recover from.
async function readJsonStdin() {
  const raw = await readStdin();
  if (!raw.trim()) {
    throw new AppError("--json-stdin requires JSON on stdin.", 400, "bad_request");
  }
  try {
    return JSON.parse(raw);
  } catch (error) {
    throw new AppError(`--json-stdin received invalid JSON: ${error.message}`, 400, "bad_request");
  }
}

function headingPathFromValue(value) {
  if (!value) {
    return [];
  }
  return value.split(">").map((part) => part.trim()).filter(Boolean);
}

// Status sets used by `mm context --filter`. "open" and "resolved" are
// agent-friendly review verbs that fan out to the underlying comment and
// suggestion enums; "all" is the no-op pass-through.
const FILTER_COMMENT_STATUSES = {
  open: new Set(["open"]),
  resolved: new Set(["resolved", "accepted", "rejected", "deferred", "stale"]),
  all: null,
};
const FILTER_SUGGESTION_STATUSES = {
  open: new Set(["pending"]),
  resolved: new Set(["accepted", "rejected", "applied", "stale"]),
  all: null,
};

// Compact per-item row for `mm context --summary`. Includes everything an
// agent typically wants on first read: id, author, kind, current status,
// re-resolved anchor location, and a short snippet of the body/rationale.
// The full record is one CLI call away (`--filter all` without --summary),
// so this projection optimizes for "scan the review state in one screen."
function summarizeComment(comment) {
  const anchor = comment.anchor || {};
  const status = comment.anchorStatus || {};
  const snippet = (comment.text || "").replace(/\s+/g, " ").trim().slice(0, 120);
  return {
    id: comment.id,
    by: comment.by,
    kind: comment.kind,
    status: comment.status,
    statusBy: comment.statusBy,
    anchorScope: anchor.scope,
    anchorStatus: status.status,
    lineStart: status.lineStart ?? anchor.lineStart ?? null,
    headingPath: anchor.headingPath || [],
    replyCount: Array.isArray(comment.replies) ? comment.replies.length : 0,
    text: snippet + ((comment.text || "").length > 120 ? "..." : ""),
  };
}

function summarizeSuggestion(suggestion) {
  const anchor = suggestion.anchor || {};
  const status = suggestion.anchorStatus || {};
  // Suggestions carry both a rationale (why) and a content (the proposed
  // edit). Rationale is the more useful scan signal — it tells the
  // reviewer what the suggestion is FOR, not what it would change.
  const body = suggestion.rationale || suggestion.content || "";
  const snippet = body.replace(/\s+/g, " ").trim().slice(0, 120);
  return {
    id: suggestion.id,
    by: suggestion.by,
    kind: suggestion.kind,
    status: suggestion.status,
    statusBy: suggestion.statusBy,
    appliedBy: suggestion.appliedBy,
    appliedAt: suggestion.appliedAt,
    anchorScope: anchor.scope,
    anchorStatus: status.status,
    lineStart: status.lineStart ?? anchor.lineStart ?? null,
    headingPath: anchor.headingPath || [],
    replyCount: Array.isArray(suggestion.replies) ? suggestion.replies.length : 0,
    rationale: snippet + (body.length > 120 ? "..." : ""),
  };
}

// Apply --filter status narrowing AND optional --summary projection. Always
// returns the full {session, outline, comments, suggestions} shape so
// downstream code can pattern-match on the same keys regardless of flags.
// `counts` is added unconditionally so a single call surfaces both the
// row data and the high-level numbers an agent wants to scan first.
function projectContextWithFilter(context, filterName, wantsSummary) {
  const commentStatuses = FILTER_COMMENT_STATUSES[filterName];
  const suggestionStatuses = FILTER_SUGGESTION_STATUSES[filterName];

  const filteredComments = (context.comments || []).filter((c) => !commentStatuses || commentStatuses.has(c.status));
  const filteredSuggestions = (context.suggestions || []).filter((s) => !suggestionStatuses || suggestionStatuses.has(s.status));

  const counts = {
    // High-level review counts. Always against the FULL context, not the
    // filtered view — answering "what's outstanding" doesn't depend on
    // what slice the caller asked for, and an agent that filtered to
    // `resolved` still wants to know the open count.
    commentsOpen: (context.comments || []).filter((c) => c.status === "open").length,
    commentsResolved: (context.comments || []).filter((c) => c.status !== "open").length,
    suggestionsPending: (context.suggestions || []).filter((s) => s.status === "pending").length,
    suggestionsApplied: (context.suggestions || []).filter((s) => s.status === "applied").length,
    suggestionsRejected: (context.suggestions || []).filter((s) => s.status === "rejected").length,
    suggestionsAccepted: (context.suggestions || []).filter((s) => s.status === "accepted").length,
  };

  const comments = wantsSummary ? filteredComments.map(summarizeComment) : filteredComments;
  const suggestions = wantsSummary ? filteredSuggestions.map(summarizeSuggestion) : filteredSuggestions;

  return {
    session: context.session,
    outline: wantsSummary ? undefined : context.outline,
    counts,
    filter: filterName,
    summary: wantsSummary,
    comments,
    suggestions,
  };
}

async function main(argv) {
  const [command, subcommand, ...rest] = argv;

  if (!command || command === "help" || command === "--help" || command === "-h") {
    process.stdout.write(usage());
    return;
  }

  if (command === "attach") {
    const { flags, positional } = parseFlags([subcommand, ...rest].filter(Boolean));
    const file = requireFile(positional, "attach");
    const result = await attachFileSession(file);
    const payload = {
      sessionId: result.session.id,
      targetFile: result.session.targetFile,
      created: result.created,
      lastActiveAt: result.session.lastActiveAt,
    };

    if (flags.has("--json")) {
      printJson(payload);
      return;
    }

    process.stdout.write(`${result.created ? "Created" : "Reopened"} minimap session ${payload.sessionId} for ${payload.targetFile}\n`);
    return;
  }

  if (command === "context") {
    const { flags, positional } = parseFlags([subcommand, ...rest].filter(Boolean));
    const file = requireFile(positional, "context");
    const context = await getFileSessionContext(file);
    if (!flags.has("--json")) {
      throw new AppError("context currently requires --json.", 400, "bad_request");
    }

    // --summary and --filter are opt-in projections layered on top of the
    // raw context. Without them the full shape is returned so existing
    // callers (tests, HTTP equivalents, scripted consumers) keep working.
    //
    // --summary  : compact per-item rows (id, by, kind, status, anchor
    //              line + status, ~120-char snippet of text/rationale).
    //              Cuts the JSON ~30x for a typical review session.
    // --filter X : narrows the items returned. Sensible review-time slices:
    //                open      — comments status=open + suggestions status=pending
    //                            (the "what's still on my plate" view; default
    //                            when --summary is on without an explicit filter)
    //                resolved  — comments resolved + suggestions accepted/rejected/applied
    //                            (the "what's been dealt with" view)
    //                all       — every comment and suggestion regardless of status
    //              These names match the agent's review mental model;
    //              status-typed slices (accept-only, applied-only) are
    //              available via --filter all + downstream parsing.
    const wantsSummary = flags.has("--summary");
    const filterRaw = valueAfter([subcommand, ...rest].filter(Boolean), "--filter");
    const wantsFilter = wantsSummary || filterRaw !== "";

    if (!wantsFilter) {
      // No projection flags — print the raw context exactly as before so
      // every existing caller (HTTP equivalents, scripted readers, the 11
      // integration tests) keeps working unchanged.
      printJson(context);
      return;
    }

    const filterName = filterRaw || "open";
    const ALLOWED_FILTERS = new Set(["open", "resolved", "all"]);
    if (!ALLOWED_FILTERS.has(filterName)) {
      throw new AppError(`Unknown --filter value "${filterName}". Allowed: open | resolved | all.`, 400, "bad_request");
    }

    const filtered = projectContextWithFilter(context, filterName, wantsSummary);
    printJson(filtered);
    return;
  }

  if (command === "comment" && subcommand === "add") {
    const { flags, positional } = parseFlags(rest);
    const file = requireFile(positional, "comment add");
    let input;
    if (flags.has("--json-stdin")) {
      // Whole body comes from stdin as JSON. Server validates the shape.
      input = await readJsonStdin();
    } else {
      const headingPath = headingPathFromValue(valueAfter(rest, "--heading"));
      input = {
        by: valueAfter(rest, "--by"),
        kind: valueAfter(rest, "--kind"),
        text: valueAfter(rest, "--text"),
        quote: valueAfter(rest, "--quote"),
        scope: flags.has("--global") ? "global" : headingPath.length > 0 ? "section" : "",
        headingPath,
        // Optional disambiguators for duplicate quotes. The server already
        // accepts these via --json-stdin and HTTP; exposing them inline keeps
        // the bare-flag path usable when an agent hits anchor_ambiguous from
        // a one-line `--quote ...` invocation. intFlag() returns undefined
        // when the flag is absent or unparseable, so the spread is a no-op.
        quoteOffset: intFlag(rest, "--quote-offset"),
        lineStart: intFlag(rest, "--line-start"),
        lineEnd: intFlag(rest, "--line-end"),
      };
    }

    const result = await addFileSessionComment(file, input);
    if (flags.has("--json")) {
      printJson(result);
      return;
    }

    process.stdout.write(`Added comment ${result.comment.id} to ${file}\n`);
    return;
  }

  if (command === "comment" && subcommand === "reply") {
    const { flags, positional } = parseFlags(rest);
    const file = requireFile(positional, "comment reply");
    const commentId = positional[1];
    if (!commentId) {
      throw new AppError("comment reply requires a comment id.", 400, "bad_request");
    }

    let input;
    if (flags.has("--json-stdin")) {
      input = await readJsonStdin();
    } else {
      input = {
        by: valueAfter(rest, "--by"),
        text: valueAfter(rest, "--text"),
      };
    }
    const result = await addFileSessionCommentReply(file, commentId, input);
    if (flags.has("--json")) {
      printJson(result);
      return;
    }

    process.stdout.write(`Added reply to ${commentId}\n`);
    return;
  }

  if (command === "comment" && (subcommand === "resolve" || subcommand === "reopen")) {
    const { flags, positional } = parseFlags(rest);
    const file = requireFile(positional, `comment ${subcommand}`);
    const commentId = positional[1];
    if (!commentId) {
      throw new AppError(`comment ${subcommand} requires a comment id.`, 400, "bad_request");
    }

    const result = await updateFileSessionCommentStatus(file, commentId, subcommand === "resolve" ? "resolved" : "open", {
      by: valueAfter(rest, "--by"),
    });
    if (flags.has("--json")) {
      printJson(result);
      return;
    }

    process.stdout.write(`${subcommand === "resolve" ? "Resolved" : "Reopened"} comment ${commentId}\n`);
    return;
  }

  if (command === "suggest" && subcommand === "add") {
    const { flags, positional } = parseFlags(rest);
    const file = requireFile(positional, "suggest add");
    let input;
    if (flags.has("--json-stdin")) {
      input = await readJsonStdin();
    } else {
      const headingPath = headingPathFromValue(valueAfter(rest, "--heading"));
      input = {
        by: valueAfter(rest, "--by"),
        kind: valueAfter(rest, "--kind"),
        content: valueAfter(rest, "--content"),
        rationale: valueAfter(rest, "--rationale"),
        confidence: valueAfter(rest, "--confidence"),
        quote: valueAfter(rest, "--quote"),
        scope: headingPath.length > 0 ? "section" : "",
        headingPath,
        // Same duplicate-quote disambiguators as `comment add`. Suggestions
        // can't have scope: "global", but quote anchors still need them.
        quoteOffset: intFlag(rest, "--quote-offset"),
        lineStart: intFlag(rest, "--line-start"),
        lineEnd: intFlag(rest, "--line-end"),
      };
    }

    const result = await addFileSessionSuggestion(file, input);
    if (flags.has("--json")) {
      printJson(result);
      return;
    }

    process.stdout.write(`Added suggestion ${result.suggestion.id} to ${file}\n`);
    return;
  }

  if (command === "suggest" && (subcommand === "accept" || subcommand === "reject")) {
    const { flags, positional } = parseFlags(rest);
    const file = requireFile(positional, `suggest ${subcommand}`);
    const suggestionId = positional[1];
    if (!suggestionId) {
      throw new AppError(`suggest ${subcommand} requires a suggestion id.`, 400, "bad_request");
    }

    const result = await updateFileSessionSuggestionStatus(file, suggestionId, subcommand === "accept" ? "accepted" : "rejected", {
      by: valueAfter(rest, "--by"),
    });
    if (flags.has("--json")) {
      printJson(result);
      return;
    }

    process.stdout.write(`${subcommand === "accept" ? "Accepted" : "Rejected"} suggestion ${suggestionId}\n`);
    return;
  }

  if (command === "suggest" && (subcommand === "preview" || subcommand === "apply")) {
    const { flags, positional } = parseFlags(rest);
    const file = requireFile(positional, `suggest ${subcommand}`);
    const suggestionId = positional[1];
    if (!suggestionId) {
      throw new AppError(`suggest ${subcommand} requires a suggestion id.`, 400, "bad_request");
    }

    const result = subcommand === "apply"
      ? await applyFileSessionSuggestion(file, suggestionId, { by: valueAfter(rest, "--by") })
      : await previewFileSessionSuggestion(file, suggestionId);
    if (flags.has("--json")) {
      printJson(result);
      return;
    }

    process.stdout.write(`${subcommand === "apply" ? "Applied" : "Previewed"} suggestion ${suggestionId}\n${result.preview.diff}\n`);
    return;
  }

  if (command === "session" && subcommand === "list") {
    const { flags } = parseFlags(rest);
    const sessions = await listFileSessions();
    if (flags.has("--json")) {
      printJson({ sessions });
      return;
    }
    for (const session of sessions) {
      process.stdout.write(`${session.id}\t${session.lastActiveAt}\t${session.targetFile}\n`);
    }
    return;
  }

  if (command === "session" && subcommand === "move") {
    const { flags, positional } = parseFlags(rest);
    const fromFile = positional[0];
    const toFile = positional[1];
    if (!fromFile || !toFile) {
      throw new AppError("session move requires from-file and to-file paths.", 400, "bad_request");
    }

    const result = await moveFileSession(fromFile, toFile);
    if (flags.has("--json")) {
      printJson(result);
      return;
    }

    process.stdout.write(`Moved minimap session ${result.session.id} to ${result.session.targetFile}\n`);
    return;
  }

  throw new AppError(`Unknown minimap command: ${[command, subcommand].filter(Boolean).join(" ")}`, 400, "bad_request");
}

main(process.argv.slice(2)).catch((error) => {
  if (error instanceof AppError) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = error.statusCode >= 500 ? 1 : 2;
    return;
  }

  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
