import { spawnSync } from "node:child_process";
import { join } from "node:path";

// Keep this text byte-identical to SEED in scripts/agent-workflow-runtime.py
// and CTX in hooks/seed-workflow.sh.
const SEED = "Project rule: invoke the agent-workflow skill before planning or editing. It first evaluates any configured applicability policy. Only an explicit whole-change exemption may skip the Work Record; otherwise every engineering task is recorded. Any implementation plan for a non-exempt task must include, as its FIRST implementation step, invoking /agent-workflow to create the Work Record and classify risk before any code edit.";
const MUTATION_TOOLS = new Set(["write", "edit", "apply_patch"]);

class GuardDenied extends Error {}

function runGuard(directory, payload) {
  const script = join(directory, "scripts", "agent-workflow-runtime.py");
  const candidates = process.env.PYTHON
    ? [[process.env.PYTHON]]
    : process.platform === "win32"
      ? [
          [join(directory, ".venv", "Scripts", "python.exe")],
          ["py", "-3"],
          ["python"],
        ]
      : [
          [join(directory, ".venv", "bin", "python")],
          ["python3"],
          ["python"],
        ];

  for (const [command, ...prefix] of candidates) {
    const result = spawnSync(
      command,
      [...prefix, script, "--runtime", "opencode"],
      {
        cwd: directory,
        input: JSON.stringify(payload),
        encoding: "utf8",
        windowsHide: true,
        timeout: 30000,
      },
    );
    if (result.error?.code === "ENOENT") continue;
    if (result.error) return { deny: result.error.message };
    const stderr = (result.stderr || "").trim();
    if (result.status === 2 && stderr.includes("[agent-workflow] DENY:")) {
      return { deny: stderr };
    }
    if (result.status !== 0) {
      return { deny: stderr || "runtime guard failed" };
    }
    return stderr ? { degraded: stderr } : {};
  }
  return { degraded: "Python unavailable; final CI remains authoritative" };
}

export default async ({ client, directory }) => ({
  "experimental.chat.system.transform": async (_input, output) => {
    try {
      if (!output || !Array.isArray(output.system)) return;
      if (output.system.length > 0) {
        output.system[output.system.length - 1] += "\n\n" + SEED;
      } else {
        output.system.push(SEED);
      }
    } catch {
      // Prompt transport is advisory and fails open.
    }
  },

  "tool.execute.before": async (input, output) => {
    if (!input || !MUTATION_TOOLS.has(input.tool)) return;
    try {
      const decision = runGuard(directory, {
        tool_name: input.tool,
        tool_input: output?.args,
        cwd: directory,
      });
      if (decision.deny) throw new GuardDenied(decision.deny);
      if (decision.degraded) {
        await client?.app?.log?.({
          body: {
            service: "agent-workflow",
            level: "warn",
            message: "Runtime guard degraded",
            extra: { reason: decision.degraded },
          },
        });
      }
    } catch (error) {
      if (error instanceof GuardDenied) throw error;
      // Adapter faults before a decision fail open and remain visible when logging is available.
      try {
        await client?.app?.log?.({
          body: {
            service: "agent-workflow",
            level: "error",
            message: "Runtime guard adapter failed open",
            extra: { reason: String(error) },
          },
        });
      } catch {
        // Logging must not break a turn.
      }
    }
  },
});