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

**Plan review:** Clean-context Astra review on 2026-09-24: service-only path and last-service marker are insufficient; setup must pin expected identity, outage writes stay in its directory, mismatch fails closed. Runtime/hook files are gray/watch.

**Approvals:** Not required at this risk level, pending risk reassessment.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Call graph and setup gap confirmed before code edits. Issue #234 is separate from merged PR #235. Clean-context Astra plan review completed; independent Sol implementation review found and drove fixes for unbound override, ownership, stale marker, setup ordering, default offline coverage, and startup cleanup. Final Sol review found no remaining actionable issues. Focused caller-surface tests: 88 passed. Full suite: 5280 passed, 34 skipped, 2 xfailed. Import-linter and local workflow/redline checks passed. CI pending PR.
