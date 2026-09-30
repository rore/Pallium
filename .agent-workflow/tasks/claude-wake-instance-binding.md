<!-- agent-workflow:start -->
**Outcome:** Claude wake intents written by hooks cannot be replayed by a different Relay instance.

**Target:** Pallium Relay wake integration.

**Scope:** Claude hook intent write/close, service wake-registry selection and registration, focused lifecycle tests, and matching docs/roadmap.

**Constraints:** Preserve the installed service's offline write-ahead durability and credential handling; never copy or replay intents across instances; add no dependency.

**Completion criteria:** With two isolated Relay instances, a hook targeting one writes and recovers intents only in that instance; a mismatched or unavailable target cannot write to another instance's intent directory; the installed default lifecycle still works.

**Requirement baseline:**
{"source":"https://github.com/rore/Pallium/issues/234","outcome":"Claude wake intents written by hooks cannot be replayed by a different Relay instance.","scope":"Claude hook intent write/close, service wake-registry selection and registration, focused lifecycle tests, and matching docs/roadmap.","constraints":"Preserve the installed service's offline write-ahead durability and credential handling; never copy or replay intents across instances; add no dependency.","completion_criteria":"With two isolated Relay instances, a hook targeting one writes and recovers intents only in that instance; a mismatched or unavailable target cannot write to another instance's intent directory; the installed default lifecycle still works."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Hook and runtime integration paths are gray/watch. Credential and durable-intent isolation needs clean-context review; no red-zone API route is needed.

**Discovery:** Hooks write to a fixed directory before POST; the service replays the same directory independently of Relay DB. Setup passes custom port only to MCP, not hooks. Persisted registry already requires an exact matching local intent.

**Material assumptions:** Installed service uses data/pallium-relay.db and its existing claude-wake sibling. Offline unbound custom targets must fail closed; a last-seen port marker is not an identity binding.

**Plan:** Derive service wake directory from resolved Relay DB, preserving installed default; publish a port-keyed service marker. Claude setup pins port, Relay identity and wake directory in an atomic hook config. Hooks write and POST only through the pinned binding, reject changed markers, and use the pinned directory during outage. Reject conflicting directory ownership before replay. No new endpoint or dependency.

**Verification plan:** Two-instance real hook intent → HTTP/restart, mismatched marker, offline/default lifecycle; existing Claude suites, full pytest, workflow check, independent Sol review and CI.

**Plan review:** Agent technical review: Astra review recorded in this Work Record at dbb6f76ac6d4f8c764374f045c823f91f0febe93 (2026-09-24). Service-only path and last-service marker were insufficient; setup must pin expected identity, outage writes stay in its directory, mismatch fails closed. The main merge did not change this plan.

**Approvals:** Not required at this risk level, pending risk reassessment.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Call graph and setup gap confirmed before code edits. Issue #234 is separate from merged PR #235. The original PR review drove fixes for unbound override, ownership, stale marker, setup ordering, default offline coverage, and startup cleanup. Merge commit d56e45270daf0f1380f74c7688309b63316d72f2 preserves current-main Codex worker shutdown and Claude binding checks. An existing lock-race subprocess test now supplies an isolated valid binding; its contention assertion is unchanged.

## Evidence

At d56e45270daf0f1380f74c7688309b63316d72f2 (merged with main c4fe7881), the exact lock-race test passed and the selector-required full non-slow suite passed: 5757 passed, 34 skipped, 2 xfailed. The initial focused run had one failure because the test child lacked a binding; it passed after fixture repair. The original pre-merge 88 focused and 5280 full results remain historical. Import-linter found no boundary violation; local Redline and Agent Workflow had no blocking finding, with the original same-commit Work Record advisory retained. Current-main PR CI remains pending.

## Result review

Agent technical review: independent Sol-low agent /root/review_pr236 in Codex task 01a0c83c-0af9-7881-9be1-89ae4bf29e09 on 2026-09-30.
Reviewed revision: d56e45270daf0f1380f74c7688309b63316d72f2.
Verification adequacy: Two-instance hook-to-HTTP, outage/restart, mismatch and installed-default caller-surface coverage plus the current full suite substantiate issue #234 without changing the protected behavior contract. No actionable findings. A transient status-probe failure may leave offline setup fail-closed until rerun; this is an availability caveat, not cross-instance replay.
