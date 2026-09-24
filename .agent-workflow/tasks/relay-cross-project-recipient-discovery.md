<!-- agent-workflow:start -->
**Outcome:**
Agents can find a known Relay recipient in another Pallium project without mistaking container-local discovery for absence.

**Target:**
Pallium Relay integration guidance.

**Scope:**
Update docs/agent-relay.md and the Codex, Claude Code, and OpenCode pallium-memory SKILL.md sources.

**Constraints:**
Keep ordinary MCP discovery container-local; use only read-only global session lookup for cross-project discovery; verify the exact target before sending; do not change Relay behavior, APIs, or CI; install only from the stable checkout after merge.

**Completion criteria:**
When the destination is in another project, each skill explains the global read-only lookup, exact task-session match, current endpoint or alias, and safe fallback; Relay docs agree; the three skill sources stay identical.

**Requirement baseline:**
{"source":"2d8fc659-fce7-4c9a-ab7d-f090a2f2f823","outcome":"Agents can find a known Relay recipient in another Pallium project without mistaking container-local discovery for absence.","scope":"Update docs/agent-relay.md and the Codex, Claude Code, and OpenCode pallium-memory SKILL.md sources.","constraints":"Keep ordinary MCP discovery container-local; use only read-only global session lookup for cross-project discovery; verify the exact target before sending; do not change Relay behavior, APIs, or CI; install only from the stable checkout after merge.","completion_criteria":"When the destination is in another project, each skill explains the global read-only lookup, exact task-session match, current endpoint or alias, and safe fallback; Relay docs agree; the three skill sources stay identical."}

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
Redline classifies three integration skill files gray and the Relay doc blue; no checkpoint or boundary applies. One coherent guidance change.

**Discovery:**
Pending final source and installer verification. The MCP recipient list is container-local, while the read-only dashboard Relay session list is service-global.

**Material assumptions:**
The installed dashboard exposes a service-global session list with exact session ID, runtime, container, endpoint ID, and alias; if that fails verification, return to planning.

**Plan:**
Pending clean-context review. Add one short cross-project discovery rule to all three mirrored skills and a concise explanation to docs/agent-relay.md. Keep routing and scope rules unchanged.

**Verification plan:**
When a known destination is in another project, the guidance names the global read-only lookup and exact-match verification → inspect the final diff and compare against the live endpoint contract.
When the guidance is mirrored, all three skill sources remain identical → compare file hashes and run focused integration packaging checks.

**Plan review:**
Pending clean-context review.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Initial context and immutable Requirement baseline recorded before source edits. Branch: feat/relay-cross-project-recipient-discovery.

## Evidence

Pending.

## Result review

Pending.
