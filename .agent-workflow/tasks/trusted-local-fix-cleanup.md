<!-- agent-workflow:start -->
**Outcome:**
Raw-turn forgetting matches Pallium's actual trusted-local, unauthenticated product boundary: no caller-supplied pseudo-authorization or misleading multi-user switch remains. Source-context visibility filtering remains intact and both changed public MCP surfaces have end-to-end regression coverage.

**Target:**
Pallium repository: raw-source forgetting and source-context expansion contracts.

**Scope:**
- Remove the authorization-only changes introduced by `30588f1` from API, MCP, app configuration/startup, core service/errors, storage, and its authorization-specific tests/docs.
- Preserve soft-delete, idempotence, audit fields, missing-entity behavior, and all source-context visibility behavior from `45900c4`.
- Correct current docs/roadmap statements that imply an authorization boundary.
- Add the smallest public-surface MCP regression coverage and supported-memory visibility coverage missing from the two recent fixes.

**Constraints:**
- Pallium has no authorization layer and none is being added.
- The service is explicitly trusted-local and must not be presented as safe for untrusted or multi-user exposure.
- No schema migration, dependency, generic visibility-policy change, or unrelated cleanup.
- One repair PR; targeted local tests; one full CI/review cycle.

**Completion criteria:**
- Raw-turn forget requires no caller identity or workspace field through HTTP or MCP and retains its prior lifecycle contract (create -> forget -> excluded from retrieval/context -> successful-mutation audit, including repeat and missing-target behavior).
- No `single_user_trusted_mode`, forget authorization error, caller-scope parameter, storage authorization predicate, or loopback compensating guard remains in live code.
- Source-context expansion still rejects invisible anchors, filters invisible neighbors and supported memories, and fails closed on invalid visibility through the caller-facing surface.
- Product/architecture docs say trusted-local and do not claim denied attempts are audited when they are not.
- Targeted tests, redline, workflow checks, PR CI, and review threads are green before merge.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Redline classifies `core/service.py` plus API schemas/routes as red contract/security surfaces, with architecture-review and api-review checkpoints. The implementation is mostly deletion but crosses several runtime layers.

**Discovery:**
- `30588f1` added 914 lines across 13 files: caller-supplied container scope, a default-on compatibility flag, storage predicates, a special bind guard, MCP/HTTP error mapping, docs, and 390 authorization-specific test lines.
- The supplied scope is not authenticated, so neither mode is an authorization boundary; retaining it conflicts with the decided trusted-local product model.
- `45900c4` is orthogonal retrieval correctness and must remain.
- Existing raw-turn lifecycle tests already cover the underlying forget contract; existing MCP tests use `server.call_tool`, and existing source-context tests cover anchor/neighbor visibility. Reuse those patterns instead of creating a new harness.

**Material assumptions:**
- ASSUMPTION: every live pseudo-authorization change is attributable to `30588f1`. DISPROVED BY: a current caller or doc independently relies on the setting/field. ACTION: stop and return to planning before deleting that dependency.
- ASSUMPTION: reversing the authorization-only commit does not alter `45900c4`. DISPROVED BY: diff or focused tests show source-context visibility removal/regression. ACTION: restore the visibility change and narrow the patch.
- ASSUMPTION: existing lifecycle tests cover all unchanged forget edge cases. DISPROVED BY: the public MCP surface lacks a regression that would catch reintroduced caller-scope requirements. ACTION: add only the missing public-surface test cases.

**Plan:**
1. Record and review this High-risk plan before guarded edits.
2. Selectively remove only the authorization changes: `caller_container_ref` from `api/schemas.py`, `api/routes.py`, and `app/mcp/client.py`; `ForgetAuthorizationError` and HTTP/MCP mapping; `single_user_trusted_mode` config/dependency/service wiring; `_resolve_forget_scope`; storage `expected_container_ref` parameters/predicates; the special loopback guard; and only the authorization-specific test. Retain the historical authorization Work Record.
3. Preserve every `45900c4` hunk in `api/routes.py`, `core/service.py`, and `app/mcp/client.py`, including route/MCP `query_visibility` threading and all three `is_visible` `query_visibility` calls; correct drift in `docs/context/decisions.md`, `roadmap/board.md`, `roadmap/ideas/fix-source-forget-scope-authorization.md`, and `roadmap/ideas/idea-authenticated-principal-for-mutation-authz.md`.
4. Reuse established MCP and source-context test patterns for the minimal missing regressions; do not duplicate already-covered lifecycle matrices.
5. Run focused tests, redline, and workflow checks; then push one PR, address every CI/review finding, satisfy required labels/checkpoints, and merge only when green.
Stop and return to planning if the reversal touches generic visibility policy, persistence schema, or requires an authentication design.

**Verification plan:**
- When a caller forgets one turn or a container through HTTP/MCP without identity, the service shall preserve the trusted-local lifecycle contract -> existing raw-turn E2E plus MCP tool regression.
- When source context is requested with public visibility, the service shall exclude private anchors/neighbors/supported memories -> focused source-context HTTP/service tests plus MCP tool regression.
- When old pseudo-auth names are searched, live code shall contain none -> repository `rg` check.
- When the final diff is classified, it shall have no boundary violation and required API/architecture checkpoints shall be satisfied -> redline artifact, workflow checker, PR labels/review.

**Plan review:**
Clean-context review completed in ## Plan review; five blocking clarifications incorporated before implementation.

**Approvals:**
Approved by user 2026-08-17: "ok, go"

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Discovery and pre-edit redline classification complete. Clean-context review complete; no guarded code edits made. Selective removal is required due to overlap with the preserved `45900c4` visibility changes.
- Trigger 3 apply_patch 1385 did not pass the actionability filter (environment/tool flake).
- Skill feedback issue filed: https://github.com/rore/agent-workflow/issues/9

- Completed selective live-code deletion of pseudo-authorization; preserved all 45900c4 query_visibility behavior. Updated the named docs/roadmap files and added minimal MCP lifecycle/tool and supported-memory visibility coverage.

## Plan review

Reviewer verdict: plan approved after five clarifications: successful-mutation audit wording; explicit selective removal list; preservation of every `45900c4` visibility hunk; named documentation/roadmap targets; and retention of the historical authorization Work Record.

## Evidence

- Focused pytest raw/MCP/source-context: 33 passed, 2 skipped (optional mcp unavailable locally).
- Config/app-run isolated from local config: 35 passed.
- py_compile of the three changed tests passed.
- rg old-symbol search returned no matches.
- Import boundary gate passed.
- Redline reported no boundary violations; architecture/API checkpoints satisfied with planned labels.
- git diff --check passed.
## Result review

Pending.
