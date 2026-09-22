<!-- agent-workflow:start -->
**Outcome:** Make startup recovery attach complete retained uncertain wake evidence to already-pending coalesced deliveries without performing another native submission.

**Target:** Pallium Relay Codex wake recovery.

**Scope:** Internal wake-candidate enumeration, recovery dispatch, Codex diagnostic association, focused caller-surface tests, and Relay roadmap alignment.

**Constraints:** Preserve one native wake per endpoint generation, busy-turn safety, reservation state, delivery/claim/ACK/TTL semantics, exact scope, model, and effort. Never convert uncertain admission into retry safety.

**Completion criteria:** After a service restart, an oldest retained uncertain delivery and later already-pending exact-scope delivery produce actionable trace guidance for the later delivery while attempts remain zero and native submissions remain one; moved or ambiguous evidence remains queued without association.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Intended production paths are watched Relay recovery/storage surfaces. The change is bounded but crosses candidate selection and native-wake deduplication.

**Discovery:** Installed validation of merged PR #216 showed the historical later delivery still reported `Queued: No activation outcome is recorded`. Startup recovery reads one oldest candidate per endpoint, so it revisits the retained delivery itself and never invokes association for later pending deliveries.

**Material assumptions:** Coalesced enumeration is internal to recovery and still orders oldest first. The existing durable reservation and scheduler remain the sole native-submission gate. Any need to change public API/schema, reservation semantics, or retry policy returns this task to planning.

**Plan:** Add `include_coalesced=False` to the internal Relay wake-candidate query. Preserve current one-per-endpoint behavior by default; when recovery opts in, keep the same filters and oldest-first ordering but return every eligible pending/expired delivery. Retain the exact per-delivery recheck and route every candidate through the unchanged scheduler so the durable reservation remains the sole native-submission gate and later deliveries receive only diagnostic association. Update the roadmap claim. Stop and re-plan if this requires a public API/schema change or any retry/fence mutation.

**Verification plan:** Default wake-candidate reads remain one-per-endpoint while opt-in recovery reads all same-endpoint candidates in order, and exact-ID lookup remains unchanged -> storage/service regression. A real caller-surface restart with a retained uncertain fence and a later already-pending delivery shall run recovery, perform no second native submission, preserve attempts=0, and expose Needs intervention -> HTTP/integration regression. Moved or incomplete evidence shall remain queued without association -> fail-closed regression. Existing repeated busy-sweep tests shall still prove one native submission -> affected suite.

**Plan review:** Clean-context reviewer `/root/coalesced_recovery_review` approved the opt-in query plan at Elevated/Moderate with no checkpoint. It requires updating recovery test doubles for the new keyword and proving default/opt-in ordering, exact-ID behavior, one native submission, actionable later trace, and moved/missing/partial fail-closed behavior. Bounded read-only analysis `/root/coalesced_recovery_plan` independently found the same smallest shared-path change.

**Approvals:** Not required unless reclassification reaches High.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

Authoritative request source: `ff5d1534-0191-47f6-b586-95dd3c980476`.

## Evidence

- `apply_patch` failed once with Windows `CreateProcessWithLogonW failed: 1327`; the permitted deterministic narrow fallback was used.
- Added the internal opt-in enumeration flag and recovery call, updated recovery doubles, storage/service ordering coverage, an authentic pre-existing-pending restart recovery regression, and roadmap wording. The scheduler/reservation path is unchanged.
- Focused storage, restart, recovery-double, and concurrency nodes: `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest ... -q -n 0` -> `6 passed in 2.02s`.
- Six-sweep busy-recipient deduplication regression -> `1 passed in 1.38s`.
- Post-rebase focused regressions -> `6 passed in 2.51s`; six-sweep busy-recipient deduplication -> `1 passed in 1.39s`.
- Affected subsystem files -> `112 passed in 28.73s` and `235 passed in 62.53s`.
- Independent read-only review `/root/final_coalesced_review` found no correctness issue. It noted unbounded recovery dispatch as a performance advisory; existing candidate reads already scan the backlog, and pagination is deferred until backlog measurements justify a separate semantic change.
- First parallel full-suite run had one non-reproducible suppressed-reservation lifecycle failure; the exact test passed immediately in isolation. Clean full rerun -> `5091 passed, 34 skipped, 2 xfailed in 228.29s`.
