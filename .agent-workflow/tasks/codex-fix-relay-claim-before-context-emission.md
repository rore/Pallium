<!-- agent-workflow:start -->
**Outcome:** Relay delivery remains visible and recoverable through hook failures, reports backlog explicitly, and never turns transient SQLite contention into an opaque server error.

**Target:** Pallium Agent Relay.

**Scope:** Relay HTTP contract/storage, Claude Code and Codex hooks, OpenCode plugin, Relay docs/roadmap, and end-to-end integration coverage.

**Constraints:** Preserve deterministic scoped routing, no memory retrieval/ranking/LLM dependency in Relay, acknowledge only host-emitted deliveries, keep send/reply idempotency, and do not change SQLite schema unless discovery proves it necessary.

**Completion criteria:** When Relay deliveries exist, every supported integration emits them without waiting on memory work; when a turn is truncated it reports `has_more` and `remaining_count`; and when a Relay write meets transient SQLite contention it either completes exactly once within the bounded deadline or returns sanitized retryable HTTP 503 with `Retry-After`.

**Risk:** High

**Complexity:** Moderate

**Reason:** API response and error contracts (`api/schemas.py`, `api/routes.py`) are red-zone surfaces, while the change also alters persistence transaction behavior. Three host integrations require coordinated, failure-mode E2E coverage.

**Discovery:** Current Python hooks claim `/relay/turn`, then await `/item-and-query`, then emit/ACK; host output is consumed only at exit, so a memory delay discards Relay. Claude raw `print` and Codex non-ASCII JSON output can fail under CP1252. OpenCode claims in `experimental.chat.system.transform`; it must claim before mutation and avoid duplicate append after ACK failure. `RelayTurnResponse` lacks backlog metadata, and storage selects rows without server-side render-safety enforcement. `_begin_immediate()` bypasses `_with_retry`; a `BEGIN IMMEDIATE` lock surfaces as HTTP 500. Existing documentation asserts Relay is memory-independent, but the implementation contradicts it. The stated canonical roadmap item is absent from this checkout; add it rather than silently treating the broader idea as its replacement.

**Material assumptions:** The host accepts explicit UTF-8 bytes from Claude and ASCII-only JSON from Codex; verify with hook unit tests simulating CP1252, otherwise stop and revise output adaptation. `has_more` can be computed from the same eligible rowset without schema changes; verify under live claims/expiry. Retry can remain below the 0.5/0.75-second hook deadlines; if SQLite's connection-level busy wait prevents that, introduce a Relay-scoped bounded acquisition mechanism rather than widening hook timeouts.

**Plan:**
1. Add the missing roadmap item with RF-005–RF-007 evidence and acceptance matrix; update Relay documentation for backlog and retry semantics.
2. Change the turn contract to expose `has_more: bool` and `remaining_count: int >= 0`; inside the immediate transaction, validate renderability before claiming, select only renderable eligible deliveries, reserve the compact backlog-notice budget, and count eligible unclaimed rows after selection (excluding expired and live claims).
3. Make Python hooks use a Relay-only fast path whenever renderable Relay exists: render, UTF-8/ASCII-safe host emission, ACK successful emission, and exit without waiting on memory. Rework OpenCode so `chat.message` claims, `messages.transform` mutates, and ACK follows one successful mutation; retain a per-turn emitted guard so ACK failure does not append twice.
4. Add bounded retry around the replayable immediate-transaction operation (not a contextmanager body); map exhaustion to sanitized `503` `{code: relay_busy, retryable: true}` plus `Retry-After`, with no SQLite text. Preserve message-ID and reply idempotency and rollback on every failed attempt.
5. Cover all API, MCP, Python-hook, OpenCode, and real SQLite lifecycle/error paths; run focused suites, full relevant suite, redline/workflow checks, then request one final consolidated architectural code review.

Key conventions: reuse `RelayService` validation and existing idempotent message/reply behavior; do not add dependencies; keep Claude/Codex common behavior symmetric; use existing redaction and bounded formatter patterns.
Target files: `api/schemas.py`, `api/routes.py`, `core/relay.py`, `storage/sqlite_relay.py`, `storage/sqlite_queue.py`, `integrations/{claude-code,codex}/hooks/{common.py,user_prompt_submit.py}`, `integrations/opencode/.opencode/plugins/{pallium.mjs,pallium-common.mjs}`, `tests/test_agent_relay_e2e.py`, `tests/test_agent_relay_hooks.py`, `tests/test_sqlite_write_retry.py`, OpenCode plugin tests, Relay docs, and roadmap.

Stop conditions: a required output encoding cannot be made host-safe without altering host contract; bounded lock acquisition cannot stay below hook deadlines; or an API error shape conflicts with existing consumer behavior.

**Verification plan:**
- When memory retrieval times out or fails after a Relay claim, each host shall emit Relay and ACK only that emitted delivery -> Python hook/OpenCode integration tests and lease-recovery E2E.
- When Unicode is delivered under CP1252, Claude and Codex shall emit valid host context without duplicate ACK -> simulated encoding regression tests.
- When backlog exceeds char or message budgets, the turn shall expose correct `has_more`/`remaining_count`, render a notice, and leave omitted deliveries unacknowledged -> HTTP plus all integration tests for cap, oversized-first, unsafe, lease/expiry, and full-drain cases.
- When a write lock clears inside the deadline, turn/send/reply/ACK shall complete exactly once; when it persists, each shall return sanitized retryable 503 with `Retry-After` and no partial write -> real SQLite contention E2E plus MCP send/reply regressions.
- When the final diff touches API and storage behavior, it shall pass focused and full Relay tests, redline, and agent-workflow validation -> recorded commands and outputs before review.

**Plan review:** Architect review received via Pallium Relay, `relay-reply-3568bad8de3211d3d341db04e3296fe819fad37880542c95062b07671cc7f6d5`, 2026-08-27. Required gates incorporated: Python Relay-only fast path; host-safe Unicode output; OpenCode claim/mutate/ACK ordering and duplicate guard; server-side render safety and backlog reservation; bounded replayable transaction retry below hook deadlines; sanitized 503 contract; exhaustive lifecycle/MCP contention coverage.

**Approvals:** Approved by user 2026-08-27: "Budget correction: do not return for another plan-review round. Incorporate the complete architectural feedback into the Work Record, implement and verify the full fix, then request one consolidated final code review."

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

2026-08-27 — Implemented the smallest shared contract change: `/relay/turn` exposes `has_more` and `remaining_count`; selection validates payload renderability, reserves the 80-character integration notice on full-size turns, and claims only selected deliveries. Claude Code and Codex emit Relay before memory work (Claude uses explicit UTF-8 bytes on non-UTF-8 terminals); OpenCode claims in `chat.message`, mutates in `system.transform`, removes the pending claim before ACK, and renders a compact backlog notice. Immediate-transaction acquisition retries for at most 0.45 seconds and maps exhaustion to `503 {code: relay_busy, retryable: true}` with `Retry-After: 1`.

Final architectural review required three corrections, all applied: restore the 15-second busy timeout before every immediate-transaction connection returns to the pool; count only renderable eligible rows and never fast-exit on a backlog-only formatter result; and restore the unrelated `uv.lock` refresh. Pre-rebase verification after those fixes: `51 passed` across Relay/API/hooks/SQLite tests including the former concurrent-feedback regression; OpenCode plugin tests `17 passed`; Python compilation and `git diff --check` passed. MCP tests remain skipped because the optional `mcp` package is absent. The local virtualenv was supplied with the workflow-only `jsonschema` and PyYAML packages; no project dependency manifest changed.

Governance closure: local redline verdict `RED` identified API red-zone files but no boundary violations; the architect-approved API review satisfied the `api-reviewed` checkpoint. `python scripts/agent-workflow-check.py --repo-root . --slug codex-fix-relay-claim-before-context-emission --redline-verdict build/redline-verdict.json` exited 0 on 2026-08-27.

Post-rebase verification: focused Relay/API/hooks/SQLite suite `56 passed`; OpenCode plugin suite `19 passed`; Python compilation and `git diff --check` passed. The final redline rerun found no boundary violations and the `api-reviewed` checkpoint satisfied. `agent-workflow-check` reported only the non-blocking advisory that this historical Work Record shares its first commit with code.
