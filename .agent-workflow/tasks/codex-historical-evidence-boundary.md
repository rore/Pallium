<!-- agent-workflow:start -->
**Outcome:**
Agents receiving historical search results are explicitly warned not to treat past workflow text as proof of live state or completed actions.

**Target:**
Pallium MCP historical-search response packaging.

**Scope:**
`app/mcp/server.py`, focused history-presentation and caller-level MCP tests, and the existing private real-corpus evaluator for verification only.

**Constraints:**
Keep the existing 2,000-character response budget, public tool signature, ranking, retrieval, telemetry, and default result count unchanged. Do not publish private corpus text or provider details.

**Completion criteria:**
Every non-empty `pallium_search_history` response retains a concise warning that recalled workflow text is past evidence and requires live verification before claiming current messages, tool state, approvals, or completed actions; caller-level E2E covers oversized Unicode results, and a capped focused replay prevents the two observed false-live-state answers without losing useful controls.

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
Agent-redline classified `app/mcp/server.py` GRAY + WATCH because this changes a caller-visible MCP response contract; tests are BLUE and no boundary violation or special checkpoint applies.

**Discovery:**
`_compact_history` already emits `historical_reminder`, but its text only says current-state questions may need verification and budget trimming deletes it before optional per-hit cues. The two harmful private cases treated old workflow text as proof of current receipt/action. The tool description also lacks this explicit boundary. Existing direct and `server.call_tool` tests cover compact history, Unicode, and the 2,000-character limit.

**Material assumptions:**
- Strengthening and preserving the existing response reminder, plus matching tool-description wording, is sufficient. If the focused replay still makes either false live-state claim, return to planning before changing integration instructions or retrieval.
- The observed defect is in search-result packaging, not source expansion. If discovery or replay shows an expansion-caused false claim, expand scope and repeat risk/plan review.

**Plan:**
Reuse the existing `historical_reminder` field: make its wording explicit, keep it through budget trimming, and update the `pallium_search_history` tool description. Add the smallest direct budget test and caller-level MCP test that assert the warning survives oversized Unicode results while the response remains bounded. Run focused tests, then an eight-call/no-judge private replay of the two harmful cases plus two useful controls. Stop and return to planning if the payload cannot remain bounded or either harmful claim persists.

**Verification plan:**
- Non-empty normal and oversized history responses retain the explicit live-state/action boundary within 2,000 characters → direct `_compact_history` tests plus `server.call_tool("pallium_search_history")` caller-level E2E with Unicode/over-budget input.
- Public signature, result count, ranking, and telemetry remain unchanged → existing MCP server, history presentation, delivery receipt, and MCP integration suites.
- The boundary changes downstream behavior without destroying useful history → private four-case paired replay, no automatic judge, maximum eight answer calls and 5,000 estimated input tokens, followed by primary-agent review.

**Plan review:**
Pending clean-context Elevated-risk review.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Discovery complete: the existing reminder is too weak and is the first field dropped under response pressure; no retrieval or ranking change is needed.

## Evidence

Pending.

## Result review

Pending.
