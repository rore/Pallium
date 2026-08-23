# Fail visibly on unknown container search

Branch: `codex/fail-visible-unknown-container-search`

<!-- agent-workflow:start -->
**Outcome:**
Agent history search distinguishes an invalid container identifier from a valid container with no matching memories.

**Target:**
Pallium repository.

**Scope:**
Agent-facing MCP historical search validation, Pallium memory skill guidance for Claude and Codex, and end-to-end tests.

**Constraints:**
Do not change authorization semantics, expose container contents, alter the public `/query` contract, or add a second canonicalization implementation. Reuse an existing read surface; return to planning if none exists.

**Completion criteria:**
An unknown container produces a compact machine-readable `container_not_found` result; a known container with no matches still returns an ordinary empty result; the exact injected `container_ref` is required by both integration skills; HTTP/MCP E2E coverage proves both branches without cross-container leakage.

**Risk:**
Routine

**Complexity:**
Moderate

**Reason:**
Clean-context redline review classifies the intended app/MCP, integration-skill, and test-only path as watch/blue with no checkpoint. Moderate complexity covers shared validation, two packaged integrations, and E2E behavior.

**Discovery:**
Pending focused inspection. Observed incident: guessed container identifiers returned the same empty result as a valid scope with no matches; using the injected canonical `git:github.com/rore/pallium` immediately returned useful history.

**Material assumptions:**
An existing read-only container listing/existence surface can validate scope from the MCP layer without changing `/query`; disprove by tracing the MCP client/server and API routes, then return to planning and reclassify before any guarded edit.

**Plan:**
Pending discovery and review.

**Verification plan:**
Pending discovery and review.

**Plan review:**
Pending.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Established context and clean-context redline classification before code inspection. Intended implementation remains app/MCP-only unless discovery disproves the reusable-read-surface assumption.

## Evidence

Pending.

## Result review

Pending.
