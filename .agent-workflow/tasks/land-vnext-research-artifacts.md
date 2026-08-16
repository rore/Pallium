# land-vnext-research-artifacts

Lands the reusable eval instruments from the vNext injection-vs-pull validation cycle, an
anonymized findings doc, and two follow-up tickets the data implies. First all-blue PR
under the `.agent-workflow/**` blue-list (#27) — should classify Routine.

<!-- agent-workflow:start -->
**Outcome:**
The two new decision-harness scenario sets are committed; an anonymized findings doc
records the injection-vs-pull results; two follow-up tickets are filed and on the board.

**Target:**
Pallium — `evals/history_pull_decision/` (scenario data), `docs/research/` (findings),
`roadmap/` (tickets + board). Docs/eval-data only; no runtime or logic code.

**Scope:**
Add `evals/history_pull_decision/scenarios_cold.json` + `scenarios_overpull_control.json`
(already authored); add `docs/research/2026-08-16-injection-vs-pull-validation.md`
(anonymized — no internal/product/container names); add two ticket files under
`roadmap/ideas/` + list them on `roadmap/board.md`.

**Constraints:**
- Findings doc must contain NO internal/external/product names or raw container refs
  (describe as "focused single-project repo" / "multi-topic monorepo container").
- No code/logic/eval-harness changes — only new scenario DATA + docs + tickets.
- Report findings honestly with their caveats (small n, structural recall bias,
  uncalibrated representation judge, #5 not run).

**Completion criteria:**
Both scenario files + findings doc + two tickets committed; board lists the tickets; CI
green (expect all-blue → Routine).

**Risk:** Routine

**Complexity:** Simple

**Reason:** —

**Approach:**
Commit the authored scenario files; write the anonymized findings doc; author two tickets
(`idea-measure-pull-filtering-accuracy-and-cost`, `fix-add-limit-to-injection-replay-simulation`);
add both to board Ideas. Separately (not in the PR): delete the 451 MB scratch snapshot.

**Verification:**
JSON files parse; doc contains no disallowed names (grep); CI: agent-workflow, redline
(expect BLUE), test lanes (trivially pass — no code).

**State:** Ready to implement
<!-- agent-workflow:end -->
