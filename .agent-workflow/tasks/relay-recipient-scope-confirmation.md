<!-- agent-workflow:start -->
**Outcome:** Relay agents can detect the resolved destination of every send and are explicitly guided not to reuse unverified exact endpoint IDs across workspaces.

**Target:** Pallium Relay MCP integration.

**Scope:** `app/mcp/server.py`, Relay MCP/E2E tests, `docs/agent-relay.md`, `roadmap/ideas/idea-exact-relay-recipient-resolution.md`, and the three repository-owned Pallium integration skill copies.

**Constraints:** Preserve intentional cross-container Relay routing, selector compatibility, response budgets, redaction, and existing HTTP contracts; do not add dependencies or change persistence.

**Completion criteria:** Long Relay send and reply responses expose canonical endpoint identity plus bounded resolved destination metadata without claim tokens; maximal/escaped identity fields remain within budget with explicit omission/truncation markers; guidance requires current discovery/alias use for role recipients and describes destination identity as an admission snapshot; short and error responses remain compatible; related roadmap wording matches service-global routing; all affected and full tests pass.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** `app/mcp/server.py` is a gray/watch runtime surface under agent-redline; tests/docs are blue. One shared formatter and mirrored guidance make this a coherent single-session change.

**Discovery:** Incident `relay-msg-99a547d886e2482bbc8a7da265cbfb7c` used a historically remembered canonical endpoint and was correctly routed cross-container to `git:github.com/rore/dictation-app`. The HTTP/store response already contained resolved delivery identity, but `_relay_text` discarded it when compacting a long payload, leaving only counts/states. Current guidance calls endpoint IDs canonical without requiring revalidation. Cross-container exact routing is intentional and covered by `tests/test_cross_container_relay_e2e.py`.

**Material assumptions:** Compact resolved-delivery metadata plus safer selector guidance is the smallest sufficient contract. Architect review confirmed that an expected-container guard is unnecessary without an explicit mismatch-rejection requirement; if that requirement appears, return to planning and reclassify for atomic API/schema admission scope before editing.

**Plan:** Preserve compact response budgeting while adding an allowlisted per-delivery projection that prioritizes message ID and canonical endpoint identity, retains bounded runtime/session/container/state/health fields when they fit, and explicitly marks omitted or truncated descriptive fields. Add caller-surface MCP coverage for long cross-container send and reply behavior, redacted and non-redacted payloads, maximal/escaped identities, idempotent reply, budget, and claim-token exclusion; add focused formatter unit coverage. Update consistent guidance across Codex/Claude/OpenCode skills and Relay docs, and correct the related roadmap's stale actor-scoped wording. Do not alter routing, persistence, or HTTP/API semantics.

**Verification plan:** Long cross-container MCP send and reply shall expose bounded admission-snapshot destination identity without claim tokens, including redacted/non-redacted and idempotent paths → focused MCP E2E test. Compact formatter shall prioritize canonical identity, safely mark maximal/escaped descriptive-field omission or truncation, and remain within 2,000 characters → formatter unit tests. Existing short/error/send/receive behavior shall remain compatible → affected MCP and cross-container test files. Mirrored guidance shall remain byte-identical and within budget → guidance-budget tests. Final regression → `python -m pytest tests/ -x -q`, workflow checker, redline checker, PR CI and independent result review.

**Plan review:** Revised and accepted after clean-context Astra architectural review `/root/relay_scope_architect` on 2026-09-12; no pre-admission guard required. The persisted `@pall-arc` requests remain queued because its task is busy.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Established the incident from persisted Relay metadata and traced exact-selector resolution through storage, HTTP, MCP client, and MCP response compaction. No product code edited; awaiting architect validation.
- Architect review classified the incident as caller misuse plus a product observability defect. It retained the formatter/guidance scope, rejected a new expected-container guard for this requirement, and added explicit overflow, reply, boundary, token-exclusion, and roadmap-drift coverage before implementation.
- Implementation touched `app/mcp/server.py`, `tests/test_mcp_server_utils.py`, `tests/test_relay_mcp_tools.py`, `tests/test_guidance_budget.py`, `docs/agent-relay.md`, `roadmap/ideas/idea-exact-relay-recipient-resolution.md`, and the three mirrored integration skills. The compact response now allowlists delivery identity, drops only oversized selector/session/container descriptions with explicit markers, prioritizes metadata before redacted payload preview, and never exposes claim tokens. The normal patch helper failed with Windows error 1327, so edits used deterministic replacements limited to these named files.

## Evidence

- Persisted delivery metadata resolves the mistaken endpoint to `git:github.com/rore/dictation-app`; current `@pall-arc` resolves to `git:github.com/rore/pallium`.
- `_relay_text` in `app/mcp/server.py` removes all resolved delivery identity when a long send exceeds the MCP response budget.

## Plan review

Clean-context Astra review `/root/relay_scope_architect`: REVISE then proceed within the existing implementation boundary; preserve canonical identity under overflow, cover send/reply boundaries, clarify admission-snapshot semantics, and correct stale roadmap wording. Persisted architect messages `relay-msg-06b03e064992409a8d5a765fab34b511` and `relay-msg-f221d067cb48430284877712d9912619` remain queued for continuity.

## Result review

Pending.
