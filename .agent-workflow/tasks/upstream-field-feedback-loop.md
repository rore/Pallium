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
The three `SKILL.md` files are byte-identical and already sit at the 2,337-character normalized budget. Codex and Claude installers copy only `SKILL.md`; OpenCode packages `skills/` recursively. Existing `tests/test_guidance_budget.py` checks surfaces but not byte parity. Agent-workflow provides a useful lazy feedback pattern, while `add-live-integration-improvement-loop-and-replay-pipeline` owns memory-quality misses and replay promotion. Runtime sources: Claude Code Skills docs (`https://code.claude.com/docs/en/skills`) document linked supporting files beside `SKILL.md`; OpenCode Skills docs (`https://opencode.ai/v2/docs/skills`) state that skill paths resolve relative to the directory containing `SKILL.md`; and the current Codex host skill contract instructs filesystem-backed skills to resolve relative resources against the `SKILL.md` directory and load them only when relevant. Static link checks plus fresh installed/package manifests will verify those conventions without loading the detailed reference into normal context.

**Material assumptions:**
npm's existing `files: ["skills/"]` includes nested references; an actual dry-run package manifest disproves this and requires the smallest manifest correction. The Pallium-owned installed skill directories may be replaced on reinstall, matching their existing whole-directory uninstall ownership; lifecycle tests disprove this if unmanaged content must be preserved.

**Plan:**
1. Add one short trigger/pointer to `integrations/{codex,claude-code,opencode}/skills/pallium-memory/SKILL.md` and byte-identical `references/field-feedback.md` files. The reference will load only after a trigger; accept only repeatable, pointable defects owned by Pallium's product, integrations, contracts, packaging, or documentation; route memory-quality misses exclusively to existing debug/flag/rate/replay mechanisms; redact private context; bound drafts to 200 words and 2,000 Unicode characters; prepare the draft before asking explicit user approval for any GitHub write; only after approval search `rore/Pallium` for duplicates; report an existing issue without creating another, create only when no duplicate exists, and return a safe unsent draft on missing `gh`, authentication/permission/network failure, or withheld approval. 2. Change `app/cli/setup_codex.py` and `app/cli/setup_claude_code.py` to replace each Pallium-managed destination skill tree with the complete source tree. Extend `tests/test_claude_code_integration.py` and `tests/test_codex_integration.py` across fresh install, overwrite/update, stale nested-file removal, repeat install, and uninstall. Keep OpenCode's recursive package entry, but add an actual `npm pack --dry-run --json` assertion in `integrations/opencode/tests/package.test.mjs` for the nested reference. 3. Extend `tests/test_guidance_budget.py` for the three-copy byte parity, bounded pointer, lazy-detail separation, relative link target, byte-identical references, reporting/privacy/fallback contracts, memory-miss exclusion, and non-ASCII-safe dual bound. Add `roadmap/features/add-context-conscious-upstream-field-feedback.md` and `roadmap/board.md` as an active integration-feedback item cross-linked to the distinct memory-quality replay feature; mark it done only after verification. 4. Run the exact focused Python and OpenCode tests, installer/package artifact parity, affected subsystem tests, full `python -m pytest tests/ -x -q`, diff hygiene, Redline/workflow checker, and clean-context result review. Stop if a runtime cannot resolve the packaged relative reference or the change requires service/API/storage state.

**Verification plan:**
When any shipped skill is loaded, normal context shall contain only the bounded trigger/pointer and all three copies shall match → guidance budget/parity test. When the trigger fires, the reference shall cover repeatability, actionability, ownership, privacy, duplicate search, bounded issue submission/fallback, and memory-quality routing → focused content-contract test and review. When Codex or Claude setup runs, the reference shall deploy and reinstall idempotently → existing installer lifecycle tests extended for the reference. When OpenCode is packed, the nested reference shall be present → `npm pack --dry-run --json` manifest check. Before PR, affected tests, full `tests/`, diff hygiene, Redline/checker, and clean-context result review shall pass.

**Plan review:**
Approved after two clean-context reviews. The final review confirmed sourced runtime-reference conventions, exact targets, explicit external-write approval, safe duplicate/fallback handling, exact installer lifecycle, strict memory-quality separation, and minimap coordination; no blockers remain.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Added a 192-character field-feedback pointer to the byte-identical Codex, Claude Code, and OpenCode skills; detailed filters, privacy rules, approval, duplicate handling, bounds, and fallbacks live only in byte-identical `references/field-feedback.md` files.
- Updated Codex and Claude setup to stage and validate the complete source tree before activation, restore the prior installation on activation failure, and remove stale nested artifacts on successful reinstall.
- Added exact tree lifecycle and failure-preservation tests, three-runtime lazy/content/parity/security contracts, a real OpenCode npm dry-run package-manifest test, and the matching package-tree README entry.
- Added and completed the distinct upstream-defect minimap feature, cross-linked to the existing memory-quality feedback/replay lane.
## Evidence

- Base revision: `19f500ac8b6125fd7f58914f4eb74bbf4cea8b85`.
- Skill normalized size: 2,529 characters (2,337 before); all three skill copies and all three references are byte-identical.
- Focused contracts plus both installer lifecycle nodes after review fixes: 8 passed.
- Installer lifecycle nodes: Codex + Claude — 2 passed.
- Affected Python files: 51 passed.
- OpenCode `npm test`: 49 passed, 7 platform skips; `npm pack --dry-run --json` includes `skills/pallium-memory/references/field-feedback.md`.
- Fresh base-to-HEAD Redline verdict: GRAY advisory; 15 scoped files, no red zones, checkpoints, boundary violations, API/schema/security/runtime-config changes.
- `agent-workflow-check.py`: clean.
- Post-review full pre-PR suite: 4,643 passed, 32 skipped, 2 xfailed, 4 existing warnings in 210.14 seconds.
## Plan review

Approved after two clean-context reviews. The first review blocked on runtime-resolution evidence, external-write approval, exact targets, full installer lifecycle, privacy/negative/Unicode cases, and minimap separation. The second caught incorrect installer test names and unnamed runtime sources. The structured record now addresses all findings; the reviewer approved implementation with no remaining blockers.

## Result review

The first clean-context result review blocked on four findings: shell-interpolated issue examples, stale Redline evidence, destructive-before-copy installer replacement, and OpenCode package documentation drift. All four were fixed. The reviewer then confirmed argv-only no-shell guidance with `--body-file`, staged activation and restoration tests, README/package parity, the fresh branch-specific Redline verdict, focused tests, diff hygiene, and the workflow gate. Final result: approved with no remaining findings.