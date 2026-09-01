<!-- agent-workflow:start -->
**Outcome:**
An unattended Codex Relay wake can execute explicitly requested Relay send, reply, and ACK calls without stopping for unavailable human approval.

**Target:**
Pallium's Codex exact-session wake launcher and installed Codex MCP policy.

**Scope:**
`app/codex_wake.py`, `app/cli/setup_codex.py`, `app/mcp/client.py`, `storage/sqlite_relay.py`, `tests/test_codex_wake.py`, `tests/test_codex_integration.py`, `tests/test_mcp_client.py`, `tests/test_agent_relay_e2e.py`, and this Work Record only.

**Constraints:**
Keep the existing workspace-write sandbox and narrow Relay authorization; do not bypass sandboxing, enable unrelated tools, or broaden global approval behavior.

**Completion criteria:**
Cold-resumed and active-queue wake turns can execute explicitly requested Relay send/reply/ACK calls without human approval. The dedicated profile exposes only those three tools, the base policy pre-approves the same three operations for already-loaded Desktop tasks, and MCP send/reply/ACK absorb bounded explicit `relay_busy` responses without retrying ambiguous failures.

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
Redline classified runtime/config paths gray/watch and tests blue. The change affects unattended MCP authorization but remains limited to the three Relay operations.

**Discovery:**
Codex 0.149.1 uses per-tool `approval_mode = "approve"` as deterministic preauthorization. `codex queue` cannot change a loaded task's policy. Live trace proved the active-task path: ACK succeeded because base config pre-approved it; `pallium_relay_send` failed because base config omitted it and defaulted to prompt under `approval_policy=never`. The dedicated profile already contains all three tools. `--approve-for-me` was tested and rejected as broader and ineffective for this queued task. A restarted live task then proved authorization fixed: ACK and send both executed without approval, but send received explicit retryable 503 `relay_busy` twice while background thread processing held SQLite. The API intentionally fails fast for hook latency; the MCP client currently exposes that retryable contract to the agent instead of consuming it.

**Material assumptions:**
- Adding `pallium_relay_send` to the existing base `tools` map makes new/restarted loaded Codex tasks resolve it to `approve`; disprove with generated-config regression or live policy block, then stop.
- Existing task bindings require a Codex restart to load the corrected base policy; disprove if the restarted task still shows the old binding, then inspect managed config precedence.
- Retrying only explicit HTTP 503 `detail.code=relay_busy` is safe because the API raises it before persistence; never retry timeouts, connection failures, or other ambiguous results.

**Plan:**
Remove `--approve-for-me` from both wake commands and restore their exact argv tests. Add `pallium_relay_send = { approval_mode = "approve" }` beside reply and ACK in the base Codex MCP config generator. Extend the setup regression to assert exactly all three approved Relay tools while keeping the server default at prompt. Reinstall Codex, restart the app once, and repeat the active-task Relay request. Make atomic reply enter through `_begin_immediate` so all three mutations expose the same bounded 503 contract. In the shared MCP client, make at most 12 attempts with the server-provided `Retry-After` capped at one second, only when HTTP status is 503 and `detail.code=relay_busy` plus `retryable=true`; then surface the final error unchanged on exhaustion. Send shall generate one stable client message ID reused across attempts. Keep hook/turn fail-fast behavior and never retry timeouts, connection failures, generic 5xx, malformed bodies, 409s, or responses marked non-retryable. Add no probe tool, bypass flag, or new policy layer.

**Verification plan:**
- When setup generates base Codex MCP config, exactly Relay send/reply/ACK shall be pre-approved and default tools shall prompt -> generated-config regression.
- When cold wake launches, it shall use the dedicated Relay profile without auto-review or bypass flags -> exact subprocess argv regression.
- When active wake queues, it shall preserve the same bounded command and rely on the loaded task's base policy -> exact subprocess argv regression.
- Explicit `relay_busy` followed by success shall be absorbed for send/reply/ACK with unchanged request payloads; exhaustion shall preserve the exact final error after 12 attempts -> focused MCP client regressions with call counts.
- Generic/malformed/non-retryable HTTP errors and connection/timeouts shall receive exactly one attempt -> focused MCP client regressions.
- Atomic reply shall map exhausted SQLite acquisition to the same sanitized 503 contract; a retry using one stable send ID shall create only one message/delivery -> HTTP E2E regressions.
- After reinstall and Codex restart, an active developer shall ACK and send `hello rotem` without manual approval or agent-managed retry -> live Relay round trip and finalized delivery evidence.

**Plan review:**
Clean-context re-review by /root/relay_approval_plan_review: APPROVED after live-evidence-driven scope change. Follow-up review `/root/relay_busy_plan_review` blocked the first retry draft, then APPROVED the revision after atomic reply shared the 503 contract and retry limits/predicate/error regressions were explicit.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Initial `--approve-for-me` approach passed 47 focused tests but failed live and is being removed. Live trace isolated the real mismatch to the base Codex MCP policy used by queued Desktop turns.
Revised implementation removes the flag and adds only pallium_relay_send to the existing base approval map. The follow-up makes atomic reply expose the same sanitized busy contract and adds bounded MCP-only retry for send/reply/ACK with stable send IDs and a 25-second aggregate deadline. Focused wake/setup/MCP/HTTP regressions pass 115/115; final live restarted-task verification remains.

## Evidence

Message `relay-msg-58c8e2e0b47543229879446724afaf77` woke `codex:@relaydev`; its delivery finalized in one attempt. Rollout event 10053 shows ACK succeeded. Event 10059 shows `pallium_relay_send` blocked by `approval_policy is never`. Generated config inspection shows base policy approves only reply/ACK, while the dedicated profile approves send/reply/ACK.

## Plan review

Initial plan review approved the bounded auto-review experiment, then live evidence disproved it. Revised base-policy plan was re-reviewed by /root/relay_approval_plan_review and APPROVED.

## Result review

Clean-context review by `/root/relay_busy_result_review`: APPROVED after two review cycles corrected malformed-success handling, aggregate timeout enforcement, and non-Relay timeout scoping.

Live follow-up evidence: message `relay-msg-1994c7ab98b24f9aa1b133497d98fa8e` woke the developer. ACK completed, proving the approval fix. Both permitted sends returned explicit 503 `relay_busy` while background thread processing remained active, so no reply was persisted. The bounded MCP retry addition was clean-context reviewed and approved.

Final live verification: `relay-msg-d5a035bef94147c3a0746ebe8598dbd4` woke `codex:@relaydev` without a manual ping. The developer received the attributed wake batch, used atomic `pallium_relay_reply`, and delivered exact payload `hello rotem` as `relay-reply-92d2d0c36ea3cee41955ae17b47e7d726e2cac4efa0c874e469c4b4c0b628363`. The original delivery reached `delivered` in one claim attempt; the reply was queued back to the already-active architect task.
