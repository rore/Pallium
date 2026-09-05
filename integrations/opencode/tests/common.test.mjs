#!/usr/bin/env node
// Parity tests for the OpenCode integration's shared helpers — the JS twin of
// tests/test_hook_common_parity.py. Asserts container derivation, actor/redaction
// behaviour, the 5-minute dedup window, injection budget trimming, and turn
// extraction / work-trace metadata match the Claude Code / Codex contract.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";

// Redirect the state dir to a temp HOME BEFORE the module is imported, so
// dedup/pin state never touches the real ~/.pallium. STATE_DIR is resolved once
// at module load, so we must set the env then dynamic-import (imports are
// hoisted; a static import would run before this assignment).
const tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-common-"));
process.env.USERPROFILE = tmpHome;
process.env.HOME = tmpHome;

let P;
test.before(async () => {
  const url = pathToFileURL(
    path.join(process.cwd(), ".opencode", "plugins", "pallium-common.mjs"),
  );
  P = await import(url);
});

test.after(() => {
  try { fs.rmSync(tmpHome, { recursive: true, force: true }); } catch { /* ignore */ }
});

// --- container_ref derivation ----------------------------------------------

test("normalizeRemoteUrl canonicalizes ssh/https/user forms", () => {
  assert.equal(P.normalizeRemoteUrl("git@github.com:user/repo.git"), "github.com/user/repo");
  assert.equal(P.normalizeRemoteUrl("https://github.com/user/repo.git"), "github.com/user/repo");
  assert.equal(P.normalizeRemoteUrl("https://github.com/User/Repo/"), "github.com/user/repo");
  assert.equal(P.normalizeRemoteUrl("https://token@github.com/user/repo"), "github.com/user/repo");
});

test("pathContainer emits path:<label>:<hash12> and path:<hash12> when label empty", () => {
  const withLabel = P.pathContainer(path.join(os.tmpdir(), "My Project"));
  assert.match(withLabel, /^path:my_project:[0-9a-f]{12}$/);
  // A basename that sanitizes to empty falls back to the bare-hash form.
  const bare = P.pathContainer("/@@@");
  assert.match(bare, /^path:[0-9a-f]{12}$/);
});

test("deriveContainerRef returns path:<...> for a non-git dir and is stable", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-nogit-"));
  const ref = P.deriveContainerRef(dir);
  assert.ok(ref.startsWith("path:"), `expected path: prefix, got ${ref}`);
  assert.equal(ref, P.pathContainer(dir));
  assert.equal(ref, P.deriveContainerRef(dir)); // stable across calls
});

test("deriveContainerRef derives a stable ref for this repo checkout", () => {
  // Runs inside a git checkout; the derivation contract (git:/repo:/path:) is
  // covered above. Assert the shape + determinism rather than the exact remote,
  // so this passes in a fork, a renamed-remote clone, or a git-less tarball.
  const ref = P.deriveContainerRef(process.cwd());
  assert.match(ref, /^(git:|repo:|path:)/);
  assert.equal(ref, P.deriveContainerRef(process.cwd()));
});

test("deriveActorRef uses the repository identity when the plugin cwd differs", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-actor-"));
  try {
    execFileSync("git", ["init"], { cwd: dir, stdio: "ignore" });
    execFileSync("git", ["config", "user.name", "Relay Operator"], { cwd: dir });
    assert.equal(P.deriveActorRef(dir), "Relay Operator");
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

// --- redaction --------------------------------------------------------------

test("redactSensitive matches the Python behavioral-parity cases exactly", () => {
  assert.equal(P.redactSensitive("Bearer sk-12345"), "Bearer [REDACTED]");
  assert.equal(P.redactSensitive("DB_PASSWORD=secret"), "DB_PASSWORD=[REDACTED]");
  assert.equal(P.redactSensitive("postgres://user:pass@host/db"), "postgres://[REDACTED]");
  assert.equal(P.redactSensitive("clean text here"), "clean text here");
});

test("redactSensitive strips Authorization headers and key blocks", () => {
  assert.equal(P.redactSensitive("Authorization: Bearer abc123"), "Authorization: [REDACTED]");
  const key = "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----";
  assert.equal(P.redactSensitive(key), "[REDACTED KEY BLOCK]");
});

// --- dedup ------------------------------------------------------------------

test("checkDedup: first false, immediate repeat true, distinct prompt false", () => {
  const sid = "dedup-session-1";
  assert.equal(P.checkDedup("some unique prompt about widgets", sid), false);
  assert.equal(P.checkDedup("some unique prompt about widgets", sid), true);
  assert.equal(P.checkDedup("a completely different prompt", sid), false);
});

test("checkDedup expires entries older than the 5-minute window", () => {
  const sid = "dedup-session-2";
  assert.equal(P.checkDedup("aging prompt", sid), false);
  // Rewrite the state file with a stale timestamp to simulate >5 min elapsed.
  const stateFile = path.join(tmpHome, ".pallium", "hooks", "state", `${sid}.json`);
  const state = JSON.parse(fs.readFileSync(stateFile, "utf8"));
  for (const k of Object.keys(state)) state[k] = Date.now() / 1000 - (P.DEDUP_EXPIRY_SECONDS + 60);
  fs.writeFileSync(stateFile, JSON.stringify(state));
  assert.equal(P.checkDedup("aging prompt", sid), false); // expired -> not a dup
});

test("checkDedup rejects an unsafe session id (no path escape, safe default)", () => {
  const before = fs.readdirSync(path.join(tmpHome, ".pallium", "hooks", "state"));
  // A traversal-y id must not dedup and must not write a state file for it.
  assert.equal(P.checkDedup("some prompt", "../../evil"), false);
  assert.equal(P.checkDedup("some prompt", "a/b"), false);
  const after = fs.readdirSync(path.join(tmpHome, ".pallium", "hooks", "state"));
  assert.deepEqual(after.sort(), before.sort(), "no state file created for unsafe ids");
});

// --- session pinning --------------------------------------------------------

test("session scope pins container and actor across resume, then disposes both", () => {
  const sid = "pin-session-1";
  P.pinContainer(sid, "git:example.com/a/b", undefined, "Relay Operator");
  assert.equal(P.resolveContainerRef("/some/other/dir", sid), "git:example.com/a/b");
  assert.equal(P.resolveActorRef("/some/other/dir", sid), "Relay Operator");
  P.pinContainer(sid, "git:example.com/a/b");
  assert.equal(P.getPinnedActor(sid), "Relay Operator");
  P.pinContainer(sid, "git:example.com/x/y", "resume", "Other Operator");
  assert.equal(P.getPinnedContainer(sid), "git:example.com/a/b");
  assert.equal(P.getPinnedActor(sid), "Relay Operator");
  P.removeSessionPin(sid);
  assert.equal(P.getPinnedContainer(sid), null);
  assert.equal(P.getPinnedActor(sid), null);
  P.pinContainer("bad id!", "git:z", undefined, "actor");
  assert.equal(P.getPinnedContainer("bad id!"), null);
});

// --- injection budget -------------------------------------------------------

function blocks(n) {
  const out = [];
  for (let i = 0; i < n; i++) {
    out.push({ title: `T${i}`, memory_object_id: `ref-${i}`, text: "x".repeat(60), expand_available: i === 0 });
  }
  return out;
}

test("formatInjection includes scope, header/footer, and all blocks under a generous budget", () => {
  const out = P.formatInjection(blocks(3), "git:example.com/a/b", 5000, "任务:α", "actor", "opencode", "private", "请求:42");
  assert.match(out, /^\[Pallium scope — /);
  assert.match(out, /"request_source_item_id":"请求:42"/);
  assert.match(out, /\[Pallium memory — container: git:example\.com\/a\/b\]/);
  assert.match(out, /\[End Pallium memory\]$/);
  assert.match(out, /ref:ref-0\]/);
  assert.match(out, /ref:ref-2\]/);
  assert.match(out, /\[\+expand\]/); // block 0 was expandable
});

test("formatInjection trims blocks that overflow the char budget", () => {
  const full = P.formatInjection(blocks(5), "c", 5000);
  const trimmed = P.formatInjection(blocks(5), "c", 400);
  assert.ok(trimmed.length <= 400 || trimmed === "", "trimmed output must respect the budget");
  assert.ok(trimmed.length < full.length, "tight budget must drop blocks");
  // First block is kept preferentially (blocks are popped from the end).
  if (trimmed) assert.match(trimmed, /ref:ref-0\]/);
});

test("formatInjection emits bounded scope without blocks and rejects unsafe identity", () => {
  const scoped = P.formatInjection([], "c", 2400, "任务:α", "actor", "opencode", "private", "请求:42");
  assert.match(scoped, /"request_source_item_id":"请求:42"/);
  assert.ok(scoped.length <= 2400);
  assert.equal(P.formatInjection([], "c", 2400), "");
  assert.equal(P.formatInjection(null, "c", 2400), "");
  assert.equal(P.formatInjection([], "c", 2400, "thread", null, null, null, "bad\nid"), "");
  assert.equal(P.formatInjection([], "c", 10, "thread", null, null, null, "request"), "");
});

// --- turn extraction + work-trace metadata ----------------------------------

function assistantMessages() {
  return [
    { info: { role: "user", id: "u1" }, parts: [{ type: "text", text: "please build it" }] },
    {
      info: { role: "assistant", id: "a1" },
      parts: [
        { type: "text", text: "Working on it." },
        { type: "tool", tool: "read", state: { status: "completed", input: { filePath: "src/a.js" }, output: "" } },
        { type: "tool", tool: "bash", state: { status: "error", input: { command: "npm test" }, output: "FAIL 1 test" } },
        { type: "tool", tool: "grep", state: { status: "completed", input: { pattern: "TODO", path: "src" }, output: "src/a.js:1: TODO x" } },
        { type: "tool", tool: "edit", state: { status: "completed", input: { filePath: "src/b.js" } } },
        { type: "tool", tool: "todowrite", state: { status: "completed", input: {} } },
      ],
    },
  ];
}

test("extractAssistantTurn folds OpenCode parts into the normalized TurnData shape", () => {
  const turn = P.extractAssistantTurn(assistantMessages());
  assert.ok(turn);
  assert.equal(turn.assistant_text, "Working on it.");
  assert.equal(turn.has_productive_action, true);
  assert.deepEqual(turn.files_modified, ["src/b.js"]);
  const toolNames = turn.tool_calls.map((c) => c.tool).sort();
  // Read/Bash/Grep are recorded; Edit (productive) and TodoWrite are excluded
  // from tool_calls per the shared EXCLUDED_TOOLS contract.
  assert.deepEqual(toolNames, ["Bash", "Grep", "Read"]);
  const bash = turn.tool_calls.find((c) => c.tool === "Bash");
  assert.equal(bash.exit_code, 1); // status:"error" -> synthetic exit code
  assert.equal(bash.failure_class, "command_error");
});

test("buildWorkTraceMetadata produces the shared work-trace shape", () => {
  const turn = P.extractAssistantTurn(assistantMessages());
  const meta = P.buildWorkTraceMetadata(turn);
  assert.ok(meta);
  assert.deepEqual(meta.files_read, ["src/a.js"]);
  assert.deepEqual(meta.grep_patterns, ["TODO"]);
  assert.deepEqual(meta.files_modified, ["src/b.js"]);
  assert.equal(meta.has_productive_action, true);
  assert.equal(meta.commands.length, 1);
  assert.equal(meta.commands[0].failure_class, "command_error");
});

test("extractAssistantTurn returns null when there is no assistant content", () => {
  assert.equal(P.extractAssistantTurn([]), null);
  assert.equal(P.extractAssistantTurn([{ info: { role: "user" }, parts: [{ type: "text", text: "hi" }] }]), null);
  assert.equal(
    P.extractAssistantTurn([{ info: { role: "assistant" }, parts: [{ type: "text", text: "   " }] }]),
    null,
  );
});

test("extractTextFromParts / stripIdeContext behave like the user-prompt path", () => {
  assert.equal(P.extractTextFromParts([{ type: "text", text: "hello" }, { type: "reasoning", text: "x" }]), "hello");
  assert.equal(
    P.stripIdeContext("real prompt <ide_selection>noise</ide_selection> more"),
    "real prompt  more",
  );
});

test("extractAssistantTurn captures apply_patch productive edits + patch_bodies metadata", () => {
  const messages = [
    { info: { role: "user", id: "u1" }, parts: [{ type: "text", text: "patch it" }] },
    {
      info: { role: "assistant", id: "a2" },
      parts: [
        { type: "text", text: "Patched." },
        {
          type: "tool",
          tool: "patch",
          state: {
            status: "completed",
            input: { operation: { path: "src/patched.js", diff: "@@ -1 +1 @@\n-old\n+new" } },
            output: "applied",
          },
        },
      ],
    },
  ];
  const turn = P.extractAssistantTurn(messages);
  assert.equal(turn.has_productive_action, true);
  assert.deepEqual(turn.files_modified, ["src/patched.js"]);
  const patch = turn.tool_calls.find((c) => c.tool === "apply_patch");
  assert.ok(patch, "apply_patch tool call recorded");
  assert.equal(patch.operation.path, "src/patched.js");
  const meta = P.buildWorkTraceMetadata(turn);
  assert.equal(meta.patch_bodies.length, 1);
  assert.equal(meta.patch_bodies[0].operation.path, "src/patched.js");
});

test("extractToolCall Glob splits and caps output paths", () => {
  const call = P.extractToolCall("Glob", { pattern: "**/*.js" }, "a.js\nb.js\nc.js");
  assert.deepEqual(call, { tool: "Glob", pattern: "**/*.js", paths: ["a.js", "b.js", "c.js"] });
});

test("deriveContainerRef returns repo:<hash12> for a git repo with no remote", () => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-repo-"));
  const run = (args) => execFileSync("git", args, { cwd: repo, stdio: ["ignore", "pipe", "ignore"] });
  run(["init"]);
  run(["config", "user.email", "t@e.st"]);
  run(["config", "user.name", "Tester"]);
  run(["config", "commit.gpgsign", "false"]);
  fs.writeFileSync(path.join(repo, "f.txt"), "hi");
  run(["add", "f.txt"]);
  run(["commit", "-m", "init"]);
  const ref = P.deriveContainerRef(repo);
  assert.match(ref, /^repo:[0-9a-f]{12}$/, `expected repo:<hash12>, got ${ref}`);
});

test("redactSensitive is unicode-safe (non-ASCII text is preserved, secrets still stripped)", () => {
  assert.equal(P.redactSensitive("提交说明 Bearer sk-üñ"), "提交说明 Bearer [REDACTED]");
  assert.equal(P.redactSensitive("café notes, no secrets"), "café notes, no secrets");
});

test("formatRelay preserves complete attributed messages and enforces budget", () => {
  const delivery = {
    delivery_id: "d-1", claim_token: "claim-1", message_id: "m-1",
    sender_runtime: "claude-code", sender_session_ref: "session-a",
    payload: "handoff שלום 你好", created_at: "2026-08-25T10:00:00+00:00",
    in_reply_to: "m-0",
  };
  const out = P.formatRelay([delivery], 2000);
  assert.match(out.text, /^\[Pallium Relay message from claude-code:session-a\]/);
  assert.match(out.text, /lower authority/);
  assert.match(out.text, /handoff שלום 你好/);
  assert.match(out.text, /delivery_id: d-1/);
  assert.match(out.text, /pallium_relay_reply/);
  assert.match(out.text, /make its Pallium Relay origin clear/);
  assert.match(out.text, /in_reply_to: m-0/);
  assert.deepEqual(out.deliveries, [delivery]);
  assert.equal(P.formatRelay([delivery], 20).text, "");
  assert.equal(P.formatRelay([{ ...delivery, payload: "bad\u0000value" }], 2000).text, "");
  const maximum = {
    ...delivery, message_id: "m".repeat(128), sender_session_ref: "s".repeat(255),
    in_reply_to: "p".repeat(128), payload: "😀".repeat(1500),
  };
  assert.ok(P.formatRelay([maximum], 2400).text);
  assert.match(P.formatRelay([{ ...delivery, payload: "line one\nline two\tvalue" }]).text, /line one\nline two\tvalue/);
});


test("buildWorkRefsMetadata caches Git state but rechecks records and HEAD", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-work-ref-"));
  const originalPath = process.env.PATH;
  try {
    execFileSync("git", ["init", "-b", "main"], { cwd: dir, stdio: "ignore" });
    execFileSync("git", ["config", "user.name", "Test"], { cwd: dir });
    execFileSync("git", ["config", "user.email", "test@example.invalid"], { cwd: dir });
    fs.writeFileSync(path.join(dir, "README.md"), "test");
    execFileSync("git", ["add", "README.md"], { cwd: dir });
    execFileSync("git", ["commit", "-m", "init"], { cwd: dir, stdio: "ignore" });
    execFileSync("git", ["checkout", "-b", "demo/item"], { cwd: dir, stdio: "ignore" });
    const tasks = path.join(dir, ".agent-workflow", "tasks");
    const record = path.join(tasks, "item.md");
    fs.mkdirSync(tasks, { recursive: true });
    fs.writeFileSync(
      record,
      "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->",
    );

    assert.deepEqual(P.buildWorkRefsMetadata(dir, ["Ticket_Ünicode"]), {
      pallium_work_refs: [
        "git-branch:demo/item",
        "agent-workflow:item",
        "Ticket_Ünicode",
      ],
    });

    process.env.PATH = "";
    assert.deepEqual(P.buildWorkRefsMetadata(dir, ["NEXT-2"]), {
      pallium_work_refs: ["git-branch:demo/item", "agent-workflow:item", "NEXT-2"],
    });
    fs.rmSync(record);
    assert.deepEqual(P.buildWorkRefsMetadata(dir), {
      pallium_work_refs: ["git-branch:demo/item"],
    });
    fs.writeFileSync(record, "<!-- agent-workflow:start -->");
    assert.deepEqual(P.buildWorkRefsMetadata(dir), {
      pallium_work_refs: ["git-branch:demo/item"],
    });
    fs.writeFileSync(
      record,
      "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->",
    );
    assert.deepEqual(P.buildWorkRefsMetadata(dir), {
      pallium_work_refs: ["git-branch:demo/item", "agent-workflow:item"],
    });

    process.env.PATH = originalPath;
    execFileSync("git", ["checkout", "main"], { cwd: dir, stdio: "ignore" });
    assert.deepEqual(P.buildWorkRefsMetadata(dir, ["ISSUE-1"]), {
      pallium_work_refs: ["ISSUE-1"],
    });

    const head = path.join(dir, ".git", "HEAD");
    const missingHead = path.join(dir, ".git", "HEAD.missing");
    fs.renameSync(head, missingHead);
    assert.deepEqual(P.buildWorkRefsMetadata(dir, ["ISSUE-2"]), {
      pallium_work_refs: ["ISSUE-2"],
    });
    fs.renameSync(missingHead, head);
  } finally {
    process.env.PATH = originalPath;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("buildWorkRefsMetadata does not negative-cache and isolates linked worktrees", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-worktrees-"));
  const one = `${dir}-one`;
  const two = `${dir}-two`;
  try {
    assert.deepEqual(P.buildWorkRefsMetadata(dir), {});
    execFileSync("git", ["init", "-b", "main"], { cwd: dir, stdio: "ignore" });
    execFileSync("git", ["config", "user.name", "Test"], { cwd: dir });
    execFileSync("git", ["config", "user.email", "test@example.invalid"], { cwd: dir });
    fs.writeFileSync(path.join(dir, "README.md"), "test");
    execFileSync("git", ["add", "README.md"], { cwd: dir });
    execFileSync("git", ["commit", "-m", "init"], { cwd: dir, stdio: "ignore" });
    execFileSync("git", ["checkout", "-b", "feature/init"], { cwd: dir, stdio: "ignore" });
    fs.mkdirSync(path.join(dir, ".agent-workflow", "tasks"), { recursive: true });
    fs.writeFileSync(
      path.join(dir, ".agent-workflow", "tasks", "init.md"),
      "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->",
    );
    assert.deepEqual(P.buildWorkRefsMetadata(dir), {
      pallium_work_refs: ["git-branch:feature/init", "agent-workflow:init"],
    });

    execFileSync("git", ["worktree", "add", "-b", "feature/one", one, "main"], { cwd: dir, stdio: "ignore" });
    execFileSync("git", ["worktree", "add", "-b", "feature/two", two, "main"], { cwd: dir, stdio: "ignore" });
    for (const [workspace, slug] of [[one, "one"], [two, "two"]]) {
      const tasks = path.join(workspace, ".agent-workflow", "tasks");
      fs.mkdirSync(tasks, { recursive: true });
      fs.writeFileSync(
        path.join(tasks, `${slug}.md`),
        "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->",
      );
      assert.deepEqual(P.buildWorkRefsMetadata(workspace), {
        pallium_work_refs: [
          `git-branch:feature/${slug}`,
          `agent-workflow:${slug}`,
        ],
      });
    }
  } finally {
    fs.rmSync(one, { recursive: true, force: true });
    fs.rmSync(two, { recursive: true, force: true });
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
