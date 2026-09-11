# Workflow applicability

Load only when `agent-workflow.yaml` contains `applicability.documentationOnly` or during bootstrap discovery.

## Decision order

1. Require the workflow if any changed path is unapproved, protected, risky, duplicated, malformed, or missing from the evidence.
2. Otherwise use a branch/PR without a Work Record.
3. Direct default-branch work is the lowest priority and needs every condition below.

Never exempt config, policy, schema, CI, agent instructions, hooks, installed/vendored harness files, Work Records, normative specs, or paths traversing symlinks/junctions. A rename supplies both paths. Any doubt selects step 1.

## Bootstrap

Discover actual tracked documentation, roadmap/planning, and root README paths from the repository; names such as `roadmap/` are not canonical. Show exact candidates in an inert proposal. Persist only the human-approved subset; reject additions absent from the proposal and omit the block on refusal. Mirror approved ordinary documentation paths into Redline blue zones; keep governance exclusions red/watch.

Resolve the actual default branch and check classic protection plus applicable rulesets live. Enable direct-default only when separately approved and both prove unprotected.

Serialize proposed and approved paths as strict NUL files. Run `python <install-root>/scripts/agent-workflow-check.py --repo-root . --bootstrap-applicability-proposal-z <proposal> --bootstrap-applicability-approved-z <approved> --bootstrap-protection-status <status>` plus `--bootstrap-direct-default-branch-approved` only when separately approved. Copy its JSON fragment into the inert draft; null or nonzero omits the block.

## Runtime

At task pickup, resolve a trusted base with `git merge-base HEAD <actual-default-upstream>`. Always union exact intended paths (which may not exist) with `git diff --name-only -z --no-renames <merge-base>` (committed + dirty tracked) and `git ls-files --others --exclude-standard -z` (untracked), deduplicating byte-for-byte. Intent-only input is valid only after verifying the checkout is clean and not ahead. Missing base, incomplete intent, or incomplete union selects the normal workflow; recheck on scope changes.

Feed that NUL file to Redline and `agent-workflow-check --changed-files-z`. CI similarly diffs the trusted PR merge base to its real head. Only a passing `workflow.applicability` removes the Work Record requirement.

Before suggesting direct default-branch work, rerun the checker with `--check-default-branch-protection`; it resolves the actual default branch and checks GitHub protection plus applicable rulesets. If protection is present or cannot be proven absent, use a branch/PR without a Work Record. A normal workflow decision always wins. This gate never authorizes commit or push and never bypasses protection.

PR CI enforces the no-Work-Record exemption and still runs Redline and repository tests. It cannot police direct pushes; the runtime gate and repository protection are that control.