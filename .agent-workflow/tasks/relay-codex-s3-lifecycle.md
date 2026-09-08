<!-- agent-workflow:start -->
**Outcome:**
With the original sender idle, a real delivery-derived Codex reply resumes it solely through Relay and supports one attributed remediation turn; if the installed path already satisfies this, close the stale wake-first gate with evidence and no production code.

**Target:**
Pallium Relay's installed Codex request, reply, wake, and remediation journey.

**Scope:**
Installed no-ping dogfood evidence; `app/codex_wake.py` and `integrations/codex/hooks/**` only if a witnessed failure requires a root fix; focused existing caller-surface tests; `docs/codex-integration.md`; `roadmap/features/add-wake-first-relay-delivery.md`; this Work Record.

**Constraints:**
Value first: write no production code for already-working behavior. Do not add speculative telemetry, schemas, storage cleanup, dependencies, or macOS/OpenCode work. Do not edit shared Relay, core, or storage surfaces without renewed classification and coordination. Preserve durable next-turn fallback, exact scope, attribution, ordinary approvals, and exact-once delivery.

**Completion criteria:**
(1) With the original sender idle, one real no-ping request → delivery-derived reply resumes the sender solely through Relay—no user prompt, app message, manual wake, or unrelated turn—and the remediation follow-up is admitted without a manual recipient turn. (2) Any witnessed failure is fixed at the narrow shared cause and leaves caller-surface E2E that proves no loss, duplicate action, wrong-scope admission, or empty internal turn. (3) If the journey passes, no production code changes. (4) Roadmap and Codex docs distinguish proven behavior from remaining work and defer telemetry or platform expansion until a concrete usability or diagnosis need exists.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Redline classifies the possible runtime and integration paths as gray. The validation crosses request, delivery, reply, wake, and remediation boundaries, but excludes red-zone API, schema, storage, core, and security surfaces.

**Discovery:**
PR #85 already recorded a real unloaded Codex target reply that independently cold-woke its unloaded sender with no app ping or visible window. PR #108 later hardened completed/no-hook classification, exact-scope admission, and unreachable feedback, with a 108-test caller-surface suite and installed single-ACK witness. Current `tests/test_codex_wake.py` already covers the shared post-persistence reply callback and busy queued claim/reply idempotence. The wake-first roadmap still lists sender-side reply admission as remaining, so evidence and roadmap have drifted. A clean-context classification marked `app/codex_wake.py` and Codex hooks gray, tests/docs/roadmap blue, overall Elevated/Moderate, with no architecture review required. Coordination message `relay-msg-7c5ed1cb1d424c25bea176596335791b` reached the owner of the concurrent alias-loss/404 diagnosis; shared Relay/core/storage edits remain out of scope.

**Material assumptions:**
The installed Codex reply wake still behaves like the accepted PR #85 and PR #108 witnesses. Disproof is a current no-ping journey that fails to admit, misroutes, duplicates, loses the delivery, or produces an empty internal turn; then stop docs-only closure and fix only that witnessed cause within the classified scope. Existing lifecycle telemetry is sufficient to determine delivery/admission/failure for this validation; if the run cannot diagnose a real failure, add only the minimum correlation needed for that failure and reclassify first.

**Plan:**
(1) Use a real useful Relay collaboration as the no-ping journey: send the request, leave the original sender idle, let the delivery-derived reply resume it solely through Relay, then send one remediation or review follow-up that the recipient admits without a manual turn. (2) Inspect durable status and task-visible evidence for exact-once delivery, reply-only sender wake, attributed follow-up admission, and absence of empty turns. (3) If it passes, change only docs, roadmap, and this Work Record to close the stale sender-reply/sustained-loop gate and state which lower-value items remain deferred. If it fails, trace all callers of the failing seam, implement the smallest root fix within the classified Codex wake/hook scope, and extend the nearest existing caller-surface E2E. (4) Run focused verification, workflow/redline checks, one required full test run before review/PR, then independent result review. Stop and re-plan before any shared Relay/core/storage, schema, API, security, or new platform work.

**Verification plan:**
When the original sender is idle and the recipient replies, the system shall resume the sender solely through Relay and admit its remediation follow-up without a manual recipient turn → Relay status plus task-visible attribution evidence for both directions.
When the live journey exposes a failure, the system shall preserve exact scope, exact-once delivery, and non-empty attributed turns after the smallest root fix → nearest existing Codex wake and agent Relay caller-surface E2E plus one regression for the witnessed failure.
When the live journey passes, the change shall contain no production-code edit → `git diff --name-only`.
When the roadmap and Codex docs are updated, they shall distinguish proven behavior from explicitly deferred lower-value work → diff checked against current live evidence and accepted PR #85 and PR #108 records.
Before PR review, the branch shall pass focused tests, workflow/redline, whitespace, and one required full test run → `python scripts/agent-workflow-check.py --repo-root . --slug relay-codex-s3-lifecycle`, redline, `git diff --check`, and `python -m pytest tests/ -x -q`.

**Plan review:**
2026-09-08 clean-context review by /root/review_relay_value_plan: APPROVE after requiring an idle original sender resumed solely by Relay and remediation admission without a manual recipient turn.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-08: Created the Work Record before code. An earlier roadmap edit hit the known Windows `apply_patch` process failure and used the repository-approved deterministic PowerShell fallback; this record was created with `apply_patch`.
- 2026-09-08: Clean-context Elevated plan review approved the value-first no-code stop condition after strengthening the live gate to require an idle sender resumed only by Relay and a remediation follow-up admitted without a manual recipient turn.
- 2026-09-08: The real collaboration gate passed. Request `relay-msg-f07d6ebe0c054e4fa38872ef8a3393d7` reached the concurrent Codex owner and its delivery-derived reply resumed this idle sender solely through Relay. Remediation `relay-reply-5b5235201e41cfa596205f632ffbac301d41bae78c5628a9bec52a6e136a7710` was admitted without a manual recipient turn, answered `APPROVE`, and again resumed this idle sender.
- 2026-09-08: The run established no Pallium defect. Actor-scoped aliases correctly reject cross-actor lookup; older host sessions retain cached actor identity. Kept routing semantics unchanged and added no production code, telemetry, retention machinery, or platform expansion. Updated only the Codex guide, wake-first roadmap evidence, and this record.

## Evidence

- Relay status reports `delivered=1` for both outbound journey legs; hook-injected attributed replies prove both idle-sender resumes without app messaging, manual wake, unrelated turn, or manual recipient admission.
- Focused caller-surface regression: `.venv\Scripts\python.exe -m pytest tests\test_codex_wake.py tests\test_agent_relay_e2e.py tests\test_relay_wake_contract.py tests\test_codex_integration.py -q -n 0` → 117 passed, one pre-existing Pydantic forward-reference warning.
- Required full run: `.venv\Scripts\python.exe -m pytest tests\ -x -q` → stopped after an unrelated parallel Claude durability failure with 1 failed, 1417 passed, 2 skipped, 1 xfailed. The exact failing node passed serially, and the prescribed `--lf --lfnf=none -q -n 0` rerun passed 13 with 224 deselected.
- `.venv\Scripts\python.exe scripts\agent-workflow-check.py --repo-root . --slug relay-codex-s3-lifecycle` → clean, including parsed redline with no boundary or checkpoint finding. `git diff --check` → clean.
- `git diff --name-only` contains no production code. Untracked `scripts/validate_relay_cutover_copies.py` is unrelated concurrent work and is excluded from this task.

## Result review

2026-09-08 clean-context review by /root/review_relay_value_result: APPROVE after correcting the stale roadmap execution-order section to mark the live reply/remediation gate complete, make lifecycle hardening next, and defer telemetry until a concrete diagnosis gap.
