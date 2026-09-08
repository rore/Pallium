// agent-workflow.mjs — OpenCode engagement for the agent-workflow harness.
//
// OpenCode does not read .claude/ or run the Claude Code hooks, so this plugin
// is the OpenCode analog of .claude/hooks/seed-workflow.sh: it injects the
// Work-Record rule into the system prompt each turn so the workflow stays
// engaged while the model plans. Reliable transport, NOT enforcement — the CI
// checker (scripts/agent-workflow-check.py) remains the only gate.
//
// FAIL OPEN: every path is wrapped so a broken plugin never breaks a turn,
// matching seed-workflow.sh's `set +e` + exit-0 behaviour.
//
// OpenCode auto-loads plugins from a project's .opencode/plugins/ directory
// (no opencode.json entry required); bootstrap installs it there.

// SEED must stay byte-identical to CTX in .claude/hooks/seed-workflow.sh.
// Keep it a single-line, double-quoted string with no " or \ — the parity
// check in tests/hooks/run.sh extracts it by regex and asserts equality.
const SEED = "Project rule: invoke the agent-workflow skill before planning or editing. It first evaluates any configured applicability policy. Only an explicit whole-change exemption may skip the Work Record; otherwise every engineering task is recorded. Any implementation plan for a non-exempt task must include, as its FIRST implementation step, invoking /agent-workflow to create the Work Record and classify risk before any code edit.";

export default async () => ({
  // Analog of seed-workflow.sh (UserPromptSubmit): append the Work-Record rule
  // to the system prompt. Mirrors pallium.mjs's experimental.chat.system.transform.
  "experimental.chat.system.transform": async (_input, output) => {
    try {
      if (!output || !Array.isArray(output.system)) return;
      if (output.system.length > 0) {
        output.system[output.system.length - 1] += "\n\n" + SEED;
      } else {
        output.system.push(SEED);
      }
    } catch {
      /* fail open — never break the user's turn */
    }
  },
});
