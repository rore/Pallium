<!-- agent-workflow:start -->
**Outcome:** Relay aliases cannot silently leave work queued on an unclaimable legacy endpoint after a supported scope transition, and this incident's stale local endpoint is repaired without losing delivery provenance.

**Target:** Pallium Relay.

**Scope:** Diagnose the legacy split endpoint; repair the local alias and endpoint state explicitly; change Relay lifecycle diagnostics or an explicit repair surface only if architecture validation shows current behavior remains a product gap; add focused HTTP/MCP E2E coverage and align operator documentation when product code changes.

**Constraints:** Preserve canonical endpoint identity, container isolation, alias/work associations, pending and claimed delivery semantics, and historical provenance. Do not assume runtime session references are globally unique. Do not silently merge, reroute, or take over endpoints. Do not change memory or Session History visibility.

**Completion criteria:** The stale local alias resolves to the intended live endpoint and no work remains silently stranded; future legacy-split cases either remain impossible under the existing transition path or produce an explicit, safe repair signal/operation; observable contracts are covered end to end through the caller-facing HTTP or MCP surface.

**Risk:** High

**Complexity:** Moderate

**Reason:** Relay endpoint identity, durable alias ownership, and pending/claimed delivery routing are persistence and cross-container contract surfaces. The current incident spans integration admission, storage lifecycle, scheduling, and operator recovery.

**Discovery:** One Codex runtime session has an older Dictation endpoint holding alias `dict-dev2` and pending deliveries plus a newer Pallium endpoint used by the installed hook. The architect sent to the alias, so Relay correctly resolved the old canonical endpoint, while a separate direct Codex task message started the target without invoking UserPromptSubmit and therefore could not claim or ACK Relay. Restart recovery reserved the old `(session_ref, container_ref)` wake; current Pallium hook admissions use the new container and cannot clear it. Commit `d1e6964a` already adds atomic stateful scope transition and should prevent future clean moves, but the stale split predates that installed code. `roadmap/features/investigate-cross-repository-relay-coordination.md` states that runtime session references are not globally unique and canonical identity is the endpoint ID, invalidating automatic convergence by `(runtime, session_ref)`. Existing explicit alias takeover moves only the alias; it does not migrate deliveries or work associations.

**Material assumptions:** The legacy split should be repaired only with explicit old and new canonical endpoint identities plus conflict checks and user intent; architecture review disproves this if it identifies an existing safe lifecycle contract that already repairs all stranded state. Product code is unnecessary if current atomic transition fully covers supported flows and the remaining incident can be resolved through existing explicit operations; a reproducible supported path that still creates or strands a split disproves this and returns the task to planning for the smallest explicit diagnostic or repair capability.

**Plan:** 1. Obtain validation from the active Pallium architecture task on whether this is legacy local state only or an ongoing product gap; stop before production edits if validation is unavailable. 2. Inspect the current mainline transition, alias takeover, close, wake-reservation, and delivery lifecycle paths against the incident. 3. Repair the local installation with existing explicit operations when they preserve all pending/claimed work; otherwise design the smallest explicit repair operation keyed by canonical endpoint identity and guarded by generation/conflict checks. 4. If product code is required, reuse existing transition primitives at their shared boundary, avoid new dependencies or automatic session-ref heuristics, and add only the operator signal/documentation needed to make the repair discoverable. 5. Restart the installed service with `scripts/restart-service.ps1`, verify `/health`, `/status`, and `/debug/queue/health`, and verify installed integration state. Target files are conditional on architecture validation: existing Relay session lifecycle code in `core/relay.py` and `storage/sqlite_relay.py`, integration admission in `integrations/codex/hooks/common.py`, existing API/MCP surfaces only if an explicit repair operation is approved, focused `tests/test_*relay*e2e.py`, and relevant Relay/operations documentation. Stop and re-plan before touching a red API/schema path or changing canonical identity/provenance semantics.

**Verification plan:** When an endpoint changes scope through the supported hook path, the alias, work associations, and pending/claimed deliveries shall remain reachable from the canonical endpoint -> focused hook-to-HTTP E2E. When legacy split repair is explicitly requested, unrelated sessions with the same runtime session reference, conflicting live endpoints, stale generations, missing endpoints, more than two endpoints, Unicode aliases, idempotent retries, and pending/claimed deliveries shall retain their documented state -> focused caller-facing HTTP/MCP E2E if a product repair surface is added. When no product change is needed, the local alias shall resolve to the intended live endpoint and queue health shall show no silently stranded work -> recipients/status inspection plus `/health`, `/status`, and `/debug/queue/health`. Before PR, run affected Relay/integration test files, `python -m pytest --lf --lfnf=none -q -n 0`, `python -m pytest tests/ -x -q`, agent-workflow check, and redline check.

**Plan review:** Pending clean-context review after Pallium architecture validation fixes the product boundary.

**Approvals:** Approved by user 2026-09-12: "This in itself sounds like a bug. Investigate what happened and why and how you got confused, validate with the architect to see if this is really a bug, if so fix it till ready and done"

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Discovery and pre-edit redline classification completed. No production code has been changed.
- Blocked pending validation from the active Pallium architecture task; the initial automatic convergence idea was rejected because runtime session references are not globally unique.

## Evidence

- Local Relay API, hook session-state, Codex session log, and Pallium service-log inspection established the split endpoint, stale alias, unclaimable delivery, and direct-message hook bypass sequence.
- Clean-context redline review classified the likely lifecycle/storage paths as gray plus watch and raised the task to High risk because durable identity and delivery routing are contract-sensitive.

## Result review

- Pending.
