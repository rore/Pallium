<!-- agent-workflow:start -->
**Outcome:** Existing Codex sessions open in VS Code can receive and act on Relay messages through supported native ingress.

**Target:** Codex Relay wake routing and hook admission.

**Scope:** The Codex activation adapter and its existing callers, hooks, tests and user documentation; narrow exact paths after the supported ingress is established.

**Constraints:** Preserve existing Desktop delivery, exact recipient and container scope, idle and busy boundaries, generation and native-spend fences, no replay, individual leases, output-before-ACK, settings and credentials. Keep experiments isolated. No competing session owner, host upgrade, global configuration change, queue deletion or protected-test weakening. Existing stopped operations remain stopped. Installed changes require a concrete approved scope and recoverable rollback.

**Completion criteria:** Focused caller-surface tests cover route selection, failure, uncertainty and duplicate boundaries; one real authorized message reaches an existing VS Code session and receives a useful response with no duplicate execution. State any unloaded-session limitation honestly. Preserve Desktop regression coverage.

**Requirement baseline:** {"source":"work-record-initial","outcome":"Existing Codex sessions open in VS Code can receive and act on Relay messages through supported native ingress.","scope":"The Codex activation adapter and its existing callers, hooks, tests and user documentation; narrow exact paths after the supported ingress is established.","constraints":"Preserve existing Desktop delivery, exact recipient and container scope, idle and busy boundaries, generation and native-spend fences, no replay, individual leases, output-before-ACK, settings and credentials. Keep experiments isolated. No competing session owner, host upgrade, global configuration change, queue deletion or protected-test weakening. Existing stopped operations remain stopped. Installed changes require a concrete approved scope and recoverable rollback.","completion_criteria":"Focused caller-surface tests cover route selection, failure, uncertainty and duplicate boundaries; one real authorized message reaches an existing VS Code session and receives a useful response with no duplicate execution. State any unloaded-session limitation honestly. Preserve Desktop regression coverage."}

**Relationships:** {"schema_version":1,"sources":null,"pull_requests":["https://github.com/rore/Pallium/pull/398"]}

**Risk:** High

**Complexity:** Moderate

**Reason:** Wake routing can initiate model turns; exact destination and no-replay guarantees are safety boundaries. Runtime and hook changes are outside the documentation-only exemption.

**Discovery:** Native queue admission can wake loaded Codex sessions without taking ownership; it does not load an unopened session or prove receipt. Explicit queue mode bypasses Desktop retained preflight. Existing retained preflight exposes idle/notLoaded on its own connection, which does not establish cross-host ownership. Seamless mixed-host routing remains unsatisfied. The complete hook packet must fit the native default context allowance of 10000 UTF-8 bytes, including scope and notices. The first coherent public-candidate full run stopped during Session History startup on a Windows service-marker replacement error. Inspection established that the CLI serve test writes PALLIUM_SERVICE_PORT directly and its existing fixture does not restore the process environment. Later tests consequently enter service-only marker publication. This fixture leak is demonstrated; it does not establish the file-locking actor or physical cause.

**Material assumptions:** Preserve exact-target checks, generation and native-spend fences. Never infer ownership from history, visibility, origin or another server's notLoaded state. Accepted or uncertain submission cannot select another transport. Explicit executable selection fails closed. Preserve newer public behavior when composing a local installation preimage.

**Plan:** First invoke agent-workflow and classify the existing non-exempt task before edits. Preserve the reviewed application implementation and bounded eight-delivery hook. Prepare the public projection against the accepted main baseline, restoring its composer-suggestion guard and leaving the shared helper unchanged. Review uncovered projection changes; reuse unchanged reviews and identity-bound evidence. Run the whole-change selector and one coherent full non-slow validation on the actual candidate. Publish the compatibility contribution with explicit limitations, resolve findings and merge normally. Continue supported mixed-host routing and executable discovery without presenting the service-wide override as the finished default. Adopt coherent merged source locally with preserved settings, dependent corrections, backups, rollback and applicable authorization; never reset dirty checkouts or replay stored work. Validation follow-through: first isolate direct CLI-entrypoint environment mutations in tests/test_app_run.py using the standard library patch.dict(os.environ) around the existing fixture yield. Preserve its configuration and concurrency setup, every production function and all original assertions. Independently review this narrow fixture plan/source before an ordered affected check and the required coherent full lane. Preserve the original failed profile and Windows marker failure; do not change native retry, deadline or file-publication behavior to obtain green.

**Verification plan:** Cover configuration precedence, invalid values and explicit executables, app isolation, Desktop routing and native-spend boundaries. Exercise ordinary and exact-trigger hooks through real HTTP and durable readback: empty/one/eight/over-limit batches, Unicode, complete-packet byte bounds, scope/notices, valid copied paging, truthful counts, malformed metadata, exact triggers and emitter failure without ACK. Retain composer regression coverage. Follow the whole-change selector; do not duplicate coverage supplied by a coherent full run. Native acceptance needs complete provider-visible first/middle/last fragments and each selected durable ACK during real traffic. Keep mixed-host ownership, unloaded wake, platform results, merge and installed adoption separate. CLI fixture isolation -> run the existing app-run tests and the failed historical lookup node in the same isolated process, checking environment restoration before the later client starts. Then use the actual whole-change selection on the final candidate; reuse unchanged application reviews and focused results truthfully.

**Plan review:** Agent technical review: the independent non-implementer accepted the original queue-mode source and bounded batching plan, including copied paging, bounded fitting, exact-trigger preservation and flush-before-ACK. Its publication assessment required restoration of the accepted composer guard and coherent helper dependency; both are now verified. Reuse unchanged reviews only at their identities. No mixed-host runtime acceptance is claimed. The same independent non-implementer accepted the narrow CLI environment-isolation plan and source after inspecting the existing fixture, direct entrypoint writes and startup consumer. Every original assertion and production function is preserved; the ordered fourteen-case regression verified environment restoration before the original failed E2E case.

**Approvals:** Approved by user 2026-11-10: "can we work on fixing relay to work also with vscode? can you open subagents and manage them until we get it working and we can continue communicating with other sessions?" The user subsequently required fixes merged into main and local alignment. Exact installed approvals cover their recorded scopes; they do not authorize unrelated environment changes.

**Exceptions:** None

**State:** Ready for review
<!-- agent-workflow:end -->

## Source and review

Branch `fix/vscode-relay-activation` is based on `a4e20de0bc56f5ff871162b6aa75573b412de3d4`. Scope includes application routing/configuration, the Codex prompt hook, caller-surface tests and user documentation. No protected contract or shared-helper edit is included.

The application change adds explicit queue selection and an optional CLI path through existing configuration precedence. Both queue callers honor the explicit executable. Default behavior preserves Desktop routing. Queue mode does not infer a host or clear a spent generation.

The hook requests eight deliveries through its existing final-scope callback, retaining older-helper signature compatibility. It fits the complete packet within 10000 UTF-8 bytes, shortens only validated copied paging views, preserves the exact trigger and ACKs emitted original claims after flush.

The public projection restores the baseline composer-suggestion guard. Hook SHA256: `02AEF3B85B8458E27C96863BB4B4415C1A7EE5EB4B264538606D4729C05C2669`. Its helper dependency is present in public main. The installed-only preservation projection must not be published unchanged.

## Validation and limits

The final isolated full non-slow run completed with 8814 passes, 37 skips, two expected failures and 697 deselected slow cases. Its XML contains 8853 ordinal-unique cases, zero failures and zero errors; the owned process exited zero. All thirteen source, record and dependency identities and the twelve-path change composition remained unchanged. The origin report verified 526 project-module origins in the candidate checkout. No application change followed this run.

The ordered CLI isolation regression passed all fourteen cases in one process, including the previously failing historical lookup case after the existing CLI tests. The fixture now restores the process environment after each CLI test. This result addresses the demonstrated test contamination; it does not identify the physical cause of the earlier Windows replacement error.

The whole-change selector selected the full lane for the actual twelve paths. Earlier failed and interrupted profiles remain retained; they are not counted as successful validation. No additional application tests are required merely to reconcile this record.

The first public-candidate full run stopped with 3905 passes, one failure, five skips and one expected failure; 697 slow cases were deselected. The failed historical lookup E2E case encountered a Windows PermissionError during isolated service-marker replacement before its subject assertions. All recorded source identities remained unchanged. This is an incomplete prefix, not full validation. A demonstrated earlier CLI test environment leak is being corrected separately from the unknown native file-replacement cause.

Earlier isolated application validation supplied 27 focused passes on unchanged application identities. Separate batching validation passed 48 unique cases with no failures, errors or skips, including a 27-message HTTP journey in eight-message groups, lease recovery, arrival, bounds, paging and emitter failure. These are focused identity-bound results, not a full-suite or current-public-projection pass. Original launch and fixture failures remain retained.

Independent review accepted those deltas, the public composer guard restoration and the narrow CLI fixture source correction. Final result review accepted the completed full-run evidence and unchanged candidate identities. Real native evidence demonstrates a loaded recipient receiving a task, acting and producing a correlated reply. Automatic return delivery, complete live batch visibility and timely backlog recovery remain unverified.

## Result review

Agent technical review: https://github.com/rore/Pallium/pull/398#issuecomment-6775297267 records the independent non-implementer's source and result GO, with no code or privacy findings.

Reviewed revision: `dd9c30756774ce8edb7985ab7e389fb0503404b8`, based on `a4e20de0bc56f5ff871162b6aa75573b412de3d4`; the final source identities are retained with the validation evidence.

Verification adequacy: the reviewer independently reconciled the full non-slow lane, ordered regression, actual selector, ordinal-unique XML census, project origins and all thirteen frozen identities. Only this record was reconciled after terminal validation.

Separate human result review and any required PR checkpoints remain unsatisfied. Implementation and rollout approvals are not relabeled as result approval. The first governance result found an invalid empty-Exceptions representation and result-review fields on one line; this record-only correction preserves requirements and evidence. The earlier local-first publication deferral was superseded by the main-convergence requirement. The interim queue override is not the finished mixed-host solution.

## Remaining delivery

Complete public-projection review, whole-change checks and normal PR validation before merge. Preserve first failures; do not increase deadlines, weaken assertions or replay uncertain submissions to obtain green.

Resolve reasonable mixed-host routing through supported current ownership/admission evidence. No cross-host owner lookup has been established in the inspected stack. Preserve Desktop unloaded wake rather than silently replacing it with queue-only behavior.

After merge, adopt coherent merged source and preserved dependent corrections. A hook-only overlay onto an older helper is not merged-main adoption. Verify installed behavior and normal traffic under applicable rollout authority. The full task remains unfinished.
