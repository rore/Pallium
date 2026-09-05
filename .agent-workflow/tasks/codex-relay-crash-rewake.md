<!-- agent-workflow:start -->
**Outcome:** A Relay delivery whose hook turn crashes after claiming is automatically re-woken after lease recovery and delivered exactly once without a manual agent turn.

**Target:** Pallium Agent Relay wake and recovery lifecycle.

**Scope:** Exact-session expired-claim recovery and wake scheduling in the shared Relay persistence/service path and existing Codex/Claude runtime adapters; actual HTTP/hook E2E; Relay roadmap/docs.

**Constraints:** Preserve the 60-second claim lease and runtime-owned identity; no model polling, hook/MCP mixing, duplicate or empty wakes, platform-specific core behavior, new dependency, or wall-clock sleep in normal tests. Reuse existing wake coalescing/reconciliation and retain durable natural-turn fallback when launch fails.

**Completion criteria:** When a hook claims an eligible delivery and terminates before context emission/ACK, lease expiry shall automatically schedule its exact session again and the real hook surface shall deliver and ACK that ID once; duplicate recovery signals, concurrent new sends, scope mismatch, restart, launch failure, and terminal empty state shall preserve pending work without duplicate action or wake loops.

**Risk:** High

**Complexity:** Moderate

**Reason:** High by engineering judgment because a failure here strands or duplicates persisted deliveries across exact-session admission, although redline classifies the intended storage/core/app paths gray with no checkpoint. Moderate spans one shared persistence query, existing reconciliation/dispatch wiring, two runtime adapters, and real lifecycle E2E.

**Discovery:** `relay_turn` already reclaims expired leases, but only when another turn occurs. `relay_pending_candidate` maps an exact expired claim to pending yet excludes expired claims from ordinary candidate selection. Codex clears in-memory wake state at admission and has no recovery scan; Claude has the sole app-local event loop, but its idle reconciliation also uses the excluding query. The persisted delivery, message, and active session rows contain exact runtime/session/container/actor identity and lease deadline. Existing dispatchers already coalesce per session and fail safely. The manual-prompt recovery test proves reclaim, not unattended wake. Redline: intended storage/core/app paths gray, tests/docs blue, no boundary violation or checkpoint; schema/API expansion would require reclassification.

**Material assumptions:** (1) Active Relay session plus delivery/message rows are the authoritative runtime-owned recovery identity; any need for model-supplied scope returns to planning. (2) The existing app-local thread can be generalized and started whenever Relay is available, independent of Claude registry persistence or health; a test counterexample requires a separate coordinator. (3) A fixed 30-second expired-claim sweep plus existing per-session adapters bounds failed-launch cost while guaranteeing retry until message expiry; measured unacceptable latency or process cost requires backoff state. (4) Existing adapter coalescing plus sweep-local exact-scope dedup suppresses repeated signals until admission; a caller-surface counterexample requires persisted retry state. (5) No schema or public API change is needed; touching either returns to redline and plan review.

**Plan:** 1. Make ordinary no-ID pending-candidate selection treat unexpired render-safe expired claims as pending for Claude idle recovery, while preserving the intentional exact-ID status/cleanup contract. Add one strict read-only SQLite/RelayService recovery query: active exact session, unexpired render-safe message, expired claimed delivery only, oldest one per `(container_ref, actor_ref, runtime, session_ref)`, optional exact-ID recheck, no mutation/schema. 2. Extract the existing app-level send wake routing into one reusable function; both sends and recovery use the same Codex/Claude validation, destination feedback, and adapter coalescing. 3. Generalize the existing app-local reconciler and start it whenever Relay is available, independent of Claude registry persistence/health. Preserve immediate event-driven Claude reconciliation; run the expired-claim sweep immediately at startup and every fixed 30 seconds, sweep-dedup by exact scope, strict recheck immediately before dispatch, and let existing asynchronous adapters serialize by session. Failed launch leaves the expired claim durable for a later sweep. 4. Drive actual HTTP plus installed-hook modules for Codex and Claude crash-after-claim, lease expiry, automatic re-wake, ACK, terminal empty, duplicate/concurrent signals, new arrival, scope/closed/expired/unrenderable exclusions, failed-launch retry cadence, service restart, Unicode/max boundary, and no synthetic memory. Use controlled clocks/events only. 5. Align RW-008 docs and stop if tests require new identity, persistence state, API/schema changes, a second background thread, or hook/MCP mixing.

**Verification plan:** When an admitted hook crashes after claim, the system shall re-wake after deterministic lease expiry and produce one delivery/ACK with an empty terminal state → actual HTTP plus Codex/Claude hook lifecycle E2E. Failure, duplicate, restart, concurrent-arrival, Unicode/max-boundary, cross-scope, closed, expired, and unrenderable cases shall preserve exact-once durable behavior → focused storage/coordinator tests with controlled clocks/events and no wall-clock sleep.

**Plan review:** Clean-context review accepted the amended plan; see `## Plan review`.

**Approvals:** Approved by user 2026-09-05: "you don't need to ask every time, you have a constant approval to get what you're working on to a done state"

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-05: Established RW-008 from merged/installed RW-007. No production code inspected or edited before the Work Record.
- 2026-09-05: Traced lease storage, service/router callbacks, Codex admission, Claude registry/reconciler, real hooks, and existing recovery tests. Root gap is unattended expiry-to-wake signaling, not reclaim semantics.
- 2026-09-05: Clean-context redline classified intended storage/core/app paths gray, tests/docs blue, with no boundary violation/checkpoint. Risk remains High by exact-once persistence judgment; plan is blocked only for clean-context review.
- 2026-09-05: Clean-context plan review blocked the Claude-gated draft, then accepted the amended Relay-wide, startup-independent, bounded-retry design. Standing user approval satisfies the High-risk gate; State moved to Ready to implement before code edits.

- 2026-09-05: Implemented one strict read-only expired-claim query over existing Relay rows, one candidate per active exact Codex/Claude session, with render safety, message expiry, closed-session, scope, and optional delivery recheck gates. Ordinary Claude pending selection now treats an expired claim as pending without changing exact-ID cleanup semantics.
- 2026-09-05: Reused the existing app-local reconciler and runtime dispatchers. The loop starts independently of Claude persistence, isolates Claude capability failures, sweeps at startup and every 30 seconds, exact-rechecks before dispatch, and leaves failed launches durable for the next bounded retry.
- 2026-09-05: Added controlled-clock actual HTTP/hook E2E for Codex and Claude crash-after-claim, real Claude Stop idle transition, both full-app restart paths, Unicode maximum payload, duplicate/terminal suppression, strict exclusions, read-only state, candidate error isolation, and retry cadence. No schema, API, dependency, identity, second thread, wall-clock sleep, or hook/MCP mixing was added.
- 2026-09-05: `apply_patch` was unavailable on this Windows host (CreateProcess error); edits used deterministic replacements limited to the named RW-008 files, per local AGENTS.md fallback.

## Evidence

- Focused Relay wake/hook/durability/registration/integration suite: 237 passed, 2 platform skips in 17.18 seconds; all newly added tests pass.
- Import boundary report, agent-workflow check, Python compilation, and `git diff --check` are clean. Ruff is not installed in the project environment, so no dependency was added solely to run it.
- Full-suite execution found one unrelated pre-existing local-config isolation failure in `tests/test_config.py::test_prompt_variants_legacy_fallback_unaffected`: the test reads the user's default Pallium config. The same unchanged test fails alone on `main`; RW-008 focused coverage is clean.
- Clean-context final review initially required a Codex startup-surface restart E2E; that test was added and the reviewer then accepted the implementation.

## Plan review

Clean-context review `/root/rw008_plan_review` initially blocked the draft because the existing loop was Claude-gated, retry cadence could hammer a 330-second Codex launch path, and coalescing/recheck invariants were implicit. The amended plan makes the coordinator Relay-wide and startup-independent, separates immediate Claude signals from a fixed 30-second expired-claim sweep, deduplicates/rechecks exact scopes, and retains durable retry. The suggestion to hide unsafe/delivered rows from `pending_candidate(delivery_id=...)` was not adopted: that method is intentional exact status used to clear stale Claude inflight state and is pinned by `test_pending_candidate_skips_unsafe_without_hiding_exact_status`; the new recovery query owns strict active/render-safe/unexpired/expired-claim eligibility instead.
