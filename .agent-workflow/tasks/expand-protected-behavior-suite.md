<!-- agent-workflow:start -->
**Outcome:** Pallium has a growing executable protected suite spanning its main caller-visible product behaviors, not a single pilot test or a hand-maintained Markdown test catalog.

**Target:** Pallium.

**Scope:** Expand `tests/behavior_contracts/**` across Relay, Session History, and Derived Memory; replace its per-test README inventory with scalable selection guidance and local test provenance; adjust exact duplicate legacy tests only if safe; align the owning roadmap item and record evidence here.

**Constraints:** Preserve accepted behavior, public APIs, production code, `agent-redline-policy.yaml`, existing CI, and workflow-only protection. No branch protection, CODEOWNERS, or dedicated CI job. Do not protect broad mixed-purpose files or promote implementation details, unsupported promises, flaky live checks, or regressions without a failure witness.

**Completion criteria:** The protected directory contains at least twelve distinct deterministic caller-visible regression tests across Relay, Session History, and Derived Memory; each states its product source and failure class near the executable test, exercises a public HTTP/MCP/hook surface and read path, and has a demonstrated historical or controlled-fault failure witness. The README contains selection and organization rules instead of enumerating tests. The existing PR `test` job and Agent Workflow checks pass for the expanded suite.

**Requirement baseline:**
{"source":"user request_source_item_id b251bead-028d-403f-8133-d17d6f1009a9","outcome":"Pallium has a growing executable protected suite spanning its main caller-visible product behaviors, not a single pilot test or a hand-maintained Markdown test catalog.","scope":"Expand `tests/behavior_contracts/**` across Relay, Session History, and Derived Memory; replace its per-test README inventory with scalable selection guidance and local test provenance; adjust exact duplicate legacy tests only if safe; align the owning roadmap item and record evidence here.","constraints":"Preserve accepted behavior, public APIs, production code, `agent-redline-policy.yaml`, existing CI, and workflow-only protection. No branch protection, CODEOWNERS, or dedicated CI job. Do not protect broad mixed-purpose files or promote implementation details, unsupported promises, flaky live checks, or regressions without a failure witness.","completion_criteria":"The protected directory contains at least twelve distinct deterministic caller-visible regression tests across Relay, Session History, and Derived Memory; each states its product source and failure class near the executable test, exercises a public HTTP/MCP/hook surface and read path, and has a demonstrated historical or controlled-fault failure witness. The README contains selection and organization rules instead of enumerating tests. The existing PR `test` job and Agent Workflow checks pass for the expanded suite."}

**Risk:** High

**Complexity:** Large

**Reason:** `tests/behavior_contracts/**` is a Redline-protected product contract surface; choosing and extracting many accepted behaviors across product areas carries semantic downgrade and false-coverage risk. Multi-domain audit and witness verification make this a large task.

**Discovery:** Pending requirements-first test audit and pre-edit Redline classification.

**Material assumptions:** Accepted public requirements with deterministic existing tests and reproducible failure classes exist in all three named domains; if not, stop and narrow only with task-owner approval rather than manufacture coverage. Existing fixtures can be reused without production changes; if not, replan.

**Plan:** 1. Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit. 2. Audit authoritative requirements and existing test nodes; select a substantial first wave with public-surface assertions and failure witnesses. 3. Obtain clean-context plan review and explicit High-risk task-owner approval before protected-path edits. 4. Add domain-organized protected tests and local provenance, simplify README, avoid duplicate legacy execution when safe. 5. Run focused, affected, and full test checks plus controlled witnesses; classify every protected path in this Work Record, then get independent result review and PR verification. Stop if an accepted requirement or witness cannot be established.

**Verification plan:** When a selected accepted behavior regresses, its protected public-surface test shall fail → historical or controlled-fault witness for each new contract. When current Pallium runs the suite, all protected tests shall pass → focused directory and affected subsystem pytest. When the PR runs, the existing `test` job shall execute the directory and Agent Workflow shall validate every protected path's classification and verification linkage → hosted CI and local combined checker. README shall not list each test → diff review.

**Plan review:** Pending clean-context review after discovery.

**Approvals:** Pending explicit user approval of the reviewed High-risk expansion plan.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->
