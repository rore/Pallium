<!-- agent-workflow:start -->
**Outcome:** For an exact empty-wake instruction that supplies a `relay-delivery-*` identifier, a fresh Codex decision selects Relay trace with that exact identifier as `message_id`, and the evaluation record reports the original valid fixture honestly.

**Target:** Pallium.

**Scope:** `integrations/claude-code/claude_md_block.py`; `integrations/codex/AGENTS.md`; `integrations/opencode/AGENTS.md`; `tests/test_guidance_budget.py`; `tests/test_codex_integration.py`; `tests/test_claude_code_integration.py`; `.agent-workflow/tasks/optimize-always-loaded-guidance.md`; `roadmap/features/optimize-always-loaded-guidance.md`; `.agent-workflow/tasks/fix-empty-wake-trace-id-guidance.md`.

**Constraints:** No Relay runtime, hook, installer, skill, tool-schema, service, or configuration change. Preserve all other compact-guidance safeguards and owner parity. Do not rerun unaffected smoke cases or claim Claude/OpenCode behavior evidence.

**Completion criteria:** The three owners explicitly map an exact supplied `relay-delivery-*` identifier into Relay trace's `message_id` argument; focused tests and owner-parity/budget checks pass; the original and relabeled case-4 fixtures and outcomes are documented without classifying the original as invalid; the affected original-prompt Codex Luna-low decision selects Relay trace with the exact identifier as `message_id`; independent review and CI pass. No executed Pallium-workflow claim is permitted.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Clean-context redline classified the integration guidance owners as gray and tests/records/roadmap as blue, with no boundary or checkpoint trigger. Moderate because the correction spans three generated owners, tests, prior evidence, one bounded model rerun, and review/PR closure.

**Discovery:** The original case-4 prompt said `Relay wake for relay-delivery-empty-example ... Inspect this exact delivery by message_id.` Relay trace accepts an exact delivery ID as the value of its `message_id` argument. Both original baseline and candidate responses failed to trace it. The fixture was then relabeled `Relay wake for message_id=relay-delivery-empty-example ...`; both relabeled runs passed and the original pair was incorrectly excluded as an ambiguous/invalid fixture. PR #202 merged before the delayed architect delivery exposed this error. Current guidance says only `trace only that delivery`, which did not teach the required argument mapping.

**Material assumptions:** The preserved original baseline is reusable only after positively matching prompt, model, catalog, stubs, cap, response schema, and baseline guidance revision; any mismatch requires one bounded two-arm rerun. Adding one explicit argument-mapping clause is sufficient; a failed original-prompt candidate rerun returns the task to planning without broader infrastructure work.

**Plan:** 1. Record and review this Work Record before code edits. 2. Add the smallest cross-owner clause: for an exact empty wake, pass the supplied exact delivery identifier as Relay trace's `message_id`; keep all other guidance unchanged. 3. Update only focused assertions and correct the prior Work Record/roadmap evidence: original pair valid and failed, relabeled pair passed but is not the primary oracle. 4. Reuse the preserved original baseline result and run only one fresh candidate decision on the exact original prompt with the same Codex Luna-low fixture/catalog/stubs/caps, preserving the response separately. Stop and return to planning if it fails. 5. Run focused tests, owner parity/budget/control checks, the repo-required one-time `python -m pytest tests/ -x -q`, workflow/redline checks, independent result review, CI, resolve review threads, and merge. Key convention: one identical marker block across all three owners; no new helper or framework. Target files are the nine concrete paths in Scope.

**Verification plan:** Exact delivery-ID mapping appears identically in all owners and emitted variants → focused guidance budget and integration tests plus byte-normalized parity check. Existing safeguards and budgets remain within their adjusted exact ceilings, with the mapping asserted in both generated base and strong arms → the same focused tests. Original case-4 behavior improves without replacing the fixture → preserved baseline failure compared with one fresh candidate run on the exact original prompt, independently graded. Evidence is honest and scoped → clean-context/result review plus Work Record/roadmap diff inspection. Repository remains healthy → workflow/redline checks and PR CI.

**Plan review:** Clean-context high-reasoning reviewer `/root/empty_wake_plan_review` returned PASS after three blockers were corrected; see `## Plan review`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-15: Created from `origin/main` commit `f22c7574` in isolated branch `feat/fix-empty-wake-trace-id-guidance`. Applicability is non-exempt because integration and Work Record paths are in scope. Clean-context redline returned GRAY: integration owners gray, tests/records/roadmap blue, no boundary or checkpoint trigger. Agent-workflow feedback trigger 2 was dropped because the defect is owned by Pallium integration guidance, not upstream agent-workflow.
- 2026-09-15: Replaced only the deficient empty-wake clause in all three guidance owners, added focused assertions in the shared safeguard test and both generated Codex/Claude arms, and raised exact measured ceilings. Focused verification passed 76/76; normalized owners match at 2,818 characters / 401 words with no invalid control characters.
- 2026-09-15: Reused the positively matched original baseline and ran one fresh Codex `gpt-5.6-luna` low candidate on the exact original prompt. It loaded the skill and selected Relay inspection with `message_id=relay-delivery-empty-example`, without receive/resend. Thread `01a0a4a2-f6b9-7ea1-a908-86280d1a22b9`; 47,349 input / 649 output tokens; one actual tool call (skill read), within cap.
- 2026-09-15: Fresh import-boundary report returned GRAY with no boundary violations or checkpoints; agent-workflow check passed clean. The delegated full-suite process hit machine-local Windows error 1327 before tests started. The elevated full suite then found one unrelated xdist failure in `test_unreachable_transport_retains_capability_but_preserves_newer_intent` after 1,470 passes; its exact serial node passed in 0.07 seconds and the prescribed last-failure run had nothing remaining. One bounded full-suite retry passed 5,018 with 34 skipped and 2 xfailed in 227.20 seconds. No further broad rerun was made.

## Plan review

- /root/empty_wake_plan_review challenged the execution-vs-decision claim, recoverability/compatibility of the reused baseline, omitted full-suite/both-arm verification, and categorical scope. The Work Record narrowed the claim to Codex decision selection, positively verified and recorded every reused-run input plus archive identifiers, named all nine files, and added the missing checks. Final clean-context re-review returned PASS with no remaining blocker.

## Evidence

- Exact original setup preserved in root Codex task `01a08755-3cf7-7691-94c7-643c67e3f3ca` and archived baseline/candidate JSONL: `The exact instruction injected for this turn is:\n"Relay wake for relay-delivery-empty-example. If no Relay message block accompanies this turn, do not conclude the inbox is empty and do not receive or resend. Inspect this exact delivery by message_id."\nNo Relay message block accompanies it.\nA trace, if requested, would report state=delivered.\n\nDetermine the next operation or operations.`
- Exact relabeling performed later: replace `Relay wake for relay-delivery-empty-example` with `Relay wake for message_id=relay-delivery-empty-example`; no other case-4 text changed.
- Archive root is resolved by `.worktrees/optimize-always-loaded-guidance/.local/guidance-smoke-20260915/temp-path.txt`. Distinct files are `codex/{baseline,candidate}/results/case-4-attempt-1-invalid-fixture.jsonl` for the original prompt and `codex/{baseline,candidate}/results/case-4.jsonl` for the relabeled prompt; all four exist. The legacy filenames are retained but are not evidence classification.
- Compatibility verified before reuse: original baseline `codex/baseline/AGENTS.md` has SHA-256 `51921d503a01ee7da7ba59cf74ed03befb47288b0b84934fb47e561d09a56c92`; its content matches `e53755a5:integrations/codex/AGENTS.md` after newline normalization and terminal-newline trimming; both arms used Codex CLI `gpt-5.6-luna`, low reasoning, ephemeral JSON/read-only mode, the same normally exposed `pallium-memory` catalog, response schema, and MCP stub pointed at closed port 9 with `PALLIUM_AGENT_REF=guidance-smoke`; the prompt capped four reasoning/tool cycles and six tool calls. Original baseline and candidate both failed to select trace. Relabeled baseline and candidate both selected trace. No configuration mismatch was found, so the original baseline is reused and only the corrected candidate is rerun.
- Corrected candidate output is preserved separately at `codex/candidate-fix-empty-wake/results/case-4-original-final.jsonl` under the same archive root. It selected the exact trace argument and did not execute Pallium; the MCP stub remained unavailable by design.

## Reproduction

The preserved original and fresh candidate commands used the same invocation contract: `codex exec --ignore-user-config --skip-git-repo-check --ephemeral --json --sandbox read-only --add-dir <installed-pallium-memory-skill> -m gpt-5.6-luna -c model_reasoning_effort="low"` plus the archived response schema and identical MCP command/args/environment described above. `-C` selected the archived baseline or candidate directory; the fresh candidate directory contains the corrected `AGENTS.md`. The exact shared prompt prefix was:

```text
This is a read-only decision exercise. Follow the project instructions. Do not execute external operations or change files; report only the operations you would attempt. Use at most four reasoning/tool cycles and six tool calls. Return only the requested JSON.
```

It was followed by `case_id=4` and the exact original case text recorded above. The archived JSONL files retain thread IDs, tool activity, structured response, and token usage; the root task retains the literal machine-specific commands. No general runner or committed fixture was added.

## Result review

- Independent high-reasoning review `/root/empty_wake_result_review` returned PASS with no blocking findings after verifying the original case-4 failures, relabeled passes, fresh candidate exact `message_id` selection, corrected scores and totals, normalized owner parity, budgets, scope, risk, and test evidence. It required three precision corrections before passing: distinguish reconstructed original-prompt scores from the first complete relabeled corpus, preserve the full case wrapper, and state normalized rather than byte equality for the archived baseline guidance. PR CI remains a separate completion gate.
