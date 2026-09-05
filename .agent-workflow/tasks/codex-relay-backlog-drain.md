<!-- agent-workflow:start -->
**Outcome:** Relay hook delivery automatically drains every bounded Codex and Claude backlog without manual turns, empty wake turns, duplicate action, or memory-routing leakage.

**Target:** Pallium Agent Relay wake and hook-delivery lifecycle.

**Scope:** Post-hook-ACK continuation wiring in `api/routes.py` and `app/dependencies.py`; safe pending-candidate selection in `storage/sqlite_relay.py`; bounded backlog handling in Codex UserPromptSubmit and Claude SessionStart/UserPromptSubmit/Stop hooks; focused caller-surface tests; Relay roadmap/docs. No public schema, MCP receive, OpenCode active wake, or new persistent state.

**Constraints:** Hook ACK is the only continuation trigger; MCP receipt ACK/reply must not schedule hook delivery. Reuse current Codex coalescing and Claude durable idle reconciler. Never schedule before successful ACK, never wake for unrenderable legacy rows, never mix hook delivery with MCP receive, preserve pinned container/actor/session scope and vnext structural work references, and use no wall-clock sleeps in normal tests.

**Completion criteria:** (1) After a successfully ACKed bounded hook batch, Codex schedules at most one exact-session continuation while safe pending work remains, and stops at empty; duplicate/failed ACKs schedule nothing. (2) Claude's existing Stop/idle reconciliation drains subsequent safe batches automatically and remains recursion-safe. (3) Every Codex/Claude Relay-claiming hook requests the 2,400-character budget, and `has_more`/`remaining_count` are surfaced as a bounded automatic-continuation notice without asking the model to pull via MCP or ingesting the trigger as memory. (4) Unsafe/legacy rows cannot block a later safe pending candidate or cause a wake loop; maximum valid Unicode deliveries remain supported. (5) Real HTTP+hook lifecycle E2E covers limits, ordering, arrivals during drain, duplicate triggers, ACK failure, exact-once IDs, scope isolation, routing suppression, and terminal empty state.

**Risk:** High

**Complexity:** Moderate

**Reason:** `api/routes.py` is a red API surface requiring api-review even though the callback is internal and public schemas stay unchanged; storage and app wiring are gray/watch paths. High follows the repository contract-surface rule. Moderate covers coordinated storage, route, wake, three hook surfaces, and lifecycle E2E.

**Discovery:** `relay_turn` returns bounded ordered claims plus `has_more`/`remaining_count`, but Codex/Claude hooks ignore both. Codex clears its per-session coalescing state on turn admission and has no post-ACK rearm; Claude already re-registers idle and signals its durable reconciler from Stop. Hook ACK uses `/relay/deliveries/ack` while MCP uses a separate receipt endpoint, providing the correct no-race boundary. `relay_pending_candidate` currently returns the first pending row without render-safety filtering, so a legacy unsafe row can block a later safe wake candidate. Existing maximum-field formatter coverage proves every currently valid delivery fits the hooks' 2,400-character turn budget, but Codex/Claude UserPromptSubmit and Claude SessionStart currently omit `max_chars`, so they claim an unbounded set before formatting; MCP intentionally preserves `max_chars=0` drain-all. OpenCode remains passive by roadmap and is not an automatic-wake target in this slice. PR #100 changed the same hook files for structural work references and is now merged; this branch started from that merge.

**Material assumptions:** (1) FastAPI response-model filtering permits internal recipient metadata on the ACK result without changing the HTTP response; a schema/OpenAPI diff disproves this and returns the task to planning. (2) A first successful hook ACK occurs after the turn callback has cleared Codex's prior scheduled generation, so current per-session coalescing can admit exactly one next wake; a concurrency test disproves this and requires redesign. (3) Claude Stop's idle registration continues to signal the persistent reconciler after recursive Stop protection; exact caller-surface E2E must prove it, otherwise Claude needs a separate minimal rearm. (4) OpenCode active continuation remains out of scope until its active wake roadmap slice; evidence of a shipped OpenCode active wake returns scope to planning.

**Plan:** 1. Extend the existing hook-ACK route with one injected, fail-soft post-success callback; expose recipient runtime/session only in the internal storage result and prove the public ACK schema/OpenAPI is unchanged. Do not invoke it for receipt ACKs, failed ACKs, or already-delivered retries. 2. In `app/dependencies.py`, use the callback only for Codex: query one exact-scope safe pending candidate after commit and feed it through the existing wake dispatcher/coalescer. Do not create a scheduler or queue. 3. Make `relay_pending_candidate` skip unrenderable legacy rows using the same payload renderability rule as `relay_turn`, while still finding later safe work; exact delivery-id status checks used by Claude recovery remain unchanged. 4. Make every Codex/Claude Relay-claiming hook explicitly request `max_chars=2400`, including Claude SessionStart, and add a short has-more notice while staying inside that same budget; it states Pallium will continue automatically and never instructs MCP receive. Preserve early exit before memory query/ingest and vnext work-ref handling. 5. Extend existing HTTP+actual-hook tests for multi-batch drain, message and character limits, safe-after-unsafe ordering, Unicode/max boundary, arrival between batches, duplicate and failed ACKs, coalesced next wake, Claude recursion/reconciler, exact-once IDs, cross-scope isolation, no synthetic memory, and no terminal wake. Stop on public schema drift, new cross-layer import, unbounded retry, or a required hook/MCP mixed path.

**Verification plan:** When a Codex hook ACK succeeds with more safe pending work, the system shall schedule one exact-session continuation and drain ordered IDs once, including a new arrival before the next batch -> real HTTP route + actual UserPromptSubmit lifecycle E2E with synchronous scheduler capture. When ACK fails or is replayed, the system shall schedule nothing -> HTTP conflict/idempotence regressions. When Claude has more than one bounded batch, Stop/idle reconciliation shall wake and drain again without recursive Stop looping -> actual Claude hooks + persistent registry/reconciler E2E with deterministic events. When unsafe legacy or over-current-budget work precedes safe work, the safe candidate shall continue and the unrenderable row shall not cause a loop -> storage + callback caller-surface regression. When `has_more` is true, both runtimes shall receive the automatic-continuation notice and perform no memory query/ingest; when false, no notice or extra wake shall occur -> hook output/routing tests. Public ACK response and OpenAPI shall remain unchanged -> response-shape/OpenAPI assertion. Final gate -> focused suites, import-linter, redline, agent-workflow, diff check, CodeRabbit, and installed Codex/Claude burst witness after integration reinstall.

**Plan review:** Initial clean-context Luna review accepted the plan. Supplemental review is pending for the newly discovered unbounded-hook-claim correction.

**Approvals:** Approved by user 2026-09-05: "you don't need to ask every time, you have a constant approval to get what you're working on to a done state"

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-05: Established RW-007 on branch `codex/relay-backlog-drain` from merged PR #100 and completed code/test/roadmap discovery. No production code edited.
- 2026-09-05: Pre-edit clean-context redline classified `api/routes.py` red with api-review required; storage/app/integration paths are gray/watch or unclassified, tests/docs blue, and no boundary violation. Raised to High under the contract-surface rule.
- 2026-09-05: Plan recorded; blocked pending clean-context plan review.
- 2026-09-05: Clean-context review accepted the plan. Incorporated bounded notice reservation and exact render-safety convergence; user standing approval satisfies the High-risk human gate. State moved to Ready to implement before production-code edits.
- 2026-09-05: Focused regression exposed omitted hook bounds: `max_chars=0` is intentionally unbounded for MCP receive but unsafe for context-injecting hooks. Expanded the same High-risk plan to cover Claude SessionStart and explicit 2,400-character requests; blocked only for supplemental clean-context review.

## Evidence

- Read-only lifecycle trace: `/relay/turn` bounds claims; hook ACK and MCP receipt ACK are separate routes; Codex admission clears scheduling before hook ACK; Claude Stop idle registration signals reconciliation.
- Existing floor: maximum valid Unicode formatter boundary, storage ordering/backlog accounting, hook memory suppression, Codex burst coalescing, Claude recursive Stop protection, and durable reconciler tests.

## Checkpoint: api-review

What is changing: extend internal hook-ACK callback plumbing so a successful bounded hook delivery can schedule the next exact-session Codex wake; public request/response schemas remain unchanged.

Why: RW-007 requires automatic bounded backlog draining through real integration surfaces.

Affected contract / model / boundary: `api/routes.py` internal callback wiring and the api-stays-thin boundary.

Compatibility / migration risk: low-medium; no schema migration or public field is intended, but callback timing affects delivery admission and exact-once behavior.

Verification: deterministic caller-surface E2E across Codex and Claude, including empty/max/over-current-budget batches, unsafe-first ordering, new arrivals, duplicate triggers, exact-once drain, memory routing, Unicode/scope isolation, and loop prevention.

## Plan review

Clean-context reviewer `/root/rw007_plan_review` (Luna, 2026-09-05) verdict: **ACCEPT; no material blocker**. The review confirmed the injected callback keeps `api/routes.py` thin, ACK commits precede candidate lookup, hook ACK and MCP receipt ACK remain separate, exact `delivery_id` status semantics remain unchanged, Codex admission can reuse current coalescing, Claude can reuse Stop/idle reconciliation if caller-surface E2E proves it, and OpenCode active wake remains out of scope. Non-blocking findings incorporated: gate continuation on a successful non-duplicate hook ACK, reserve any `has_more` notice inside the existing 2,400-character output budget, and make no-ID pending-candidate safety match `relay_turn` so legacy-invalid work cannot loop ahead of a safe row.
