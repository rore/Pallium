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

**Plan:** First invoke Agent Workflow, establish this immutable baseline and classify risk before code edits. Independently review this plan. Extend only the existing private bounded diagnostic sink and recovery paths with process-unique local episode correlation and fixed terminal metadata. Mark phase entry/completion and registration attempt immediately around existing calls; distinguish explicit busy, uncertain registration, post-registration guard refusal, constructor/READY failure and true exhaustion. Include pre-reconnect refusal without duplicate terminal output. Preserve predicates and cleanup order. Extend existing recovery fixtures and at least one MCP caller-surface lifecycle journey; add privacy, sink failure and multi-worker correlation controls. Run focused tests, affected files and the whole-change validation selector; run the required non-slow suite once before result review or publication, preserving any failures. No CI rerun campaign or unrelated accommodations. Return for scoped review if source reach expands.

**Verification plan:**
- Truthful every-terminal observations and unique local correlation -> parameterized controls in tests/test_codex_worker_reconnect.py, including multiple workers and episodes.
- Unchanged native calls, retry budgets, errors and cleanup -> existing same-epoch, idle-retirement and busy-recovery assertions plus failing-sink controls.
- Caller-surface observable lifecycle and bounded private sink -> existing MCP protocol journey with real isolated diagnostic file and privacy/rotation assertions.
- Whole-change validation and independent adequacy -> scripts/test-plan.py --base origin/main, reported required checks, one required non-slow suite, import boundaries, workflow/Redline and independent result review.
- No installed recovery claim -> source-only evidence clearly separated from unperformed loaded-client rollout and installed acceptance.

**Plan review:** Agent technical review: independent recovery_diagnostics_review, PLAN GO for decb746bfb12b8e82d581ad6c947589c1ec88bec; see Plan review below.

**Approvals:** Not required at Elevated risk. Standing user authorization covers isolated bug work; manager authorized this bounded source diagnostic. Installed changes are excluded.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Plan reviewed before implementation. Base is current main `9d01176483d7a353d1f88de7830a31e409c5959b`; branch `feat/relay-reconnect-outcome`. The separate expiry-detection pull request remains parked and is not part of this diff. Manager owns the shared roadmap; contribution reconciliation is pending a source result.

The existing bounded client log now records one fixed terminal row for an observed recovery episode, with a process-local episode ordinal, phase, attempt, registration status, fixed outcome, and already-evaluated safety state. Healthy READY polling remains silent. IDs are allocated independently of the file-sink lock; invalid metadata and sink failures remain contained. Independent source review accepted preservation of native operations, predicates, retry budgets and cleanup decisions at `4a41ffae`. Synchronous file logging adds timing overhead; this is not a guarantee against filesystem stalls. The installed client was not changed.

## Plan review

Agent technical review: independent recovery_diagnostics_review, PLAN GO for `decb746bfb12b8e82d581ad6c947589c1ec88bec`. The reviewer inspected the exact record and existing recovery/test surfaces, accepted the three-file scope, safeguards and verification plan, and found no blocker. Implementation review must verify exception-path predicate semantics, native call/disposal counts and containment of diagnostic allocation/logging failures. This does not approve installed rollout or establish broader recovery qualification.

## Evidence

Final-source validation at `4a41ffaed2d8a38c96ec5dab1635cf3b60183387`: the one full non-slow validation used the existing Windows serial/remainder split. Serial: 70 passed, two skipped, nine slow cases deselected in 94.39s. Remainder: 8,354 passed, 35 skipped, two xfailed in 632.06s. Combined: 8,424 passed, 37 skipped, two xfailed; 8,463 distinct XML cases, zero overlap and zero failures/errors. All 191 reconnect-file cases passed on the final source. Application/test hashes were identical before and after the run. Runtime: Python 3.13.14, SQLite 3.53.1, SQLAlchemy 2.0.48, pytest 8.4.2 and xdist 3.8.0. Whole-change selection chose full; import boundaries, fresh gray/watch Redline classification, whitespace, private-identifier scan and the current implementation-state workflow check passed. Final result review and platform CI remain separate gates. Evidence is retained in ignored qualification records; no installed host was used.

Earlier drafting checks remain separate from final validation: 48 focused passes in 2.71s; 187 reconnect-file passes in 47.45s on a preceding draft; and seven changed-node passes in 0.77s after its first refinements. Those passes do not substitute for the final-source full run above. All runs used a process-local isolated home and fresh temp directory. Coverage includes healthy-poll silence, sanitization and rotation, sink/allocation failure, distinct worker episodes, exhaustion and early-stop reporting, registration uncertainty, post-REGISTER fences, unresolved state mutation, and preservation of an exception during candidate setup. MCP journeys used isolated test peers; no installed host was exercised.

Independent source review `b4a6ff9f` identified optional-diagnostic allocation failure handling, overconfident REGISTER refusal labels, and candidate-fence exception phase attribution, plus missing caller-surface evidence. The bounded corrections and corresponding controls were added. The focused review-fix run then reported 51 passed and 2 failed in 2.82s: both failures exposed a stale intermediate `ready-retired` outcome surviving into the terminal record. That run remains failed evidence. The worker stopped after that run; the parent applied one diagnostic-only reset and ran the two exact failed cases, followed by the single final full validation above.

## Result review

Agent technical review: independent recovery_diagnostics_review returned RESULT GO for the source candidate after inspecting the primary XML, commands, log summaries and matching source/test hashes. The previous SOURCE GO remains applicable to the unchanged code.

Reviewed revision: `4a41ffaed2d8a38c96ec5dab1635cf3b60183387`.

Verification adequacy: all completion criteria are covered by the final-source full validation, including 191 reconnect cases and the existing MCP caller-surface recovery journeys. The 8,463 XML cases have no duplicates, partition overlap, failures or errors. Privacy, correlation, terminal outcomes and diagnostic-failure containment are covered. Earlier failed draft evidence remains failed and separate. Final record-only updates do not create a newly tested application candidate.

Earlier source review returned SOURCE NO-GO for `b4a6ff9f71bc57323aef006f5ff9e7392562e1e3`: optional allocation failure, overconfident registration labels, later-failure attribution and missing caller-surface assertions. Those bounded findings were corrected and accepted by SOURCE GO at `4a41ffae`. The review-fix run also exposed a transient outcome surviving into a new attempt. A diagnostic-only reset at actual attempt entry corrected it; the two exact failed cases passed in 0.70s before the successful final full run. No behavioral assertion was weakened.

Source implementation and local validation are complete. [PR #381](https://github.com/rore/Pallium/pull/381) is open; platform CI and review conversations remain merge gates. No installed rollout, connection recreation or service restart occurred. This task does not establish installed recovery reliability or identify the physical claim-deadline cause; synchronous filesystem logging retains timing overhead.
