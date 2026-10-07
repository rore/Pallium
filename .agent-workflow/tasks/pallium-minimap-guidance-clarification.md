<!-- agent-workflow:start -->
**Outcome:** Clarify which explicit Minimap work assignments use Pallium work associations.

**Target:** Pallium runtime skill guidance.

**Scope:** Three runtime `pallium-memory` skills, their work-association references, and the existing assertion in `tests/test_guidance_budget.py`.

**Constraints:** Preserve exact refs, callable tools, successful results, capacity, structural refs, optional-provider safety, and successful attach/detach; do not change roadmaps, associations, hooks, service, config, or installed consumers.

**Completion criteria:** All runtimes qualify assigned implementation, investigation, testing, and substantive review; casual browsing, passive inspection, and clerical edits remain excluded; mirrors match and the 3,072-byte budget holds.

**Requirement baseline:**
{"source":"user-approved task scope; independent plan review","outcome":"Clarify which explicit Minimap work assignments use Pallium work associations.","scope":"Three runtime `pallium-memory` skills, their work-association references, and the existing assertion in `tests/test_guidance_budget.py`.","constraints":"Preserve exact refs, callable tools, successful results, capacity, structural refs, optional-provider safety, and successful attach/detach; do not change roadmaps, associations, hooks, service, config, or installed consumers.","completion_criteria":"All runtimes qualify assigned implementation, investigation, testing, and substantive review; casual browsing, passive inspection, and clerical edits remain excluded; mirrors match and the 3,072-byte budget holds."}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Integration skill paths are gray and outside the documentation-only exemption. One bounded guidance change across identical mirrors plus its existing string assertion.

**Discovery:** Three integration skill and reference copies are byte-identical. SKILL.md is exactly 3,072 normalized bytes. The existing guidance test asserts the superseded exclusion wording. The stable checkout is clean at the same baseline commit; Codex/Claude skills refresh via setup commands, and OpenCode loads the bundled stable plugin through its user-level loader. No consumer refresh is in scope.

**Material assumptions:** All runtimes share the same wording and work-ref procedure; if a runtime-specific contract appears, stop and replan. The authoritative Minimap item-ref command and existing generic workflow remain sufficient; if any safeguard would need changing, stop and request review.

**Plan:** Replace the two participation triggers in all three skill/reference mirrors with the reviewed wording. Update only the existing contract assertion to match. Keep the CLI command and all exact-work safety procedures unchanged. Stop if parity, budget, or a protected expectation cannot be preserved.

**Verification plan:** Runtime skills remain byte-identical and at or below 3,072 normalized bytes; work-association references remain byte-identical and retain safety clauses → existing focused guidance budget/contract test. Whole change is correctly classified and required checks are completed → `scripts/test-plan.py --base origin/main` and its reported workflow checks.

**Plan review:** Agent technical review: independent reviewer (2026-10-07); scope, wording, risk, and safety constraints approved.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

2026-10-07: Updated the six mirrored skill/reference files and the existing guidance assertion. Read-only refresh inventory completed; no consumer setup or roadmap changes.

## Evidence

- Focused guidance contract: `uv run --offline --extra dev python -m pytest tests/test_guidance_budget.py -q -n 0` — 11 passed.
- Selector: `scripts/test-plan.py --base origin/main` selected `python -m pytest tests/ -x -q`. The first run lacked optional `mcp`; `pytest.importorskip("mcp")` ran before `_serve_protocol` was defined, so an importing test saw a missing name. The target test files match baseline `17f9304b`, `PYTHONPATH` is unset, and CI installs the `dev`, `vector`, and `mcp` extras.
- Full lane with the CI-equivalent extras: `uv run --offline --extra dev --extra vector --extra mcp python -m pytest tests/ -x -q` — 6,269 passed, 34 skipped, 2 xfailed.
- Fresh Redline: GRAY, no boundary violations or checkpoints; exit 1 is the expected gray-review advisory. Import-linter report had no violations.
- Agent Workflow check: clean. `git diff --check`: clean. Three skill hashes match at exactly 3,072 normalized bytes; all three work-association reference hashes match.

## Result review

Agent technical review: independent reviewer (2026-10-07); wording and assertion changes accepted, safeguards unchanged.
Reviewed revision: `17f9304b0ee68081d7801075e507d97ac4909fe9` plus the reviewed worktree diff.
Verification adequacy: focused guidance test passed 11; full selector-required suite passed 6,269 with 34 skipped and 2 xfailed after using the same optional extras as full CI.
