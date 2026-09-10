<!-- agent-workflow:start -->
**Outcome:** Pallium-enabled agents understand what Relay work associations mean, when automatic structural references are sufficient, and when to attach, detach, or discover participants explicitly.

**Target:** Pallium.

**Scope:** The three runtime `pallium-memory` skill copies, their installed work-association reference files, and the shared guidance budget/parity test.

**Constraints:** Keep all runtime skills byte-identical and within the existing 2,530-character ceiling. Preserve Relay, Session History, derived-memory, and field-feedback safety guidance. No runtime/API/schema changes.

**Completion criteria:** Every runtime skill routes relevant work-association tasks to installed guidance explaining automatic structural references, explicit attach/detach criteria, participant discovery, association limits/semantics, and dashboard visibility; parity and budget tests pass.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Pre-edit Redline classified the three integration skill files gray and the focused test blue, with no boundary or checkpoint findings. This is one bounded guidance-only behavior change.

**Discovery:** The installed skill omits work associations entirely. The three runtime skill files are byte-identical, installation copies the complete skill tree, and `tests/test_guidance_budget.py` enforces parity plus a 2,530-character ceiling. The skill has only seven normalized characters of headroom, so detailed inline guidance would violate its measured prompt budget; the existing field-feedback section establishes a lazy-loaded installed-reference pattern. Product docs and the dashboard already expose automatic structural refs, up to three explicit refs, participant lookup, closed-session opt-in, and exact History semantics.

**Material assumptions:** The three runtimes should receive identical guidance; disproved by a runtime-specific tool or semantic difference, in which case stop and split the wording. The existing installer copies reference files with the full skill tree; disproved by the installation test, in which case stop and reassess scope. MCP tool descriptions remain the detailed argument contract; disproved if the reference must duplicate schemas, in which case stop before adding that duplication.

**Plan:** Add one compact relevance trigger to all three identical skill files, trimming redundant Relay prose rather than raising the budget. Put the detailed decision rules in identical installed `references/work-associations.md` files: structural refs are automatic, explicit refs are for stable known work that adds collaboration value, obsolete explicit refs detach, discovery is read-only, associations grant no access or History coverage, and the dashboard exposes the same state. Add one focused cross-runtime trigger/reference contract assertion. Target files: `integrations/{codex,claude-code,opencode}/skills/pallium-memory/{SKILL.md,references/work-associations.md}`, `tests/test_guidance_budget.py`. Stop on parity loss, budget growth, installation-copy failure, or any runtime/API change.

**Verification plan:** All runtime skills route relevant tasks to identical installed references containing the required decisions and remain byte-identical/within budget → focused `tests/test_guidance_budget.py`; installed Codex skill is refreshed from the merged primary checkout → setup output plus installed-file equality check.

**Plan review:** Clean-context `gpt-6-astra` high review `/root/skill_guidance_plan_review`: APPROVE. It confirmed the lazy-loaded reference preserves the prompt budget and required parity/install-tree verification.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

2026-09-10 discovery and pre-edit Redline complete. Smart plan review identified the seven-character budget ceiling. The revised lazy-loaded reference plan was approved; implementation may change only the six skill/reference files and focused guidance test.

2026-09-10 implementation complete: added the shared-work/link-correction trigger, identical installed references, and one cross-runtime contract test. Existing Relay and memory safety language remains; wording was compressed only to preserve the fixed prompt budget. Used the documented deterministic write fallback after apply_patch failed with Windows error 1327.

## Evidence

Pending.

## Result review

Pending.
