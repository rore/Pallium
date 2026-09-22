<!-- agent-workflow:start -->
**Outcome:** Relay status explains retained uncertain wakes, queued accepted wakes, expired unclaimed messages, delivered messages, and incomplete evidence without changing delivery behavior.

**Target:** Pallium Relay.

**Scope:** Existing delivery-trace explanation and its dashboard/MCP projections; focused tests; canonical Relay roadmap item.

**Constraints:** Wake, claim, ACK, TTL, retry, scope, model, effort, and busy-turn interruption behavior remain unchanged; no private incident data enters fixtures or docs.

**Completion criteria:** Each required state produces accurate operator guidance through actual caller surfaces; delivered state overrides obsolete activation failure guidance; focused and required repository checks pass.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline reports GRAY because non-dashboard app runtime code may change; several projections and legacy/partial evidence paths require coordinated verification.

**Discovery:** `storage/sqlite_relay.py::relay_trace_message` is the single explanation seam used unchanged by core, HTTP, dashboard, and MCP. Existing snapshots distinguish never-claimed expiry (`attempts=0`, `claimed_at=None`) without mutation. Delivered already precedes stale activation evidence. The clarification branch is clean but adds separate activation-scope API fields and is intentionally not folded into this status-only slice.

**Material assumptions:** Caller-visible explanation text is sufficient to make these existing states actionable without a new response field; disprove if focused HTTP/dashboard/MCP tests show a consumer strips or replaces it, then return to planning. Existing claim counters remain authoritative for never-claimed expiry; disprove on claim-lifecycle inspection or tests, then stop.

**Plan:** Change only explanation precedence/text in `storage/sqlite_relay.py`. Build an orthogonal evidence-gap suffix and include it on all-delivered, mixed-state, and all-expired terminal summaries. Precedence: all-delivered; mixed recipient states with counts so pending/expired recipients are not hidden; all-expired, using never-claimed wording only when every snapshot has zero attempts/no claim and otherwise stating that prior claim/activation evidence did not produce acknowledged delivery; legacy/truncated/pruned pending evidence as unknown/qualified; then pending uncertain as needs-intervention with held-retry ordinary-turn guidance, pending unreachable as needs-intervention, pending accepted as queued/safe-turn guidance, and deferred/failed/absent fallbacks. Add focused lifecycle, fan-out, Codex/Claude, evidence-gap, expired-with-prior-claim, HTTP/dashboard, and MCP regressions in existing Relay trace tests. Update the canonical roadmap with PR #209 diagnostics, this status slice, the unresolved automatic-recovery blocker, and the separate clarification branch. Stop if implementation requires API/schema/core contract or delivery-behavior changes.

**Verification plan:** All-delivered precedence, mixed fan-out counts, accepted/uncertain pending for Codex and Claude, expired never-claimed versus claimed, and legacy/truncated/pruned qualification → focused `tests/test_relay_delivery_trace.py`; HTTP/dashboard equality and MCP preservation → existing caller-surface tests plus focused `tests/test_relay_mcp_tools.py`; no delivery-state mutation or retry/claim/ACK change → existing lifecycle assertions and affected Relay subsystem tests; repository policy → agent-redline and agent-workflow checks, then `python -m pytest tests/ -x -q` before review/PR.

**Plan review:** Clean-context review approved the corrected precedence and test plan; see `## Plan review`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Planning opened from `a1b7a79c38d3394922422305834cffaf0c0eeb03`; no code edits made.
- Discovery confirmed one shared storage projection and no required API/schema change. The clarification branch remains separate because its evidence-scope fields are complementary API work, not required for actionable trace guidance.
- Added focused trace/MCP regressions for actionable uncertain, queued, expiry, delivery precedence, mixed fan-out, evidence gaps, and caller projections; initial delegated run lacked pytest, so Sol owns executable verification.
- Reverified the running Desktop binary as `codex-cli 0.155.0-alpha.9.2`; its public queue surface still has no caller idempotency key or authoritative queue readback, so automatic uncertain-failure recovery remains an upstream blocker rather than part of this slice.
- Independent result review found and drove two corrections: neutral prior-claim expiry wording and any-recipient legacy gap detection. Expanded focused coverage now exercises every explanation fallback and aggregate branch.

## Plan review

Initial clean-context review rejected the first precedence sketch: any-delivered could hide pending fan-out; accepted/uncertain outcomes could overstate incomplete evidence; expiry needed never-claimed versus prior-claim wording; accepted-pending needed retained-delivery guidance. The revised plan adds explicit aggregate-state, evidence-gap, expiry, runtime, and caller-surface coverage. First re-review required gap disclosure on mixed states and a terminal all-expired prior-claim branch; both are now explicit. Final clean-context re-review approved with no remaining blocker.

## Evidence

- Revision `9462fd08` carries the final reviewed implementation.
- `uv run --all-extras python -m pytest tests/test_relay_delivery_trace.py tests/test_relay_mcp_tools.py -q -n 0` → 142 passed.
- `uv run --all-extras python -m pytest tests/ -x -q` → 5066 passed, 34 skipped, 2 xfailed.
- Import-boundary backend passed; final redline verdict is GRAY for `storage/sqlite_relay.py`, with no boundary, API, schema, security, config, or checkpoint findings.
- `uv run --with jsonschema --with pyyaml python scripts/agent-workflow-check.py --repo-root . --slug relay-actionable-wake-failure` → clean.

## Result review

- Independent review returned the task to implementation: neutralize expired prior-claim hook wording, treat any legacy fan-out recipient as an evidence gap, and cover every explanation fallback/aggregate branch.
- Targeted non-implementer re-review confirmed all three findings resolved, completion criteria and evidence adequate, and no remaining actionable correctness findings.
