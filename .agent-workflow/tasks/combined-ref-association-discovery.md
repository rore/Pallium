<!-- agent-workflow:start -->
**Outcome:**
Implement and close the smallest Pallium guidance-only slice for explicit work/history-reference association, preserving all existing structural hooks and independent capability subsets.

**Target:**
Seven product/test files: the six Codex, Claude Code, and OpenCode `pallium-memory` SKILL/reference guidance mirrors plus the existing `tests/test_guidance_budget.py` assertions. Existing runtime hooks, identity resolvers, Relay, and Session History remain unchanged.

**Scope:**
Approved implementation is guidance-only Slice A in exactly seven product/test files (six Pallium skill mirrors plus the existing guidance-budget test); use existing explicit Relay work-reference list/attach/detach and exact History tools for explicitly assigned work. Do not change runtime hooks, identity resolvers, or History semantics.

**Constraints:**
Work in the isolated branch/worktree from origin/main. Do not execute repository-local or arbitrary provider code, and do not add a per-turn subprocess. Supplied refs are authoritative; missing providers/configuration must fail safely without changing normal work. Preserve legacy Pallium roadmap scope behavior and existing stored identifiers. No auto-discovery from passive Minimap browsing, no path-derived scope, no silent eviction of explicit refs, no mandatory cross-tool dependency, and no on-hold legacy repair. Invoke Pallium operations only when the named MCP tools are callable; only successful list/attach/detach results are authoritative. Attempted or failed calls never prove mutation; unavailable calls fall back to ordinary work or broad History. An association never implies task ownership, activity, acceptance, completion, or History/memory access.

**Completion criteria:**
The six guidance mirrors are reviewed, tested with the focused guidance-budget check and existing lifecycle E2E regression, documented, roadmap-aligned, merged, and installed/verified; explicit assignment, lazy/safe guidance, successful-call authority, capacity, current-session explicit-origin ownership, idempotency, cleanup, Unicode, independent-subset behavior, and the non-ownership/non-access guarantee are covered.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:**
The six integration skill mirrors are gray/unclassified while the focused tests are blue; redline reports no architecture checkpoint. Risk remains Elevated conservatively because the guidance governs identity association and History use, but complexity is Moderate because this release changes one coherent guidance slice only.

**Discovery:**
Codex and Claude duplicate the Work Record resolver in `integrations/codex/hooks/common.py` and `integrations/claude-code/hooks/common.py`; OpenCode mirrors it in `integrations/opencode/.opencode/plugins/pallium-common.mjs`. All currently read branch state and `.agent-workflow/tasks/<slug>.md`; Codex/Claude use hardcoded `roadmap` for the Work Record scope. `core/work_ref.py` caps normalized refs at five; integration helpers accept up to three explicit Relay refs; `app/mcp/server.py` already exposes exact work-ref History search and treats broad `work_refs` as compatibility-only. Relay persistence already has idempotent structural refresh and explicit attach/detach with E2E coverage. Current source-of-truth docs state that structural refs are continuity hints, exact work search is narrow, broad search remains available, and missing identity must not be guessed.

**Material assumptions:**
- Existing Pallium Relay list/attach/detach and exact/broad History tools provide the complete current contract; evidence that any guidance claim exceeds those surfaces returns the plan to review.
- Minimap v1 is shipped in main/v0.3.1 and its callable command is authoritative; if the command is unavailable, ordinary work continues without attachment.
- Agent Workflow remains an explicit open coordinated gap: its structural output lacks `scope_ref`, so it is not an attachable custom/resumed reference. No automatic resolver is part of this release.
**Plan:**
1. Workflow invocation, Work Record creation, and risk classification occurred before implementation planning. This release changes guidance only and retains all existing default structural hooks.
2. For explicitly assigned Minimap work, invoke only the callable command `node <skill>/runtime/cli.js roadmap item-ref <item-id> --repo <absolute-repo-path> --json`. It returns the exact `scope_ref` and `local_ref`; no passive browsing or auto-discovery is allowed.
3. Invoke Pallium operations only when the named MCP tools are callable. Call `pallium_relay_work_refs` first; only a successful result is authoritative. Reuse an exact existing pair or call `pallium_relay_attach_work_ref` with the exact returned pair; only a successful attach result proves mutation and its returned canonical key may be used for exact History on subsequently captured turns. Capacity or any failed/attempted call skips attachment and continues ordinary work or broad History without unavailable calls. Detach only the current session explicit origin that this flow successfully attached, on actual leave; only a successful detach is authoritative.
4. Update exactly these six mirrors and the existing guidance-budget test: `integrations/codex/skills/pallium-memory/SKILL.md`, `integrations/codex/skills/pallium-memory/references/work-associations.md`, `integrations/claude-code/skills/pallium-memory/SKILL.md`, `integrations/claude-code/skills/pallium-memory/references/work-associations.md`, `integrations/opencode/skills/pallium-memory/SKILL.md`, and `integrations/opencode/skills/pallium-memory/references/work-associations.md`. Each `SKILL.md` preserves the generic exact-work/link-correction trigger and adds the explicit Minimap trigger; each `references/work-associations.md` owns the detailed CLI, callable-tool, lifecycle, and fallback guidance; the existing test asserts those relationships.
5. Keep runtime hooks, identity resolvers, Relay, and History unchanged for this release. The Agent Workflow adapter gap remains an explicit open roadmap/coordinated dependency, with no automatic resolver, pickup/resume/handoff behavior, locator/argv/timeout protocol, supplied-ref hook path, cache, or event framework.
**Verification plan:**
- Guidance contract -> `tests/test_guidance_budget.py::test_work_association_guidance_is_lazy_aligned_and_safe` plus the existing guidance budget check.
- Lifecycle regression -> existing work-reference association E2E lifecycle coverage, including callable-tool gating, successful-result authority, list/attach/detach, current-session explicit-origin ownership, capacity, idempotency, cleanup, Unicode, later-turn exact History behavior, and the guarantee that association implies no task ownership/activity/acceptance/completion or History/memory access.
- Mirror parity -> compare the six skill/source mirrors and run their existing integration checks; no runtime hook or History behavior changes are expected.
- Governance -> fresh redline, workflow checker, focused tests, CI, inline review resolution, and installed skill verification.
**Plan review:**
Manager approved the guidance-only Slice A scope. Independent Sol review: **APPROVE** — the narrowed seven-file guidance/test slice now preserves the generic trigger, states callable-tool gating, successful-result authority, exact explicit-origin ownership, precise History timing, and the non-ownership/non-access guarantee; Slice B remains deferred.
**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Plan review

Manager approved the guidance-only Slice A scope and requested a complete producer→consumer→stored-ref contract. Independent Sol review initially BLOCKED the plan because callable-tool and successful-result semantics, explicit-origin ownership, and the non-ownership/non-access guarantee were not explicit; the capability matrix overclaimed Agent Workflow/Minimap-only behavior; Slice B leaked into completion gates; and the exact six-file/test scope was not stated. Resolution: the Work Record now requires callable named MCP tools and successful results as the only authority, records current-session explicit origin and the full negative guarantee, uses the corrected matrix, removes Slice B from current completion, and justifies all six mirrors (SKILL lazy trigger plus reference lifecycle detail). Independent Sol re-review: **APPROVE**. Review findings were resolved by restoring the complete generic non-Minimap workflow as an additive section, moving per-operation callability and successful-result authority for list, attach, detach, participant, and History operations plus unavailable/failure/capacity skip semantics into that generic contract, correcting attach/list fallback, clarifying conditional per-turn History tagging and explicit-only detach, and strengthening tests for generic and Minimap relationships. Final smart reviewer: **APPROVE** — generic and Minimap contracts are aligned and no runtime changes are present.


## Implementation

Phase 1 discovery and manager plan review are recorded. Updated only the six approved guidance mirrors and the existing guidance-budget assertions; runtime hooks, identity resolvers, Relay, History, roadmap, and config remain unchanged. apply_patch failed with the machine-local Windows sandbox error 1327, so deterministic PowerShell replacements were used as the documented fallback.

## Discovery evidence

- Codex: `integrations/codex/hooks/common.py` (`_structural_work_refs`, `discover_work_refs`, `structural_work_refs_payload`, `build_work_refs_metadata`, `fetch_confirmed_work_refs`). It reads the branch from `.git/HEAD`, emits `git-branch:<branch>`, and emits `agent-workflow:<slug>` only when `.agent-workflow/tasks/<slug>.md` exists with marker bounds. `structural_work_refs_payload` hardcodes `roadmap` as the scope root for agent-workflow refs.
- Claude: `integrations/claude-code/hooks/common.py` has the same resolver and hardcoded `roadmap` behavior. User-prompt and stop hooks call discovery, Relay enrichment, metadata construction, and thread identity propagation (`integrations/claude-code/hooks/user_prompt_submit.py`, `stop.py`).
- OpenCode: `integrations/opencode/.opencode/plugins/pallium-common.mjs` mirrors the branch/Work Record resolver and `roadmapScopeRef`; tests in `integrations/opencode/tests/common.test.mjs` assert the current paths and identity vectors. The workflow plugin itself (`.opencode/plugins/agent-workflow.mjs`) invokes the guard by repo-relative `scripts/agent-workflow-runtime.py` and does not resolve Work Records.
- Current history association: `core/work_ref.py` caps normalized refs at `MAX_WORK_REFS = 5`; `app/mcp/server.py` exposes exact `pallium_search_history_by_work_ref` and treats broad-search `work_refs` as compatibility-only. `integrations/*/hooks/common.py` caps confirmed explicit Relay refs at 3, while structural refs are prepended and caller refs are not truncated in that helper; downstream metadata sanitization enforces the five-ref limit (`core/service.py`).
- Existing Relay association: `storage/sqlite_relay.py` persists `relay_session_work_refs` with `(endpoint_id, work_ref, origin)` identity and refreshes structural refs idempotently; explicit attach/detach APIs and participant lookup are covered by `tests/test_relay_work_ref_associations_e2e.py`, `tests/test_relay_work_ref_identity.py`, `tests/test_structural_work_refs_e2e.py`, and `tests/test_relay_mcp_lifecycle.py`.
- Identity/current session: Codex and Claude hooks receive `session_id`, use it as `thread_ref`, and maintain durable per-session pin/dedup state in their respective common modules. MCP context resolves explicit args before `PALLIUM_THREAD_REF`; Relay work-ref tools fail closed without integration-injected identity (`app/mcp/context.py`, `app/mcp/server.py`). OpenCode passes `message.sessionID` through its plugin payload and tests cover user/assistant/idle paths.

## Source-of-truth read

Read `README.md`, `docs/context/README.md`, `docs/context/architecture.md`, `docs/context/lessons.md`, `docs/context/decisions.md`, `docs/context/state.md`, `docs/context/operations.md`, `docs/session-history.md`, `docs/designs/013-work-ref-cross-surface-continuity.md`, `docs/designs/015-vnext-historical-work-execution.md`, `roadmap/scope.md`, `roadmap/board.md`, and the relevant roadmap items `add-work-ref-cross-surface-continuity`, `add-structural-session-work-references`, `add-distinct-work-and-broad-history-search-tools`, and `fix-lookup-and-expansion-active-attribution`. The source-of-truth boundary is explicit: structural refs are continuity hints, exact work search is intentionally narrow, broad search remains available, and missing identity must stay absent rather than guessed.

## Cross-repo dependencies

- Agent Workflow owner: provider-only resolver approval was verified and implementation is underway, but the exact-scope adapter remains open. Any future Slice B needs a separately reviewed trusted installer-configured path or remains agent-invoked via existing explicit attach; no repo/PATH/cwd discovery.
- Minimap owner: v1 explicit-item identity CLI is already shipped in main/v0.3.1; the INSTALL-only patch commit `b7a20de...` exists unmerged pending combined verification. Neither dependency expands this PR.
- Pallium owner: implement Slice A only after clean-context review; keep all runtime subsets independently usable. Slice B remains deferred.

## Combined closure checklist

- [ ] Parent/architect accepts this plan and contract.
- [ ] Verify the already-shipped Minimap v0.3.1 command/source mirror if referenced by Slice A.
- [ ] Pallium Slice A six guidance mirrors reviewed and tested.
- [ ] Focused `tests/test_guidance_budget.py::test_work_association_guidance_is_lazy_aligned_and_safe`, existing guidance budget check, and lifecycle E2E regression pass.
- [ ] Source mirrors, docs, roadmap, Work Record, and installed state reconciled.
- [ ] Fresh redline/workflow checks, focused tests, CI, inline review resolution, and PR merge complete.
## Verification notes

Focused guidance budget: uv run python -m pytest tests/test_guidance_budget.py -q -n 0 — 7 passed. Relay lifecycle regression: uv run python -m pytest tests/test_relay_work_ref_associations_e2e.py -q -n 0 — 11 passed. Fresh redline: GRAY only for the six unclassified integration mirrors, blue for the test, no boundary violations/checkpoints; workflow checker passed clean. Mirror byte-equivalence and git diff --check passed. Slice B has no approved automatic locator design.

## Provider combination matrix

| Combination | Actual usable behavior | Missing/error fallback |
|---|---|---|
| None | Ordinary agent work only. | No Pallium association, Minimap identity, or Agent Workflow integration is implied. |
| P only | When named MCP tools are callable and return success, Pallium can list current refs, reuse an exact pair, attach an explicitly supplied scoped pair when the successful list lacks it, detach the current session explicit origin this flow successfully attached, and search exact History subject to per-turn association lookup. | Fallback applies when no exact scoped pair was supplied, a required tool is unavailable or fails, or capacity prevents attach; failed/attempted calls prove no mutation. Association implies no task ownership/activity/acceptance/completion or History/memory access. |
| Agent Workflow only | Native Agent Workflow capability only; no Pallium association or History behavior. | Pallium remains uninvolved; ordinary work continues. |
| Minimap only | Native Minimap capability only: explicit item ID can produce its exact pair through the v1 CLI. | Without Pallium, no stored association or History behavior. |
| P + Agent Workflow | Pallium association/list/attach/detach/exact search plus independent native Agent Workflow behavior. | Agent Workflow refs lacking `scope_ref` are not attachable; if Pallium has no exact pair, use broad History. |
| P + Minimap | Complete explicit path: item ID -> `node <skill>/runtime/cli.js roadmap item-ref <item-id> --repo <absolute-repo-path> --json` -> exact pair -> callable successful Pallium list/reuse or attach -> returned canonical key -> later-turn exact History -> detach only the current session explicit origin this flow successfully attached on leave. | Missing/error/unavailable Minimap or Pallium, failed/attempted calls, or capacity failure skips attachment and ordinary work continues or uses broad History; no guessing. Association implies no task ownership/activity/acceptance/completion or History/memory access. |
| Agent Workflow + Minimap | Independent native Agent Workflow and Minimap capabilities only. | No Pallium association or History behavior without Pallium. |
| P + Agent Workflow + Minimap | P + M explicit association/search path, plus independent native Agent Workflow structural behavior. | Any missing/error subset degrades only that subset; P still requires an exact supplied pair and otherwise uses broad History. |
## Current design boundary

This guidance-only release intentionally does not add automatic pickup/resume/handoff handling, a resolver locator, argv or timeout protocol, a supplied-ref hook path, or any cache/event framework. The Agent Workflow containment and exhaustive v1 validation remain upstream blockers. The minimal adapter gap is explicit: Agent Workflow's `agent-workflow:<slug>` lacks the `scope_ref` required by Pallium attach, so guidance must not pretend it can attach custom/resumed work.





