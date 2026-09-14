<!-- agent-workflow:start -->
**Outcome:** Codex integration readiness reports distinguish installed configuration from verified hook execution, actionable definition changes, normal Relay backlog, and unknown MCP exposure.

**Target:** Pallium.

**Scope:** `app/codex_readiness.py`, `app/cli/setup_codex.py`, Codex UserPromptSubmit/common hook entrypoints, Relay dashboard summary/renderer, focused tests, Codex docs, canonical Relay roadmap/board, and this Work Record.

**Constraints:** Preserve Codex-owned trust metadata; never approve hooks or manufacture trust hashes; no routing repair, new monitoring framework, or assertion that unknown trust/MCP state is a confirmed failure.

**Completion criteria:** Unchanged reinstall preserves verified evidence without a new review warning; changed hook command/path tells the user review and restart are required; existing trust metadata survives; unavailable trust introspection is labeled unknown; pending after a wake with no later exact-endpoint check-in is neutral awaiting evidence and becomes actionable only when corroborated by current review-required or explicit failure evidence; later check-in clears that observation while claim/delivery separately proves recovery; MCP exposure uncertainty is reported separately; canonical roadmap puts Relay reliability first with owners; an installed real Codex task proves send, next-turn hook claim/injection/ACK, reply, and work-ref attach/detach across the affected setup or leaves qualification explicitly incomplete.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Clean-context redline review classified the intended app setup/readiness surface as gray with no boundary or contract checkpoint. Moderate complexity spans several observable integration states and recovery transitions.

**Discovery:** `app/cli/setup_codex.py` already reconciles managed definitions idempotently, preserves Codex-owned `[hooks.state]` trust metadata, and distinguishes changed versus unchanged hooks, but verifies only HTTP `/status` and leaves no durable post-setup readiness evidence. `integrations/codex/hooks/user_prompt_submit.py` is the actual Relay claim/injection entrypoint. Existing immutable `relay_delivery_trace`, endpoint `last_seen_at`, delivery attempts/state, and PR #186 split-identity evidence can identify a wake attempt with no later endpoint check-in without a timer or monitor. Codex alone owns trust and MCP inventory, so both remain explicitly unknown until observable execution/tool presence proves otherwise. Canonical tracking is `roadmap/features/add-wake-first-relay-delivery.md`; `roadmap/board.md` currently mis-prioritizes Session History ahead of reliability.

**Material assumptions:** Existing setup comparison and status/dashboard telemetry are sufficient; disprove by finding no reusable hook-definition comparison or no observable endpoint activation/backlog signal, then return to planning rather than add a monitoring subsystem. Codex trust state cannot be authoritatively inspected by Pallium; disprove only with a documented Codex-owned readiness API, then reassess the plan.

**Plan:** Add one stdlib-only file marker helper shared by setup/dashboard and dynamically loaded by the direct hook. Setup writes `review_required` only when managed hook definitions changed, preserves a matching verified marker on unchanged reinstall, creates `unknown` for legacy/no evidence, and says restart/review plus MCP exposure remains host-owned and unknown. The exact UserPromptSubmit executable+script instance changes that marker to execution-observed `verified`; a stale path cannot clear it, marker I/O is fail-open, and no trust hash is read or written. Extend the existing Relay summary with one exact-delivery/endpoint read-only aggregate for unexpired Codex deliveries still pending with attempts=0 when prepared/completed wake trace is newer than endpoint check-in. Render this as neutral `awaiting_recipient_checkin`; it is actionable only when current `review_required` or explicit failure evidence independently corroborates it. Later exact-endpoint check-in clears awaiting evidence; claim/delivery separately proves delivery recovery. Deduplicate repeated/associated trace rows and treat absent/pruned evidence as unknown. Update `roadmap/board.md`, stale opening/execution-order prose, and three owner/next-action rows in `add-wake-first-relay-delivery.md`: this readiness slice, separate MCP exposure diagnosis, and guarded stranded-delivery dispositions. Add focused setup, hook, HTTP lifecycle including healthy busy negative cases, renderer, docs, and roadmap tests. After merge/stable reinstall, run a bounded real Codex task witness covering send -> natural/queued next-turn hook delivery -> processing/reply -> work-ref attach/detach; label any manual fallback and do not equate hook/service success with MCP exposure. Stop and re-plan if a public API/schema/core/persistence surface or background monitor is required.

**Verification plan:** Unchanged reinstall shall preserve verified evidence and produce no review-required warning -> focused setup E2E. Changed command/path shall preserve unrelated/trust data and report review plus restart -> focused setup E2E. Missing/malformed/unreadable evidence and Codex-owned trust introspection shall remain unknown -> focused helper/CLI/dashboard tests. Matching UserPromptSubmit execution shall verify its marker while stale/Unicode paths cannot and I/O failure does not block delivery -> actual hook entrypoint tests. Prepared/completed wake newer than exact endpoint check-in with pending attempts=0 shall produce one neutral awaiting observation; current review-required corroboration shall make one actionable note; a healthy busy accepted wake shall not be called failed; later check-in with remaining backlog, claim/delivery, expiry, absent/pruned and repeated/associated trace rows shall clear or remain unknown without duplicates -> HTTP lifecycle E2E through `/dashboard/api/relay/summary`. MCP uncertainty shall remain separate -> focused renderer/CLI test. Roadmap board and stale execution prose shall make reliability first and name three owners/next actions -> docs assertion. Final diff -> affected subsystem tests, workflow/redline checks, full tests once, then stable install plus real Codex task send/hook/ACK/reply/work-ref attach-detach witness with fallback labeled.

**Plan review:** Approved clean-context review; all three planning findings resolved under `## Plan review` (2026-09-14).

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Added `app/codex_readiness.py`, a bounded atomic marker that records only
  reconciled hook-definition state and exact matching UserPromptSubmit execution.
  Missing, malformed, oversized, unreadable, or mismatched evidence stays
  `unknown`; marker failure is fail-open for Relay delivery.
- Setup preserves Codex-owned trust data, reports service/configuration,
  execution evidence, hook trust, and MCP exposure separately, and removes its
  marker best-effort on uninstall.
- The Relay dashboard now reports bounded exact-delivery/endpoint
  `awaiting_recipient_checkin` evidence. Accepted busy work is neutral; current
  `review_required` or persisted `failed`/`deferred` evidence makes the signal
  actionable. Missing/pruned trace evidence is unknown. The diagnostic is
  read-only and exposes no local hook paths.
- Updated the renderer, Codex integration docs, canonical Relay roadmap, board,
  and scope. No routing repair, ACK, retarget, trust mutation, or scheduler retry
  behavior changed.
- Live incident correlation found the native wake in the exact target rollout at
  `2026-09-14T12:46:59Z`, while Pallium hook/scope evidence and exact endpoint
  check-in stopped at `2026-09-14T09:28:06Z`. This proves Codex admission
  without subsequent observed hook/check-in evidence; hook execution failure and
  trust status remain unconfirmed. The durable accepted reservation
  then retained the earliest delivery and suppressed later wake submissions as
  designed; weakening RW-022 deduplication would not repair the inactive hook.
- Later evidence showed the same target receiving injected Relay payload and scope
  while its callable inventory still exposed no Pallium MCP tools. This confirms
  hook readiness and MCP exposure are independent; RW-028 remains open.
- Editing used the permitted deterministic named-file PowerShell fallback after
  one `apply_patch` attempt failed with Windows error 1327.

## Evidence

- Smart clean-context result review found and drove fixes for exact entrypoint
  identity, anti-self-verification, bounded reads, mixed failure wording,
  renderer coverage, and test-state isolation; final review approved with no
  remaining correctness or security finding.
- `tests/test_codex_integration.py`: 41 passed before review corrections; the
  corrected suite plus exact lifecycle target passed 44 tests. Final full-file
  rerun is part of the pre-PR verification below.
- `tests/test_dashboard.py`: 57 passed, including exact recipient check-in,
  review-required, explicit failure, associated trace, pruned/unknown, expiry,
  no-expiry persistence, and real claim clearing.
- `tests/test_codex_wake.py`: 70 passed, preserving scheduler, admission, ACK,
  and durable deduplication behavior.
- `tests/dashboard_plain_language_renderer.mjs`: all cases passed, including
  review-required, mixed failures, healthy busy waiting, and unknown evidence.
- Python syntax compilation passed for every changed Python file. `git diff
  --check` passed. The repository virtual environment does not include Ruff, so
  Ruff was not claimed locally.
- Full repository suite: 4,969 passed, 34 skipped, 2 expected failures in
  202.65 seconds. Its only first-run failure was an existing byte-for-byte
  dashboard snapshot assertion over live age counters; the test now excludes only
  `*_age_seconds`, its exact node passed, and the full rerun is green.
- Import-boundary report passed. Final redline is Gray/Elevated with no boundary
  violation or checkpoint; the agent-workflow checker exits clean.
- Installed real Codex qualification remains intentionally pending until merge,
  stable-checkout reinstall, Codex review/restart, and the bounded send -> hook
  claim/injection/ACK -> reply -> work-reference attach/detach witness.
## Plan review

- Confirmation 2026-09-14: approved. The revised plan resolves all three findings below: neutral awaiting evidence with corroborated actionability, installed-session qualification, and complete roadmap priority alignment. The findings below describe the initial review and are resolved by the revised plan. Matching Unicode paths must verify successfully; only stale or mismatched paths must fail to verify.
- Initial verdict: changes required before implementation. The shared stdlib marker and existing dashboard query are appropriately small; no monitor, trust manipulation, or delivery repair is needed. No structural risk escalation was identified.
- P2 (blocking) - distinguish observation from failure. `app/codex_wake.py` emits `prepared` before debounce and `completed` after native queue submission; a healthy busy or delayed recipient still has pending attempts=0 and an older endpoint check-in. This predicate proves only that no later check-in has been observed, not that execution failed or trust is missing. Keep it as neutral awaiting-check-in evidence, or make the actionable warning conditional on separate current review-required or explicit failure evidence. State which trace stages count, join by the exact delivery/endpoint, treat absent/pruned traces as unknown, and add delayed/busy accepted wake coverage. A check-in can clear this observation; describe recovery as verified only when the hook/claim outcome independently supports it. Test later check-in with remaining backlog, claim/delivery, expiry, and repeated/associated trace rows without duplicate counts or warnings.
- P2 (blocking) - add installed real-session verification to the completion gate. A direct hook subprocess test proves executable behavior, not that the installed Codex host invoked it. Require a bounded witness using the installed command in an actual Codex task: changed definitions show review-required; after ordinary host review/restart, actual UserPromptSubmit execution records evidence; one pending Relay delivery is claimed/injected/ACKed; the corresponding warning clears; unchanged reinstall preserves evidence and trust metadata. Follow the stable-checkout installation lifecycle and record runtime/platform plus evidence, or explicitly leave installed qualification incomplete if host restart is unavailable. Do not manufacture trust, manually invoke the script as a substitute, or claim MCP exposure from hook/service success.
- P2 (blocking) - reconcile existing roadmap priority prose, not just append owner rows. `roadmap/features/add-wake-first-relay-delivery.md` still says the next feature is session-to-work associations near its opening and in `Next execution order`; those contradict the board's done entries and the architect's reliability-first direction. Update both stale execution statements together with board ordering and the three owner/next-action tracks. Keep shipped milestones and residual platform qualification distinct from this new readiness slice.
- Marker design accepted with explicit semantics: verified means the matching current UserPromptSubmit executable/script was observed running, not current Codex trust, every task's readiness, successful Relay delivery, or MCP tool exposure. Preserve the pending review-required marker on unchanged reinstall until matching execution; a stale command/path must not clear it. Missing, malformed, or unreadable state stays unknown and marker I/O must never prevent ordinary hook delivery. Include these transitions, command/path changes, unrelated/trust preservation, Unicode paths, uninstall/reinstall, and one-note rendering in the focused existing E2E/renderer tests.

## Result review

- Approved by an independent Astra review after all findings were corrected.
  No production correctness or security findings remain. Installed-session
  qualification remains the final completion gate and must not be inferred from
  deterministic tests.
