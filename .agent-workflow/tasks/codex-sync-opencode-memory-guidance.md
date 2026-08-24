<!-- agent-workflow:start -->
**Outcome:** OpenCode receives the same current Pallium history, scope, date, and supersession instructions as Claude and Codex.

**Target:** Pallium OpenCode integration.

**Scope:** `integrations/opencode/AGENTS.md`, `integrations/opencode/skills/pallium-memory/SKILL.md`, and this Work Record.

**Constraints:** No plugin/runtime/config changes; preserve OpenCode's existing loader and MCP behavior.

**Completion criteria:** Both OpenCode guidance files match their canonical Codex peers exactly, OpenCode's native tests pass, and the installed loader resolves to the merged checkout.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Redline classifies `integrations/opencode/**` as gray because the policy has no matching zone; there is no boundary or contract risk. The change is two coherent guidance files.

**Discovery:** The global OpenCode loader already imports `integrations/opencode/.opencode/plugins/pallium.mjs` from this checkout and its 36 native tests pass. The OpenCode skill and AGENTS block lag the canonical Codex peers on exact scope propagation, date/outdated handling, and resume-first wording.

**Material assumptions:** OpenCode exposes the same Pallium MCP tool and injected-scope contract described by the canonical guidance. Disproof: plugin/README uses different tool names or scope semantics; action: stop and author host-specific wording instead of copying. Current plugin and README support the assumption.

**Plan:** Replace the two OpenCode guidance files with their canonical Codex counterparts, then verify exact hashes, native OpenCode tests, workflow/redline checks, and the global loader target. Stop if parity changes OpenCode-specific runtime behavior.

**Verification plan:** Exact file parity → SHA-256 comparisons; OpenCode behavior unchanged → `node --test tests/*.test.mjs` from `integrations/opencode`; governance → agent-workflow and redline local checks; installed runtime current → inspect loader target and live service health.

**Plan review:** See `## Plan review` below.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Discovery and redline classification completed, followed by clean-context approval. Implementation used the documented deterministic Windows fallback after one apply_patch error 1385: copied the two canonical Codex guidance files over their OpenCode peers. No plugin, config, or runtime file changed. Skill feedback issue filed: https://github.com/rore/agent-workflow/issues/14.

## Evidence

Verification at the working-tree revision: SHA-256 parity passed for both guidance files; OpenCode native tests passed 36/36; the global loader resolves to this checkout; live health is ok with vector search and embedding provider healthy. A fresh three-file redline verdict is GRAY/Elevated with no boundary risk or checkpoints; agent-workflow then passed clean. The earlier High result was traced to PR #62's stale build artifact and discarded.

## Result review

Completion criteria are satisfied. Final scope remains the two OpenCode guidance files plus the Work Record; runtime/config behavior is unchanged, the compatibility assumption holds, and the fresh diff remains Elevated/Simple. Skill-feedback trigger 3 passed the actionability filter because the operating instructions name a missing Unix-only local check on a Windows-supported repository; upstream feedback filed as https://github.com/rore/agent-workflow/issues/14.

## Plan review

Approved after clean-context review, one decision at a time:

1. **Scope decision — copy only the two OpenCode guidance files.** Approved. The Work Record names exactly `integrations/opencode/AGENTS.md` and `integrations/opencode/skills/pallium-memory/SKILL.md`; the plugin and README document the existing runtime contract and are not part of the edit.

2. **Parity decision — use the canonical Codex peers.** Approved. The OpenCode AGENTS block is missing exact `container_ref`/`thread_ref` provenance wording, and the OpenCode skill is missing resume-first, date/outdated, and full-scope guidance present in `integrations/codex/AGENTS.md` and `integrations/codex/skills/pallium-memory/SKILL.md`.

3. **Compatibility assumption — OpenCode supports the same MCP tool and injected-scope contract.** Supported by the scoped OpenCode plugin and README: they use the named Pallium endpoints/tools and explicitly preserve private visibility, container resolution, and session/thread scope. No host-specific wording is required.

4. **Verification decision — exact parity, native tests, governance checks, and loader inspection.** Approved. Run SHA-256 parity checks against the canonical peers, `node --test tests/*.test.mjs` from `integrations/opencode`, the workflow/redline checks, and a read-only loader-target/health inspection. Do not alter integration runtime files during verification.

No blocking findings. The plan may advance to implementation.