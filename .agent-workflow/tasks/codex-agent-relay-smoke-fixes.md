# Agent Relay R1 smoke-test fixes

Branch: `codex/agent-relay-smoke-fixes`

<!-- agent-workflow:start -->
**Outcome:**
Natural Claude Code, Codex, and OpenCode Relay interactions identify the current sender without recipient-list inference, reply exactly once with deterministic attribution, and follow a deliberate Git-project switch and best-effort closes the old project registration.

**Target:**
Agent Relay HTTP/MCP contracts and bundled Claude Code, Codex, and OpenCode integrations.

**Scope:**
Add a delivery-derived reply operation; clarify current-session MCP arguments and guidance; expose delivery IDs in attributed blocks; update Claude/Codex project-scope resolution for deliberate Git-repository changes; close the old Relay registration on transition; add public HTTP/MCP/hook E2E coverage; align Relay docs and roadmap evidence.

**Constraints:**
Keep Relay deterministic and separate from memory/retrieval. Preserve the existing general HTTP send contract. Do not infer the current session from recency, titles, or aliases. Do not follow transient non-Git cwd changes. Do not move queued messages between projects. Hooks remain fail-open and bounded.

**Completion criteria:**
A received delivery can be replied to with only its delivery ID and payload; Pallium derives sender, recipient, and parent and retries idempotently. MCP naming/sending uses explicit current/sender field names and exact injected scope guidance. Claude/Codex retain scope within one repo and temporary non-Git directories, but entering another Git repo updates the pin and closes the prior Relay session before registering the new scope. All boundaries, conflicts, duplicate calls, cross-scope delivery IDs, Unicode, reply chains, and runtime hook formatting are covered through public surfaces.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
The fix changes API/MCP contracts and session lifecycle across guarded core, API, storage, and runtime integration paths. It does not add schema or alter memory state.

**Discovery:**
Live smoke testing showed successful persistence, alias routing, next-turn injection, and acknowledgement, but agents listed recipients to discover themselves; a natural reply first impersonated the original Claude sender and then emitted a second correct Codex reply; and a Claude session pinned at a non-Git parent could not join the Pallium project after a deliberate cwd change. The shared cause is model-owned identity plus unconditional session-start container pinning.

**Material assumptions:**
- `agent_ref` is the current Relay runtime and `thread_ref` is the current immutable session ID in bundled scope.
- A delivery-derived reply is one idempotent reply action per delivery; additional conversation turns are new messages/replies.
- A `git:` or `repo:` cwd is a recognized project. A `path:` cwd is retained only when no recognized project is pinned.
- Project transition closes the old scoped Relay session and releases its project-local alias; queued old-project deliveries remain pinned there.
- OpenCode plugin instances remain project-bound by their injected `directory`/`worktree`.

**Plan:**
1. Add delivery-derived reply lookup and public HTTP/MCP tool, reusing the existing validated send path and a deterministic reply message ID.
2. Rename agent-facing MCP sender/current-session parameters and update all three skills plus attributed delivery blocks.
3. Add deliberate recognized-project switching to Claude/Codex user-prompt hooks and close the previous Relay registration best-effort.
4. Add HTTP/MCP/hook/OpenCode E2E for live failures and every affected boundary; run focused and full regression plus governance checks.
5. Update docs/roadmap with observed evidence, open a PR, resolve review/CI findings, and merge only when green.

**Verification plan:**
- Reply → exact delivery, delivered-state requirement, cross-scope/unknown/pending conflict, Unicode bounds, deterministic duplicate retry, different-payload conflict, and chain length >2 through HTTP/MCP.
- Identity UX → MCP schemas/descriptions and installed guidance require exact scope mapping and prohibit recipient discovery for self-identification.
- Project lifecycle → same-repo subdir, non-Git excursion, path-to-Git, Git-to-Git, failed close, old-session close/alias release, and new-scope registration through actual hooks.
- Runtime rendering → delivery ID and reply instruction fit exact 2,400-code-point envelope in Python and OpenCode.
- Regression/governance → focused Python/Node suites, full pytest, import/redline/workflow checks, and `git diff --check`.

**Plan review:**
Completed diff reviewed against the prior R1 contract; see `## Plan review` below. The user explicitly waived the agent-workflow interaction for this Relay track.

**Approvals:**
Approved by user 2026-08-25T18:01:00+03:00: "so now analyze all that went here, see if there are any fixes or improvements this points to. if so, you have approval to do a fix cycle, this is a night job for you, i won't be here"

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Plan review

The live smoke trace and implemented diff were reviewed against the approved R1 contract. The smallest shared corrections are: derive reply identity from a delivered record instead of model-owned endpoints; make retry identity deterministic from the delivery ID; expose current identity through explicit MCP argument names and injected scope; and allow only recognized Git project changes to replace a session pin. No schema, broker, wake-up, conversation manager, semantic routing, or OpenCode project-switch mechanism was added.
## Implementation

Added one delivery-derived reply route and MCP tool over the existing send path, explicit current/sender MCP argument names, delivery IDs and reply instructions in all runtime blocks, and recognized-project switching in Claude/Codex prompt hooks. No schema, dependency, broker, live delivery, semantic routing, or OpenCode lifecycle change was added.

## Evidence

- Focused HTTP/MCP/hook/lifecycle suite: 145 passed.
- OpenCode integration suite: 40 passed.
- Guidance budgets: 2 passed.
- Full non-slow Python regression: 3,904 passed, 12 skipped, 2 xfailed after deselecting the documented pre-existing `test_prompt_variants_legacy_fallback_unaffected` failure. The unfiltered isolated legacy test fails unchanged and is already named in `docs/runbooks/2026-06-27-injection-policy-handoff.md`.
- Import-linter: 8 contracts kept, 0 broken. Workflow checker: clean. Compileall and `git diff --check`: clean.
- Redline: RED for `api/routes.py`/`api/schemas.py`, no boundary violation; PR requires CODEOWNER approval or `api-reviewed` label.
- `apply_patch` hit the documented Windows `CreateProcessWithLogonW` error 1385 once. Per repository instructions, all edits then used narrow deterministic replacements limited to named files.
## Result review

Automated review found one material lifecycle gap and one wording ambiguity. A failed old-project close could not be retried after the new pin replaced the old reference. Fixed by retaining a deduplicated list of pending Relay closes in the existing atomic session-pin record, retrying it at each model-bound turn, and clearing only successful closes; a two-turn failure→success regression runs for both Claude Code and Codex. The reply guide now states explicitly that the original message sender becomes the reply recipient. Focused post-review hook/integration verification: 94 passed. The generic docstring-coverage suggestion was not applied because it is unrelated repository-wide churn and not a project gate.