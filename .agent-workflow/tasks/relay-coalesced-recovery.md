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

**Plan:** Pending clean-context review of the smallest safe internal enumeration shape.

**Verification plan:** Pending plan review; must include real app-restart caller-surface coverage proving one native submission and later pending needs-intervention guidance, plus moved/ambiguous fail-closed cases and existing busy-sweep regressions.

**Plan review:** Pending.

**Approvals:** Not required unless reclassification reaches High.

**Exceptions:** —

**State:** Draft
<!-- agent-workflow:end -->

Authoritative request source: `ff5d1534-0191-47f6-b586-95dd3c980476`.
