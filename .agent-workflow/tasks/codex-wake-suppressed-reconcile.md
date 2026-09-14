<!-- agent-workflow:start -->
**Outcome:** Durable Codex wake reservations are released when their exact Relay delivery is authoritatively `suppressed`, so completed offline repairs cannot keep stale capacity fences.

**Target:** Codex Relay wake reservation reconciliation.

**Scope:** Add `suppressed` to the existing exact-delivery terminal reconciliation rule in `app/codex_wake.py`; extend focused lifecycle/recovery tests in `tests/test_codex_wake.py`; align the operational description if needed.

**Constraints:** Preserve exact `RelayNotFoundError` release. Preserve fail-safe retention for unavailable checks, missing or malformed response fields, endpoint mismatches, pending deliveries, and active or expired-lease claimed deliveries. Preserve generation-CAS batch release and schedule cleanup semantics. Do not mutate Relay delivery state, manually delete installed reservations, change schema/API/profile behavior, or broaden terminal handling beyond authoritative stored Relay lifecycle states.

**Completion criteria:** Persisted startup/recovery and send-time collision reconciliation release an endpoint-matching exact delivery in `suppressed` state. HTTP readback remains `suppressed`; pending and claimed fences remain; batch write failure still retains all fences. One subsequent eligible delivery reserves and produces exactly one native wake. Focused/full tests and CI pass. The installed service restart reduces the two observed suppressed reservations without removing the four observed pending reservations.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** This is a one-token operational behavior correction in shared wake reconciliation. It removes only a terminal delivery state already excluded from live delivery and does not change public API, persistence format, or architecture.

**Discovery:** Post-merge installed acceptance for PR #193 reduced the polluted wake registry from 248 reservations to 6. Exact read-only delivery traces showed two survivors were stored `suppressed` and four were genuinely `pending`. The reconciler currently releases only `delivered` and `expired`; unknown states intentionally retain, so `suppressed` was treated as uncertainty even though offline endpoint repair makes it an authoritative terminal Relay state.

**Material assumptions:** `suppressed` is terminal and cannot become pending/claimed again; its endpoint identity remains authoritative. Disproof would be any supported transition out of `suppressed`; stop and re-plan if found.

**Plan:** 1. Confirm every write/transition involving Relay `suppressed` and the reconciler callers. 2. Add `suppressed` to the existing terminal-state set. Extend the existing endpoint-repair suppression lifecycle through persisted recovery, and extend send-time collision coverage to assert one subsequent eligible delivery produces exactly one native wake while pending/claimed fences remain. 3. Run focused, affected, full, import/workflow checks and obtain smart result review. 4. PR, resolve automated review/CI, merge only green, sync both main checkouts, reinstall integration only if changed, restart through `scripts/restart-service.ps1`, and verify health plus the four pending survivors.

**Verification plan:** Endpoint repair -> stored `suppressed` -> HTTP readback -> persisted registry reload/recovery -> fence removed; send-time suppressed collision -> subsequent pending delivery -> exactly one native wake; live pending/claimed and malformed/unavailable retention plus exact-not-found release -> existing reconciliation tests; installed acceptance -> exact-delivery trace plus registry count before/after wrapper restart; whole result -> affected/full pytest, import linter, agent-workflow/redline, smart review, PR CI.

**Plan review:** Clean-context reviewer `/root/empty_wake_result_review` approved the corrected plan after requiring valid `Simple` complexity, exact-not-found retention wording, and explicit persisted-recovery/send-time-collision coverage.

**Approvals:** Approved by user 2026-09-14T22:43:34+03:00: "so take ownership of this and fix"; reinforced by 2026-09-14 dogfood instruction: "if we find an issue with relay, we should improve and fix".

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Added authoritative `suppressed` to the existing terminal delivery allowlist in `_reservation_is_stale`; exact not-found release and all fail-safe retention paths are unchanged.
- Extended the existing send-time collision regression so both delivered and suppressed fences release, one subsequent pending delivery is reserved, and exactly one native wake is started.
- Extended the existing endpoint-repair E2E through persisted Codex registry reload and startup recovery; HTTP still reports the delivery as suppressed while the stale wake fence is removed.
- No docs, API, schema, dependency, or integration-profile change was needed. `apply_patch` remained unavailable due the documented local Windows process error, so edits used exact deterministic replacements.

## Verification

- Focused lifecycle nodes -> 4 passed.
- Complete affected files: `python -m pytest tests/test_codex_wake.py tests/test_relay_endpoint_repair_e2e.py -q -n 0` -> 107 passed.
- Full suite: `python -m pytest tests/ -x -q` -> 5,010 passed, 34 skipped, 2 xfailed.
- Smart result review: `/root/empty_wake_result_review` -> APPROVE, no concrete findings; confirmed terminality, exact-not-found/uncertainty behavior, generation CAS, persisted recovery, and exactly-once wake coverage.
- Redline/workflow: GRAY with no checkpoints or boundary/API/schema/security/config findings; workflow check clean.
- Import boundary: `python scripts/run-import-linter.py --out build/import-linter-report.json` -> exit 0.
- `git diff --check` -> clean.
