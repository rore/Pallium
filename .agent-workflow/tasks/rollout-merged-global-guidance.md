<!-- agent-workflow:start -->
**Outcome:** The installed managed Pallium guidance for Codex and Claude exactly reflects merged commit `c419981b` while every user-authored and unrelated section remains byte-preserved.

**Target:** Pallium local Codex and Claude integrations.

**Scope:** Update only the managed Pallium blocks in `C:\Users\I347041\.codex\AGENTS.md` and `C:\Users\I347041\.claude\CLAUDE.md`; record this rollout in this Work Record.

**Constraints:** Use the stable merged source and a supported guidance-only updater when available. Preserve user cost/model/Relay bullets and all unrelated text. Do not contact `relaydev` or `workflow-dev`, create Claude sessions, change hooks/settings/trust, restart services/hosts, or rerun behavior tests.

**Completion criteria:** The two installed managed blocks match their merged emitted base guidance exactly; before/after evidence proves hooks and trust unchanged, user/unrelated text preserved, and actual installed sizes reported.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Clean-context redline classified the Work Record blue and external global instruction files gray, with no boundary, red zone, contract surface, or checkpoint. Elevated because global instructions affect every local agent; simple because only two managed blocks may change.

**Discovery:** Full `pallium setup codex` and `pallium setup claude-code` are unsuitable: they also reconcile MCP/config/hooks/readiness, reinstall skills, create state, probe the service, and may require restart. Existing tested helpers `_append_agents_md_block("base")` and `_append_claude_md_block("base")` replace only marker-bounded guidance. Dry-run replacement from stable commit `c419981b` found exactly one marker pair and base arm in each file, exact preserved prefix/suffix text, CRLF-only inputs, and expected blocks of Codex 2,859 chars / 404 words and Claude 2,858 / 404.

**Material assumptions:** A supported updater can replace guidance without mutating hook definitions, trust, settings, or services; if not, stop and report its exact side effects before execution. Managed markers are unique and user additions are outside them; otherwise stop without writing.

**Plan:** From stable isolated commit `c419981b`, create durable raw-byte backups and a manifest under ignored `.local/rollout-merged-global-guidance/` before either target write. The manifest records exact path/existence/SHA-256 for both guidance files and every frozen Codex/Claude hook, settings, config, readiness, and trust file, plus commit and SHA-256 provenance for both helper modules and guidance sources. Exercise each tested `_append_*_block("base")` helper against a same-filesystem staging copy; require exact raw prefix/suffix preservation and retain the complete expected output bytes. Immediately before final writes, rehash every target/frozen file against the manifest. Invoke only the same two helpers on the real targets; never call either full installer. Require final bytes to equal staged expected bytes, frozen hashes/readiness state to remain unchanged, and installed blocks/sizes to match merged output. On any write or verification failure, restore both raw backups, verify restoration hashes, and retain recovery artifacts; if restoration fails, stop and report exact recovery paths.

**Verification plan:** Exact managed-block equality → normalized installed marker text equals merged emitted text after removing its single terminal newline outside the end marker, and complete final raw files equal staged helper output. Preservation → raw prefix and suffix bytes outside each marker span equal their durable backups. No hook/trust/settings mutation → every frozen path hash and bounded readiness/trust state equals its immediate pre-write manifest. Recovery → inject no failure, but on any observed mismatch restore and hash-check both backups before reporting. No service restart → perform no service operation. Installed sizes → measure final managed blocks directly.

**Plan review:** Clean-context high-reasoning reviewer `/root/rollout_plan_review` returned PASS after the durable recovery, byte-equality, immediate drift-check, complete manifest, and bounded trust-state corrections; see `## Plan review`.

**Approvals:** Not required at this risk level; user explicitly requested local rollout.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-15: Created isolated branch `feat/rollout-merged-global-guidance` from merged `origin/main` commit `c419981b`. Applicability is non-exempt because global agent instructions and a Work Record are outside the documentation-only allowlist. Clean-context pre-edit redline returned GRAY with no boundary, checkpoint, or contract finding.
- 2026-09-15: Discovery rejected the full setup commands because they mutate surfaces explicitly frozen during relay wake investigation. The existing tested marker replacement helpers are guidance-only; a no-write preview confirmed unique markers, base arms, exact stable-source blocks, CRLF-only inputs, and preservation of all text outside each managed block.
- 2026-09-15: The first guarded staging attempt stopped before target writes because the builder output includes one terminal newline after the end marker while marker-span extraction ends at the marker. Both installed hashes remained unchanged. Independent re-review approved comparing the span to builder output with only that terminal newline removed, while retaining whole-file staged byte equality; the first recovery directory is preserved and attempt 2 will use a new directory.
- 2026-09-15: Attempt 2 used only the two reviewed `_append_*_block("base")` helpers. Durable backups and the complete manifest were written before either target update. Both installed files exactly matched their staged helper outputs; raw prefix/suffix bytes were preserved; all frozen hook, config, settings, readiness, and trust files remained byte-identical; bounded Codex readiness remained `verified` with hook trust and MCP exposure `unknown`. No setup command, service/host restart, hook change, settings change, task contact, or behavior test occurred.
- 2026-09-15: Fresh import-boundary, redline, agent-workflow, repository-scope, and whitespace checks passed. The final repository diff is only this Work Record. Independent high-reasoning result review returned PASS with no remaining finding.

## Plan review

- `/root/rollout_plan_review` confirmed the private tested helpers are the narrowest existing updater path but blocked execution on three gaps: recovery covered exceptions rather than verification failures, helper newline reconstruction was not proven byte-preserving, and the snapshot/provenance manifest was underspecified.
- Plan amended to stage through the actual helpers, preserve durable original bytes before either write, compare raw prefix/suffix and complete expected bytes, recheck all hashes immediately before writing, roll back both targets on write or verification failure, verify restoration, retain failed recovery artifacts, and record exact source/frozen-file provenance. Re-review returned PASS with no remaining blocker.

## Evidence

- Pre-rollout Codex readiness was `verified`; Codex-owned hook trust and MCP exposure were and remain `unknown` by the bounded public readiness API. Attempt-2 manifest and raw backups: `.local/rollout-merged-global-guidance-attempt2/`. The stopped pre-write attempt remains at `.local/rollout-merged-global-guidance/`.
- Codex global guidance changed SHA-256 `2f21342f353c2050644a82909304957e1d7dd2ae65d3424be9126843e2891be9` → `35f4d932e784ee59e354fe8723a1344c153af02a3c05e3edf6a8f4799d8da144`; final file 5,986 bytes. Claude changed `f183b3f0e59fab65a3a50dd0d5d2f3268f2d021ba3477c036c6f4631bd2d3f0d` → `aa5884988d8107adb0837d18a058db72cdb5d70445fe29714957dfa4ed49a272`; final file 6,689 bytes.
- Actual installed marker spans are 2,858 characters / 404 words for both runtimes. Merged emitted base sizes are Codex 2,859 / 404 (one terminal newline after the end marker) and Claude 2,858 / 404. Independent reconciliation returned `all_pass=true`: whole files equal staged helper output, marker text equals merged output, raw user/unrelated prefix and suffix bytes are unchanged, and all five frozen non-guidance files plus readiness state are unchanged.

## Result review

- Independent high-reasoning reviewer `/root/rollout_result_review` returned PASS. It reconciled both installed base blocks to merged `c419981b`, verified all sizes and hashes, confirmed raw preservation of user/unrelated text including cost/model/Relay bullets, confirmed all five frozen files unchanged, and found the stopped attempt consistent with no target writes. It also confirmed no full-installer or restart claim.
