# Passive native enrollment diagnostics

<!-- agent-workflow:start -->
**Outcome:** Distinguish absent native enrollment from later custody loss without changing Relay delivery or the user's working environment.

**Target:** Existing retained Codex enrollment lifecycle and wake-health read surfaces.

**Scope:** Passive service-owned enrollment metadata, bounded lifecycle reason logging, existing status/summary composition, focused caller-surface tests and operations guidance. This is a diagnostic slice of relay-recovery-closure, not a second owner of that recovery round.

**Constraints:** No enrollment, reopen, retry, claim, ACK, submission or identity-fence behavior change. No payload, token, capability, private path, SID, process environment, handle or session identity output. No native transport call from a diagnostic read. Preserve fail-open diagnostics, bounded reads, existing scheduling-only assessment and unrelated settings/data. No installed copy, reload, restart, configuration, version or launcher change without exact human scope approval.

**Completion criteria:** Existing HTTP status and Relay summary distinguish never enrolled, remembered enrollment, disconnected retained enrollment and released enrollment, retain fixed last failure stage/reason and continuity-protocol evidence, and remain read-only under errors/concurrency. Logs distinguish lifecycle transitions without raw errors or secrets. Isolated tests cover success, denied enrollment, custody release, preserved reconnect authority, service replacement, shutdown and redaction/noninterference. Independent smart review, whole-change validation and PR CI pass; diagnostics alone never close installed recovery acceptance.

**Requirement baseline:**
{"source":"user:so take ownership of this and fix","outcome":"Distinguish absent native enrollment from later custody loss without changing Relay delivery or the user's working environment.","scope":"Passive service-owned enrollment metadata, bounded lifecycle reason logging, existing status/summary composition, focused caller-surface tests and operations guidance. This is a diagnostic slice of relay-recovery-closure, not a second owner of that recovery round.","constraints":"No enrollment, reopen, retry, claim, ACK, submission or identity-fence behavior change. No payload, token, capability, private path, SID, process environment, handle or session identity output. No native transport call from a diagnostic read. Preserve fail-open diagnostics, bounded reads, existing scheduling-only assessment and unrelated settings/data. No installed copy, reload, restart, configuration, version or launcher change without exact human scope approval.","completion_criteria":"Existing HTTP status and Relay summary distinguish never enrolled, remembered enrollment, disconnected retained enrollment and released enrollment, retain fixed last failure stage/reason and continuity-protocol evidence, and remain read-only under errors/concurrency. Logs distinguish lifecycle transitions without raw errors or secrets. Isolated tests cover success, denied enrollment, custody release, preserved reconnect authority, service replacement, shutdown and redaction/noninterference. Independent smart review, whole-change validation and PR CI pass; diagnostics alone never close installed recovery acceptance."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Additive operational metadata in runtime code requires independent review and strict noninterference. The proposed patch neither changes custody/authorization nor exposes identity or capability data. The parent recovery round remains High/Large; this narrow observational slice does not downgrade it.

**Discovery:** Both stable clones are f31ac141. No retained registration appears after service restart at 12:35:50 UTC; dispatch fails before state read at stage=reopen/category=peer-mismatch starting12:36:07. That category covers saved registration absent as well as identity rejection. Existing scheduling-only health cannot distinguish these cases. Existing private hook observer does not observe native enrollment. Native client correctly returns False for a signaled old service before checking bootstrap; no normal-restart defect is proved. Old/new process ages do not establish owner or loaded worker revision. Manager requests a narrow supported passive lifecycle diagnostic, isolated validation only. CI fixture correction remains frozen in separate worktree at f37b69d4 with6343 serial passes and smart approval.

**Material assumptions:** A cached service-owned event snapshot can distinguish lifecycle observations without inspecting opaque native state or invoking transport. Continuity opt-in proves the registration protocol used, not the loaded worker version or reachability. A remembered registration is not proof that its source is still live. If implementation requires native read probes, new authority, identity exposure or live environment changes, stop and revise this plan.

**Plan:** First invoke /agent-workflow and classify risk before code edits (completed). Reuse RetainedService lifecycle seams and relay_wake_health; atomically replace one flat, fixed-shape cached snapshot containing event time, historical accepted-in-this-service latch, remembered-registration state, cached custody-handle presence, continuity opt-in and last fixed failure stage/category. Status returns a defensive copy without acquiring _custody_lock, checking native liveness, invoking transport or logging. Unknown/missing/malformed service evidence is unavailable, never inferred as never enrolled. Historical acceptance survives denial, clear/drop and repeated cleanup; continuity is protocol evidence, not worker version. Distinguish authority cleared with custody still present, retained disconnect and unresolved handles; preserve the meaningful last failure across inherited cleanup and stop. Catch metadata-publication failures without changing original results. Expose through existing /status and dashboard Relay-summary composition, preserving scheduling-only assessment. No new tool, endpoint, configuration, subsystem or dependency. Enrich only existing fixed logging emission points if useful; no new synchronous sink call on reads or critical transitions. Existing stderr logging is synchronous and is not claimed to have a bounded sink. Review every _drop/_clear_registration caller to label observations honestly. Delegate bounded implementation/testing to a cheap agent after clean-context smart review; root reviews the diff and combined evidence. Keep the approved CI fixture release and this diagnostic slice separate. Installed rollout remains held pending exact change/impact/backup/rollback approval.

**Verification plan:** When status/summary is read, native enrollment state is observed without enrollment, native I/O, durable writes or queue progress → existing HTTP read-surface lifecycle tests with before/after state and transport-call assertions. When enrollment is accepted or rejected, metadata records the actual protocol and fixed outcome without changing the response → existing retained registration fixtures and redaction sentinels. When custody is dropped or preserved, metadata distinguishes released from retained-disconnected authority without changing fences → retained wake/continuity tests. When diagnostics fail or concurrent transitions occur, callers retain original results and snapshots have bounded coherent shape → failure/concurrency tests. Whole-change selector, affected serial subsystem and full non-slow suite, workflow/Redline/import checks and independent result review precede PR release.

**Plan review:** Agent technical review: /root/ci_fixture_plan_review (gpt-6.1-sol/high), approved repaired plan at 5152a99aa87af872112a5a886c08c8472c9e68d5. All five findings are resolved; Elevated/Moderate and existing isolated-work authorization suffice for this exact passive scope. No additional High-risk human decision is required. Source/result review and validation remain gates; admission, identity, delivery or live-environment expansion returns to planning. No production code edited before approval.

**Approvals:** Existing human incident/implementation authorization applies to isolated repository changes. No new authority or working-environment mutation is requested; Elevated requires technical review. Parent High-risk recovery approvals are not substituted for any later changed requirement or live operation approval.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Intended paths

- app/codex_bridge_pipe.py: RetainedService cached metadata and existing lifecycle seams only.
- app/relay_wake_health.py, app/main.py, app/dashboard.py: reuse both existing read surfaces.
- tests/test_relay_wake_health.py, tests/test_codex_retained_wake.py or existing continuity fixtures: observable lifecycle and noninterference coverage.
- docs/context/operations.md and this Work Record: meaning, limits and release evidence.

## Single new observation

An operator can distinguish whether this service epoch never accepted native
enrollment or accepted it and later dropped/retained-disconnected its custody,
with the last recorded fixed failure stage/reason and continuity opt-in. This
does not identify a live native owner, prove worker version, explain historical
unrecorded failures, or prove unattended payload consumption.

## Pre-edit review disposition

Smart review identified five concrete repairs: baseline/classification/state,
atomic lock-free copy, historical versus current evidence, clear/drop/unresolved
cleanup distinctions, and synchronous logging noninterference. The revised plan
addresses all five. Both HTTP views must cover never enrolled, legacy/continuity
acceptance, denial before/after acceptance, retained disconnect/reopen,
authority-cleared with custody present, unresolved cleanup, maintenance/source
disconnect, repeated shutdown/replacement, missing/malformed evidence,
concurrent read while custody lock is held, redaction and defensive-copy mutation.
Original caller results/native call counts/durable Relay state remain unchanged.
Repaired-plan confirmation approved 5152a99a; implementation may now begin.
