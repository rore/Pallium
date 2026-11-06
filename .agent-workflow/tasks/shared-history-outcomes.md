# Shared History search outcomes

<!-- agent-workflow:start -->
**Outcome:** All four Pallium integrations share guidance for capability availability, scoped Session History search outcomes, and evidence of later recall.

**Target:** Bundled Pallium History replay references.

**Scope:** Append the approved capability and search outcomes section to the existing Claude Code, Codex, OpenCode, and Hermes History replay references. Record the work in this Work Record.

**Constraints:** Preserve the four skill files, existing replay guidance, Hermes catalog and scope rules, and the existing parity and size guards. Keep the OpenCode V2 change separate. Use an isolated source candidate.

**Completion criteria:** The four bundled replay references contain the same approved appendix. The first three references retain byte parity, and all four keep their existing links and prefixes. Verify guidance and packaging guards and the selected whole-change lane.

**Requirement baseline:** {"source":"work-record-initial","outcome":"All four Pallium integrations share guidance for capability availability, scoped Session History search outcomes, and evidence of later recall.","scope":"Append the approved capability and search outcomes section to the existing Claude Code, Codex, OpenCode, and Hermes History replay references. Record the work in this Work Record.","constraints":"Preserve the four skill files, existing replay guidance, Hermes catalog and scope rules, and the existing parity and size guards. Keep the OpenCode V2 change separate. Use an isolated source candidate.","completion_criteria":"The four bundled replay references contain the same approved appendix. The first three references retain byte parity, and all four keep their existing links and prefixes. Verify guidance and packaging guards and the selected whole-change lane."}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** The four integration references are outside the documentation-only allowlist. Redline classifies them as gray, with no protected contract, red zone, or checkpoint.

**Discovery:** Each bundled skill links to an existing History replay reference. Claude Code, Codex, and OpenCode share identical reference bytes. Hermes supplies trusted scope and omits the status tool from its model catalog. The appendix makes status conditional.

**Material assumptions:** The reviewed reference preimages and linked skills match the selected clean upstream. A mismatch stops the append before source edits.

**Plan:** Append the identical reviewed section to each reference and compare all four prefixes, appendix bytes and skill links. Keep the Hermes preamble intact.

**Verification plan:**
- Identical appendix and first-three parity → raw-byte comparison of four references and original prefixes.
- Existing skill and link guards → focused guidance budget and Hermes packaging checks.
- Whole-change scope → current-main selector, Redline and Agent Workflow checks and the selected lane.

**Plan review:** Agent technical review: retained four-reference History appendix review, 2026-11-05, technical GO.

**Approvals:** Not required at this risk level. The task owner requested the shared guidance across hosts and the manager selected this isolated source scope.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

The clean private checkout uses current main. All four reference preimages matched the reviewed content. The source edit is limited to the same appended section in the four existing references.

The four references now contain the approved appendix. Source preparation was selected separately from verification execution. The existing guidance budget, replay parity and Hermes reference packaging checks and the selector's non-slow lane remain due.

On 2026-11-05 the task owner selected “Use draft PR CI for this update.” This one-time exception to local-first ordering applies to the exact four-reference update. The first full run is pending through ordinary draft PR CI. Both Linux jobs must pass all 11 cases in `tests/test_guidance_budget.py` and `tests/test_setup_hermes.py::test_setup_status_repeat_and_remove_preserve_unrelated_profile`. Windows smoke omits these 12 cases. Windows smoke and governance are required separately. Merge and rollout require separate decisions.
