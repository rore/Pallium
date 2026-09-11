<!-- agent-workflow:start -->
**Outcome:** Relay agents can detect the resolved destination of every send, never receive delivery claim tokens through normal Relay responses, and are explicitly guided not to reuse unverified exact endpoint IDs across workspaces.

**Target:** Pallium Relay MCP integration.

**Scope:** `app/mcp/server.py`, Relay MCP/E2E tests, `docs/agent-relay.md`, `roadmap/ideas/idea-exact-relay-recipient-resolution.md`, and the three repository-owned Pallium integration skill copies.

**Constraints:** Preserve intentional cross-container Relay routing, selector compatibility, response budgets, redaction, and existing HTTP contracts; do not add dependencies or change persistence.

**Completion criteria:** Relay send and reply responses never expose claim tokens; long responses expose canonical endpoint identity plus bounded resolved destination metadata; maximal/escaped identity fields remain within budget with explicit omission/truncation markers; guidance requires current discovery/alias use for role recipients and describes destination identity as an admission snapshot; short responses otherwise remain compatible and preserve receipts without mutating caller data; related roadmap wording matches service-global routing; all affected and full tests pass.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** `app/mcp/server.py` is a gray/watch runtime surface under agent-redline; tests/docs are blue. One shared formatter and mirrored guidance make this a coherent single-session change.

**Discovery:** Incident `relay-msg-99a547d886e2482bbc8a7da265cbfb7c` used a historically remembered canonical endpoint and was correctly routed cross-container to `git:github.com/rore/dictation-app`. The HTTP/store response already contained resolved delivery identity, but `_relay_text` discarded it when compacting a long payload, leaving only counts/states. Current guidance calls endpoint IDs canonical without requiring revalidation. Cross-container exact routing is intentional and covered by `tests/test_cross_container_relay_e2e.py`.

**Material assumptions:** Compact resolved-delivery metadata plus safer selector guidance is the smallest sufficient routing contract. Architect follow-up confirmed that filtering claim tokens from every successful MCP response belongs in this shared formatter and remains Elevated/Simple; shallow copies must preserve receipts and caller data. An expected-container guard remains unnecessary without an explicit mismatch-rejection requirement; if that appears, return to planning and reclassify for atomic API/schema admission scope.

**Plan:** Shallow-copy successful Relay responses and delivery dictionaries, remove only `claim_token` before the short-response size check, and preserve receipts/caller data. Preserve compact response budgeting with an allowlisted per-delivery projection that prioritizes message ID and canonical endpoint identity, retains bounded runtime/session/container/state/health fields when they fit, and explicitly marks omitted or truncated descriptive fields. Add caller-surface MCP coverage for long cross-container send/reply behavior and the claimed-reply idempotent retry lifecycle; add focused formatter unit coverage. Update mirrored skills/docs and correct stale roadmap wording. Do not alter routing, persistence, claim semantics, or HTTP/API contracts.

**Verification plan:** Long cross-container MCP send/reply shall expose bounded admission-snapshot destination identity without claim tokens → focused MCP E2E test. Short claimed-reply retry shall return the same message without a claim token while preserving receipt, ACK usability, and single-reply idempotence → MCP lifecycle E2E test. Formatter shall not mutate caller data, shall prioritize canonical identity, and shall keep maximal/escaped output within 2,000 characters with omission markers → formatter unit tests. Existing error/send/receive behavior shall remain compatible → affected MCP and cross-container tests. Mirrored guidance shall remain identical and within budget → guidance-budget tests. Final regression → `python -m pytest tests/ -x -q`, workflow/redline checks, PR CI, and independent result review.

**Plan review:** Revised and accepted after clean-context Astra architectural review `/root/relay_scope_architect` on 2026-09-12; no pre-admission guard required. Follow-up review approved same-formatter claim-token sanitization as Elevated/Simple with no new checkpoint. Persisted `@pall-arc` requests remain queued because its task is busy.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Established the incident from persisted Relay metadata and traced exact-selector resolution through storage, HTTP, MCP client, and MCP response compaction. No product code edited; awaiting architect validation.
- Architect review classified the incident as caller misuse plus a product observability defect. It retained the formatter/guidance scope, rejected a new expected-container guard for this requirement, and added explicit overflow, reply, boundary, token-exclusion, and roadmap-drift coverage before implementation.
- Implementation touched `app/mcp/server.py`, `tests/test_mcp_server_utils.py`, `tests/test_relay_mcp_tools.py`, `tests/test_guidance_budget.py`, `docs/agent-relay.md`, `roadmap/ideas/idea-exact-relay-recipient-resolution.md`, and the three mirrored integration skills. The compact response now allowlists delivery identity, drops only oversized selector/session/container descriptions with explicit markers, prioritizes metadata before redacted payload preview, and never exposes claim tokens. The normal patch helper failed with Windows error 1327, so edits used deterministic replacements limited to these named files.
- Skill-feedback trigger 2/7 dropped: the missing recipient-validation guidance is owned by Pallium, not the supported agent-workflow upstream, and is fixed in this task.
- Result review found and blocked an over-broad stale-delivery phrase introduced while compressing guidance. Restored the exact `already_delivered=true` trigger and added a contract assertion; normal delivered hook work remains actionable.
- Result review then identified a pre-existing short-response path that can expose a non-null delivery claim token on an idempotent reply retry after claim. Paused before PR and returned to planning because the user requires discovered Relay defects to be fixed; awaiting architect scope/risk decision.
- Architect follow-up approved including the same-formatter credential fix in this PR at Elevated/Simple: copy response/deliveries, remove only `claim_token`, preserve receipt and caller data, and cover claim → retry → ACK without duplicate reply.
- Implemented claim-token sanitization before the short-response size check using shallow response/delivery copies. Unit coverage proves caller data and receipts are preserved; the caller-surface lifecycle proves claimed idempotent retry returns the same message, exposes no token, and remains ACKable. Affected Relay/MCP subsystem verification: 183 passed.

## Evidence

- Persisted delivery metadata resolves the mistaken endpoint to `git:github.com/rore/dictation-app`; current `@pall-arc` resolves to `git:github.com/rore/pallium`.
- `_relay_text` in `app/mcp/server.py` removes all resolved delivery identity when a long send exceeds the MCP response budget.
- Focused formatter, cross-container send/reply, escaped-boundary, idempotence, redaction, and guidance tests: 17 passed.
- Full regression on final code revision `da421397`: 4,864 passed, 33 skipped, 2 xfailed in 209.47 seconds.

## Plan review

Clean-context Astra review `/root/relay_scope_architect`: REVISE then proceed within the existing implementation boundary; preserve canonical identity under overflow, cover send/reply boundaries, clarify admission-snapshot semantics, and correct stale roadmap wording. Persisted architect messages `relay-msg-06b03e064992409a8d5a765fab34b511` and `relay-msg-f221d067cb48430284877712d9912619` remain queued for continuity.

## Result review

Pending.
