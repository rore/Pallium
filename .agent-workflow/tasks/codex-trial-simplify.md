# Codex trial simplification

<!-- agent-workflow:start -->
**Outcome:** The finite Codex trial path has less duplicated and write-only code while every caller-visible admission, metadata validation, fail-closed dispatch, and durable fence behavior remains unchanged.

**Target:** Pallium Codex bridge, MCP bridge entrypoints, Relay boundary, and one private operator plan.

**Scope:** Remove write-only owner_tool_after; share shadow/inventory metadata validation; reuse endpoint validator; optionally inline single-use suppression helper; root consolidates ignored private operator plan.

**Constraints:** No behavior relaxation, service/live actions, configuration/schema/protected-contract changes, or worker publication.

**Completion criteria:** Equivalent caller outcomes, shorter source, focused and selected validation, independent review, private plan consolidation.

**Requirement baseline:** {"source":"user source item dc52fe68-8c3a-46b4-a6ec-4b2362f552a9 plus root task","outcome":"The finite Codex trial path has less duplicated and write-only code while every caller-visible admission, metadata validation, fail-closed dispatch, and durable fence behavior remains unchanged.","scope":"Remove write-only owner_tool_after; share shadow/inventory metadata validation; reuse endpoint validator; optionally inline single-use suppression helper; root consolidates ignored private operator plan.","constraints":"No behavior relaxation, service/live actions, configuration/schema/protected-contract changes, or worker publication.","completion_criteria":"Equivalent caller outcomes, shorter source, focused and selected validation, independent review, private plan consolidation."}

**Risk:** High

**Complexity:** Moderate

**Reason:** `app/mcp/server.py` is an API contract red zone and `core/relay.py` is an architecture red zone; the change spans runtime, API, and Relay boundary code. Metadata validation and native suppression are security-sensitive even though this is intended as behavior-preserving cleanup.

**Discovery:** The shadow and inventory tools repeat the same `resolve_codex_thread_ref` and turn metadata checks at `app/mcp/server.py:1127-1145,1168-1184`. `owner_tool_after` is assigned but never read. `core/relay.py:119-130` repeats its own endpoint validator. `app/dependencies.py:633-641` has one helper caller. Existing tests in `tests/test_codex_mcp_desktop_bridge.py` and `tests/test_codex_bridge_pipe.py` exercise the caller paths. No configured behavior-contract path is in scope.

**Material assumptions:** Existing metadata rejection/public-result behavior can be preserved by extracting only the shared parser, with each tool retaining its current fallback reason. A caller-visible mismatch or changed exception mapping stops this cleanup. The private operator plan is ignored and root-owned; source edits do not depend on its contents.

**Plan:** Extract a private helper returning the validated `(thread_ref, turn_ref)` pair or an invalid result; keep shadow and inventory exception/public-result handling in their callers, including exceptions from metadata extraction. Delete write-only after-descriptor state without changing `_observe` or before-descriptor validation. Reuse `_codex_trial_endpoint` for the two repeated validation blocks. Keep the single-use fail-closed suppression helper: its explicit boundary is clearer than inlining it. Keep root's private operator consolidation out of published source. Stop on any changed caller-visible rejection, extra native action, or altered fail-closed branch.

**Verification plan:** When valid or malformed current-caller metadata reaches each MCP tool, it shall yield the same request or denial as before → focused `tests/test_codex_mcp_desktop_bridge.py` cases and exact invalid/conflict variants. When before/after inventory and trial dispatch run, they shall preserve existing public outcomes and at most one owner action → focused `tests/test_codex_bridge_pipe.py` and Relay wake tests. When the diff is coherent, run affected files and `scripts/test-plan.py --base origin/main` selected checks once; independent reviewer assesses exact diff and test adequacy.

**Plan review:** Agent technical review: `/root/service_handoff_security` GO on 2026-10-01 after reading this Work Record and the named source; preserve each caller's exception mapping and retain the explicit fail-closed suppression helper. No blocking finding.

**Approvals:** Approved by user 2026-10-01 (source item dc52fe68-8c3a-46b4-a6ec-4b2362f552a9): "in general, let's simplify when we can"; direct follow-up: "are you doing this?" Root confirmed this authorizes the exact behavior-preserving cleanup.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Classified before source edits. Independent plan review accepted the three required cuts and rejected the optional suppression-helper inline as a poor clarity trade-off. Branch `feat/codex-trial-simplify` starts at `18261b24035d20e963c9f1319bcafeb1b3feb996` in the isolated managed checkout.

Implemented the shared caller pair parser with each MCP tool's original fallback result and exception mapping intact. Removed write-only after-descriptor state and calculation while preserving general inventory validation and before-descriptor admission. Reused the Relay endpoint validator in two public boundary methods. Added one existing caller test assertion for the distinct missing-metadata exception result. Root independently consolidated the ignored private operator plan from 282 to 163 lines, retained an exact historical copy and all B1/B2/CAS cleanup commands, and received security review acceptance; these private files are outside the published diff. Root parsed its three Python blocks and one PowerShell block without executing them.

## Evidence

Focused MCP protocol cases: 25 passed. Focused non-slow Relay trial/fence cases: 6 passed. Focused slow post-exit/owner-action cases: 23 passed and one Windows `PermissionError` reading a just-created outcome file after its existence predicate; exact `--lf --lfnf=none` passed (1). Cause of the first-pass read failure is unclassified; no production path for that outcome-file reader changed. `scripts/test-plan.py --base origin/main` selected full non-slow (`python -m pytest tests/ -x -q`). Affected MCP/Relay/SQLite files: 304 passed. Affected slow native-bridge file: 258 passed. The selected full non-slow suite passed once: 5809 passed, 34 skipped, 2 xfailed in 334.96 seconds under an isolated subprocess `USERPROFILE`. Source commit `ac65ada8f704c8c7ad8bfe0bc639dfde4dd7cdd9` removes 13 net production lines; one tighter protocol assertion yields 11 net code/test lines removed.

## Result review

Agent technical review: `/root/service_handoff_security` final ACCEPT; the reviewed refactor preserves metadata extraction, invalid/conflict and exception/public outcomes, post-exit inventory validation, endpoint rejection, and unchanged fail-closed dispatch.
Reviewed revision: `0d07faf4f44eb404fba464f8b32af41023bf08da` (source/test commit `ac65ada8f704c8c7ad8bfe0bc639dfde4dd7cdd9`).
Verification adequacy: exact MCP invalid/conflict and missing-metadata outputs, affected native inventory/Relay trials, and the full selected lane cover the equivalent behavior claim. The one first-pass outcome-file `PermissionError` remains unclassified and passed exact rerun; it is not evidence of a production fix.
