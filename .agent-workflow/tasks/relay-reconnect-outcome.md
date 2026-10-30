# Record the terminal outcome of retained reconnect recovery

<!-- agent-workflow:start -->
**Outcome:** A failed or completed retained Codex reconnect can be distinguished from retry exhaustion, uncertain registration and safety refusal through one bounded private terminal diagnostic, without changing recovery behavior.

**Target:** Pallium Codex retained MCP client.

**Scope:** app/mcp/codex_desktop_bridge.py, tests/test_codex_worker_reconnect.py, and this Work Record.

**Constraints:** Preserve caller-visible results, protocol operations and their order, finite retry/deadline budgets, registration no-replay rules, cleanup and identity/I/O fences. No raw exceptions, payloads, tokens, paths or session identifiers in the new diagnostic. No new dependencies, settings, generic observer framework, installed changes, connection recreation, service restart, synthetic traffic or changes to parked work.

**Completion criteria:** Every retained reconnect episode emits at most one truthful terminal observation with process-unique local correlation, entered/completed phase, attempt ordinal, registration-attempt status and already-computed safety flags. Diagnostic failure does not change return values, errors, native calls, retries or disposal. Caller-surface lifecycle tests exercise recovery and failure with bounded private output. Source validation and independent review identify remaining installed qualification limits.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"A failed or completed retained Codex reconnect can be distinguished from retry exhaustion, uncertain registration and safety refusal through one bounded private terminal diagnostic, without changing recovery behavior.","scope":"app/mcp/codex_desktop_bridge.py, tests/test_codex_worker_reconnect.py, and this Work Record.","constraints":"Preserve caller-visible results, protocol operations and their order, finite retry/deadline budgets, registration no-replay rules, cleanup and identity/I/O fences. No raw exceptions, payloads, tokens, paths or session identifiers in the new diagnostic. No new dependencies, settings, generic observer framework, installed changes, connection recreation, service restart, synthetic traffic or changes to parked work.","completion_criteria":"Every retained reconnect episode emits at most one truthful terminal observation with process-unique local correlation, entered/completed phase, attempt ordinal, registration-attempt status and already-computed safety flags. Diagnostic failure does not change return values, errors, native calls, retries or disposal. Caller-surface lifecycle tests exercise recovery and failure with bounded private output. Source validation and independent review identify remaining installed qualification limits."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":["https://github.com/rore/Pallium/pull/381"]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** The runtime client file is gray and watched by Redline; observations cross exception-heavy recovery control flow. Tests and record are blue. No public API, schema, persistence or authentication behavior changes are proposed.

**Discovery:** Existing bounded close diagnostics identify READY retirement but omit the terminal reconnect phase and decision. Constructor, READY, REGISTER and safety failures can all return no replacement. Successful registration replies can also fail subsequent guards. Existing tests exercise these paths and caller-surface MCP recovery; reuse them. The current logger is rotating and failure-contained. Claim deadline exhaustion and processor contention are separate unresolved incidents; this observation does not explain their physical causes.

**Material assumptions:** Existing recovery control flow and already-computed flags suffice for truthful observations without new protocol, property or clock probes. If implementation requires reevaluating guards, changing short-circuit order or introducing new behavior, stop and return to planning. An installed client cannot emit new source diagnostics until it is recreated; rollout is excluded from this task.

**Plan:** First invoke Agent Workflow, establish this immutable baseline and classify risk before code edits. Independently review this plan. Extend only the existing private bounded diagnostic sink and recovery paths with process-unique local episode correlation and fixed terminal metadata. Mark phase entry/completion and registration attempt immediately around existing calls; distinguish explicit busy, uncertain registration, post-registration guard refusal, constructor/READY failure and true exhaustion. Include pre-reconnect refusal without duplicate terminal output. Preserve predicates and cleanup order. Extend existing recovery fixtures and at least one MCP caller-surface lifecycle journey; add privacy, sink failure and multi-worker correlation controls. Run focused tests, affected files and the whole-change validation selector; run the required non-slow suite once before result review or publication, preserving any failures. No CI rerun campaign or unrelated accommodations. Complete the demonstrated original-acceptance defects through the Correction plan below, reviewed before further application edits. Return for scoped review if source reach expands.

**Verification plan:**
- Truthful every-terminal observations and unique local correlation -> parameterized controls in tests/test_codex_worker_reconnect.py, including multiple workers and episodes.
- Unchanged native calls, retry budgets, errors and cleanup -> existing same-epoch, idle-retirement and busy-recovery assertions plus failing-sink controls.
- Caller-surface observable lifecycle and bounded private sink -> existing MCP protocol journey with real isolated diagnostic file and privacy/rotation assertions.
- Whole-change validation and independent adequacy -> scripts/test-plan.py --base origin/main, reported required checks, one required non-slow suite, import boundaries, workflow/Redline and independent result review.
- No installed recovery claim -> source-only evidence clearly separated from unperformed loaded-client rollout and installed acceptance.

**Plan review:** Agent technical review: independent recovery_diagnostics_review, initial PLAN GO for decb746bfb12b8e82d581ad6c947589c1ec88bec. Correction plan review is pending; application edits remain blocked until it passes.

**Approvals:** Not required at Elevated risk. Standing user authorization covers isolated bug work; the task owner explicitly authorized completing the demonstrated diagnostic and episode-oracle corrections in the existing three-file scope. Installed changes and new runtime machinery are excluded.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Plan reviewed before implementation. Base is current main `9d01176483d7a353d1f88de7830a31e409c5959b`; branch `feat/relay-reconnect-outcome`. The separate expiry-detection pull request remains parked and is not part of this diff. Manager owns the shared roadmap; contribution reconciliation is pending a source result.

The existing bounded client log now records one fixed terminal row for an observed recovery episode, with a process-local episode ordinal, phase, attempt, registration status, fixed outcome, and already-evaluated safety state. Healthy READY polling remains silent. IDs are allocated independently of the file-sink lock; invalid metadata and sink failures remain contained. Independent source review accepted preservation of native operations, predicates, retry budgets and cleanup decisions at `4a41ffae`. Synchronous file logging adds timing overhead; this is not a guarantee against filesystem stalls. The installed client was not changed.

## Plan review

## Correction plan

Current-head CI results are terminal and preserved before further edits. Risk remains Elevated and complexity Moderate: the same gray/watch client file, blue reconnect tests and Work Record are the only intended paths. No API, schema, persistence, locking, dependency or runtime-configuration surface is added. Requirement baseline and caller-visible behavior stay unchanged.

1. Return `_finish`'s existing computed unresolved boolean; current callers ignore the return, and new uses affect diagnostic metadata only. Carry cleanup-discovered True into the terminal record. Retain observed True across subsequent metadata resets; no extra property or truth-conversion probe is permitted. Old-client cleanup that discovers a genuinely new refusal may supersede a candidate outcome; a previously known post-registration refusal must otherwise retain its specificity.
2. Capture post-registration guard values at their existing short-circuit read positions, using local unknown defaults and strict already-observed booleans. Preserve native getter/truth-test order and count. Mark False only after the existing full success predicate establishes it. Non-boolean or unevaluated state remains unknown. Reuse `_finish`'s returned computed result rather than reading the client again.
3. Track the existing service-check call boundary so its exception is attributed correctly while healthy READY polling stays silent. Keep READY-failure outcomes distinct from refusal before reconnect. Capture the existing window comparison at its original short-circuit position; no hoisted or additional clock call is allowed. No writer thread, queue or logging framework is added; the accepted synchronous I/O limitation stays explicit.
4. Make the existing MCP journey's teardown deterministic. After forwarding the real successful terminal record, arm a test-only wrapper of the owned worker's idle queue read. Signal that the idle read is waiting, then release it only on the existing stop event from protocol teardown and raise the existing queue-empty condition. Prove the successful episode and the distinct shutdown-refusal episode explicitly: exactly one terminal row per unique episode, the expected phases/flags/attempt counts, and every original native operation, registration, metadata and disposal assertion. Do not use `len >= 1`, discard unexplained rows, add production calls, or relax watchdogs.
5. The parent owns the client-file correction; the existing implementer owns only the bounded reconnect-test edits. Use controlled accessors/clock fixtures to verify unchanged read order, old-cleanup unresolved/error, post-registration refusal/cleanup, same-channel success and service/window exceptions. Run focused regression nodes first, then the affected file and one selector-required coherent validation after source review. Preserve the prior failed CI and drafting runs. Reuse the existing independent reviewer for the corrected plan and result; stop on scope or behavioral expansion.

The separate Windows gate-test failure remains preserved evidence with unknown physical cause. Do not edit its assertions, production acquisition budgets or locking behavior as part of this three-file correction.

Agent technical review: independent recovery_diagnostics_review, PLAN GO for `decb746bfb12b8e82d581ad6c947589c1ec88bec`. The reviewer inspected the exact record and existing recovery/test surfaces, accepted the three-file scope, safeguards and verification plan, and found no blocker. Implementation review must verify exception-path predicate semantics, native call/disposal counts and containment of diagnostic allocation/logging failures. This does not approve installed rollout or establish broader recovery qualification.

## Evidence

Final-source validation at `4a41ffaed2d8a38c96ec5dab1635cf3b60183387`: the one full non-slow validation used the existing Windows serial/remainder split. Serial: 70 passed, two skipped, nine slow cases deselected in 94.39s. Remainder: 8,354 passed, 35 skipped, two xfailed in 632.06s. Combined: 8,424 passed, 37 skipped, two xfailed; 8,463 distinct XML cases, zero overlap and zero failures/errors. All 191 reconnect-file cases passed on the final source. Application/test hashes were identical before and after the run. Runtime: Python 3.13.14, SQLite 3.53.1, SQLAlchemy 2.0.48, pytest 8.4.2 and xdist 3.8.0. Whole-change selection chose full; import boundaries, fresh gray/watch Redline classification, whitespace, private-identifier scan and the current implementation-state workflow check passed. Final result review and platform CI remain separate gates. Evidence is retained in ignored qualification records; no installed host was used.

Earlier drafting checks remain separate from final validation: 48 focused passes in 2.71s; 187 reconnect-file passes in 47.45s on a preceding draft; and seven changed-node passes in 0.77s after its first refinements. Those passes do not substitute for the final-source full run above. All runs used a process-local isolated home and fresh temp directory. Coverage includes healthy-poll silence, sanitization and rotation, sink/allocation failure, distinct worker episodes, exhaustion and early-stop reporting, registration uncertainty, post-REGISTER fences, unresolved state mutation, and preservation of an exception during candidate setup. MCP journeys used isolated test peers; no installed host was exercised.

Independent source review `b4a6ff9f` identified optional-diagnostic allocation failure handling, overconfident REGISTER refusal labels, and candidate-fence exception phase attribution, plus missing caller-surface evidence. The bounded corrections and corresponding controls were added. The focused review-fix run then reported 51 passed and 2 failed in 2.82s: both failures exposed a stale intermediate `ready-retired` outcome surviving into the terminal record. That run remains failed evidence. The worker stopped after that run; the parent applied one diagnostic-only reset and ran the two exact failed cases, followed by the single final full validation above.

## Result review

Current qualification is held at published head `d54e2500948ef0838116146eb8201fa207042928`. Required CI run `41100874464` failed in both Linux versions and Windows smoke; there was no rerun. Linux 3.12 failed `test_busy_auto_reconnect_recovers_without_a_fresh_call[1-ready]` (one failed, 5,601 passed, 37 skipped, two xfailed); Linux 3.13 failed its `[1-register]` case (one failed, 5,771 passed, 37 skipped, two xfailed). Both new assertions expected one terminal row across the whole protocol journey but observed two. Source permits a separate refusal episode during shutdown; retained row truncation does not establish that complete correlation. Preserve one-record-per-episode and native/disposal assertions rather than weakening the count without explanation.

Windows smoke failed `test_cleanup_cannot_release_a_replaced_provider_gate` (one failed, 534 passed, seven skipped): `late_begin` acquisition failure preceded the intended body, then the fixture's cleanup assertion found the original gate still locked. The physical delay and causal relationship to this change remain unestablished. Redline, selection and workflow compliance passed. CodeRabbit posted eight comments across seven unresolved threads.

Independent follow-up technical review holds the previous source/result GO: old-client cleanup can discover unresolved ownership after candidate success recorded False, leaving an inaccurate terminal flag. Other valid precision gaps concern service-check exceptions, window exhaustion and retaining known state or specific outcomes. Synchronous sink overhead was an explicitly accepted limitation; a writer framework is outside the approved slice. No extra/reordered clock or property probes are authorized. The next source correction and any further CI require the task owner's bounded disposition; current assignment is final-head verification only. This local bookkeeping is not pushed while preserving the completed published-head evidence.

Earlier agent technical review: independent recovery_diagnostics_review returned RESULT GO after inspecting the local XML, commands, log summaries and matching source/test hashes. That earlier approval is retained as history and is superseded by the current qualification hold above.

Reviewed revision: `4a41ffaed2d8a38c96ec5dab1635cf3b60183387`.

Earlier verification-adequacy assessment: the local full validation included 191 reconnect cases and existing MCP caller-surface journeys; its 8,463 XML cases have no duplicates, partition overlap, failures or errors. Subsequent platform failures and follow-up source review identified missing edge-case precision and an unresolved episode-correlation oracle, so that local evidence does not establish current completion criteria. Earlier failed evidence remains failed and separate. Record-only updates do not create a newly tested application candidate.

Earlier source review returned SOURCE NO-GO for `b4a6ff9f71bc57323aef006f5ff9e7392562e1e3`: optional allocation failure, overconfident registration labels, later-failure attribution and missing caller-surface assertions. Those bounded findings were corrected and accepted by SOURCE GO at `4a41ffae`. The review-fix run also exposed a transient outcome surviving into a new attempt. A diagnostic-only reset at actual attempt entry corrected it; the two exact failed cases passed in 0.70s before the successful final full run. No behavioral assertion was weakened.

The source implementation and prior local validation are retained, but [PR #381](https://github.com/rore/Pallium/pull/381) is blocked by required platform CI and unresolved diagnostic correctness findings. No installed rollout, connection recreation or service restart occurred. This task does not establish installed recovery reliability or identify the physical claim-deadline cause; synchronous filesystem logging retains timing overhead.
