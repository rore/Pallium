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
  minimap context <file> --json
  minimap comment add <file> --by <actor> --kind <kind> --text <text> [--global|--heading <path>|--quote <text>] [--json]
  minimap comment add <file> --json-stdin [--json]   # body: {by, kind, text, scope?, headingPath?, quote?, quoteOffset?, lineStart?, lineEnd?, confidence?}
  minimap comment reply <file> <comment-id> --by <actor> --text <text> [--json]
  minimap comment reply <file> <comment-id> --json-stdin [--json]   # body: {by, text}
  minimap comment resolve <file> <comment-id> --by <actor> [--json]
  minimap comment reopen <file> <comment-id> --by <actor> [--json]
  minimap suggest add <file> --by <actor> --kind <replace|insert_after|delete> --quote <text> --content <text> [--rationale <text>] [--json]
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
    printJson(context);
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
