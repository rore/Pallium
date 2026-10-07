# Codex wake output failure

<!-- agent-workflow:start -->
**Outcome:** A recognized internal Codex wake cannot continue as a successful empty hook result when its payload or blocking output fails.

**Target:** Codex UserPromptSubmit integration.

**Scope:** Hook-local output and exception handling in integrations/codex/hooks/user_prompt_submit.py, existing hook/deadline caller-surface tests and relevant operations/roadmap evidence. Separate repair under relay-recovery-closure; do not mix passive enrollment diagnostics.

**Constraints:** Preserve exact wake recognition, ordinary prompt fail-open behavior, output-before-ACK, leases, scope, identity fences and existing deadlines. No shared output-helper semantic change, dependency, setting, native transport, service or installed-environment change. Never weaken protected behavior contracts or count simulated coverage as installed-host acceptance.

**Completion criteria:** Recognized wakes with failed payload or suppression output return Codex's blocking exit signal without ACK or memory work; successful suppression and emitted payload paths retain their existing observable behavior. Deterministic deadline/write/exception failures and successful/ordinary-prompt controls pass caller-surface tests, independent review, full validation and PR CI. Installed qualification remains separately open until approved and witnessed.

**Requirement baseline:**
{"source":"user:so take ownership of this and fix","outcome":"A recognized internal Codex wake cannot continue as a successful empty hook result when its payload or blocking output fails.","scope":"Hook-local output and exception handling in integrations/codex/hooks/user_prompt_submit.py, existing hook/deadline caller-surface tests and relevant operations/roadmap evidence. Separate repair under relay-recovery-closure; do not mix passive enrollment diagnostics.","constraints":"Preserve exact wake recognition, ordinary prompt fail-open behavior, output-before-ACK, leases, scope, identity fences and existing deadlines. No shared output-helper semantic change, dependency, setting, native transport, service or installed-environment change. Never weaken protected behavior contracts or count simulated coverage as installed-host acceptance.","completion_criteria":"Recognized wakes with failed payload or suppression output return Codex's blocking exit signal without ACK or memory work; successful suppression and emitted payload paths retain their existing observable behavior. Deterministic deadline/write/exception failures and successful/ordinary-prompt controls pass caller-surface tests, independent review, full validation and PR CI. Installed qualification remains separately open until approved and witnessed."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Unclassified hook path has an Elevated floor. This repairs an accepted fail-closed obligation without changing authority or persistence; output failures and exception ordering require independent judgment. The parent recovery round remains High/Large.

**Discovery:** The parent diagnostic validation exposed empty suppression stdout with exit zero; that original invocation remains unattributed. Separate controlled expiry immediately before emit_utf8 reproduced the defect, while normal and restored-output-budget controls emitted the block successfully. common.emit_utf8 returns false on expiry or stream failures. UserPromptSubmit ignores that result during suppression. Failed payload emission also reaches the outer exception handler and exits zero without ACK. Current wake recognition occurs after scope/actor resolution, so earlier exceptions are not classified. Existing tests and roadmap/features/add-wake-first-relay-delivery.md require recognized unverified wakes to stop before memory/model work. Official release documentation supports UserPromptSubmit exit two with a stderr reason; exit zero without output continues. This is a simulated source/caller defect, not an explanation of the installed native reopen outage.

**Material assumptions:** Supported Codex hosts honor the documented exit-two blocking contract; installed behavior remains to be separately qualified. Input must be successfully read and parsed to identify a wake; malformed/unreadable input and external host termination cannot be classified or repaired by this hook. A stderr error must not turn the intended exit two into exit one; a blocked stderr pipe or host hard timeout can still prevent completion. Unexpected additional exact-wake routing defects return to planning rather than silently expanding this fix.

**Plan:** Invoke /agent-workflow and classify before code edits (completed). First obtain clean-context smart plan review. Initialize recognition/emission flags before the outer try. Move existing exact wake recognition immediately after validating the prompt, before scope/actor resolution, without broadening its grammar. Set the emitted flag immediately after emit_context returns, before diagnostics or ACK; partial output never sets it. Reuse the existing JSON block for ordinary suppression. On failed block emission or a caught exception before a recognized wake payload has successfully emitted, use one hook-local failure exit: write and flush a fixed best-effort stderr blocking reason, then os._exit(2) in finally. This avoids Python cleanup changing the blocking signal to exit 120 after buffered-stream errors; do not flush or replay uncertain stdout. Existing scope and relay_turn calls unwind their original lock/HTTP cleanup before this exit; timed-out daemon I/O can be terminated with the hook, without replay or rollback. Keep ordinary prompts fail-open and emitted-payload/failed-ACK behavior unchanged, including no retroactive block or undo of committed ACK. Do not change common.emit_utf8 or create generic output machinery. Extend existing deadline/hook fixtures with deterministic expiry and write failures, exception-before-scope and normal/success controls, including real hook plus HTTP lease/state evidence and actual subprocess return codes. A cheap implementer owns the bounded patch; root and an independent smart reviewer verify it. Stop if cleanup inspection disproves safe hook-only exit or changes require authority, shared deadline semantics, protected requirement changes or live environment mutation. Final selector, full serial non-slow suite and exact-head CI gate the PR. Deployment requires an exact separately approved change/impact/backup/rollback plan.

**Verification plan:**
When suppression output expires or fails, the recognized wake shall exit two without memory/ACK work → existing hook caller tests with deterministic clock, write/flush failures, Unicode input and absent payload assertions.
When stdout partially writes or fails to flush, or stderr writing/flushing fails, the hook shall preserve its actual blocking process signal without claiming rollback or receipt → isolated subprocess tests asserting return code two, captured output and no ACK/memory side effects, plus successful-stream controls. In-process SystemExit assertions alone are insufficient.
When verified payload output fails after claim, the wake shall exit two without ACK and retain its recoverable lease → existing real hook/HTTP fault fixtures and the normal delivery read path.
When scope/discovery/formatting fails after recognition, the wake shall block without ordinary ingestion → injected exception caller-surface cases before and after scope resolution.
When payload output succeeds, the hook shall ACK only afterwards and preserve failure/recovery states → existing emitted-payload/ACK-loss lifecycle tests, including later lease recovery.
When suppression output succeeds or a prompt is ordinary/near-match/unreadable, existing documented behavior shall remain → existing block JSON, normal ingestion and malformed-input controls.
When the complete isolated patch is reviewed, all required checks shall pass → whole-change selector, full non-slow serial suite, workflow/Redline/import checks, smart result review and required platform CI.

**Plan review:** Agent technical review: /root/wake_output_plan_review, independent gpt-6.1-sol/high, approved repaired plan f7a1a286bc9df7f447dc176476a1ea1d223e34e7 at Elevated/Moderate. The finalization/subprocess blocker is resolved. Original scope/Relay state calls unwind before the failure-only process exit; timed-out daemon claims remain recoverable rather than rolled back. In-process failure tests must intercept the exit without substituting for actual subprocess proof. No additional High-risk plan decision or live authorization is inferred.

**Approvals:** Existing user authorization covers isolated implementation. No new live environment approval is implied. Technical review must confirm classification; a High-risk reassessment requires a separately presented human plan decision.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Source evidence and limits

- Parent diagnostic Work Record: .agent-workflow/tasks/relay-native-enrollment-diagnostics.md in its independent worktree.
- Accepted obligation: roadmap/features/add-wake-first-relay-delivery.md, implementation sequence for Codex loaded tasks.
- Official release behavior: [OpenAI hook documentation](https://learn.chatgpt.com/docs/hooks), common output and UserPromptSubmit sections, inspected 2026-10-07. These docs are not installed-host evidence.
- Existing source callers: suppression branch, emit_context failure branch and top-level exception handler in user_prompt_submit.py; common.py emit_utf8 and emit_context remain unchanged.
- Historical original failure, native enrollment outage, restart/scope-move acceptance and other stranded incidents remain unresolved by this repair.

## Recovery state

Branch feat/relay-wake-output-failure, original base 658affdd8c1af9ad2cefc3d10368f32811c50bd8. Reviewed implementation is committed at 9208294a0c7e29d98abeb23efb65f3f1a07b3689. The actual merged diagnostic dependency ae110a511cadd8e52c3da14c5b5961cf1ff01552 is integrated at 236e4e14; hook, caller-test, redelivery-test and roadmap blobs remain exactly as source-reviewed. Focused/affected and combined full serial validation are complete. Next: final result review and exact-head PR CI. No live operation or installed acceptance is complete.

## Pre-edit review repair

The initial independent review found Python standard-stream finalization can
override SystemExit with exit 120. [Python exit documentation](https://docs.python.org/3.13/library/sys.html#sys.exit).
The revised plan uses the smallest direct child-hook failure exit, not stream
replacement or a generic output subsystem. os._exit skips cleanup and buffered
flushes, so its use is limited to this standalone hook's recognized failed-output
path after synchronous request/lock unwinding; successful output, ACK and normal
prompt exits remain untouched. [Python process exit documentation](https://docs.python.org/3.13/library/os.html#os._exit).
Real subprocess cases are required for zero/partial output, stdout and stderr
write/flush failures. Blocked pipes and external host kill remain unqualified.
Pre-edit intended-path Redline is GRAY with no checkpoints or boundary violations.

Independent review approved the repaired plan and verified synchronous cleanup
seams. Before implementation, intercept the new failure-exit seam in existing
in-process failing-emission tests, including redelivery-envelope and observer
tests. Only separate subprocess assertions qualify the real exit status. The
diagnostic full suite is still running; queue pytest until it completes.

## Implementation

Intended implementation paths: integrations/codex/hooks/user_prompt_submit.py;
existing tests/test_agent_relay_hooks.py, tests/test_hook_deadline_safety.py,
tests/test_codex_relay_fault_harness.py and tests/test_relay_redelivery_envelope.py
for changed failure-exit assertions/interception and actual subprocess/HTTP
coverage; docs/context/operations.md, the canonical wake roadmap and this record
for accurate scope/evidence. The redelivery-envelope path is an existing caller
fixture identified by review, not a new feature or protected requirement change.
Do not change shared conftest, production common.py or diagnostic worktree files.
No pytest runs until root releases the currently running full-suite lane.

Implementation progress: exact generic and delivery-ID wake recognition occurs
immediately after prompt validation, before scope/actor resolution. A hook-local
blocking exit handles recognized pre-emission exceptions and failed block output;
the successful payload-emission latch is set immediately after the existing
emitter returns and before event recording or ACK. The prior implementation draft
also changed exact-delivery mismatch routing; that unapproved change was removed.
Whether existing exact-ID/rendered-batch mismatch behavior needs separate work is
an unresolved question, not a confirmed defect, and is outside this repair.

Validation evidence: after the isolated output-failure lane was released, syntax
compilation passed. Focused caller/subprocess/HTTP-recovery nodes passed with
`python -m pytest tests/test_agent_relay_hooks.py::test_codex_wake_records_only_proven_emit_and_ack_stages tests/test_agent_relay_hooks.py::test_codex_recognized_wake_exceptions_before_emission_block tests/test_agent_relay_hooks.py::test_codex_ordinary_prompt_exception_remains_fail_open tests/test_agent_relay_hooks.py::test_codex_wake_post_emission_exceptions_do_not_retroactively_block tests/test_agent_relay_hooks.py::test_codex_unreadable_hook_input_is_not_classified_as_wake tests/test_agent_relay_hooks.py::test_codex_recognized_wake_output_failures_exit_two_in_subprocess tests/test_relay_redelivery_envelope.py::test_hook_redelivery_after_emit_or_ack_gap_preserves_exact_id_and_receipt -q -n 0`
(11 passed). The four affected files passed serially with
`python -m pytest tests/test_agent_relay_hooks.py tests/test_hook_deadline_safety.py tests/test_codex_relay_fault_harness.py tests/test_relay_redelivery_envelope.py -q -n 0`
(227 passed). Subprocess cases use the actual common output helper for payload
write/flush failures and deterministic deadline expiry, and assert real exit 2.
The first focused run had one new-test assertion failure: the test
guessed an arbitrary partial-output length; it was corrected to assert the exact
configured prefix and the rerun passed. The repaired coverage now includes actual
payload write/flush failures, deterministic deadline expiry, stderr write/flush
failures, success controls, pre-emission exceptions, post-emission diagnostic/ACK
exceptions, ordinary and unreadable input controls, and HTTP lease recovery.
Malformed response and near-match controls remain covered by existing tests. No
full suite, live host qualification, or environment operation was run. Next:
parent source review, independent result review, then the required selector and
full validation under parent coordination.

Content hashes recorded for this review (Work Record itself excluded): hook
`integrations/codex/hooks/user_prompt_submit.py`:
`684626e8404a1c74f8cf78b01940bc906d9b07e5`; caller/subprocess tests
`tests/test_agent_relay_hooks.py`:
`2465e9e5eab5e24cc7aac680f33ef7cad377f4c3`; HTTP recovery test
`tests/test_relay_redelivery_envelope.py`:
`6be128119cde32c09436fdb4db588401f5707d63`; operations
`docs/context/operations.md`:
`e3e596a58116fcdeaffcc906064e8f361ca75a6c`; roadmap
`roadmap/features/add-wake-first-relay-delivery.md`:
`639ac8c7dd671211bb7caf61bdff42a58c6759a2`.

## Source review before full validation

Independent gpt-6.1-sol/high review by /root/wake_output_plan_review approved the
4368e120 plus frozen six-file candidate for full validation. No code/test blockers
remain; original render/ACK routing and shared helpers are unchanged. Root fixed
the two documentation findings: model-visible empty wakes are qualified for hooks
that cannot recognize/complete the wake, and stderr errors do not alter exit two
though blocked pipes/host termination can prevent completion. Recovery state now
reflects implementation rather than pre-edit planning. Full and CI remain gates;
the original invocation, installed outage and parent recovery stay unresolved.

Skill feedback trigger 2 dropped: these are consumer implementation/documentation
corrections, not defects in the upstream agent-workflow instructions.

## Combined dependency and validation gate

PR300 merged normally at 2026-10-07T17:18:12Z as
ae110a511cadd8e52c3da14c5b5961cf1ff01552. GitHub's first CI attempt failed with
an internal server error (correlation 0b9efd4e-c60d-4a28-a916-03830628a9a2);
its aggregate job never existed. Failed-only retry was rejected. One full retry
on unchanged reviewed head a275aea2236814298323c759d98c831ec8e50bac passed,
including CI result, both Python matrices, Windows smoke and governance.
Fresh fully exhausted review queries found no threads or inline comments.
CodeRabbit was rate-limited and did not perform source review; the independent
smart source/result review is the technical evidence. No gate was waived.

The isolated output branch merged the exact actual dependency without source
conflicts. Reviewed hook/test/roadmap blobs are unchanged. Whole-change selection
requires full validation; import-linter reported zero violations. Fresh Redline
was GRAY with no checkpoints, boundary violations or protected behavior changes;
workflow compliance was clean using the known Python runtime directly. The
PowerShell adapter could not locate Python in this isolated checkout; no PATH or
persistent environment setting was changed. The combined full serial run remains
pending, not passed. Everyday and installed clones/service remain unchanged;
their sync/restart scope has been presented for explicit approval separately.

## Completed full validation

Root ran the whole non-slow suite once on frozen combined revision
b950ac708f79e4d3c3dbecf61b4479962f29a103 using the existing shared interpreter,
with this isolated checkout as the working directory:
`python -m pytest tests/ -x -q -n 0 --durations=20`.
The owning root process completed at 2026-10-07T17:43:09Z with exit zero:
6376 passed, 34 skipped, 480 deselected, 2 xfailed in 1392.79s (23m12s).
No source or test changed during the run. Simulated native fixtures and actual
hook subprocesses are not installed native-host recovery qualification.

The bounded cheap worker regenerated all Git-native changed-path/numstat/U0
artifacts on this exact revision. Import-linter exited zero with no violations;
Redline returned the expected GRAY advisory with no checkpoints, boundaries or
protected-contract changes; workflow compliance exited zero and was clean.
Root inspected the artifacts before accepting the report. The worker could not
poll root's process because tool sessions are agent-scoped; it did not start a
duplicate suite. Final result adequacy review and exact-head PR CI remain gates.

Separate operational observations remain open: the installed service's queue
diagnostic timed out at five seconds while subsequent health and status reads
succeeded. Existing logs show automatic supervisor API-child restarts after
failed probes, most recently startup at 15:33:12Z, not a root deployment. The
logged WinError 64 is the existing accept patch's handled transient path; no
causal accept defect is established. A worker's standalone injected-future plus
real ephemeral Proactor round-trip passed, but is not a genuine kernel-error or
installed-service witness. It used the everyday checkout contrary to the
requested isolated directory; ordinary ignored bytecode-cache writes are possible.
No intentional source/settings/service change occurred, and that execution-scope
deviation was disclosed to the human and routed by the manager to Astra reviewer.
The 0.003s measured only its async scenario/cleanup, not process startup. These
observations neither expand this patch nor close the original native incident.
