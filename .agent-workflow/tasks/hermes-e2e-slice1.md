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

Follow-up technical review after run 8 identifies trusted tool identity's public seam: model_tools._execute_tool omits turn_id from registry.dispatch, but supplies session_id/turn_id through ids.hook_kwargs() to public tool_execution middleware. For pallium_relay_reply, bind that trusted pair in a plugin-local ContextVar, call next_call(args) unchanged, and reset its token in finally. The registered handler requires its host-provided session_id to match the bound session and exact admitted turn. Missing middleware/context refuses. Every other tool delegates unchanged. Do not short-circuit reply: Hermes scope/pre_tool_call/guardrail authorization lives inside next_call. Reviewer verified synchronous dispatch and ContextVar propagation in terminal_approval_batch. This preserves native authorization without a host patch, private registry access or guessed identity. Actual rerun and boundary tests must prove the complete round trip before claiming qualification. Ready to implement this exact reviewed correction.

Follow-up technical review at checkpoint dc730848 resolves the reply exposure blocker: run 7's provider Tool Search catalog contains pallium_relay_reply, proving registration succeeded. Pinned public docs and tools/tool_search.py show that Tool Search defers plugin functions behind bridge tools. The accepted smallest supported fix is tools.tool_search.enabled: off in the disposable profile before host/session startup, with that setting included in the frozen config guard and actual provider-schema assertion. No plugin toggle, private registry edit or user-environment change is needed. The default Tool Search bridge path remains later qualification. Implementation is ready again for this exact config-only narrowing and rerun.

Follow-up technical review on 2026-10-19 accepts only the frozen disposable v0.22.2/local-stub experiment: public plugins.list RPC inventories actual loaded name/version/enabled state before/after, but exposes no middleware count. Strict own-plugin config is necessary; bundled auto-loads bypass that list, so pinned bundled source must be checked for execution middleware and unexpected enabled inventory refused. The harness must assert effective local provider/config and provider receipt before ACK with no hotload during the journey. Plugin revalidates its frozen config and trusted execution model/provider/base_url/api_mode. General detection of arbitrary middleware hotloads has no public PluginContext seam and remains a wider-release blocker. This narrows qualification; it does not authorize general installation or relax payload/identity proof.

Accepted by clean-context reviewer `/root/hermes_e2e_review` on 2026-10-19 at HEAD 79cae04af813d7736c2d0900fedb9fbced8f1eb0. Admission must compare the complete attributed payload and host session/turn in the effective llm_execution request, forward the same request to next_call, and ACK only after successful downstream execution; the real provider stub independently verifies that request. Qualify only the explicit single-plugin/provider topology; refuse competing execution middleware. Persist the exact scoped metadata fence before injection, retain uncertainty across reload, and test identity, stripping, downstream failure and marker refusal. Hermes activation remains passive with no inferred admission evidence/fallback. Exclude Hermes from legacy Codex ACK/reply executor selection while preserving existing runtime behavior. No scope expansion or renewed human approval required.

**Approvals:**
Approved by user 2026-10-19: "ok, let's start with slice 1. keep it isolated from the reliability work, use cheaper models where it makes sense, and focus on getting the real e2e round trip working."
This approves the immediately preceding proposed slice: minimal plugin/runtime plumbing for an isolated actual-host round trip. It grants no live environment change or expansion into broader reliability behavior.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Created an isolated managed checkout and branch from the recorded main base.
  The prior feasibility branch and its pending validation remain preserved.
- Pre-edit whole-change applicability requires a Work Record. Fresh boundary
  report has no violations; Redline triggers architecture and API checkpoints.
  Independent plan review passed with the conditions recorded above.

## Evidence

The complete released-host round trip passed on 2026-10-19. Final native run:
`python -m pytest tests/test_hermes_relay_native_e2e.py -m slow -q -n 0` —
**1 passed in 25.34s**, with a minimal OS-only inherited environment and explicit
disposable profile/data paths. It proves HTTP send, automatic idle marker wake,
trusted-turn claim, complete attributed Unicode payload at the actual provider,
integration ACK after provider observation, native reply dispatch through normal
Hermes authorization, and original sender receipt. Wrong-recipient and closed
endpoint controls passed. No owned host/seed processes remained after cleanup.

- Hermes: v0.22.2, clean pinned source
  `d923a5eb487a17c0a68801bba9ef0f56c81040a8`, Windows, existing read-only CPython
  3.14.6 base. The venv, dependencies, profile and test data are disposable; no
  global interpreter/PATH/configuration or live service changed. No paid model.
- Tested plugin SHA256:
  `e77b9e108ce8765a38585f88a6c702ab0d544444d1481c117060d833304196e4`.
  Parent verified it matches the working file. Actual public inventory before/after,
  strict frozen config, direct function schema, request attribution and ordered
  provider/ACK/reply evidence are asserted by the test.
- Final artifacts:
  `%TEMP%\pytest-of-I347041\pytest-6339\test_released_hermes_idle_rela0`
  (`provider-requests.json`, `relay-calls.json`, host/driver logs). The Relay artifact
  records the copied plugin hash. Run 9 also passed before environment hardening.
- `tests/test_hermes_relay_plugin.py`: **41 passed in 25.02s**, covering API scope,
  read-only pending, identity/nonce matching, payload/reply bounds, stripped/history
  context, downstream failure, profile/config/provider drift, retained reload
  fences, normal authorization, ContextVar cleanup and unchanged other-tool behavior.
- Unchanged shared implementation at 069f4824 retains focused evidence:
  `tests/test_agent_relay_e2e.py` **64 passed**;
  `tests/test_relay_wake_contract.py` **9 passed**. Native collection uses no optional
  Hermes import in the base test environment. `git diff --check` passed.
- Whole-change selector requires `python -m pytest tests/ -x -q`. The full non-slow
  suite has **not run**: the reliability owner has not granted a local resource slot.
  No PR/merge readiness or complete feature qualification is claimed.

Runtime execution corrected source-only assumptions: `on_session_end` is per turn;
Tool Search defers registered tools by default; ordinary handler dispatch drops
turn_id while public tool middleware retains it. The direct-tool frozen profile
and context-local normal-dispatch bridge resolve these without host patches or
private registry access. Arbitrary middleware hotloads, default Tool Search bridge,
broader providers/profiles and recovery remain unqualified.

The plugin and harness were assigned to cheaper workers with disjoint ownership;
parent reviewed the trust boundaries and an independent reviewer supplied plan
and native-seam review. Initial directory creation required a deterministic scoped
write after apply_patch could not create the out-of-root parent; no broader paths
were edited. Skill feedback trigger 3 dropped: these were external native-host
integration assumptions, not an Agent Workflow defect.

## Result review

Agent technical review: /root/hermes_e2e_review, 2026-10-19, accepted for the
explicitly narrow isolated slice-1 experiment; no actionable code blocker.
Reviewed revision: 8840efed.
Verification adequacy: adequate for the frozen real-host/local-stub proof and
focused trust-boundary behavior; insufficient for publication until the required
full non-slow suite and separate human result review are complete.

Reviewer inspected the whole shared/plugin/harness/docs delta and actual final
artifacts: six provider requests contain no receipt/claim-token fields; exactly
one ACK follows provider response, and one reply reaches the original sender.
Normal host authorization, bound session/turn, private receipts, metadata fencing,
negative controls and unchanged other-tool behavior were accepted. The earlier
partial review at dc730848 was not a complete-result endorsement.

Fresh whole-change checks at 8840efed: import-linter zero violations; Redline
High/shadow API and architecture checkpoints remain unsatisfied, size verdict ok
(11 non-record files, 1727 changed lines); Agent Workflow advisory only, no
blocking predicate. Canonical feature remains in progress with slice-1 proof and
remaining qualification recorded. No PR, main push, deployment or live setup.

## Recovery

Owner: this chat; canonical item `add-hermes-agent-integration`,
`roadmap/features/add-hermes-agent-integration.md`. Keep this isolated branch for
full validation and review; never install it into the live service. The native
slice-1 proof is achieved; the broader feature remains in progress.

Next: independent final review, then run the selector-required full suite in the
coordinated resource window. The original source-only feasibility branch is not a
prerequisite for this proof; do not duplicate its probes or spend a second full-suite
run there. Shared merge overlap with reliability remains the four additive core/API
files and must be coordinated before publishing.

The test-slot request is with the Pallium manager. Relay scope update
`relay-msg-8efbcc7bbf794dcfb56401e6e51c3205` remained pending despite queued wake
and a completed recipient turn with a trace gap, so the authorized reviewer received
an app-message fallback. Completion/validation coordination was sent separately as
`relay-msg-bdea2fd912e44260b2b382095758f1fe`; wake evidence is not receipt or slot
approval. The completion message also remained pending/attempts 0 after its wake
turn completed; trace reports native activation did not complete. App-message
fallback reported that concrete failure and clarified that only the E2E branch
needs a full-suite slot; the earlier source-only branch is superseded. No tests
have been started on the reliability owner's behalf. The recipient later
confirmed that the delayed update arrived; this was delayed delivery, not proven
permanent loss. The manager's full-suite slot decision remains pending.
