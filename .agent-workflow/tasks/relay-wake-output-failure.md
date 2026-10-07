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

Branch feat/relay-wake-output-failure, exact base 658affdd8c1af9ad2cefc3d10368f32811c50bd8. Only this pre-edit record exists. Next: independent plan review, then implement only its approved scope. Do not overlap pytest with the diagnostic worktree's running full suite.

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
