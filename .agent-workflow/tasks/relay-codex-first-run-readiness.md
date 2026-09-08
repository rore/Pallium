<!-- agent-workflow:start -->
**Outcome:**
A fresh Codex setup tells the user that Relay wake is not ready until Codex has reviewed and trusted the new hooks, and gives the shortest safe activation step while trusted reruns remain accurate.

**Target:**
Pallium's Codex integration installer.

**Scope:**
`app/cli/setup_codex.py`; focused installer coverage in `tests/test_codex_integration.py`; `docs/codex-integration.md`; `roadmap/features/add-wake-first-relay-delivery.md`; this Work Record.

**Constraints:**
Do not calculate, write, bypass, or infer Codex hook trust; do not change hook commands, wake routing, MCP configuration, trust/security state, public API, persistence, dependencies, or unrelated `scripts/validate_relay_cutover_copies.py`. Preserve reinstall and service-verification behavior.

**Completion criteria:**
(1) After setup installs new or changed hooks, output shall state that configuration is installed but Relay wake requires restarting Codex and approving its hook review if prompted; it shall not claim wake-ready integration. (2) Existing trusted installs remain safe to rerun: setup changes no trust state and conditional activation guidance stays accurate. (3) User docs describe Codex's review prompt and prohibit the dangerous bypass flag as an installation shortcut. (4) A real isolated-home setup → Codex-owned review → hook-execution witness shall qualify the roadmap gate on the exact tested version/platform without modifying the live Codex home.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Redline classifies `app/cli/setup_codex.py` as gray+watch and the remaining scoped paths as blue; no red zone, boundary violation, or checkpoint applies. Moderate complexity reflects an externally owned, hash-based trust lifecycle that must be verified without reimplementing or weakening it.

**Discovery:**
The installer enables hooks and writes three commands, then unconditionally prints `Done. Pallium is now integrated with Codex.` Codex CLI 0.149.1 exposes `--dangerously-bypass-hook-trust` specifically because enabled hooks normally require persisted review; its installed binary says new/changed hooks need review and untrusted hooks do not run. The installed config stores per-hook `trusted_hash` values under `[hooks.state]`, while Pallium neither owns nor should reproduce that hash contract. The current setup docs omit the review/restart step, and the wake roadmap keeps first-run qualification open. Existing tests cover hook registration but not the setup completion message.

**Material assumptions:**
Codex continues to present its own review UI for new or changed hooks and persists trust by hook hash. If a supported Codex command/API exposes exact trust readiness during implementation, consider reporting it without writing it; otherwise keep the installer honest with unconditional activation guidance. If Codex no longer gates hooks, stop and re-plan the docs-only qualification. If correctness requires modifying trust or runtime wake behavior, stop and reclassify.

**Plan:**
(1) Reuse the existing installer output path: replace the unconditional ready claim with a configuration-installed result plus restart/review-if-prompted instructions, explicitly avoiding `--dangerously-bypass-hook-trust`. (2) Extend `tests/test_codex_integration.py` through the public `install()` surface with temporary paths and service verification stubbed; assert files are installed, a sentinel Codex-owned trust entry is preserved across rerun, and output contains the activation boundary. (3) Update Codex setup docs. (4) Run a real setup against a new isolated `USERPROFILE`/`CODEX_HOME`, launch installed Codex without the bypass flag, approve its own hook review if prompted, submit one bounded witness turn, and verify hook-owned state plus persisted trust; copy authentication only inside the isolated temporary directory and delete that directory after the witness. Record exact Codex version/platform and qualify the roadmap only if this passes. (5) Run the exact installer test, the full Codex integration file, workflow/redline and whitespace checks, one full suite, then clean-context result review. Stop before any Pallium trust-state write/hash logic, hook command change, wake runtime change, live Codex-home mutation, or new dependency.

**Verification plan:**
When setup runs against an empty Codex home, it shall install configuration while stating that Relay wake awaits Codex hook review if prompted → public `install()` lifecycle test with temporary files and captured output.
When setup is rerun with existing config, it shall preserve Codex-owned trust state and repeat conditional guidance → lifecycle test seeded with a sentinel `[hooks.state]` entry and second install.
When users follow setup docs, they shall see the required restart/review step and a warning not to bypass trust → focused doc assertion and diff review against installed Codex 0.149.1 behavior.
When a real fresh isolated Codex home starts after setup, Codex shall own the review and persist trust before the Pallium hook executes → interactive isolated-home installed witness with no bypass flag, exact version/platform, hook-state evidence, and live-home non-mutation check.
Before PR review, the scoped change shall pass Codex integration tests, workflow/redline, whitespace, and one full suite → named pytest/checker commands and clean-context result review.

**Plan review:**
2026-09-08 clean-context review by /root/review_relay_first_run_plan: APPROVE after requiring the isolated installed-state witness and conditional review-if-prompted wording.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-08: Established the first-run readiness scope before code; clean-context classification returned Elevated/Moderate with installer watch visibility and no checkpoint or boundary violation.
- 2026-09-08: Discovery confirmed Pallium's false-ready completion message, Codex-owned per-hook trust hashes, and missing activation guidance. No production trust inspection or mutation is planned.
- 2026-09-08: Clean-context Elevated plan review approved after adding a real isolated-home Codex trust/hook witness and conditional rerun wording.
- 2026-09-08: Replaced the installer's unconditional ready claim with configuration-installed plus restart/review-if-prompted guidance; added public install lifecycle coverage and explicit docs without adding trust logic.
- 2026-09-08: Windows Codex 0.149.1 isolated-home witness showed the native three-hook review, persisted three hashes through Codex, ran all three hooks, and returned `TRUST_WITNESS_OK`. No bypass was used. A whole live-config hash proved too broad because Codex owns unrelated config; targeted pre/post Pallium hook trust entries were unchanged. The temporary home and copied auth were deleted.
- 2026-09-08: PR review identified that the focused assertions did not directly pin the restart wording; added the two exact installer/docs assertions and reran both regression tests (2 passed).

## Evidence

- Exact setup/docs checks: `.venv\Scripts\python.exe -m pytest tests\test_codex_integration.py::test_codex_install_reports_hook_review_boundary_and_preserves_codex_trust tests\test_codex_integration.py::test_codex_setup_docs_require_owned_hook_review -q -n 0` → 2 passed.
- Affected file: `.venv\Scripts\python.exe -m pytest tests\test_codex_integration.py -q -n 0` → 29 passed. The initial run hit the pre-existing Windows skill-directory rename race; the exact node and prescribed `--lf --lfnf=none` reruns passed, then the affected file passed.
- Installed witness: real `.venv\Scripts\python.exe -m app.run setup codex` under an isolated `USERPROFILE`/`CODEX_HOME`, followed by real `codex -C C:\Dev\rore\Pallium --no-alt-screen "Reply exactly TRUST_WITNESS_OK. Do not use tools."` without a trust bypass.
- Installed results: Windows Codex CLI 0.149.1 displayed `3 hooks are new or changed`; Codex's UI persisted exactly three isolated `trusted_hash` entries; SessionStart, UserPromptSubmit, and Stop all completed; the bounded turn returned `TRUST_WITNESS_OK`; one isolated hook-state file proved UserPromptSubmit execution; targeted live Pallium trust entries were unchanged; the isolated auth and home were removed.
- Full repository gate: `.venv\Scripts\python.exe -m pytest tests\ -x -q` → 4658 passed, 32 skipped, 2 xfailed, with four pre-existing Pydantic warnings in 194.88s.
- `.venv\Scripts\python.exe scripts\agent-workflow-check.py --repo-root . --slug relay-codex-first-run-readiness` → clean; `git diff --check` → clean.
- Skill-feedback check: all triggers No.

## Result review

2026-09-08 clean-context review by /root/review_relay_first_run_result: APPROVE. Evidence supports all completion criteria and the Windows Codex 0.149.1-qualified roadmap status; Codex retains trust ownership and the diff remains minimal. Approval reconfirmed after the PR-review restart-assertion follow-up; 2 focused tests passed.