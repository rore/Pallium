# MCP Relay sender retry identity

Canonical source: `roadmap/features/add-wake-first-relay-delivery.md`, sender retry identity checklist, at `a2726453323a363b0656ddf3d87a2d4b0d86937e`. Roadmap edits remain with the parent task's designated shared checkout.

<!-- agent-workflow:start -->
**Outcome:** MCP send callers can retry a committed send after response loss using one caller-supplied message identity without duplicating the durable message.

**Target:** Pallium Relay MCP send.

**Scope:** app/mcp/server.py, tests/test_relay_mcp_tools.py, tests/test_mcp_server.py, docs/agent-relay.md, and this Work Record.

**Constraints:** Preserve omitted-ID behavior and existing sender/payload/recipient/expiry conflict checks. No storage, schema, scheduler, native wake, installed environment, or response redesign changes. Preserve all protected behavior contracts.

**Completion criteria:** Same-ID retry after committed-send response loss yields one message and delivery through public reads; conflicting sender, payload, recipient or expiry rejects without mutation; omitted IDs still generate independent messages; empty and over-128 IDs reject, 1/128-character Unicode IDs succeed, and omitted/null expiry semantics remain intact.

**Requirement baseline:**
{"source":"roadmap/features/add-wake-first-relay-delivery.md@a2726453323a363b0656ddf3d87a2d4b0d86937e","outcome":"MCP send callers can retry a committed send after response loss using one caller-supplied message identity without duplicating the durable message.","scope":"app/mcp/server.py, tests/test_relay_mcp_tools.py, docs/agent-relay.md, and this Work Record.","constraints":"Preserve omitted-ID behavior and existing sender/payload/recipient/expiry conflict checks. No storage, schema, scheduler, native wake, installed environment, or response redesign changes. Preserve all protected behavior contracts.","completion_criteria":"Same-ID retry after committed-send response loss yields one message and delivery through public reads; conflicting sender, payload, recipient or expiry rejects without mutation; omitted IDs still generate independent messages; empty and over-128 IDs reject, 1/128-character Unicode IDs succeed, and omitted/null expiry semantics remain intact."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":["https://github.com/rore/Pallium/pull/354"]}

**Behavior changes:**
[{"target":"task-context.scope","classification":"equivalent","before":"app/mcp/server.py, tests/test_relay_mcp_tools.py, docs/agent-relay.md, and this Work Record.","after":"app/mcp/server.py, tests/test_relay_mcp_tools.py, tests/test_mcp_server.py, docs/agent-relay.md, and this Work Record.","reason":"Add one expected message_id=None field to the existing exact client-forwarding assertion; preserve every previous payload/scope assertion and unchanged externally omitted-ID behavior."}]

**Risk:** High

**Complexity:** Simple

**Reason:** app/mcp/server.py is a red API contract surface requiring api-review. One optional argument exposes an existing client/storage contract; no new storage behavior or dependency.

**Discovery:** MCP tool omits message_id although its docstring already describes existing-ID expiry. PalliumMcpClient.relay_send already accepts optional message_id, generates a UUID when absent, and passes explicit identities unchanged. RelaySendRequest accepts 1–128 characters. SQLite relay_send matches sender identity, payload, recipient selector, redaction, parent, and supplied expiry before returning the existing status. tests/test_relay_mcp_tools.py already provides registered FastMCP call_tool plus real HTTP ASGI/storage fixtures and public status/turn reads. Existing callers omit the new argument and need no edits. No behavior_contracts path changes.

**Material assumptions:** Existing client/storage identity semantics fully implement the required contract. If caller-surface regression exposes a defect beyond tool forwarding, return to planning rather than extending persistence scope. No installed or native qualification is needed to prove this repository contract.

**Plan:** Add optional nullable message_id with Field(min_length=1, max_length=128) to registered pallium_relay_send and forward it unchanged to relay_send. Briefly document generating/reusing one ID for identical retries after uncertain response; omitted ID remains a new send. Extend existing FastMCP/ASGI tests: commit via real HTTP then suppress its response, retry same ID, inspect public status and claim/ACK lifecycle; parameterize conflicts and identity boundaries, and assert omitted IDs remain independent. Reuse existing expiry fixtures and error helpers. Stop on scope expansion, conflicting baseline, or unmet review/approval gate. No production code edits until technical plan review and exact-scope human approval are recorded.

**Verification plan:** Registered schema asserts optional nullable 1–128-character string. Caller-surface fault test drives FastMCP call_tool → client → HTTP → SQLite, loses the committed response, retries, observes one message/delivery via status and turn, ACKs, and observes no second delivery. Sender/payload/recipient/expiry conflicts assert HTTP 409 and unchanged original status/inboxes. Boundary cases include empty/129 rejection and 1/128 Unicode acceptance. Omitted/null ID calls produce separate identities; existing expiry matrix proves omitted/null/finite expiry behavior. Run exact new nodes first, then affected MCP files only after parent allocates sole application-test slot. Before eventual review/PR run scripts/test-plan.py --base origin/main and its reported checks, workflow check, and full non-slow suite once when authorized; no publication or full CI in this slice.

**Plan review:** Agent technical review: /root/sender_api_plan_review, 2026-10-21, GO with no blocking findings after reading this record at 55d8fc61 plus server registration, client relay_send/_post_or_error, HTTP schema/routes, core Relay.send, SQLite relay_send/_expiry_matches, MCP expiry/lifecycle fixtures and client forwarding tests. Reviewer requires send help to allow identical same-supplied-ID retry after uncertain response instead of contradictory blanket resend prohibition; accepted.

**Approvals:** Approved by user 2026-10-21: "So this is all regarding reliability. So if there are things to research more or fix here, then they should be part of what we're doing." Root supplied request_source_item_id c3ecdd91-903f-4c6c-a011-f23a7791571a and confirmed this followed its reviewed recommendation to expose existing stable-ID MCP support. Subsequent user scope confirmation: "This all should go as tasks we need to fix for reliability" (1d8902c1-e762-4086-b569-42c305faf58e). These quotes authorize the reliability fix at scope level; root adopts the additive optional message_id plan without storage or contract weakening. No claim of literal field-specific user wording is made.

**Exceptions:** —

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Checkpoint: api-review

What changes: expose existing optional caller message_id through MCP send. Compatibility risk: low; omission still follows existing generated-ID path. Verification: registered-schema and caller-surface retry/conflict/boundary tests. API checkpoint required for eventual PR.

## Implementation

- 2026-10-21: Verified GitHub main and fetched origin/main both resolve to a2726453323a363b0656ddf3d87a2d4b0d86937e. Created native worktree C:/Dev/rore/Pallium/build/relay-mcp-retry-identity on fix/relay-mcp-retry-identity. Primary dirty files and installed clone untouched.
- Source discovery complete; applicability is normal workflow because app/mcp/server.py is a protected red API path. No exemption claimed.
- Pallium work association list failed because no exact container_ref was injected. No identity was guessed and no association is claimed.
- Plan review accepted; additive optional message_id and forwarding implemented without client/storage changes. Tool help and docs now describe safe same-identity retry after uncertain response.
- Added 16 parameter cases in the existing FastMCP/ASGI test file: registered schema, four expiry variants with post-commit response loss and pending/delivered retries, five identity conflicts, and six Unicode/boundary/omitted/null cases. Fault injection wraps actual ASGI transport; client HTTP/error logic remains intact.
- Focused execution found two new test setup mistakes (turn response nests endpoint under session; no /relay/recipients route); corrected to use actual registration responses. Affected coverage found exact help capitalization and mocked kwargs expectations; retained the qualified Do not resend caution and added expected message_id=None without weakening assertions. No client/storage changes were needed.

## Evidence

Application-test slot was allocated after PR325's first cohort and released immediately after owned root 41044 exited at 2026-10-21T08:25:34.677Z. Existing isolated runtime C:/Users/I347041/AppData/Local/Temp/po-7o13uuj6/v/Scripts/python.exe; child-only environment scrub/private short Temp profile, assertions enabled, retained-process-handle cap/drain runner. No dependency or installed-environment changes.

- AST parsing of app/mcp/server.py and tests/test_relay_mcp_tools.py passed using the existing development Python; git diff --check passed. Neither check imports the application or consumes the application-test slot.
- All 16 new cases passed with evidence reuse: schema (new-cases-short, head 0d247ecf); response-loss four expiry variants (remaining15, head 36037600); conflict/boundary/generated-ID eleven cases (remaining11, head 2e3bc1bb, runner exit 0). Later changes affect only test setup/assertion bookkeeping and help punctuation/capitalization; message identity forwarding is unchanged.
- All 337 existing cases in tests/test_relay_mcp_tools.py, tests/test_mcp_server.py, tests/test_mcp_client.py and tests/test_mcp_integration.py passed: 217 in affected, one in affected-remaining, 119 in affected-final (head 3bcfc1c5). Passing nodes were explicitly deselected on continuation. New 16 were excluded from the affected runs. Logs, JUnit, source/lock hashes, private-environment recipes and process receipts are retained under build/retry-identity/ in this worktree.
- Failure receipts are preserved: new-cases failed before any test body because sandbox temporary-directory setup/CIM snapshot were unavailable; new-cases-short and remaining15 exposed the two test setup errors; affected and affected-remaining exposed exact existing help/mock expectations. Each concrete failure was corrected, with no blanket rerun and no expectation weakening.
- Final affected runner: exit 0, uncapped, root exit verified, streams complete, direct-child snapshot empty, clean worktree and unchanged source/lock hashes. This is a direct-child snapshot, not universal/reparented-descendant proof.
- Actual import-linter boundary backend passed; fresh Redline/workflow evidence generated. Workflow status advisory solely for the eventual PR api-review checkpoint label/CODEOWNER evidence. Baseline, relationships, High approval, independent plan review and boundary/behavior-contract predicates passed; protected test paths are unchanged.
- Selector reports full lane: python -m pytest tests/ -x -q. Root conditionally authorized one full after independent receipt/runner/runtime-parity GO; /root/sender_api_plan_review supplied EXECUTION GO. The cleaned manifest removed unused copied fixture/private-root/tree fields and pinned clean source 3dc1021829a32933f8043b95b196b2f7b8cc91b0, uv.lock and changed-source hashes. Full manifest SHA256 e0dc83fb0168ef34cbdc7d9464319aa47fbf27c9bd46585a92c859de3f699d5a; reviewed runner uses a 1,200-second owned-process cap and private child environment.
- Read-only full runtime inventory under build/retry-identity/runtime-lock-comparison.json enumerates all 66 distributions at the existing private venv; each matches environment-active uv.lock versions. Recursive metadata dependencies for project dev/vector/mcp extras satisfy Windows/Python markers and installed-version specifications with zero errors. This is local locked-version/dependency parity, not hosted-runtime parity. No package installation occurred.
- The ONE required full run FAILED: 6,320 passed, six skipped, two xfailed, one setup error in 435.04 seconds. Exact node: tests/test_relay_wake_health.py::test_reservation_authority_bound_is_observed_without_weakening_validation[0-/dashboard/api/relay/summary]. At tests/test_relay_wake_health.py:165 the world fixture's registry.initialize(old_owner_drained=True) returned False; the captured warning is codex_wake_initialization_failed error_type=ImmediateTransactionBusyError. This slice changes no wake-health/core/storage paths. Physical cause and baseline status are unproven; neither flakiness nor a relationship to earlier incidents is asserted.
- Full receipt: pytest exit 2 / runner exit 2, uncapped, owned root 78292 exit verified at 2026-10-21T08:49:07.4589711Z, both streams complete, direct-child snapshot empty, same clean head and source/lock hashes. stdout SHA256 4aebe35d30799b3735d3947f81ce460d3a03649547117c6f4ec5d4504c0ec4a6; JUnit 18bd4d7f07169eb5dbd6aa2d8e508a1a3746b54ce1e0aad913c73a84db64ddb7; stderr empty. Raw recipe, intent, runner, logs, XML and result are retained under build/retry-identity/full-prepared/. Parent notified immediately of slot release. No retry, new diagnostic, scope expansion, CI/publication or installed qualification has run.

## Historical result review

Agent technical review: /root/sender_api_plan_review independently verified the final diff, 353 unique passing focused/affected nodes with no unresolved failed node, six JUnit hashes, runtime ledger and cleaned runner before giving full EXECUTION GO. Reviewed revision: 3dc1021829a32933f8043b95b196b2f7b8cc91b0. Verification adequacy: focused contract coverage passed; required full qualification failed as recorded above. The actual failed-full receipt and limited classification were supplied for independent read-only review; that review is pending. No final readiness claim is made.

## Recovery

Base revision a2726453323a363b0656ddf3d87a2d4b0d86937e; branch fix/relay-mcp-retry-identity; latest application/test revision 3bcfc1c5670fe9b6eba23220b9e8c6d608721683; tested full source/record revision 3dc1021829a32933f8043b95b196b2f7b8cc91b0. Production forwarding, documentation and focused/affected verification are complete. BLOCKER: required full qualification failed at the exact wake-health setup node above. Next: independent failed-evidence review and parent decision on the bounded owning-test investigation; do not automatically rerun or alter unrelated production/tests. Retain worktree for this concrete unresolved verification purpose. Roadmap contribution remains pending owner reconciliation; broader reliability tasks remain open. Publication is held.

## Current-main integration

2026-10-23 manager assigned completion to @pal-dev1 after existing source/evidence review. Original clean0fb119bb88b26996b347a22273d92bd25cc3b27b and its evidence remain untouched at build/relay-mcp-retry-identity. New isolated branch feat/relay-mcp-retry-identity at build/relay-mcp-retry-identity-20261023 preserves all eight original commits and merges verified GitHub/current origin/main2768022ebf8b302d09a9955da38f3fc5d61504a4 without conflicts: integration437094ef32c8e16bc2f25548b7fb52b16048c299. Net diff against current main remains exactly the five declared source/test/docs/record files. Server and both focused test blobs are identical to tested3dc10218; docs preserve both current-main and retained sender guidance.

The earlier failed wake-health fixture and registry/recovery source are unchanged, while current-main storage now releases the local writer gate after confirmed settlement, before reset/close cleanup. That base change neither proves the old setup failure cured nor qualifies this integrated candidate. Selector still requires the full non-slow lane. Preserve original353 focused/affected evidence as historical correspondence; proposed current-base validation is both affected MCP files followed by one required full, under reserved executor authority. A separately qualified failure-only installer observer may accompany that genuinely required full instead of adding a diagnostic-only full run. No tests, publication, API label, merge or installed operation occurred during this integration. State remains Blocked pending current-base verification, independent result review, API checkpoint and the separate High-risk human result review.

## Integrated verification and restart recovery

The integrated candidate1f5ec4db27047e10ab0f0ec6e610d1c15b7c719d completed both separately granted checks before the user pause. Exact affected MCP files:264 normal passes,0 failures/errors/skips,46.83s; JUnit SHA256c4fd9e256a223338e9e210078ce3c1d530c7559bcd056fd62ad277c7bac65c05. Required full non-slow suite:8071 passed,37 skipped,2 xfailed,0 failures/errors,583.58s; JUnit SHA256106f48120c984e6a9b000242f6e15e74f15ae5c15218c1ddf434a6b08341084e. Evidence: build/sender-current-main-focused-01 and build/sender-current-main-full-01. The older6320-pass failed full receipt remains failed; this later result neither rewrites it nor identifies its physical cause.

Both runs used the unchanged qualified CPython3.13.14/SQLite3.53.1/SQLAlchemy2.0.48 runtime,66 dependency pins plus project0.1.0, matching runtime artifacts/lock and exact candidate package origins. Fresh external p-r1/p-r2 parents returned Git128 and matching-test process censuses were empty before intent. The full runner verified1883 tracked source hashes plus the qualified private observer. Root46284 creation2026-10-23T10:29:44.8267270Z exited uncapped, complete streams, empty bounded direct-child snapshot and clean unchanged source/head/lock; wrapper623.064s. These snapshots do not establish universal or reparented-descendant cleanup. No rename-failure capture occurred, so the original installer cause remains unknown.

The full had already terminated before the user pause's controlled-stop attempt; no process was killed. The immutable pause checkpoint accurately preserves the execution result separately from interrupted pending acceptance. After the user restart and verified recovery, the same sender_evidence_review accepted both preserved results via manager chat01a16320-c588-72b0-a098-cb3d137b1e75. No rerun occurred, and no old queued grant was reused.

### Original full-specific authority

Frozen recipe92b6a26a0046223c8bb9e1ae622b229c3ab6db6f97ff9900cdcafe2590a50ada retains its preparation-time executor_authorization=PENDING; it was not rewritten after execution. The actual full-specific grant was received in this chat from manager01a16320-c588-72b0-a098-cb3d137b1e75 after focused264 acceptance and Claude lease release, before the root creation above. Its exact received instruction includes:

> Grant sole executor for ONE required sender integrated full at candidate1f5ec4db27047e10ab0f0ec6e610d1c15b7c719d: reviewed recipe92b6a26a0046223c8bb9e1ae622b229c3ab6db6f97ff9900cdcafe2590a50ada, tests/ -x -q configured4workers/not-slow,1200s owned cap, fresh non-Git Temp/p-r2, pinned729runner/B91runtime, qualified first-failure-only rename observer234fc5146f7a5e34f9548a6f6323baaef20c7db959f73cc2e2aa87248471f7cf.

No send timestamp is invented. Existing received-turn authority, frozen recipe/intent and preflight establish the sequence; the later acceptance confirms it without retroactively changing that recipe.

## Result review

Agent technical review: sender_evidence_review, same independent native reviewer, acceptance relayed by manager chat01a16320-c588-72b0-a098-cb3d137b1e75 in this resumed task.

Reviewed revision: 1f5ec4db27047e10ab0f0ec6e610d1c15b7c719d, with exact affected264-pass and full8071-pass receipts, recipe92b6a26a, runtime/source identities and preserved execution authority.

Verification adequacy: accepted integrated focused and required full results; zero failures/errors in both, expected full platform skips/xfails retained. Application/test blobs remain those independently reviewed before integration. This is ready for a concrete draft PR and normal CI, not merged or released. The API checkpoint and separate High-risk human result review remain explicit final acceptance gates; no API label or human result approval is fabricated. Existing source-publication authority supersedes the earlier preparation-only phase restriction. Manager retains canonical roadmap ownership; report the PR/contribution and remaining reliability work there. Retain both original and integrated checkouts/evidence until delivery and safe cleanup disposition. Trigger dropped: the private observer API-binding mistake and local command encoding failure were harness/environment issues, not Agent Workflow defects.

## Draft publication

Draft PR354 https://github.com/rore/Pallium/pull/354 created at121d83920de33f20be968368e61f49e3f96d778c against main2768022e and attached to this task. It publishes the reviewed source with accepted264 focused and8071 full results, preserves the older failed full and unknown installer cause, and clearly leaves normal CI/API checkpoint/separate High human result review open. Publication descendants update only this Work Record; application/test correspondence to1f5ec4db is unchanged. No merge, API label, installed access or live rollout occurred. Manager owns roadmap linkage and final acceptance coordination.

## Current CI failure and bounded fixture plan

CI39943233525 on b5998d866d3b5407587a2a022764024c82774c94 failed Python3.12 at tests/test_agent_relay_hooks.py::test_claude_relay_uses_utf8_and_skips_memory_after_a_claim:3263 passed,22 skipped,1 xfailed,1 failed in405.50s. Python3.13, Windows smoke and governance passed. Retained build/sender-ci-b5998d86/failed.log SHA256 f549981a10db26cb1579dccd48a56b74530bc5ffb2b5c87f1985e2c6640c25f7. The captured session_state_write_failed phase=pre_attempt_deadline occurs before the native session-lock attempt; relay_turn returns None before the test's mocked HTTP delivery, then the hook takes the memory path. No claimed delivery reached the UTF-8/ACK subject. Physical latency cause remains unknown; unchanged hook source does not establish unrelatedness.

Existing sender_evidence_review, relayed by manager01a16320-c588-72b0-a098-cb3d137b1e75, accepted the smaller preparation-only correction: pre-create the isolated session directory and exact utf8.lock containing one byte before hook.main. Reuse the existing session-directory preparation pattern in this file. Keep native lock acquisition/release, actual relay_turn, mocked transport and all UTF-8, exact scope, footer, length, ACK and skip-memory assertions intact. The earlier proposal to mock relay_turn is not used. Native lock-setup refusal remains independently covered by tests/test_hook_common_parity.py::test_session_lock_failure_reports_actual_boundary_without_changing_wait (eight expanded phase/runtime cases) and tests/test_claude_code_hooks/test_session_pin.py::TestPinAndGet::test_lock_setup_exhaustion_refuses_pin_before_native_acquisition. No product clock, timeout, retry, protected contract or API behavior changes. This adds one blue ordinary test path to the existing High-risk API task; its risk and remaining human/API gates stay unchanged. Review the actual diff, then propose the changed exact UTF-8 node plus the existing eight-case lock-boundary node under one new finite executor grant. No duplicate full run. If setup still fails, retain evidence and reassess before changing the boundary. Current readiness is blocked by failed CI; earlier accepted results remain historical evidence.
