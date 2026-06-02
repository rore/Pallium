#!/usr/bin/env node
import fs from "node:fs/promises";
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
  minimap comment add <file> --by <actor> --kind <kind> (--text <text>|--text-file <path>) [--global|--heading <path>|--quote <text>|--quote-file <path>] [--json]
  minimap comment reply <file> <comment-id> --by <actor> (--text <text>|--text-file <path>) [--json]
  minimap comment resolve <file> <comment-id> --by <actor> [--json]
  minimap comment reopen <file> <comment-id> --by <actor> [--json]
  minimap suggest add <file> --by <actor> --kind <replace|insert_after|delete> (--quote <text>|--quote-file <path>) (--content <text>|--content-file <path>) [--rationale <text>|--rationale-file <path>] [--json]
  minimap suggest accept <file> <suggestion-id> --by <actor> [--json]
  minimap suggest reject <file> <suggestion-id> --by <actor> [--json]
  minimap suggest preview <file> <suggestion-id> [--json]
  minimap suggest apply <file> <suggestion-id> --by <actor> [--json]
  minimap session list [--json]
  minimap session move <from-file> <to-file> [--json]

For any --foo-file flag, the file contents (UTF-8) are used in place of inline --foo.
Useful when text contains shell-hostile characters (apostrophes, backticks, newlines) —
write the text to a file first, then pass --text-file path/to/text.md.
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

// Resolve a value that can be passed inline (--foo "...") or from a file
// (--foo-file path/to/text.md). Inline value wins if present. The file
// contents are used as UTF-8 with trailing newline trimmed — agents
// generally pass a file when they have multi-line or special-character
// text that's hostile to shell quoting (especially PowerShell).
async function valueFromInlineOrFile(args, inlineFlag, fileFlag) {
  const inline = valueAfter(args, inlineFlag);
  if (inline) {
    if (args.includes(fileFlag)) {
      throw new AppError(`Pass either ${inlineFlag} or ${fileFlag}, not both.`, 400, "bad_request");
    }
    return inline;
  }
  const filePath = valueAfter(args, fileFlag);
  if (!filePath) {
    return "";
  }
  try {
    const raw = await fs.readFile(filePath, "utf8");
    return raw.replace(/\r?\n$/, "");
  } catch (error) {
    throw new AppError(`Could not read ${fileFlag} ${filePath}: ${error.message}`, 400, "bad_request");
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
    const headingPath = headingPathFromValue(valueAfter(rest, "--heading"));
    const text = await valueFromInlineOrFile(rest, "--text", "--text-file");
    const quote = await valueFromInlineOrFile(rest, "--quote", "--quote-file");
    const input = {
      by: valueAfter(rest, "--by"),
      kind: valueAfter(rest, "--kind"),
      text,
      quote,
      scope: flags.has("--global") ? "global" : headingPath.length > 0 ? "section" : "",
      headingPath,
    };

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

    const text = await valueFromInlineOrFile(rest, "--text", "--text-file");
    const result = await addFileSessionCommentReply(file, commentId, {
      by: valueAfter(rest, "--by"),
      text,
    });
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
    const headingPath = headingPathFromValue(valueAfter(rest, "--heading"));
    const content = await valueFromInlineOrFile(rest, "--content", "--content-file");
    const rationale = await valueFromInlineOrFile(rest, "--rationale", "--rationale-file");
    const quote = await valueFromInlineOrFile(rest, "--quote", "--quote-file");
    const input = {
      by: valueAfter(rest, "--by"),
      kind: valueAfter(rest, "--kind"),
      content,
      rationale,
      confidence: valueAfter(rest, "--confidence"),
      quote,
      scope: headingPath.length > 0 ? "section" : "",
      headingPath,
    };

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
