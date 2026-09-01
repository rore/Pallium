<!-- agent-workflow:start -->
**Outcome:**
An unattended Codex Relay wake can execute explicitly requested Relay send, reply, and ACK calls without stopping for unavailable human approval.

**Target:**
Pallium's Codex exact-session wake launcher.

**Scope:**
`app/codex_wake.py`, `tests/test_codex_wake.py`, and this Work Record only.

**Constraints:**
Keep the existing workspace-write sandbox and narrow `pallium-relay` MCP allowlist; do not bypass sandboxing or approvals globally.

**Completion criteria:**
Both cold-resume and active-queue wake commands route approval requests through Codex automatic review, while retaining the dedicated Relay profile and hidden-process behavior.

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
Redline classified `app/codex_wake.py` gray/watch and tests blue. The change affects unattended approval handling but remains limited to the Relay wake commands.

**Discovery:**
Codex CLI 0.149.1 exposes `--approve-for-me` on `codex exec` and `codex queue`. The installed `pallium-relay` profile narrows enabled MCP tools and marks them approved, but the live wake still reported that Relay send was blocked by the no-approval policy, showing the unattended invocation lacks an approval reviewer.

**Material assumptions:**
- `--approve-for-me` on the outer `codex exec` invocation applies to `exec resume`; disprove with CLI rejection or live policy block, then stop and reassess.
- `codex queue --approve-for-me` carries automatic review into the queued turn; disprove with the same live block, then stop and reassess.

**Plan:**
Add `--approve-for-me` to the existing cold-resume and active-queue argv in `app/codex_wake.py`. Update the two regressions to assert each complete argv, and retain the profile-install regression proving only Relay send/reply/ACK are enabled. Reuse the existing `pallium-relay` profile, workspace-write sandbox, hidden-process helper, and wake prompt; add no new policy layer or bypass flag. Stop if Codex rejects the flag, exposes another MCP tool through the profile, changes sandbox boundaries, or a live Relay reply remains blocked.

**Verification plan:**
- When a cold wake launches, the command shall include the Relay profile and automatic approval review -> exact subprocess argv test.
- When an active-session wake queues, the command shall include the Relay profile and automatic approval review -> exact subprocess argv test.
- When either wake command runs, its profile shall expose only Relay send/reply/ACK and shall not bypass the workspace-write sandbox -> profile regression plus absence of the bypass flag in exact argv tests.
- When the architect sends an explicitly authorized Relay request to an idle developer, the cold-resumed developer shall ACK/reply without manual approval and finalize delivery -> live Pallium round trip and status evidence.
- When the target has an active writer, the queued turn shall ACK/reply without manual approval and finalize delivery -> controlled active-turn live round trip if the target can be held active; otherwise the exact active-writer subprocess regression remains the bounded evidence and the Work Record reports the live limitation.

**Plan review:**
Clean-context review by `/root/relay_approval_plan_review`: APPROVED after full-argv, bounded-profile, and both-path verification revisions.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Discovery and elevated-risk classification complete. No code edits have begun. Initial clean-context findings tightened full-argv, allowlist/sandbox, and both-path verification.

## Evidence

Pending.

## Plan review

Initial review: CHANGES REQUIRED. The reviewer requested full argv assertions, bounded profile/sandbox proof, and separate cold/active evidence. Revised review: APPROVED; all findings are reflected in the plan and stop conditions.

## Result review

Pending.

