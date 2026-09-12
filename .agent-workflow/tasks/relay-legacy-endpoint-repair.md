<!-- agent-workflow:start -->
**Outcome:** Operators can repair a legacy Relay split without guessing identity, expanding access, replaying completed work, or losing the original delivery route. The concrete three-endpoint incident remains untouched until a complete reviewed manifest classifies every pending delivery.

**Target:** Pallium Relay.

**Scope:** Add one offline operator CLI with dry-run manifest and guarded apply; add the minimum durable repair audit/provenance record and terminal `suppressed` delivery state; reuse the existing SQLite Relay transaction and configuration paths; add caller-facing CLI E2E and storage lifecycle coverage; document the maintenance procedure. No HTTP, MCP, dashboard mutation, hook admission, activation scheduler, automatic convergence, or general endpoint merge API.

**Constraints:** Canonical endpoint IDs are the only repair identities. Matching runtime/session is a completeness check, never authorization. The operator must name every source and the destination with their exact scopes and explicitly classify every non-expired pending delivery as `adopt` or `suppress`. Preserve message and delivery IDs, sender and recipient admission provenance, attempts, timestamps, TTL, existing terminal states, aliases, destination work refs, and source delivery history. Do not copy historical visibility, take over aliases, migrate source work refs, or broaden container access. Refuse claimed deliveries, live service/API, active or uncertain wake reservations, alias/work-ref conflicts, incomplete same-runtime/session source sets, stale manifests, or any row drift. Coordinate but do not modify the unmerged activation-contract branch.

**Completion criteria:** A dry run produces a deterministic, human-reviewable manifest containing the complete affected row set and dispositions. Apply under one `BEGIN IMMEDIATE` transaction revalidates the exact row-set witness, records immutable repair provenance, retargets only explicitly adopted pending deliveries, terminally suppresses only explicitly classified fallback duplicates, tombstones every named source against repeat retargeting, and is idempotent for the same manifest. Any ambiguity or drift fails before mutation. The CLI and installed procedure cover empty/max/over-max inputs, three-source completeness, stale/missing/corrupt generations, alias/work-ref/collision conflicts, Unicode, TTL races, live claims/reservations, crash/retry, and full dry-run → apply → inspect lifecycle.

**Risk:** High

**Complexity:** Moderate

**Reason:** This changes durable Relay delivery routing and adds persistence provenance. `storage/sqlite_schema.py` is a red persistence surface and requires the persistence-review checkpoint. The offline CLI avoids an unnecessary public API/security contract.

**Discovery:** Fresh read-only evidence disproved the earlier two-endpoint/old-alias narrative. Exact Codex session `01a08a12-9bb6-7741-9fc6-59309bc6c9a2` currently has three canonical endpoints: closed `relay-session-aa729a9c9e5b43658b29b67dfad572fa` in `repo:e84a3c08cf47` with 1 pending delivery; active `relay-session-6fa6d21a776544959913a11f06af3192` in `git:github.com/rore/dictation-app` with 23 pending and 47 delivered; and active `relay-session-950d523eb0e34cb2975e6b5f8c50ce86` in `git:github.com/rore/pallium` holding alias `dict-dev2` with 1 delivered. All generations are absent (legacy generation zero) and all work-ref counts are zero. Current supported scope transition atomically moves one canonical endpoint, alias, work refs, and delivery route; alias takeover alone moves only the alias, and close/re-admit does not migrate stranded deliveries. No existing public operation can losslessly repair a pre-transition split. Delivery `recipient_container_ref` is the admission snapshot; claim routing uses `recipient_endpoint_id`. A retarget therefore needs separate durable repair provenance rather than overwriting the historical route. Wake reservation state is not transactionally coupled to Relay SQLite, so v1 must run with the service quiescent and fail closed on any observable reservation rather than clear or rearm it.

**Material assumptions:** Pair-only repair is insufficient for this incident and will be rejected when another same-runtime/session endpoint exists outside the manifest. The smallest honest suppression representation is a terminal `suppressed` delivery plus an immutable repair audit row; using `delivered` or `expired` would falsify the observable lifecycle. Source endpoints are retained as historical rows and receive an immutable repair tombstone rather than being deleted or silently reactivated. Existing endpoint generations are included in the witness, with absent meaning legacy zero only; authority comes from exact endpoint IDs, scopes, full row inventory, and operator acknowledgement. If the activation branch changes reservation location or fencing before this PR is ready, rebase and revise the reservation preflight before claiming compatibility.

**Plan:** 1. Invoke agent-workflow and classify risk before code edits (completed); obtain Pallium architecture direction and direct user approval (completed). 2. Add a small stdlib-only `app/tools/relay_endpoint_repair.py` command. Dry run requires the service to be stopped, exact destination/source endpoint IDs plus expected scopes, a complete same-runtime/session endpoint set, and an explicit `adopt`/`suppress` disposition for every live pending source delivery. It emits a versioned canonical-JSON manifest and SHA-256 witness; it never mutates. 3. Add an offline storage apply helper in `storage/sqlite_relay.py` and additive schema records in `storage/sqlite_schema.py`: immutable repair header/tombstones and per-delivery original-route/disposition provenance. Apply uses `BEGIN IMMEDIATE`, re-reads every affected endpoint, alias, generation, work-ref, message, delivery, and repair row, compares the full witness, rejects claims/reservations/conflicts, then retargets adopted pending rows by endpoint ID or marks explicitly classified duplicates `suppressed`. Preserve admission container, runtime/session, IDs, timestamps, attempts, TTL, and terminal rows. Same manifest replay returns the recorded result; a different replay against tombstoned sources fails. 4. Keep source endpoints/history in place, prohibit alias takeover and source work-ref migration in v1, and document that a separate reviewed manifest is required for any later repair. 5. Add CLI E2E through subprocess/configured temporary databases plus focused storage/status tests for the full boundary matrix. Update `docs/context/operations.md`, `docs/agent-relay.md`, the Relay wake fixture/state wording, and this record. 6. Run focused files, affected Relay suites, `--lf`, workflow/redline/persistence checks, and the full suite once; obtain clean-context smart result review, then PR/CI/merge. 7. After merge, sync stable main, restart only with `scripts/restart-service.ps1`, verify `/health`, `/status`, `/debug/queue/health`, rerun installed integration setup/verification, and only then generate the real three-source dry-run. Do not apply that real manifest until the consumer explicitly confirms all 24 pending `adopt`/`suppress` choices.

**Verification plan:**
- Dry-run/apply provenance, exact adoption/suppression, terminal-state preservation, alias/work-ref/history retention, and idempotent replay -> subprocess CLI E2E against configured temporary databases plus repair-audit reads.
- Missing/stale/extra endpoints, wrong scopes/runtime/session, two-of-three partial repair, zero/one/max/over-max sources/dispositions, absent/corrupt generations, alias collision/change, any source work ref, delivery/message/TTL drift, claimed and expiry races, live service/reservation, corrupt manifest, duplicate IDs, Unicode, rollback, and committed retry -> negative CLI E2E asserting unchanged database snapshots.
- Suppressed deliveries are terminal and never selected, woken, ACKed, replied to, or replayed -> existing caller-surface claim/ACK/reply/status/wake suites with focused additions.
- PR readiness -> focused test nodes/files, affected Relay suites, `python -m pytest --lf --lfnf=none -q -n 0`, one `python -m pytest tests/ -x -q`, workflow/redline/persistence checks, and `git diff --check`.

**Plan review:** Pallium architecture direction from `@astra-reviewer` approved an explicit operator-recovery capability but required this concrete plan before production edits. It forbids automatic runtime/session convergence, partial repair of the current three-endpoint incident, unguarded generation checks, provenance loss, live-claim/reservation clearing, alias takeover, visibility copying, and non-idempotent retargeting. Clean-context implementation-plan review is pending on this revision.

**Approvals:** Approved by user 2026-09-12: "This in itself sounds like a bug. Investigate what happened and why and how you got confused, validate with the architect to see if this is really a bug, if so fix it till ready and done"; reconfirmed with "Approve" after architecture returned the guarded operator-recovery direction.

**Exceptions:** —

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

- Read-only incident discovery, current storage/claim/reply/status tracing, reuse audit, activation-branch coordination, and architecture validation are complete.
- No production code or live Relay state has been changed. The installed three-endpoint incident remains diagnostic-only.
- A new transient outage at 2026-09-12T14:18:20Z was separately correlated to an API-process exit and reported to the originating dictation task; it is not evidence for endpoint convergence and remains a separate observability follow-up.

## Evidence

- Exact local endpoint inventory and counts are recorded in Discovery; the original Codex session metadata places the session first in `C:\Dev\rore\dictation_app` while the current task runs from `C:\Dev\rore\Pallium-installed`.
- `storage/sqlite_relay.py` routes claims by canonical `recipient_endpoint_id`, preserves `recipient_container_ref` as admission provenance, and has no repair primitive.
- Existing offline manifest/commit patterns in `app/tools/secrets_purge.py` and `app/tools/operational_fact_migration_pr5.py` provide the reusable dry-run/apply shape without a new dependency.
- Architecture verdict received from `@astra-reviewer`; direct `@pall-arc` delivery remains pending because that task is occupied, and no task was interrupted.

## Result review

- Pending.
