# Fail visibly on unknown container search

Branch: `codex/fail-visible-unknown-container-search`

<!-- agent-workflow:start -->
**Outcome:**
Agent history search makes a wrongly supplied container visible and tells the caller to use the exact injected identifier instead of silently resembling a retrieval miss.

**Target:**
Pallium repository.

**Scope:**
Agent-facing MCP historical-search result/tool guidance, Pallium memory skill guidance for Claude and Codex, and end-to-end tests.

**Constraints:**
Do not change authorization semantics, expose or enumerate containers, alter the public /query contract, add a container registry, or add a second canonicalization implementation. Empty responses must remain compact.

**Completion criteria:**
An empty historical search echoes the requested container and gives a compact exact-ID hint; non-empty results do not pay that token cost; both integration skills and the MCP tool contract require copying the injected container_ref unchanged and never deriving or guessing it; E2E coverage proves the behavior without cross-container leakage.

**Risk:**
Routine

**Complexity:**
Moderate

**Reason:**
Clean-context redline review classifies the intended app/MCP, integration-skill, and test-only path as watch/blue with no checkpoint. Moderate complexity covers shared validation, two packaged integrations, and E2E behavior.

**Discovery:**
Observed incident: guessed container identifiers returned the same empty result as a valid scope with no matches; using the injected canonical git:github.com/rore/pallium immediately returned useful history. Trace: MCP server → client POST /query → API/service/query executor. No REST/MCP surface or generic storage helper defines container existence; containers are implicit and may become valid on first ingest. /dashboard/api/containers is SQLite/dashboard-only and lists derived-memory containers, so it is not a valid raw-history preflight.

**Material assumptions:**
DISPROVED: no authoritative container-existence surface exists, and adding one would invent registry semantics plus an API contract. Revised assumption: echoing the supplied scope and strengthening exact-ID instructions prevents/diagnoses the observed agent error without claiming the container is invalid; disprove if the MCP empty-result budget cannot hold the compact hint, then shorten wording rather than widening scope.

**Plan:**
Reuse _compact_history in app/mcp/server.py: accept the resolved container, and only when a source-only result is empty add requested_container_ref plus a short instruction to copy the injected identifier exactly. Strengthen the search tool docstring and both packaged Pallium skills with never derive, guess, or normalize. Extend compact MCP tests for empty/non-empty token behavior and the existing public MCP-to-HTTP lifecycle for wrong-scope isolation. Do not touch API/core/storage. Update this record, run focused integration tests, restart, refresh integrations, and close via PR. Stop if the 300-character empty-result budget cannot be preserved.

**Verification plan:**
Empty search shall expose requested scope and exact-ID hint within 300 chars → compact-history + MCP tool tests. Non-empty search shall omit the hint → regression test. Packaged Claude/Codex skills shall carry identical exact-ID guidance → integration tests/hash parity. Existing visibility/canonicalization contracts shall remain green → focused history/MCP/container tests and CI. Installed integrations and service shall match merged code → setup refresh, restart, live health/search check.

**Plan review:**
self — minimal app/MCP-only correction; no truthful container-not-found state exists without a new registry/API contract, which is intentionally skipped.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Established context and clean-context redline classification before code inspection. Intended implementation remains app/MCP-only unless discovery disproves the reusable-read-surface assumption.
- Discovery disproved container-existence preflight. Returned to planning and narrowed the fix to exact-ID prevention plus compact empty-result diagnostics; Risk remains Routine because API/core/storage stay untouched.
- The compact-history response now echoes a bounded requested container and exact-ID hint only for empty source-only searches. Successful results, errors, and fail-closed visibility responses retain their prior compact shape.
- Claude and Codex packaged guidance now requires copying the injected container_ref unchanged and never deriving, guessing, or normalizing it.
- Added compact boundary tests and extended the existing public MCP-to-real-HTTP lifecycle to prove a matching item in the canonical container does not leak into a guessed container.
- apply_patch failed once with machine-local Windows error 1385; the test and record edits used narrowly scoped deterministic IO.File replacements as required.

## Evidence

- Focused public-path suite: 78 passed across MCP integration/server, history client, guidance budget, and Claude/Codex integration tests.
- Compact tests cover empty normal/max/over-max scope, successful-result omission, error/fail-closed omission, and the 300-character ceiling.
- Public lifecycle seeds matching history in the canonical container, calls the FastMCP tool through the real /query ASGI route with the guessed container, and asserts zero cross-container results plus the echoed scope/hint.
- git diff --check passed (line-ending notices only); workflow checker returned clean.
- Local service health after restart: status=ok, embedding_provider_ok=true; packaged Claude/Codex integrations were refreshed successfully.
- The Codex task's already-open MCP connection still returned the pre-change shape, as expected for a process held open by the client; fresh server instances are covered by the public lifecycle test and installed guidance takes effect for new tasks.

## Result review

APPROVE — clean-context review confirmed the dependency lock is clean, the public MCP-to-ASGI wrong-scope lifecycle proves zero leakage plus the compact diagnostic, the Work Record is accurate, and focused tests/workflow gates pass.
