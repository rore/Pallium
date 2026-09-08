#!/usr/bin/env node

import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("package includes the lazy field-feedback reference", () => {
  assert.ok(process.env.npm_execpath, "run this check through npm test");
  const output = execFileSync(
    process.execPath,
    [process.env.npm_execpath, "pack", "--dry-run", "--json", "--ignore-scripts"],
    { cwd: root, encoding: "utf8" },
  );
  const files = JSON.parse(output)[0].files.map((file) => file.path);
  assert.ok(files.includes("skills/pallium-memory/references/field-feedback.md"));
});
