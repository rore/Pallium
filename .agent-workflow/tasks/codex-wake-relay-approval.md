<!-- agent-workflow:start -->
**Outcome:**
An unattended Codex Relay wake can execute explicitly requested Relay send, reply, and ACK calls without stopping for unavailable human approval.

**Target:**
Pallium's Codex exact-session wake launcher and installed Codex MCP policy.

**Scope:**
`app/codex_wake.py`, `app/cli/setup_codex.py`, `tests/test_codex_wake.py`, `tests/test_codex_integration.py`, and this Work Record only.

**Constraints:**
Keep the existing workspace-write sandbox and narrow Relay authorization; do not bypass sandboxing, enable unrelated tools, or broaden global approval behavior.

**Completion criteria:**
Cold-resumed and active-queue wake turns can execute explicitly requested Relay send/reply/ACK calls without human approval. The dedicated profile exposes only those three tools, and the base policy pre-approves the same three operations for already-loaded Desktop tasks.

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
Redline classified runtime/config paths gray/watch and tests blue. The change affects unattended MCP authorization but remains limited to the three Relay operations.

**Discovery:**
Codex 0.149.1 uses per-tool `approval_mode = "approve"` as deterministic preauthorization. `codex queue` cannot change a loaded task's policy. Live trace proved the active-task path: ACK succeeded because base config pre-approved it; `pallium_relay_send` failed because base config omitted it and defaulted to prompt under `approval_policy=never`. The dedicated profile already contains all three tools. `--approve-for-me` was tested and rejected as broader and ineffective for this queued task.

**Material assumptions:**
- Adding `pallium_relay_send` to the existing base `tools` map makes new/restarted loaded Codex tasks resolve it to `approve`; disprove with generated-config regression or live policy block, then stop.
- Existing task bindings require a Codex restart to load the corrected base policy; disprove if the restarted task still shows the old binding, then inspect managed config precedence.

**Plan:**
Remove `--approve-for-me` from both wake commands and restore their exact argv tests. Add `pallium_relay_send = { approval_mode = "approve" }` beside reply and ACK in the base Codex MCP config generator. Extend the setup regression to assert exactly all three approved Relay tools while keeping the server default at prompt. Reinstall Codex, restart the app once, and repeat the active-task Relay request. Add no probe tool, bypass flag, or new policy layer.

**Verification plan:**
- When setup generates base Codex MCP config, exactly Relay send/reply/ACK shall be pre-approved and default tools shall prompt -> generated-config regression.
- When cold wake launches, it shall use the dedicated Relay profile without auto-review or bypass flags -> exact subprocess argv regression.
- When active wake queues, it shall preserve the same bounded command and rely on the loaded task's base policy -> exact subprocess argv regression.
- After reinstall and Codex restart, an active developer shall ACK and send `hello rotem` without manual approval -> live Relay round trip and finalized delivery evidence.

**Plan review:**
Clean-context re-review by /root/relay_approval_plan_review: APPROVED after live-evidence-driven scope change.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Initial `--approve-for-me` approach passed 47 focused tests but failed live and is being removed. Live trace isolated the real mismatch to the base Codex MCP policy used by queued Desktop turns.
Revised implementation removes the flag and adds only pallium_relay_send to the existing base approval map. Focused wake/setup regressions pass 47/47; live restarted-task verification remains.

## Evidence

Message `relay-msg-58c8e2e0b47543229879446724afaf77` woke `codex:@relaydev`; its delivery finalized in one attempt. Rollout event 10053 shows ACK succeeded. Event 10059 shows `pallium_relay_send` blocked by `approval_policy is never`. Generated config inspection shows base policy approves only reply/ACK, while the dedicated profile approves send/reply/ACK.

## Plan review

Initial plan review approved the bounded auto-review experiment, then live evidence disproved it. Revised base-policy plan was re-reviewed by /root/relay_approval_plan_review and APPROVED.

## Result review

Pending.