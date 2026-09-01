<!-- agent-workflow:start -->
**Outcome:** Sending an exact-session Relay message through the installed MCP wakes that Codex session without a separate user or agent ping.

**Target:** Pallium Relay Codex integration.

**Scope:** Add the smallest Codex-only post-persist notification in `app/mcp/server.py`, its focused MCP regression and one live two-session smoke.

**Constraints:** Persist first. Queue notification carries no Relay payload or capability. Wake failure must not fail or consume the durable message. Exact Codex sessions only; no runtime broadcast, retry coordinator, batching activation, schema/API/service/dashboard change, Claude/OpenCode work, managed App Server, or `uv.lock` edit.

**Completion criteria:** A successful exact-session or exact-alias Relay MCP send launches one `codex queue --thread <resolved-session>` notification without changing the durable send result; broadcasts, other runtimes, malformed results, and launch failure leave the normal-turn fallback intact.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** `app/mcp/server.py` is guarded gray runtime code. The change is intentionally one runtime adapter and one observable journey, but process launch and installed-session verification require cautious review.

**Discovery:** The existing MCP send receives the persisted response including resolved deliveries. `codex queue --thread ... --message ...` is already proven to target an existing session. Waking in the MCP adapter avoids API/storage/schema changes and reuses the normal UserPromptSubmit inbox hook. Windows resolves the npm shim as `codex.cmd`, not the PowerShell `codex` command.

**Material assumptions:** The installed MCP process can launch native `codex.exe` on Windows (or `codex` elsewhere) and the static notification causes the target's normal UserPromptSubmit hook to run; disprove with focused subprocess/mock, then stop without adding another transport. The returned delivery list contains runtime-owned exact Codex session refs; disprove with response inspection, then do not guess or list recipients. Queue launch failure is non-fatal because the persisted message remains pending; verify by simulated launch failure plus ordinary-turn retrieval.

**Plan:** (1) Clean-context review this minimal MCP-only boundary. (2) Add one private helper in `app/mcp/server.py` that, after successful exact-session send persistence, launches the platform Codex queue command once only when the original selector is exact (`codex:<session>` or `codex:@<alias>`) and it resolves to one Codex delivery with a constant notification and fully detached/suppressed stdio; swallow launch failure so fallback stays pending. (3) Invoke it only from MCP send, never reply or runtime broadcast. (4) Add focused tests for exact argv, no payload in notification, broadcast/non-Codex skip, launch failure, and unchanged returned result. Stop on any need for schema, HTTP API, service restart, managed server, or second payload path.

**Verification plan:** When MCP send returns an exact Codex delivery, one native queue notification shall target its resolved session and contain no message payload → focused MCP server test. When launch fails or delivery targets another runtime, persisted send shall return normally with no wake → focused failure/skip tests plus status/ordinary-turn retrieval. A live dogfood probe remains outside this implementation turn and requires its own observed runtime evidence; unit tests do not claim hook admission.

**Plan review:** Clean-context review `/root/wake_plan_review` (2026-09-01): approved the MCP-only boundary with one correction—gate wake on an exact original selector as well as one resolved Codex delivery, because a singleton runtime broadcast is not an exact-session authorization.

**Approvals:** Not required at this risk level; user explicitly requested this exact minimal wake slice on 2026-09-01.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->
## Plan review

- 2026-09-01 `/root/wake_plan_review` (clean context): the queue helper stays within the approved MCP-only boundary if it requires both an exact original selector and one returned Codex delivery with a nonempty session reference. A singleton `codex` broadcast is otherwise indistinguishable from an exact delivery and must not wake. Suppressed detached subprocess launch with swallowed `OSError` preserves the durable fallback.

## Implementation

- 2026-09-01: Implemented the reviewed MCP-only exact-Codex vertical slice in `app/mcp/server.py`: only `codex:<session>` or `codex:@alias` selectors that resolve to exactly one Codex delivery launch detached native `codex.exe queue` on Windows (or `codex` elsewhere), with a constant payload-free notification and suppressed stdio. Broadcast, non-Codex, malformed, and launch-failure paths leave the persisted response and ordinary-turn fallback unchanged. Focused MCP regression: 7 passed, 4 existing Pydantic warnings; `git diff --check` passes. Live proof: an MCP send of `MINIMAL-WAKE-SMOKE-20260901-1001` to idle `codex:@relaydev` persisted as `relay-msg-59308b316c0044ad9619ec1d93f670bb`; the native queue notification started that exact task without an app ping, its normal Relay hook delivered the payload, and it returned `WAKE-OK`. This experimental dogfood slice does not claim the prior production-batch G2/G3 guarantees.
- 2026-09-01 review fix: the first live wake exposed a visible Windows console from DETACHED_PROCESS. Replaced it with CREATE_NO_WINDOW and added a Windows flag regression. A second idle-target send, elay-msg-9590dc369da142e7b99112003f97d8b9, woke elaydev without an app ping and returned NO-WINDOW-OK without opening a command window.
