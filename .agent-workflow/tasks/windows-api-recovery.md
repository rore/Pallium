<!-- agent-workflow:start -->
**Outcome:** A managed replacement must prove it answered the same health response before the supervisor accepts readiness or terminal startup failure.
**Target:** Windows API outage recovery at baseline 24fe8d64.
**Scope:** Readiness-only changes in `app/supervisor.py`, outer `/health` and receipt writing in `app/main.py`, a private proof helper, affected readiness and receipt tests, and supervisor readiness guidance. Keep `run/api_token` as an advisory atomic `{pid}` receipt with the existing lifecycle.
**Constraints:** No live faults, service operations, live DB access, replay, timeout expansion, cache-policy changes, or further local broad runs. Publish one PR for the exact reviewed readiness candidate and its first hosted validation; no merge before hosted disposition. Leave the separately owned accept-log mitigation untouched.
**Completion criteria:** The retained loopback bind-conflict case goes green with owned cleanup. Managed health accepts only the responding launch's fresh proof, including before accepting terminal 503. Plain health, startup fences, and PID receipt lifecycle stay intact; the launch nonce is absent from HTTP, logs, and receipts.
**Requirement baseline:**
{"source":"work-record-initial","outcome":"Reproduce false replacement readiness with a real loopback listener and production startup.","scope":"Test-only characterization in tests/test_supervisor_recovery_e2e.py and this record. Production changes require a separately reviewed plan in this same record.","constraints":"No live faults, service operations, live DB access, replay, timeout expansion, cache-policy changes, broad suite, publication or merge. Leave the separately owned accept-log mitigation untouched.","completion_criteria":"A deterministic isolated regression reaches production startup and supervisor readiness with observable bind failure and owned process cleanup; report exact evidence and a bounded correction decision."}
**Behavior changes:**
[
  {"target":"task-context.outcome","classification":"requirement-change","before":"Reproduce false replacement readiness with a real loopback listener and production startup.","after":"A managed replacement must prove it answered the same health response before the supervisor accepts readiness or terminal startup failure.","reason":"The retained RED established false readiness; the owner released the reviewed correction.","impact":"Managed probes no longer borrow another listener's health.","alternatives":"Stop at the retained characterization.","authority":{"scope":"task","name":"task-owner"},"approval":{"by":"user","reference":"Approval reaffirmed by the task owner after presentation of exact plan 75650792, as relayed by the project manager. Public-safe verbatim excerpt; full source retained privately.","verbatim":"you got a blanket approval"}},
  {"target":"task-context.scope","classification":"requirement-change","before":"Test-only characterization in tests/test_supervisor_recovery_e2e.py and this record. Production changes require a separately reviewed plan in this same record.","after":"Readiness-only changes in `app/supervisor.py`, outer `/health` and receipt writing in `app/main.py`, a private proof helper, affected readiness and receipt tests, and supervisor readiness guidance. Keep `run/api_token` as an advisory atomic `{pid}` receipt with the existing lifecycle.","reason":"The exact reviewed scope removes nonce storage and the receipt's readiness role.","impact":"The receipt changes from `{nonce, pid}` to `{pid}`; it grants no readiness, terminal-failure, or kill authority.","alternatives":"Keep the secret on disk or remove the receipt and lose its existing lifecycle.","authority":{"scope":"task","name":"task-owner"},"approval":{"by":"user","reference":"Approval reaffirmed by the task owner after presentation of exact plan 75650792, including the PID-only receipt, as relayed by the project manager. Public-safe verbatim excerpt; full source retained privately.","verbatim":"you got a blanket approval"}},
  {"target":"task-context.completion_criteria","classification":"requirement-change","before":"A deterministic isolated regression reaches production startup and supervisor readiness with observable bind failure and owned process cleanup; report exact evidence and a bounded correction decision.","after":"The retained loopback bind-conflict case goes green with owned cleanup. Managed health accepts only the responding launch's fresh proof, including before accepting terminal 503. Plain health, startup fences, and PID receipt lifecycle stay intact; the launch nonce is absent from HTTP, logs, and receipts.","reason":"Verify the correction, not just the characterization.","impact":"Focused checks cover ownership and preserved startup behavior.","alternatives":"Stop at the retained characterization.","authority":{"scope":"task","name":"task-owner"},"approval":{"by":"user","reference":"Approval reaffirmed by the task owner after presentation of exact plan 75650792, as relayed by the project manager. Public-safe verbatim excerpt; full source retained privately.","verbatim":"you got a blanket approval"}},
  {"target":"task-context.constraints","classification":"requirement-change","before":"No live faults, service operations, live DB access, replay, timeout expansion, cache-policy changes, broad suite, publication or merge. Leave the separately owned accept-log mitigation untouched.","after":"No live faults, service operations, live DB access, replay, timeout expansion, cache-policy changes, or further local broad runs. Publish one PR for the exact reviewed readiness candidate and its first hosted validation; no merge before hosted disposition. Leave the separately owned accept-log mitigation untouched.","reason":"Advance the reviewed correction to hosted validation after the isolated full attempt stopped at an unchanged dependency boundary.","impact":"First hosted checks only; no rerun, rollout, or weakened gate.","alternatives":"Repeat local validation in a different environment or leave the reviewed correction unpublished.","authority":{"scope":"task","name":"task-owner"},"approval":{"by":"user","reference":"Standing task-owner release approval, reaffirmed after presentation of the exact readiness scope. Full source retained privately.","verbatim":"you got a blanket approval"}}
]
**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}
**Risk:** Elevated
**Complexity:** Moderate
**Reason:** Provisional classification for the proposed production slice: watched `app/**` runtime paths and blue tests; ownership verification spans the supervisor and startup app. No public API route/schema, policy, protected test or storage change is proposed. Reassess on any scope expansion.
**Discovery:** The isolated RED below establishes that a token written before bind and a health response from another listener can satisfy the current probe. The file also contains the launch nonce. Production readers are confined to the old supervisor gate; lifecycle and native reconnect tests use the file as a receipt. The boot app owns `/health` before and after initialization.
**Material assumptions:** Incident evidence does not establish the first live outage cause. Assume the startup proof identifies a launch to its existing supervisor, not a general HTTP authentication protocol. Stop if another production consumer of nonce-on-disk, a required mixed-version contract, or an inseparable drain dependency is found.
**Plan:** Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit; reuse this existing record. Obtain the task owner's exact scope/requirement disposition and a non-implementer plan review. Then implement only the response-bound readiness proposal below. Leave retry/drain, installed state, and the separate accept-log mitigation untouched.
**Verification plan:**
- Retained RED goes green with real bind conflict and owned cleanup → `tests/test_supervisor_recovery_e2e.py`.
- Response-bound readiness and terminal failure, direct health, stop/deadline/exit → focused loopback, supervisor and startup-health cases.
- Atomic PID-only receipt, cleanup and native incarnation checks → launch-token tests, app-run lifecycle, startup-health lifecycle, and the affected native reconnect caller.
- Reconciled whole change before publication → current-base selector, full non-slow suite, and local workflow checks.
**Plan review:** Agent technical review: Independent clean-context GO on exact plan blob `75650792af59eea63e035fac83a65d3938fc43f0`, confirmed by the manager. Elevated/Moderate. The architect's earlier advice is not the independent sign-off.
**Approvals:** The task owner reaffirmed standing approval after presentation of the readiness-only plan and PID-only receipt. The manager owns publication for the exact reviewed candidate. No drain or live operations.
**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Baseline: `24fe8d64d778156eba320de3d25a9adb8efafe0e`.
Branch: `fix/windows-api-recovery`.
Canonical roadmap remains owner-managed in the designated shared checkout:
`roadmap/features/add-wake-first-relay-delivery.md`; no roadmap edits here.
The characterization ran before standing developer ownership was assigned. The
current owner accepted the readiness slice and read `roles/developer.md` as
explicit guidance while its name mapping awaits publication.

The enroll-settlement lane reached an independent environment blocker before
the readiness release. Edit only `app/supervisor.py`, `app/main.py`,
`app/_startup_proof.py`, the affected supervisor, health, launch-token,
app-run and native reconnect tests, and the existing supervisor design note.

The supervisor now generates a fresh challenge after TCP connect and verifies
the proof before reading the health body. The outer app captures its launch
nonce at construction. The receipt holds only the PID; neither readiness nor
terminal classification reads it. No changes to retry, drain, or restart policy.

Discovery: readiness verifies a shared token file separately from the HTTP response.
The production lifespan writes that token before Uvicorn binds. Bind failure then
waits for the non-abandoning constructor, leaving the candidate alive while an older
listener can answer the readiness HTTP request. Retry also advances after failed
tree cleanup, losing the previous attempt's handle.

Private incident excerpts and exact machine-local sources belong under ignored
`build/`, not this publishable record. Original runtime trigger is not established.

## Verification

On `24fe8d64`, the focused real-loopback test reached the candidate's
actual bind failure. Its process was still alive and its token file
matched. The unmodified production probe returned `True` using the
other listener's HTTP response. The test failed at that exact assertion
in 4.54 seconds. Both owned fixture processes were drained. This proves
false readiness, not the cause of the first live TCP failure.

No production patch was approved at the characterization checkpoint. The
architect recommended response-bound identity and verified drain before
another launch. The readiness owner reuses this RED without rerunning it.

## Evidence

The focused Windows readiness candidate passed **178 tests**. This includes
the retained bind-conflict regression against an older healthy and terminal
listener with misleading, absent, and corrupt receipts. It also covers
ordinary health, matching proof, malformed and duplicate headers, deadline,
stop and exit, and the atomic receipt lifecycle. The strengthened replay case
passed separately after changing it to replay a proof from an actual earlier
request. The one slow native reconnect case deselected by default passed
when selected explicitly. It verified the exact PID receipt, distinct launch
incarnations and owned cleanup.

The uncommitted candidate was reconciled to current main
`a5ab4d3b447b0e9949b4f25fd66cc9801acd7e61`. No candidate path overlapped
the base changes, and all ten product, test and documentation blobs
match the focused snapshot. The exact hashes are retained locally.
The fresh selector requires the full lane. Import boundaries and Agent
Workflow passed; Redline was GRAY with no blocking findings.

The branch then moved to current main `d2cf30514fbac50be00e38d3c0b36fd048278556`
without changing any of the ten candidate blobs. Fresh workflow and import
boundary checks passed; Redline remained GRAY with no blocking findings.
Lockfile-verified `pyte` and `wcwidth` wheels on the test process's path
cleared import preflight without installation.

The single full non-slow Windows CPython 3.13 run stopped with **1 failed,
4,597 passed, 3 skipped, 1 xfailed** (pytest exit 2). The first failure was
`test_hermes_bridge.py::test_bridge_stdio_call_on_supported_sdk[False-sdk1]`.
The bridge deliberately omits `PYTHONPATH` from its child environment.
The child uses the same interpreter as pytest but cannot see the
target-installed `pydantic` dependency. The bridge, fixture, and MCP entry
point are unchanged by this candidate. The full run is not green; prior
focused evidence stands separately. No rerun, bridge change, or weakening
of the child environment. The next prerequisite is an isolated interpreter
that can import its dependencies without inherited `PYTHONPATH`. Logs and
JUnit are retained locally. No live changes, publication, or drain work.

## Result review

Agent technical review: independent clean-context result GO, relayed by the
project manager; exact review source retained privately.
Reviewed revision: uncommitted candidate on `24fe8d64`, carried forward
with identical product, test and documentation bytes onto `a5ab4d3b`.
Verification adequacy: adequate for the focused readiness contract. The
review verified proof before health or terminal-failure classification,
unchanged direct health and lifecycle fences, and the PID-only receipt.
The GO does not qualify the full suite. The manager accepted the unchanged
Hermes dependency failure as the local run disposition and released the exact
candidate for its first normal hosted validation. Merge remains pending that
result. Do not rerun the local full suite.

## Proposed recovery fix

- Bind each managed startup probe to the process answering that exact
  HTTP request. The architect rejected sending the launch nonce to the
  listener: an unrelated listener could echo a fixed success header.
  Keep the nonce in the supervisor and child. Send a fresh random
  challenge of fixed format and length; the startup `/health` handler
  returns HMAC-SHA256 of that challenge under its own launch nonce, with
  a fixed domain prefix. Verify the exact response with `compare_digest`
  before checking readiness or interpreting terminal 503. Do not emit
  or log the nonce. No new endpoint or change to health JSON, status,
  time limits, direct no-nonce probes, or initialization semantics.
- The shared file is not readiness evidence. Neither a matching file
  nor an absent or invalid file can let an unrelated listener pass.
  Reuse the loopback RED. Cover old-listener healthy and terminal
  responses, missing/invalid/wrong-launch and replayed proof, matching
  health statuses, malformed health even with valid proof, and existing
  stop, deadline and child-exit fences. Plain health stays unchanged.
- Treat an unsuccessful drain as distinct from ordinary startup failure.
  A retry must not launch over a still-running owned process or a port
  whose owner cannot be verified. Do not kill an unrelated listener.
  Preserve the process handle for cleanup or report a terminal recovery
  failure. Prove failed drain launches no successor and successful
  drain allows replacement, on Windows and for the existing POSIX path.
- Keep the readiness proof and drain handling reviewable separately.
  Neither change is evidence of what triggered the original stall.
   No timeout expansion, dependency change, or live fault injection.

## Readiness-only plan review target

- In `app/supervisor.py` and the outer `/health` handler in `app/main.py`,
  share a small private startup-proof helper. Use a fresh 128-bit challenge
  encoded as 32 lowercase hex characters for each managed request. Use
  domain-separated HMAC-SHA256 under the per-launch value already passed in
  the child environment. Return a fixed 64-character lowercase hex proof
  only to one well-formed challenge. Reject missing, ambiguous, malformed,
  wrong-launch and replayed response proofs before health interpretation.
  No launch nonce in HTTP, logs, or final or temporary receipt files.
  No request schema parameter, new endpoint, change to ordinary health,
  or claim of protection from a local process that already controls the
  child's environment.
- Capture the launch value once in the production app factory. Add the proof
  to responses from the existing outer health route, including well-formed
  terminal initialization failure. This preserves the status, body and
  initialization handling. The supervisor checks proof on the same HTTP
  response, retains the response/body limits and absolute timeouts, and
  rechecks stop, deadline and process exit before success or terminal
  fail-fast. No-expected-nonce direct probes retain their prior behavior.
- Remove the managed readiness file/grace gate. Keep the existing atomic
  `run/api_token` creation/removal lifecycle as a PID-only receipt. This is
  an advisory receipt only, not proof
  of the current or exclusive owner. Its shared temporary path and
  unconditional shutdown unlink do not guarantee receipt custody when
  processes overlap. It does not authorize readiness, terminal failure,
  or a kill. Preserve receipt lifecycle and exact-PID checks in the
  affected launch-token, app-run, health, and native reconnect tests.
  Replace obsolete supervisor file/grace expectations with same-response
  HTTP checks and update current readiness guidance that relies on the
  nonce file. Keep the bind-conflict regression's observed bind failure
  and live-but-unbound child checks; seed the misleading matching file
  from the fixture, not from the candidate's secret storage.
- Verify both production startup surfaces with real loopback HTTP and a
  disposable child: positive matching challenge, owned healthy/degraded/
  initialized policy and terminal 503, and unrelated healthy/terminal
  listeners despite misleading, missing or invalid files. Exercise bad and
  repeated headers, stale challenge, valid proof with malformed health,
  direct no-challenge behavior and deadline/stop/exit fences. Retain owned
  child/thread cleanup. No installed fault, live DB, replay, timing increase,
  dependency, or cache changes. The separately observed failed-drain retry
  is a follow-up, not fixed or claimed safe by this change.

The exact plan received independent GO and owner release before implementation.

## Separate read-only stall diagnosis

The retained incident logs show a contended OpenCode **enroll** writer
with a long completed settlement span, matched to earlier busy-waiter
observations by the existing writer ID. This establishes an in-worker
stall for that writer, not a poll-body stall or a queue-only explanation.
In `storage/sqlite_queue.py`, successful settlement runs from the end of
the transaction body through `session.flush()` and SQL `COMMIT` to the
settled callback. The busy-timeout reset and session close occur later.
The retained span cannot tell flush from COMMIT or identify the physical
cause. Other slow or busy route records still mix worker admission and
execution time.

`/health` does not consume a diagnostic permit or query SQLite;
`/status` and `/debug/queue/health` share two diagnostic permits and do
storage work. OpenCode wake workers use different permits, so the
endpoint pattern does not establish that wake traffic exhausted the
diagnostic lane or caused the caller stalls.

If further diagnosis is authorized, first split worker entry from the
operation and split flush from COMMIT for the observed enroll path.
Reuse the existing isolated Relay capacity and writer diagnostic
fixtures with separate held-admission and held-settlement controls.
Record only fixed phases, verbs and elapsed times. Attribute diagnostic
wait or body time separately before linking the two symptoms. No live
test, service change, timing change, or readiness implementation follows
from this finding; the readiness gates and failed-drain follow-up remain
unchanged.
