# Relay concurrency qualification

<!-- agent-workflow:start -->
**Outcome:** Identify and correct the proven shared bottleneck that prevents tens of concurrent Relay sends, claims and detail reads from completing while HTTP health remains responsive.

**Target:** Pallium Relay HTTP control plane on isolated origin/main6be22d77fc059d687563433f94b2523cc90686c0.

**Scope:** tests/test_relay_capacity_isolation.py, tests/test_relay_load_smoke.py and this Work Record on fix/relay-concurrency. Read production callers and storage to identify the cause; any production edit requires a reviewed exact scope extension before editing. Root coordinates overlapping app/main.py and app/supervisor.py ownership with the async-startup developer.

**Constraints:** No installed tools, configuration, database, service, native runtime transport, integration or live load changes. Use isolated private main/Relay databases and inert native transports. Preserve validation, scope, ACK, claim leases, generation fences, callback order, cancellation and transaction acquisition deadlines. Do not raise capacities/timeouts, retry failed calls, skip assertions or introduce a runner/framework to restore green. Root owns private execution, full validation, integration and release; no PR or push by this worker.

**Completion criteria:** A deterministic HTTP regression establishes whether all four shared Relay worker slots blocked in wake callbacks starve independent reads/claims while health progresses. An isolated actual HTTP mixed-load witness drives 20-50 simultaneous caller journeys and records per-phase latency, status outcomes, health responsiveness and bounded thread/SQLite lock evidence. Native sends are inert, real SQLite/HTTP/claim/ACK behavior is exercised, and persisted identity/lifecycle/counts remain exact. Correct only the cause demonstrated by the evidence, with independent plan/result review and focused/selected validation before acceptance.

**Requirement baseline:**
{"source":"human source ca5ef5ce-dc17-48ce-b249-9f50f1f3fe2b as provided by root; bounded assignment 2026-10-11","outcome":"Identify and correct the proven shared bottleneck that prevents tens of concurrent Relay sends, claims and detail reads from completing while HTTP health remains responsive.","scope":"tests/test_relay_capacity_isolation.py, tests/test_relay_load_smoke.py and this Work Record on fix/relay-concurrency. Read production callers and storage to identify the cause; any production edit requires a reviewed exact scope extension before editing. Root coordinates overlapping app/main.py and app/supervisor.py ownership with the async-startup developer.","constraints":"No installed tools, configuration, database, service, native runtime transport, integration or live load changes. Use isolated private main/Relay databases and inert native transports. Preserve validation, scope, ACK, claim leases, generation fences, callback order, cancellation and transaction acquisition deadlines. Do not raise capacities/timeouts, retry failed calls, skip assertions or introduce a runner/framework to restore green. Root owns private execution, full validation, integration and release; no PR or push by this worker.","completion_criteria":"A deterministic HTTP regression establishes whether all four shared Relay worker slots blocked in wake callbacks starve independent reads/claims while health progresses. An isolated actual HTTP mixed-load witness drives 20-50 simultaneous caller journeys and records per-phase latency, status outcomes, health responsiveness and bounded thread/SQLite lock evidence. Native sends are inert, real SQLite/HTTP/claim/ACK behavior is exercised, and persisted identity/lifecycle/counts remain exact. Correct only the cause demonstrated by the evidence, with independent plan/result review and focused/selected validation before acceptance."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Current intended changes are blue tests and workflow metadata, but the mission-critical concurrency diagnosis spans worker admission, native callback locks and durable lifecycle contracts. No production paths are authorized in this initial scope; reclassify and obtain the exact API/persistence checkpoint if the proven correction reaches those contracts.

**Discovery:** app/main.py uses the same four-token Relay limiter for DB operations, wake snapshots/callbacks and recursive activation projections; diagnostics use a separate two-token limiter and health runs directly. Existing load smoke creates48 concurrent ingests but executes24 Relay sends, turns and ACKs serially; health is checked only at the end. Existing callback capacity regressions hold one callback while checking health, not all four shared slots while another read/claim waits. Existing claim E2E concurrency uses two callers. Production message_status acquires BEGIN IMMEDIATE even for an unexpired payload read; trace writes share the Relay database. These are concrete coupling points, not attribution of the live outage. The accept error storm and supervisor recovery were observed by root; no process stack was captured before old PID25272 exited.

**Material assumptions:** All-four callback saturation may starve independent Relay operations even though offloading protects the event loop. If controlled instrumentation disproves this, retain the result and inspect actual transaction occupancy/admission evidence before choosing a fix. SQLite acquisition errors and transport timeouts have distinct causes and must be recorded separately. The actual historical live trigger remains unknown until direct evidence identifies it.

**Plan:** Invoke Agent Workflow applicability and classify risk before test/source edits; normal workflow applies because intended tests are outside the documentation-only exemption. Create and commit this Work Record first. Read native scheduler locks and all shared runner callers. Submit a precise deterministic saturation regression and a20-50-concurrent mixed HTTP witness plan for independent review before implementation. Root runs isolated focused RED/qualification, then approve the smallest proven source correction with coordinated file ownership and updated scope/risk before source edits. Preserve evidence and finish focused/affected/selector/result review before root integration.

**Verification plan:** Root runs exact new node/file with -q -n0, the slow mixed load target with -m slow if applicable, then affected concurrency/Relay lifecycle files. Record actual request status/body categories and phase timings without payload content, health latency, native initiation counts, persisted public readback and bounded worker/SQL evidence. Use causal events for regression ordering; watchdogs prevent hangs, not runtime-speed assertions. Full non-slow selection and final platform validation remain root-owned requirements for a completed application change.

**Plan review:** Pending independent review of the precise reproduction plan. No test/source edits until GO.

**Approvals:** Root explicitly authorized this isolated branch, Work Record and bounded concurrency proof based on human source ca5ef5ce-dc17-48ce-b249-9f50f1f3fe2b. No live changes or production correction approved in this initial scope.

**Exceptions:** None

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

2026-10-11: Agent Workflow and Redline applied before any test/source edit. Whole-change documentation exemption does not apply to the intended test paths; tests and Work Record are blue, with Elevated/Moderate judgment for uncertain concurrency diagnosis. Isolated clean checkout from6be22d77 switched to root-requested fix/relay-concurrency. Source edits await concrete proof, exact scope/risk reassessment, independent review and overlap coordination.

## Evidence

No tests or live operations executed by this worker. Root owns live recovery and private execution. Existing load/capacity coverage does not establish mixed20-50-request Relay progress or all-four callback isolation.

## Result review

Pending; no implementation or validation result claimed.
