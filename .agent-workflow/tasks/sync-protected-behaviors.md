<!-- agent-workflow:start -->
**Outcome:**
Pallium uses the latest Agent Workflow consumer assets, and its protected-behavior roadmap defines a concrete, evidence-based adoption plan without enabling protection prematurely.

**Target:**
Pallium.

**Scope:**
Refresh the installed Agent Workflow skill/runtime/hook/plugin/doc assets and owned AGENTS marker; update `roadmap/features/add-protected-behavioral-requirements-regression-suite.md`; add this Work Record.

**Constraints:**
Preserve Pallium configuration, third-party hooks, application code, CI, CODEOWNERS, historical Work Records, and existing behavior. Do not add `behaviorContracts` policy until candidate paths have required-CI and ownership evidence.

**Completion criteria:**
The installed assets match one pinned upstream `main` revision; installation/config regression checks pass; the roadmap names the protected path strategy, qualification rules, migration sequence, and evidence required before policy activation.

**Requirement baseline:**
{"source":"user-request:a55d6d9e-d71c-48e3-8fdd-f6c2e1a7b503","outcome":"Pallium uses the latest Agent Workflow consumer assets, and its protected-behavior roadmap defines a concrete, evidence-based adoption plan without enabling protection prematurely.","scope":"Refresh the installed Agent Workflow skill/runtime/hook/plugin/doc assets and owned AGENTS marker; update `roadmap/features/add-protected-behavioral-requirements-regression-suite.md`; add this Work Record.","constraints":"Preserve Pallium configuration, third-party hooks, application code, CI, CODEOWNERS, historical Work Records, and existing behavior. Do not add `behaviorContracts` policy until candidate paths have required-CI and ownership evidence.","completion_criteria":"The installed assets match one pinned upstream `main` revision; installation/config regression checks pass; the roadmap names the protected path strategy, qualification rules, migration sequence, and evidence required before policy activation."}

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Clean-context Redline classified the mixed consumer footprint GRAY because skill, hook, settings, and plugin paths are unclassified. The refresh spans several runtime integrations and a new governance contract.

**Discovery:**
Agent Workflow `main` is clean and pinned at `b239a80`; behavioral integrity landed in `f6a68c6`, `8fc0cd8`, and `ff08171`. Pallium's dual skill trees and vendored checker/reporter/schema/runtime assets predate it. Pallium has no CODEOWNERS, `main` has no branch protection or rulesets, and the customized CI workflow lacks the upstream base-revision CODEOWNERS evidence path, so `behaviorContracts` cannot be activated safely in this task. Existing Relay regressions are spread across broad files; protecting those files directly would route unrelated maintenance through behavior review.

**Material assumptions:**
Pinned upstream `b239a80` is the intended source; disprove by source inconsistency or failing consumer verification, then stop. A new dedicated contract directory can share one required CI and owner set; disprove during candidate evidence review, then split or defer incompatible candidates rather than weakening controls.

**Plan:**
1. From pinned `C:\Dev\rore\agent-workflow` `b239a80`, overlay `dist/agent-workflow/**` onto both `.agents/skills/agent-workflow/**` and `.claude/skills/agent-workflow/**`; require every manifest entry and size to match and stop on unexplained extra executable files rather than deleting extras. Byte-copy these mappings: `dist/agent-workflow/scripts/{agent-workflow-check.py,agent-workflow-runtime.py,agent-workflow-runtime.sh,agent-workflow-runtime.ps1,format-verdict-comment.py}` → `scripts/`; `dist/agent-workflow/agent-redline/scripts/agent-redline-report.py` and `agent-redline/extensions/python/scripts/run-import-linter.py` → `scripts/`; the Redline policy schema → `.agent-redline/agent-policy.schema.json`; all six `dist/agent-workflow/hooks/*` → `.claude/hooks/`; the OpenCode plugin → `.opencode/plugins/agent-workflow.mjs`; checkpoint and Redline reference docs → their existing `docs/` mirrors. Merge only the owned AGENTS marker with `merge-agents-section.py`; run `install-settings.py` against explicit Claude and Codex files. Snapshot and reject non-owned settings/hook/AGENTS changes. Do not touch the customized CI workflow, policies, CODEOWNERS, application code, or history. 2. Refine the queued roadmap around `tests/behavior_contracts/**`: one plain Markdown catalog and dedicated public-surface E2E regressions selected from accepted behavior plus original failure evidence. State the real enforcement split: the required `behavior-contracts` check proves execution; Redline makes protected-path edits red and requires classification/linkage; base-branch CODEOWNERS plus required Code Owner review authenticates repository authority; humans decide whether `equivalent` or `coverage-only` is honest. No custom semantic-equivalence parser or weakening detector. Future activation uses two gates: first merge an explicitly authorized governance/CI PR adding CODEOWNERS, base-revision CODEOWNER evidence plumbing, the dedicated check, required status, and required Code Owner review; verify them live. Only a later reviewed PR may add the Redline `behaviorContracts` block. Stop if candidates do not share the same required check and last-match owner set. 3. Run `uv run python .claude/hooks/install-settings.py --runtime claude --settings .claude/settings.json`, `uv run python .claude/hooks/install-settings.py --runtime codex --settings .codex/hooks.json`, and `uv run python .claude/hooks/merge-agents-section.py --file AGENTS.md --template C:\Dev\rore\agent-workflow\dist\agent-workflow\templates\agents-section.md.template` twice to a zero diff. Verify source mappings, non-owned preservation, script/schema syntax, the existing workflow merge-base regression, fresh Redline/workflow checks, and the repository suite required before review.

**Verification plan:**
When the sync completes, every manifest entry in both skill trees and each explicit byte-copy mapping shall match pinned `b239a80`, with no unexplained extras or non-owned config change → manifest/hash inventory, exact diff review, and second runs of the three exact installer/merge commands in Plan step 3 producing zero diff. When the roadmap is reviewed, it shall define the path, inclusion/exclusion rules, original-failure witness, truthful enforcement split, and two-stage activation prerequisites → exact roadmap diff inspection. Existing consumer behavior shall remain green → `uv run python -m pytest tests/test_agent_workflow_ci.py -q -n 0` for its actual merge-base/PR-head invariant; `uv run python -m py_compile` for copied Python scripts/hooks; JSON/YAML schema validation; fresh Redline verdict plus `uv run python scripts/agent-workflow-check.py --repo-root . --slug sync-protected-behaviors`; then `uv run python -m pytest tests/ -x -q` once.

**Plan review:**
Clean-context review `/root/plan_review`: APPROVE after two revision rounds. See `## Plan review`.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Established task context and requirement baseline before repository edits.
- Clean-context Redline verdict: GRAY; no boundary finding, checkpoint, watch flag, or contract-surface flag. Agent Workflow mapping: Elevated risk.
- Clean-context plan review approved after the enforcement model, explicit file mapping, idempotence commands, and staged activation gates were corrected.
- Synced pinned Agent Workflow `b239a80` into both skill trees and all explicit consumer mappings; upstream helpers changed only the owned AGENTS marker and preserved Claude/Codex settings. Refined the protected-behavior roadmap around a dedicated contract directory and requirements-first selection.
- Trigger 1 dropped: repeated `apply_patch` failure `1327` is the documented machine/runtime constraint, not an Agent Workflow defect; deterministic replacements were limited to the Work Record and roadmap file.


## Plan review

Clean-context reviewer `/root/plan_review` returned REVISE:

- Replace the roadmap's automated semantic-weakening claim with the actual split among required CI, Redline path protection and classification, CODEOWNERS authority, and human semantic judgment.
- Enumerate authoritative source-to-destination mappings and distinguish byte copies from merge-controlled settings and AGENTS content.
- Name exact idempotence commands, preservation assertions, and manifest/extras handling.
- Split future governance/CI enablement from later `behaviorContracts` activation and require live verification between them.

The Plan and Verification plan above incorporate all four findings. First re-review requested exact runnable checks and full helper commands; both were specified. Final re-review verdict: APPROVE.
## Evidence

Verified the exact working tree on `feat/sync-protected-behaviors`, based on Pallium `e7e68067f3ddd0f4837714fe241e06770f22b064`, against Agent Workflow `b239a80b427ae96ac0e6fed8e3b9d49cbde187ae`:

- both skill trees: 67 source files, 67 target files, zero missing/extra/different; every explicit script/schema/plugin mapping matched by SHA-256
- hooks and documentation mirrors: byte-identical; Claude settings, Codex hooks, guarded-paths sidecar, and AGENTS merge were byte-idempotent on the second exact run
- copied Python scripts/hooks compiled; `agent-workflow.yaml` and `agent-redline-policy.yaml` validated against the synced schemas
- `uv run python -m pytest tests/test_agent_workflow_ci.py -q -n 0`: 1 passed
- import-linter: no boundary violations; fresh Redline: GRAY, no checkpoint; synced workflow checker: clean
- `uv run python -m pytest tests/ -x -q`: 5096 passed, 34 skipped, 2 xfailed in 230.83s
- `git diff --check`: passed

## Result review

Independent non-implementer `/root/plan_review`: APPROVE after the roadmap overclaim was narrowed. Completion criteria, evidence, scope, assumptions, final Elevated risk, source parity, and enforcement claims were accepted.