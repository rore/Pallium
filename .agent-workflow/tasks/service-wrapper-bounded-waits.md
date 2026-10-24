# Bound Windows restart wrapper children

<!-- agent-workflow:start -->
**Outcome:** The repository Windows restart wrapper does not wait indefinitely for its own preflight, initialization or taskkill child, and reports uncertain settlement without starting a replacement service.

**Target:** Repository Windows service restart wrapper.

**Scope:** scripts/restart-service.ps1, its existing tests/test_restart_service.py command-double harness, narrowly related operations guidance and this Work Record. Source preparation and review only until separately authorized validation.

**Constraints:** Preserve installed-task discovery, process ownership filters, MCP exclusion, preflight-before-stop ordering and the existing 180-second readiness phase. Failed or uncertain wake initialization leaves the service stopped. No automatic restart, registration replacement, executable rollback or settings/data restoration. Only wrapper-owned child handles/resources may be settled. No installed-path, ownership/CIM, socket or credential inspection; no wrapper/parser/test/fault/live-service execution, installation or new infrastructure. Existing Hermes PR and pal-dev1 capture remain separate.

**Completion criteria:** Preflight timeout fails before stopping the service; initialization timeout or uncertain child settlement never starts it; native taskkill waiting is finite, with existing nonzero partial-failure verification preserved. Shared preparation accounting starts before preflight and includes cleanup without renewing waits; the readiness phase retains its existing allowance. Every owned process handle is disposed and root-only termination is not claimed as descendant settlement. Existing real-script command-double tests cover timeout, nonzero, success, failed cleanup and cumulative-budget behavior without weakening current assertions. Independent source review accepts the actual delta; runtime validation remains explicitly pending.

**Requirement baseline:**
{"source":"manager-source-only-wrapper-assignment-2026-10-24","outcome":"The repository Windows restart wrapper does not wait indefinitely for its own preflight, initialization or taskkill child, and reports uncertain settlement without starting a replacement service.","scope":"scripts/restart-service.ps1, its existing tests/test_restart_service.py command-double harness, narrowly related operations guidance and this Work Record. Source preparation and review only until separately authorized validation.","constraints":"Preserve installed-task discovery, process ownership filters, MCP exclusion, preflight-before-stop ordering and the existing 180-second readiness phase. Failed or uncertain wake initialization leaves the service stopped. No automatic restart, registration replacement, executable rollback or settings/data restoration. Only wrapper-owned child handles/resources may be settled. No installed-path, ownership/CIM, socket or credential inspection; no wrapper/parser/test/fault/live-service execution, installation or new infrastructure. Existing Hermes PR and pal-dev1 capture remain separate.","completion_criteria":"Preflight timeout fails before stopping the service; initialization timeout or uncertain child settlement never starts it; native taskkill waiting is finite, with existing nonzero partial-failure verification preserved. Shared preparation accounting starts before preflight and includes cleanup without renewing waits; the readiness phase retains its existing allowance. Every owned process handle is disposed and root-only termination is not claimed as descendant settlement. Existing real-script command-double tests cover timeout, nonzero, success, failed cleanup and cumulative-budget behavior without weakening current assertions. Independent source review accepts the actual delta; runtime validation remains explicitly pending."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Script, tests, docs and record are blue paths, but a restart wrapper can strand a service or leave a delayed destructive child. Engineering judgment raises risk to Elevated. No production API, storage, dependency, CI or protected-contract edits are intended.

**Discovery:** Base fd14a77d19713e878105a537de0dfee9735dc88e has Start-Process Wait=true for preflight, cloned for initialization after stop; synchronous native taskkill is also unbounded. The readiness timer starts later. Existing real-script test doubles cover ordering, native task errors and readiness. Bounded search found historical PR307 and earlier wrapper records, but no already-reviewed repair of these waits. No search is to be repeated.

**Material assumptions:** Existing ReadinessTimeoutSeconds names the readiness phase, so do not silently consume that allowance with preparation. Use a separate explicit preparation allowance shared across all owned children and settlement, rather than a new public option or a fresh allowance per child. Synchronous process-start/kill/dispose and CIM/ScheduledTask calls cannot honestly be advertised as a hard OS wall. No temporary environment/settings state exists in the inspected wrapper to restore.

**Plan:** Introduce one small local owned-child helper using Start-Process without Wait, finite Process.WaitForExit, cleanup in finally and handle disposal. Give all preparation children one monotonic deadline established before preflight, with a cleanup reserve inside that allowance; keep readiness accounting separate and unchanged. Route preflight, initialization and native taskkill through it; fail closed on timeout/uncertain settlement while preserving settled nonzero taskkill's existing verification. Reuse and extend the existing process/command doubles; no new transport, supervisor framework or dependency. Review budget placement, root-versus-descendant limits and failure diagnostics before implementation. Stop on unresolved source-contract or review findings.

**Verification plan:**
- Preflight timeout never stops service; initialization timeout never starts it -> existing real-wrapper harness call-order assertions and new owned-process timeout scenarios, when separately permitted.
- Native taskkill nonzero/timeout and uncertain root cleanup -> existing partial-failure cases plus finite-wait, kill/refusal and disposal scenarios, when separately permitted.
- Shared deadline, no renewed cleanup allowance and unchanged readiness -> process-double wait-argument/cumulative-time scenarios and existing readiness-boundary cases, when separately permitted.
- Source-only checkpoint -> independent actual-delta review; later smallest isolated command is python -m pytest tests/test_restart_service.py -q -n 0. No such command is authorized or run by this record.

**Plan review:** Agent technical review: /root/hermes_wake_metadata_fresh_review, existing clean nonimplementer, SOURCE-ONLY PLAN GO at base fd14. Elevated/Moderate, preserved failure behavior, budget compatibility and verification adequacy accepted; actual-delta review and runtime validation remain separate. Exact preparation equation: prepBudget=validated ReadinessTimeoutSeconds; reserve=min(2 seconds, prepBudget/4), inside one monotonic preparation timer established before preflight. No per-child renewal or additional cleanup allowance. The readiness phase retains its own full original allowance after Start-ScheduledTask. Clamp remaining milliseconds before Int32 conversion; check remaining work before stop and start; report root-only settlement and synchronous OS limits honestly.

**Approvals:** Ordinary repository source correction and review authorized by manager under the authenticated user instruction "Please don't let this halt. Drive this till completion", Sentinel_4deb39dfc7948191a235b48364fea67f, 2026-10-24T12:39:32.287220+00:00. The manager explicitly clarified that restoration means only wrapper-owned resource/temporary-state cleanup, not service restart or settings changes. No local validation or live operation is approved.

**Exceptions:** None.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Workflow invoked and normal applicability selected before code edits: the intended script/test/record paths are not documentation-exempt. Separate source-only checkout C:/Dev/rore/Pallium/build/service-wrapper-bounds-20261024/Pallium, branch feat/service-wrapper-bounded-waits, exact base fd14a77d19713e878105a537de0dfee9735dc88e. Hermes PR352 remains clean at 1bc96c9d and unchanged. Required source plan review is accepted; source-only implementation may proceed. The apply_patch method rejection was reconciled centrally: use the prescribed Git-native edit route for this distinct task, not another writer or the held pal-dev1 append. No test or live authority follows.

## Evidence

Source reads and Git metadata only. No parser, test, import, wrapper, process-ownership query or service operation has run. No original installation or working profile was read or modified. Stable roadmap association for this separate generic wrapper correction was not supplied; sources remain unresolved rather than invented.
