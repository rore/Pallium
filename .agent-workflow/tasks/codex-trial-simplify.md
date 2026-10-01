# Codex trial simplification

<!-- agent-workflow:start -->
**Outcome:** The finite Codex trial path has less duplicated and write-only code while every caller-visible admission, metadata validation, fail-closed dispatch, and durable fence behavior remains unchanged.

**Target:** Pallium Codex bridge, MCP bridge entrypoints, Relay boundary, and one private operator plan.

**Scope:** Remove write-only `owner_tool_after` from `app/codex_bridge_pipe.py`; share the existing shadow/inventory runtime caller-metadata validator in `app/mcp/server.py`; reuse `_codex_trial_endpoint` in two `core/relay.py` methods; inline the one-use trial suppression helper in `app/dependencies.py` only if it is clearer. Root separately consolidates the ignored private `build/live-inventory-operator-plan.md` and its preserved historical copy under `build/` without publishing it.

**Constraints:** Preserve exact invalid/conflicting metadata behavior, positive before-descriptor and post-exit inventory, source/target separation, native dispatch suppression, SQLite fence semantics, all fixed public outcomes, and privacy. No service, live gate, delivery, configuration, protected behavior contract, or schema change. Root owns publication, merge, install, and private operator edits.

**Completion criteria:** Existing MCP and private bridge caller tests show equivalent valid and invalid outcomes; one-use helper/validator code is shorter; selected application checks pass once; independent review finds no behavior relaxation; root's private plan has one current live-source sequence with historical commands retained.

**Requirement baseline:** {"source":"user source item dc52fe68-8c3a-46b4-a6ec-4b2362f552a9 plus root task","outcome":"The finite Codex trial path has less duplicated and write-only code while every caller-visible admission, metadata validation, fail-closed dispatch, and durable fence behavior remains unchanged.","scope":"Remove write-only owner_tool_after; share shadow/inventory metadata validation; reuse endpoint validator; optionally inline single-use suppression helper; root consolidates ignored private operator plan.","constraints":"No behavior relaxation, service/live actions, configuration/schema/protected-contract changes, or worker publication.","completion_criteria":"Equivalent caller outcomes, shorter source, focused and selected validation, independent review, private plan consolidation."}

**Risk:** High

**Complexity:** Moderate

**Reason:** `app/mcp/server.py` is an API contract red zone and `core/relay.py` is an architecture red zone; the change spans runtime, API, and Relay boundary code. Metadata validation and native suppression are security-sensitive even though this is intended as behavior-preserving cleanup.

**Discovery:** The shadow and inventory tools repeat the same `resolve_codex_thread_ref` and turn metadata checks at `app/mcp/server.py:1127-1145,1168-1184`. `owner_tool_after` is assigned but never read. `core/relay.py:119-130` repeats its own endpoint validator. `app/dependencies.py:633-641` has one helper caller. Existing tests in `tests/test_codex_mcp_desktop_bridge.py` and `tests/test_codex_bridge_pipe.py` exercise the caller paths. No configured behavior-contract path is in scope.

**Material assumptions:** Existing metadata rejection/public-result behavior can be preserved by extracting only the shared parser, with each tool retaining its current fallback reason. A caller-visible mismatch or changed exception mapping stops this cleanup. The private operator plan is ignored and root-owned; source edits do not depend on its contents.

**Plan:** First obtain independent technical review of this narrow cleanup. Extract a private helper returning the validated `(thread_ref, turn_ref)` pair or an invalid result; keep shadow and inventory exception/public-result handling in their callers. Delete write-only after-descriptor state without changing `_observe` or before-descriptor validation. Reuse `_codex_trial_endpoint` for the two repeated validation blocks. Inline the fail-closed suppression wrapper only if the locked dispatch remains clearer. Keep root's private operator consolidation out of published source. Stop on any changed caller-visible rejection, extra native action, or altered fail-closed branch.

**Verification plan:** When valid or malformed current-caller metadata reaches each MCP tool, it shall yield the same request or denial as before → focused `tests/test_codex_mcp_desktop_bridge.py` cases and exact invalid/conflict variants. When before/after inventory and trial dispatch run, they shall preserve existing public outcomes and at most one owner action → focused `tests/test_codex_bridge_pipe.py` and Relay wake tests. When the diff is coherent, run affected files and `scripts/test-plan.py --base origin/main` selected checks once; independent reviewer assesses exact diff and test adequacy.

**Plan review:** Pending independent technical review.

**Approvals:** Approved by user 2026-10-01 (source item dc52fe68-8c3a-46b4-a6ec-4b2362f552a9): "in general, let's simplify when we can"; direct follow-up: "are you doing this?" Root confirmed this authorizes the exact behavior-preserving cleanup.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Classified before source edits. Waiting for independent plan review. Branch `feat/codex-trial-simplify` starts at `18261b24035d20e963c9f1319bcafeb1b3feb996` in the isolated managed checkout.

## Evidence

No tests run or production changes made yet.

## Result review

Pending implementation.
