# reuse-kpi-artifact-taxonomy

The primary reuse KPI's eligible-session denominator is ~zero on real Claude/Codex traffic: the
substantive predicate requires assistant `artifact_kind IN {assistant_output, tool_use_summary,
todo_snapshot}` (simulation-only kinds), but production stop hooks write assistant turns as
`artifact_kind="message"`. Fix: also count a production assistant `message` with non-empty content as
substantive work. Non-empty guard matters — a tool-only turn writes an EMPTY-content `message`
(`integrations/codex/hooks/stop.py:146` exits only when BOTH assistant_text AND tool_calls are empty),
which must NOT qualify.

<!-- agent-workflow:start -->
**Outcome:**
`_reconstruct_eligible_sessions` counts a real assistant turn (`role='assistant'`,
`artifact_kind='message'`, non-empty content) as substantive work, alongside the existing simulation
kinds. Real Claude/Codex sessions now enter the eligible denominator; empty-content tool-only `message`
rows still do not. No change to eligibility-N / prior-indexed / forgotten logic.

**Target:**
`evals/historical_lookup_measurement.py` (`_reconstruct_eligible_sessions` only) + one test. Offline
eval; no production runtime path.

**Scope:**
- SELECT `length(content)` in the session query; classify assistant `message` as work only when non-empty.
- Update the pinned-predicate docstring to match.
- One test: assistant `message` (non-empty) + user turn → eligible; tool-only empty-content `message` → not substantive.

**Constraints:**
- Do NOT change the prior-indexed / eligibility-N / forgotten-exclusion logic.
- Empty-content `message` (tool-only turns) must not qualify.
- No internal/product names.

**Completion criteria:**
A session of user + non-empty assistant `message` turns is eligible; an empty-content-only assistant
session is not; existing simulation-kind tests still pass; new test added; suite green.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Offline eval-only, single function, ~5-line localized change with a test; no guarded/red
runtime path. (If redline CI detects a higher zone, bump to expanded + clean-context review.)

**Approach:**
Add a non-empty check for `message`-kind assistant turns in the existing Python aggregation; select
`length(content)` from SQL to avoid transferring blobs.

**Verification:**
New test in the measurement test module; full `pytest tests/ -q` (expect the known pre-existing
`test_config` env-leak failure only); redline + agent-workflow CI.

**State:** Ready for review
<!-- agent-workflow:end -->
