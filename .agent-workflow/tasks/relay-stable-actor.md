<!-- agent-workflow:start -->
**Outcome:** Cross-repository Relay sessions can use one explicit integration-owned actor identity instead of changing with each repository's local Git name.

**Target:** Pallium.

**Scope:** Claude Code, Codex, and OpenCode integration actor derivation; focused unit and hook-to-service E2E tests; Relay setup documentation.

**Constraints:** Preserve Python per-session identity pinning and the existing Git/local fallback when `PALLIUM_HOOK_ACTOR_REF` is absent or blank; keep standalone integrations dependency-free; do not change MCP trusted-scope, Relay authorization, or routing.

**Completion criteria:** When `PALLIUM_HOOK_ACTOR_REF` is nonblank, a fresh session in each shipped integration shall use its trimmed value across repositories without invoking Git; a valid cached Python-session actor shall remain pinned on resume; absent/blank configuration shall preserve Git/local fallback; caller-level registration and cross-container delivery tests plus workflow checks shall pass.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Agent-redline classified integration runtime files as gray and tests/docs as blue, with no boundary violation or required policy checkpoint. Moderate complexity reflects three runtime integrations plus real-service lifecycle E2E coverage.

**Discovery:** Live post-merge E2E proved delivery to `dashboard-dev`, broadcast rejection, and actor isolation, but also showed the same human resolves as `Rotem Hermon`, `rore`, or `local` across repositories. Claude Code, Codex, and OpenCode derive actors from repo-local `git config user.name`. Reusing `PALLIUM_ACTOR_REF` is unsafe because stdio MCP requires configured actor and container as a trusted pair; a dedicated integration-only variable avoids changing that security contract.

**Material assumptions:** `PALLIUM_HOOK_ACTOR_REF` is configured consistently before participating hosts start; a cached Python actor remains authoritative for an existing/resumed session, while fresh sessions adopt the configured value. If caller-level tests show the new variable leaks into or conflicts with MCP trusted scope, return to planning.

**Plan:** Add `PALLIUM_HOOK_ACTOR_REF` precedence after valid cache hits and before deadline/Git fallback in both Python hook-common copies, and beneath OpenCode pinned-session lookup but before Git in its existing helper. Reuse current parity/test harnesses for trimmed Unicode override, absent/blank fallback, deadline exhaustion, cache pinning, and cache-write failure. Add caller-level Claude/Codex hook journeys that register different repository containers under one configured actor and prove cross-container delivery. Add an OpenCode public `chat.message` → real service registration/list/send → public message transform/ack → `session.deleted` close journey, reusing the existing Python-to-Node bridge pattern rather than mocked fetch. Document configuration and fresh-session rollout in `docs/agent-relay.md`. Stop if MCP scope behavior changes or integration parity diverges.

**Verification plan:** Nonblank configured identity bypasses Git in all integrations while cached resume stays stable → focused Python parity and OpenCode helper tests. Blank/unset identity preserves Git/local fallback, including deadline/cache-write edges → focused existing identity suites. Real Claude/Codex hooks register one actor across different containers and Relay delivers between them → caller-level hook-to-service E2E. OpenCode public hooks register, receive/ack, reuse the pinned actor, and close against the real service/read paths → Node bridge E2E. Existing routing stays intact → cross-container HTTP/MCP E2E suites. Repository process remains compliant → redline report and agent-workflow checker.

**Plan review:** Accepted by third clean-context Elevated-risk review; see Plan review acceptance below.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Discovery complete: the smallest shared fix is explicit environment precedence before Git in both standalone hook copies; no Relay core, schema, or routing change is needed.
- Plan-review boundary: returned to planning before implementation. Resolve the inherited MCP environment constraint, qualify the cache-precedence contract, and add caller-surface verification before repeating clean-context review.
- Revised-plan boundary: use integration-only `PALLIUM_HOOK_ACTOR_REF`, cover OpenCode, preserve cached-session identity, and prove registration/delivery through real hook surfaces without changing MCP trusted scope.
- Repeated-plan-review boundary: integration-only configuration and cache/deadline ordering are accepted. Remain Blocked until the plan explicitly covers OpenCode public hooks against the real service and session/delivery read paths; the existing mocked-fetch plugin suite does not discharge caller-level E2E coverage.
- OpenCode-E2E revision boundary: require a public hook lifecycle against the real service and observable session/delivery/status read paths, including pinned reuse and close; complexity raised to Moderate.
- Accepted-plan boundary: third clean-context review found the explicit OpenCode real-service lifecycle closes the remaining coverage gap. Implementation may begin within the recorded integration/test/doc scope; verification is still pending.

## Evidence

- Pending.

## Plan review

- Clean-context reviewer inspected both hook-common actor/cache implementations, session-start and prompt call sites, identity-cache/deadline tests, cross-container HTTP/MCP E2E tests, Relay docs, workflow plan-review instructions, and redline policy. Elevated/Simple classification fits the proposed hook/test/doc scope; no policy boundary change is proposed.
- Blocking setup finding: `app/mcp/context.py:resolve_relay_context` rejects a configured `PALLIUM_ACTOR_REF` without `PALLIUM_CONTAINER_REF`, even when a tool caller supplies the injected scope pair. Thus a stable actor exported to a host and inherited by stdio MCP can disable Relay tools. The current MCP E2E explicitly removes both variables and cannot establish compatibility. Specify and verify a supported hook/MCP environment setup; if code changes to trusted MCP scope are necessary, update scope, classification, and plan before implementation. Merely recommending a global actor variable in Relay docs is insufficient.
- Cache-precedence assumption: preserving a valid cache is consistent with existing code, but the cache is keyed by repository/context fingerprint, not the entire session lifetime. `pin_container(..., source="resume")` retains it; startup/project/config transitions can invalidate it. A resumed session with an old Git-derived actor will ignore a newly configured actor under this plan. Qualify the unconditional completion criterion, document that rollout requires fresh sessions (not only host restart/resume), and test valid-cache precedence plus invalidation with the explicit variable. No evidence requires changing the proposed cache-first order.
- Blocking verification gap: the proposed unit cases and existing cross-container suites do not drive real actor derivation through the hook surface; those suites supply actor values directly. Add a focused caller-level journey for both integrations using different repo-local Git names and one configured Unicode/trimmed actor, assert registered/listed identity and cross-container delivery, and cover fresh versus cached/resumed behavior. Include absent/blank fallback, exhausted deadline (configured actor still wins), and cache-write failure without changing returned identity in the focused parity checks. Keep existing actor-isolation and lifecycle suites as regression coverage.
- Docs must identify the supported configuration location, exact same value across participating runtimes, cache/reset behavior, and the MCP paired-scope restriction. The helper also supplies history/derived-memory attribution, so describe the effect on future hook scope accurately; this is not a Relay-only identity override. No implementation files were edited and no tests were run for this plan-only review.
- Revision response: the plan now uses a dedicated integration-only variable so `resolve_relay_context` remains unchanged, adds OpenCode parity, qualifies fresh versus cached sessions, and requires hook-to-service delivery coverage. A repeated clean-context review is pending.

- Repeated clean-context review: read the revised Work Record, workflow plan-and-review requirements, redline policy, all three actor helpers and their cache/caller paths, Python parity/deadline/cache tests, OpenCode helper/plugin tests, cross-container HTTP E2E, MCP scope resolver, and Relay docs. Elevated/Simple remains appropriate. `git diff HEAD -- app/mcp/context.py` is empty; no implementation files were edited or tests run.
- Accepted design: a dedicated process-environment `PALLIUM_HOOK_ACTOR_REF` is the smallest integration-owned override that avoids coupling to MCP's paired `PALLIUM_ACTOR_REF`/`PALLIUM_CONTAINER_REF` trusted scope. The name also covers OpenCode public plugin hooks; configure the environment inherited by the OpenCode server, not only its MCP child. Read the trimmed value beneath existing actor caches and before Git/deadline fallback, retaining best-effort cache writes and Git/local fallback when absent or blank. No new storage, routing, shared package, or MCP behavior is warranted.
- Cache/doc clarification: OpenCode's `resolveActorRef` already returns `getPinnedActor` before calling `deriveActorRef`; inserting the override only in `deriveActorRef` correctly preserves that pin. Fresh-session rollout therefore applies to OpenCode too. Python pins remain conditional on the repository/config fingerprint and can invalidate at startup/project/config transitions. Documentation must distinguish these behaviors, identify that future history/memory attribution also uses this actor, and avoid treating the variable as authentication or an MCP scope setting.
- Remaining blocking coverage finding: `integrations/opencode/tests/plugin.test.mjs:installFetch` replaces `global.fetch` with canned responses. Extending only that suite proves outgoing payloads but cannot establish real actor registration, actor-filtered session listing, cross-container delivery, or disposition. Explicitly add an OpenCode public-hook-to-real-service journey with the configured trimmed Unicode actor and different repository-local names, assert identity through `/relay/sessions`, then observe delivery through the public hook/transform and persisted status; preserve the pinned identity on reuse and close through the public deletion event. A small bridge to the existing service fixture is sufficient. Claude/Codex real-hook journeys plus current HTTP/MCP regressions are appropriate for those runtimes, provided they do not mock actor derivation or registration results.
- Review bookkeeping fallback: sandboxed reads and `apply_patch` failed with Windows error 1327. Used approved elevated reads and a deterministic replacement confined to this Work Record; implementation files remain untouched.
## Plan review acceptance

- Third fresh clean-context review accepts the Elevated/Moderate plan. Read all three actor helpers and their caller/cache paths, Python identity/deadline and Relay tests, OpenCode helper/plugin tests and Python-to-Node harness, MCP context resolution, Relay documentation, and workflow review requirements. No blocker remains at the planning checkpoint.
- The explicit OpenCode public `chat.message` registration, real-service session listing/send, public `experimental.chat.messages.transform` receive/ack, pinned reuse, and `session.deleted` close journey addresses the previous mocked-fetch coverage gap. Reuse the Node harness structure, but route Relay requests through the real service and verify session/message status through public reads; canned responses or captured-payload replay alone do not meet acceptance.
- `PALLIUM_HOOK_ACTOR_REF` remains a sound integration-only choice: resolve its trimmed value after valid pins and before Git/deadline fallback. MCP continues to read only its existing paired trusted-scope variables. Retain fresh-session rollout guidance, Python fingerprint invalidation versus OpenCode pin behavior, and future history/memory attribution scope. No implementation files were edited or tests run by this plan-only review.
- Review bookkeeping fallback: sandboxed reads and the single `apply_patch` attempt failed with Windows error 1327. Used approved elevated reads and a deterministic replacement confined to this Work Record.

## Result review

- Pending.
