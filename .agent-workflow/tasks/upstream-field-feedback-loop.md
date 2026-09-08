<!-- agent-workflow:start -->
**Outcome:**
Pallium's shipped agent skills surface a tiny on-demand trigger for repeatable upstream defects and load the full safe reporting workflow only when that trigger fires.

**Target:**
Pallium integrations.

**Scope:**
The Codex, Claude Code, and OpenCode `pallium-memory` skills; their install/package paths; focused alignment, budget, and install tests; and a minimap feature record.

**Constraints:**
No telemetry, service API, or feedback database. Normal context gains only a short trigger/pointer. Reports target `rore/Pallium`, redact private data, and exclude memory-quality misses handled by existing flag/rate/debug/replay mechanisms.

**Completion criteria:**
All three shipped skills carry the same bounded pointer and lazily loaded detailed workflow; fresh Codex/Claude installs and the OpenCode package include it; tests prevent drift and budget regressions; minimap records the distinct product-feedback lane.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Redline classifies integration skills as gray and setup scripts as app-layer watch, with no red/API/persistence/security/boundary surface. Multiple runtimes and installed-artifact behavior require coordinated verification.

**Discovery:**
The three `SKILL.md` files are byte-identical and already sit at the 2,337-character normalized budget. Codex and Claude installers copy only `SKILL.md`; OpenCode packages `skills/` recursively. Existing `tests/test_guidance_budget.py` checks surfaces but not byte parity. Agent-workflow provides a useful lazy feedback pattern, while `add-live-integration-improvement-loop-and-replay-pipeline` owns memory-quality misses and replay promotion.

**Material assumptions:**
Relative skill references are supported by all three runtimes; a failed installed-artifact or package test disproves this and requires a packaging-compatible reference path. npm's existing `files: ["skills/"]` includes nested references; a dry-run package manifest disproves this and requires the smallest manifest correction.

**Plan:**
1. Add one short field-feedback trigger/pointer to the three identical skills and a self-contained `references/field-feedback.md` copy under each, reusing the existing actionability/filter shape while targeting `rore/Pallium`. 2. Change the Codex and Claude installers to copy the complete skill directory so lazy references deploy with `SKILL.md`; keep OpenCode's existing recursive `skills/` package entry. 3. Extend existing guidance-budget/parity and installer lifecycle tests, and add a completed minimap feature entry without reopening the memory-quality replay lane. 4. Run focused Python/OpenCode/package checks, installed-artifact parity, the affected subsystem tests, the full pre-PR suite, and independent result review. Stop if a runtime cannot resolve relative references or the change requires a service/API/storage surface.

**Verification plan:**
When any shipped skill is loaded, normal context shall contain only the bounded trigger/pointer and all three copies shall match → guidance budget/parity test. When the trigger fires, the reference shall cover repeatability, actionability, ownership, privacy, duplicate search, bounded issue submission/fallback, and memory-quality routing → focused content-contract test and review. When Codex or Claude setup runs, the reference shall deploy and reinstall idempotently → existing installer lifecycle tests extended for the reference. When OpenCode is packed, the nested reference shall be present → `npm pack --dry-run --json` manifest check. Before PR, affected tests, full `tests/`, diff hygiene, Redline/checker, and clean-context result review shall pass.

**Plan review:**
Pending clean-context review.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Established `feat/upstream-field-feedback-loop` from current `origin/main` and completed focused discovery plus clean-context Redline classification before implementation edits.
- Redline result: gray integration skills, watch-only setup scripts, blue tests/roadmap, no boundary or contract-class surface; workflow mapping is Elevated/Moderate.

## Evidence

- Base revision: `19f500ac8b6125fd7f58914f4eb74bbf4cea8b85`.

## Plan review

Pending.

## Result review

Pending.
