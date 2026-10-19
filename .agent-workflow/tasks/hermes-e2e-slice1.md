# Hermes slice 1: real-host Relay round trip

Canonical item: `roadmap/features/add-hermes-agent-integration.md`
(`add-hermes-agent-integration`). Branch `feat/hermes-e2e-slice1`; owner checkout
`C:\Users\I347041\.codex\worktrees\hermes-e2e-slice1\Pallium`.
Base: `701608cd0f666fe5106bf7c91e2e98bf0fe21d0c`. Prior source-only probes are
preserved separately on `feat/hermes-feasibility`; do not repeat or depend on
merging them before this experiment.

<!-- agent-workflow:start -->
**Outcome:**
Demonstrate a repeatable real released-Hermes idle Relay round trip: an existing sender persists a message, Hermes wakes automatically and receives the exact attributed payload, the integration verifies admission and ACKs, Hermes invokes its reply tool, and the original sender receives that reply.

**Target:**
Pallium's isolated experimental Hermes integration, one loaded TUI/gateway-backed Windows host/profile/container with a local provider stub.

**Scope:**
This Work Record; additive Hermes runtime recognition in core/relay.py, core/relay_activation.py and api/schemas.py; a payload-free exact-scope pending-candidate route in api/routes.py reusing the existing service method; integrations/hermes/{plugin.yaml,__init__.py,README.md}; tests/test_hermes_relay_plugin.py and tests/test_hermes_relay_native_e2e.py; the canonical Hermes item and its directly affected scope paragraph. Temporary pinned Hermes source, a disposable Python environment/profile/workspace, isolated service data and loopback ephemeral ports may be created for qualification.

**Constraints:**
Do not edit reliability-owned branches/checkouts, existing runtime delivery/retry/ACK semantics, database schema, CI, behavior contracts, dependencies or governance. No live installation, PATH/global environment change, updater change, paid inference, user application/service operation, or use of the installed Pallium service. Use actual supported Hermes plugin/host surfaces; do not monkeypatch host internals or impersonate another runtime. Keep normal claims/ACK/replies on existing Relay APIs; the provider stub never performs ACK. Maintain exact identity/scope, bounded input, full attributed inclusion and no blind wake retry from the first experiment. This is a narrow experimental topology, not general Hermes qualification. Coordinate overlapping merges and full-local-suite resource use with the reliability owner.

**Completion criteria:**
An E2E test launches the pinned actual Hermes host with the real plugin and a local model stub, exercises the complete send/wake/payload/ACK/reply journey through ordinary caller surfaces, records exact source/runtime identity and cleanup, and passes wrong-recipient and missing/stripped-context controls without false admission. Tests cover the introduced plugin/API validation and refusal paths. Required checks and review are recorded honestly; unsupported profiles/restarts/middleware combinations remain unqualified rather than advertised as working.

**Requirement baseline:**
{"source":"user:c905e768-ad3a-4c69-a255-a35c68a339d1","outcome":"Demonstrate a repeatable real released-Hermes idle Relay round trip: an existing sender persists a message, Hermes wakes automatically and receives the exact attributed payload, the integration verifies admission and ACKs, Hermes invokes its reply tool, and the original sender receives that reply.","scope":"This Work Record; additive Hermes runtime recognition in core/relay.py, core/relay_activation.py and api/schemas.py; a payload-free exact-scope pending-candidate route in api/routes.py reusing the existing service method; integrations/hermes/{plugin.yaml,__init__.py,README.md}; tests/test_hermes_relay_plugin.py and tests/test_hermes_relay_native_e2e.py; the canonical Hermes item and its directly affected scope paragraph. Temporary pinned Hermes source, a disposable Python environment/profile/workspace, isolated service data and loopback ephemeral ports may be created for qualification.","constraints":"Do not edit reliability-owned branches/checkouts, existing runtime delivery/retry/ACK semantics, database schema, CI, behavior contracts, dependencies or governance. No live installation, PATH/global environment change, updater change, paid inference, user application/service operation, or use of the installed Pallium service. Use actual supported Hermes plugin/host surfaces; do not monkeypatch host internals or impersonate another runtime. Keep normal claims/ACK/replies on existing Relay APIs; the provider stub never performs ACK. Maintain exact identity/scope, bounded input, full attributed inclusion and no blind wake retry from the first experiment. This is a narrow experimental topology, not general Hermes qualification. Coordinate overlapping merges and full-local-suite resource use with the reliability owner.","completion_criteria":"An E2E test launches the pinned actual Hermes host with the real plugin and a local model stub, exercises the complete send/wake/payload/ACK/reply journey through ordinary caller surfaces, records exact source/runtime identity and cleanup, and passes wrong-recipient and missing/stripped-context controls without false admission. Tests cover the introduced plugin/API validation and refusal paths. Required checks and review are recorded honestly; unsupported profiles/restarts/middleware combinations remain unqualified rather than advertised as working."}

**Risk:** High

**Complexity:** Moderate

**Reason:**
Fresh Redline identifies core/relay.py as architecture-review and api/routes.py/api/schemas.py as api-review; these are caller-visible contracts. Plugin paths and the activation projector are gray. High risk applies even though the intended shared change is additive and small. No persistence migration or retrieval/ranking behavior changes are planned.

**Discovery:**
The current service validates exactly three runtimes. pending_candidate() already reads exact registered scope without claiming/ACKing; it has no HTTP route. Existing claim/ACK/reply APIs are reusable. Prior pinned-source probes established host-derived session/turn kwargs and showed pre_api_request alone cannot attest later middleware execution. Hermes v0.22.2 (d923a5eb487a17c0a68801bba9ef0f56c81040a8) is the researched release; source cache is available. PR314 overlaps the four shared files; PR297/306 own OpenCode. Existing development root is dirty and remains untouched. The real host must be provisioned entirely in a disposable location; no existing Hermes application is assumed.

**Material assumptions:**
The released TUI/gateway host can be launched against a disposable profile and local provider through supported entrypoints. If not, stop at the exact host/bootstrap blocker; do not substitute extracted functions for E2E proof. A single explicit profile/container and known plugin configuration can establish a qualified request/admission boundary; if downstream rewrites/short-circuits prevent proof, retain the claim without ACK and report the missing seam. A plugin-owned durable metadata-only wake marker can fence uncertain injection in this topology without changing the Relay schema; review must confirm its scope and limitations before implementation. Missing broad recovery or multi-profile support must fail closed or stay explicitly unsupported.

**Plan:**
1. Invoke Agent Workflow, evaluate applicability, create/classify this record before code edits (done).
2. Obtain clean-context technical plan review. In parallel, the cheaper worker may inspect and provision only the disposable released host/source/environment; no repository implementation before review passes.
3. Add only Hermes runtime recognition and a validated exact-scope pending-candidate HTTP read. Keep activation projection unqualified/passive until actual evidence justifies any stronger capability; do not modify scheduler/recovery/storage authority.
4. Add an explicitly enabled experimental native plugin: fixed loopback service/profile/container configuration; register the actual conversation on a seed natural turn; poll metadata; durably fence an exact delivery before public inject_message; claim on the actual matching turn; verify full attributed payload at the supported LLM execution boundary; ACK only after successful qualified forwarding; expose a host-session-bound reply tool. Fail closed on missing/mismatched identity, payload or permission. Use plugin data for wake-attempt metadata only, not payloads or a second delivery queue. No automatic retry after uncertain injection.
5. Launch the real released host via its supported protocol with a local provider stub. Prove the idle round trip, wrong target, stripped payload/no false ACK, and cleanup through normal Relay status/read paths. The stub observes requests and emits deterministic tool-call responses; it never claims or ACKs.
6. Complete focused new-surface tests, selector-required whole-change checks in a coordinated resource window, and clean-context result review. Publish only after required gates pass; no live deployment is included.
Key conventions: standard-library plugin HTTP and filesystem fencing where sufficient; use public Hermes plugin APIs and existing Pallium HTTP contracts. Target files are exact in Scope; reassess if dependencies/entrypoints require more. Stop rather than silently broadening the host topology or relaxing an identity/admission contract.

**Verification plan:**
When an idle real host has a pending message, it starts a turn automatically and the original sender receives its reply -> real released-host/provider-stub E2E asserting provider payload, integration-origin ACK, reply and cleanup through HTTP reads. When the target/scope or effective payload is wrong, no incorrect claim/ACK/reply occurs -> negative caller-surface controls. When pending is queried, no delivery state or payload changes -> exact-scope HTTP tests. When injection is uncertain, no blind retry occurs -> plugin fence/reload/refusal tests. When publishing, existing runtimes remain compatible -> affected subsystem checks, complete-path test selector, full non-slow suite once when its local slot is granted, existing platform CI and clean-context review. Behavior contracts unchanged.

**Plan review:**
Agent technical review: /root/hermes_e2e_review, 2026-10-19, HEAD 79cae04af813d7736c2d0900fedb9fbced8f1eb0, accepted with the conditions below.

Follow-up technical review after run 8 identifies trusted tool identity's public seam: model_tools._execute_tool omits turn_id from registry.dispatch, but supplies session_id/turn_id through ids.hook_kwargs() to public tool_execution middleware. Register that middleware only for pallium_relay_reply and invoke its existing host-bound reply logic with trusted middleware IDs; forward every other tool unchanged via next_call(args). Keep the registered handler's missing-turn refusal intact. This uses the documented short-circuit contract, adds no host patch or guessed identity, and stays within the recorded plugin paths/frozen one-plugin topology. Actual rerun and boundary tests must prove the complete round trip before claiming qualification. Ready to implement this exact reviewed correction.

Follow-up technical review at checkpoint dc730848 resolves the reply exposure blocker: run 7's provider Tool Search catalog contains pallium_relay_reply, proving registration succeeded. Pinned public docs and tools/tool_search.py show that Tool Search defers plugin functions behind bridge tools. The accepted smallest supported fix is tools.tool_search.enabled: off in the disposable profile before host/session startup, with that setting included in the frozen config guard and actual provider-schema assertion. No plugin toggle, private registry edit or user-environment change is needed. The default Tool Search bridge path remains later qualification. Implementation is ready again for this exact config-only narrowing and rerun.

Follow-up technical review on 2026-10-19 accepts only the frozen disposable v0.22.2/local-stub experiment: public plugins.list RPC inventories actual loaded name/version/enabled state before/after, but exposes no middleware count. Strict own-plugin config is necessary; bundled auto-loads bypass that list, so pinned bundled source must be checked for execution middleware and unexpected enabled inventory refused. The harness must assert effective local provider/config and provider receipt before ACK with no hotload during the journey. Plugin revalidates its frozen config and trusted execution model/provider/base_url/api_mode. General detection of arbitrary middleware hotloads has no public PluginContext seam and remains a wider-release blocker. This narrows qualification; it does not authorize general installation or relax payload/identity proof.

Accepted by clean-context reviewer `/root/hermes_e2e_review` on 2026-10-19 at HEAD 79cae04af813d7736c2d0900fedb9fbced8f1eb0. Admission must compare the complete attributed payload and host session/turn in the effective llm_execution request, forward the same request to next_call, and ACK only after successful downstream execution; the real provider stub independently verifies that request. Qualify only the explicit single-plugin/provider topology; refuse competing execution middleware. Persist the exact scoped metadata fence before injection, retain uncertainty across reload, and test identity, stripping, downstream failure and marker refusal. Hermes activation remains passive with no inferred admission evidence/fallback. Exclude Hermes from legacy Codex ACK/reply executor selection while preserving existing runtime behavior. No scope expansion or renewed human approval required.

**Approvals:**
Approved by user 2026-10-19: "ok, let's start with slice 1. keep it isolated from the reliability work, use cheaper models where it makes sense, and focus on getting the real e2e round trip working."
This approves the immediately preceding proposed slice: minimal plugin/runtime plumbing for an isolated actual-host round trip. It grants no live environment change or expansion into broader reliability behavior.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Created an isolated managed checkout and branch from the recorded main base.
  The prior feasibility branch and its pending validation remain preserved.
- Pre-edit whole-change applicability requires a Work Record. Fresh boundary
  report has no violations; Redline triggers architecture and API checkpoints.
  Independent plan review passed with the conditions recorded above.

## Evidence

Pre-edit path/risk evidence: `%TEMP%\pallium-hermes-e2e-slice1-01a1489e`.
Shared runtime/API implementation adds Hermes without changing existing runtime
semantics. The new metadata-only HTTP route delegates to the existing exact-scope
query. Activation remains passive/unqualified with no inferred admission evidence.
Partial clean-context review `/root/hermes_e2e_review` found no shared-code blocker.

Focused checks on the shared working diff, 2026-10-19:
- `tests/test_hermes_relay_plugin.py`: 12 passed; a subsequently added closed/stale
  wake node passed separately. Covers HTTP registration, scope, read-only pending,
  validation, ACK/reply lifecycle and non-Codex callback routing.
- `tests/test_agent_relay_e2e.py`: 64 passed.
- `tests/test_relay_wake_contract.py`: 9 passed.
- Implementation-readiness check: advisory only; required technical and human
  plan approvals recognized. Redline PR checkpoints remain advisory/unsatisfied.

The real-host bootstrap and plugin are still in progress. These HTTP checks do
not establish native wake or payload admission. Full-suite resource coordination
remains pending; no full-suite run, PR readiness, or completion is claimed.

Released-host bootstrap succeeded through the supported `hermes serve --isolated`
WebSocket protocol: gateway ready, session create, prompt submit and complete seed
turn. The loopback SSE provider stub observed `/v1/chat/completions`; no paid model
was used. Source is pinned at d923a5eb487a17c0a68801bba9ef0f56c81040a8. Environment,
dependencies, profile and logs are under the recorded temporary root. The venv
reuses an existing read-only uv CPython 3.14.6 base (created 2026-06-27); no global
interpreter, PATH, configuration or live service was changed. Seed process cleanup
was reported by its owner; full integration cleanup remains an E2E assertion.

The plugin and native harness are separately assigned to cheaper workers with
disjoint file ownership; parent reviews and owns shared contracts. Coordination
fallback: the scope/test-slot Relay update remained pending despite queued wake
evidence and a later completed recipient turn (trace gap). App-message fallback
reported that concrete issue to the authorized reviewer. The reviewer confirmed
the test-slot request is already with the Pallium manager; no slot is granted.

## Recovery

Latest native run 7 proves actual released-host automatic idle marker wake,
trusted-turn claim, complete attributed provider request, then integration ACK.
It **fails** the complete round trip: `pallium_relay_reply` is absent from the
provider's advertised tool list, so no reply is dispatched or received. Seven
bounded host attempts resolved SSE/title behavior, public inventory expectations,
the per-turn `on_session_end` behavior, and tool schema/configuration issues. No
more host runs are authorized without a concrete supported activation fix; the
independent reviewer is examining public plugin activation/order/scope. No Hermes
source modification or private registry mutation is permitted.

Run 7 artifacts: `%TEMP%\pallium-hermes-e2e-slice1-01a1489e\pytest-test-run7\test_released_hermes_idle_rela0`
(`provider-requests.json`, `relay-calls.json`, host/driver logs). The harness asserts
actual provider tool exposure before emitting a reply call; it cannot fabricate
success with an undeclared tool. Host/driver/server cleanup was reported by its
owner. Frozen qualification is not established by this partial result.

Current focused plugin/API file: **37 passed**. It covers stripped/historical
payload, wrong session/turn/provider, profile/config change, no ACK on downstream
failure, retained reload fence, exact payload/reply bounds, and host-bound reply.
Native-test collection needs no Hermes dependency in the base environment.
Fresh import-linter report has zero violations. Redline remains High with API
and architecture shadow checkpoints. Whole-change selector requires the full
non-slow suite; the coordinated slot remains ungranted, so it has not run.

The three plugin files were created through a deterministic scoped write after
apply_patch could not create the out-of-root parent directory; no broader paths
were edited. Skill feedback trigger 3 is dropped: native tool exposure is an
external-host integration issue, not an Agent Workflow defect.

Owner: this chat. Next action: disposable released-host/plugin round trip and
independent result review. Keep this worktree for E2E qualification; never install
it into the live service. The approved target is experimental slice 1 only.
