# Codex MCP tool exposure incident

<!-- agent-workflow:start -->
**Outcome:** Record the measured Codex Desktop MCP exposure incident and its supported recovery.

**Target:** Pallium Codex integration troubleshooting.

**Scope:** This Work Record and `docs/codex-integration.md` only.

**Constraints:** No runtime, MCP, setup, trust, configuration, service, or active-session mutation. Treat the host's internal failure mechanism as inferred, not proven. Exclude private session IDs and transcripts.

**Completion criteria:** Preserve the working-versus-affected comparison, distinguish hook delivery from MCP exposure, record the separate Claude result, and document recovery for enabled configuration with task-local tool loss.

**Risk:** Routine

**Complexity:** Simple

**Reason:** BLUE classification: documentation-only operational guidance and evidence, with no guarded runtime path.

**Approach:** Correct the troubleshooting table, retain sanitized incident evidence here, run the workflow checker, and obtain a smart result review.

**Verification:** Inspect the Markdown and links, run `git diff --check`, run the agent-workflow checker, and complete an independent smart review.

**State:** Ready for review
<!-- agent-workflow:end -->

## Incident assessment

- On the same Codex host and checkout, one existing task exposed 28 Pallium tools and successfully called recipient discovery, while multiple existing long-running tasks exposed zero Pallium tools across repeated turns despite earlier successful Pallium calls.
- The server remained enabled and required, and hook delivery continued. Warm-turn, model, reasoning-effort, repository scope, and current model-metadata comparisons did not explain the split.
- The evidence localizes the observed fault to the Codex host/task tool-exposure boundary. The exact internal rehydration mechanism remains inferred. The symptom matches public Codex reports #26196 and #15508.
- Codex Desktop's MCP-server Restart action is the supported first recovery. A Pallium runtime cannot expose tools omitted from the host's task tool catalog without host startup or protocol evidence.
- Existing affected-task send/reply/attach/detach recovery remains blocked until a supported host restart is possible. Acceptance does not require creating a new task or interrupting an active task.
- The user approved the delegated work and pull-request workflow. BLUE classification required no separate plan review.

## Implementation

- Corrected Codex troubleshooting to separate invalid setup from long-running task-local MCP exposure loss.
- Made no runtime, setup, service, dependency, or active-session changes.
- Coordinated the separate Claude installation-path drift with the deployment owner.

## Evidence

- Codex control: one existing task exposed 28 Pallium tools and completed live recipient discovery.
- Affected Codex sample: multiple existing tasks repeatedly exposed zero Pallium tools, had earlier successful Pallium MCP calls, and continued receiving hooks.
- Claude Code 2.1.270 control: an existing session received a hook delivery, loaded Pallium through ToolSearch, completed recipient discovery, and replied atomically.
- Claude's user-scope server was connected but referenced the development checkout; stable-checkout repointing is delegated to the deployment owner.
- `codex mcp` provides configuration commands but no supported restart/rebind command; Codex Desktop exposes the supported MCP-server Restart action.
- `git diff --cached --check` passed, and the agent-workflow checker returned clean with no boundary violations.
- Independent Astra result review found no factual, privacy, inference-boundary, or Work Record mismatch.
