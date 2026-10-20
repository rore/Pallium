# Hook HTTP transport: lazy TLS initialization

<!-- agent-workflow:start -->
**Outcome:**
Plain HTTP hook requests avoid unnecessary TLS trust-store initialization while HTTPS retains standard certificate verification and existing request semantics.

**Target:**
Standalone Claude Code and Codex hook HTTP clients; roadmap/features/add-wake-first-relay-delivery.md incident ledger owned by root.

**Scope:**
integrations/claude-code/hooks/common.py; integrations/codex/hooks/common.py; tests/test_agent_relay_hooks.py; tests/test_codex_integration.py; tests/test_codex_wake.py; tests/test_hook_deadline_safety.py; tests/test_hook_common_parity.py; tests/test_relay_capacity_isolation.py; this Work Record.

**Behavior changes:** [{"target":"task-context.scope","classification":"equivalent","before":"integrations/claude-code/hooks/common.py; integrations/codex/hooks/common.py; tests/test_agent_relay_hooks.py; tests/test_codex_integration.py; tests/test_codex_wake.py; tests/test_hook_deadline_safety.py; tests/test_hook_common_parity.py; this Work Record.","after":"integrations/claude-code/hooks/common.py; integrations/codex/hooks/common.py; tests/test_agent_relay_hooks.py; tests/test_codex_integration.py; tests/test_codex_wake.py; tests/test_hook_deadline_safety.py; tests/test_hook_common_parity.py; tests/test_relay_capacity_isolation.py; this Work Record.","reason":"Root and architecture reviewer accepted a test-only steady-state lifecycle preflight for the new CI failure; production and original cancellation/deadline contracts unchanged."}]

**Constraints:**
Fresh origin/main only; no wholesale combined-source copy, REL14/15/storage/performance changes, global opener/cache, dependencies, infrastructure, identity or credential-policy relaxation, deadline widening, installed changes, live calls, push or publication. Preserve proxies, redirects, HTTPS verification, original authority and lifecycle. Root owns test-slot coordination, PR/CI/merge and separately approved installed scope.

**Completion criteria:**
Exact reviewed helper/callsite extraction, twelve boundary regressions and necessary mock/network-guard migrations, genuine focused RED/GREEN on main base, affected and selector-required validation, independent review and root handoff.

**Requirement baseline:**
{"source":"root delegated independent lazyTLS fix within direct human performance-fix authorization","outcome":"Plain HTTP hook requests avoid unnecessary TLS trust-store initialization while HTTPS retains standard certificate verification and existing request semantics.","scope":"integrations/claude-code/hooks/common.py; integrations/codex/hooks/common.py; tests/test_agent_relay_hooks.py; tests/test_codex_integration.py; tests/test_codex_wake.py; tests/test_hook_deadline_safety.py; tests/test_hook_common_parity.py; this Work Record.","constraints":"Fresh origin/main only; no wholesale combined-source copy, REL14/15/storage/performance changes, global opener/cache, dependencies, infrastructure, identity or credential-policy relaxation, deadline widening, installed changes, live calls, push or publication. Preserve proxies, redirects, HTTPS verification, original authority and lifecycle. Root owns test-slot coordination, PR/CI/merge and separately approved installed scope.","completion_criteria":"Exact reviewed helper/callsite extraction, twelve boundary regressions and necessary mock/network-guard migrations, genuine focused RED/GREEN on main base, affected and selector-required validation, independent review and root handoff."}

**Risk:** High

**Complexity:** Moderate

**Reason:**
HTTP transport crosses HTTPS certificate and credential-redirect security boundaries in both standalone integrations. Architecture review required; no protected behavior contract edits.

**Discovery:**
urllib initializes default HTTPSHandler even for local HTTP, unnecessarily loading the trust store inside hook request budgets. The reviewed combined candidate uses a request-local lazy HTTPS handler and demonstrated twelve transport boundary passes. Fresh origin/main is cf5581147d9a1e1ec8ac73e8e8d186fb948a4269; it lacks the combined diagnostic load-observer seams, so those two migration lines must not be ported. Only named helper/callsite/test changes are extracted, preserving main's existing REL14/15 behavior.

**Material assumptions:**
The source owner's reviewed helper is compatible with main's unchanged urllib callsites. Generic HTTP uses default proxy/redirect semantics; credential requests keep explicit proxy denial and redirect rejection. HTTPS initialization happens before actual HTTPS open and remains retryable after initialization failure. Stop and revise if extraction requires broader runtime changes.

**Plan:**
First invoke Agent Workflow and classify/create this record before code edits (done). Reuse the clean managed checkout on fix/hook-lazy-tls from freshly fetched origin/main, retaining immutable Stage1/Stage2 branches. Read the source owner's minimal patch and adapt only named hunks to main context: local LazyHTTPSHandler, _build_opener, _urlopen, four generic requests and two Claude credential builders. Port twelve boundary cases and exact mock/bootstrap guard migrations. Obtain independent actual-source review, prepare existing private guarded runner, coordinate exclusive focused RED/GREEN and affected files, then run fresh whole-change selector and its required full once. Root owns publication/merge/installed scope; do not copy unrelated combined code or construct new harnesses.

**Verification plan:**
HTTP/TLS boundaries -> real local HTTP success/error/redirect requests, lazy standard HTTPS initialization/verification, HTTP-to-HTTPS redirect and failed-initializer retry across both hook copies.
Caller safety -> existing hook request/deadline/credential/ACK/bootstrap tests with faithful mocks and network denial.
Independent release -> exact-base focused RED/GREEN, affected files, static/workflow checks, selector-required full and clean nonimplementer review.

**Plan review:**
Agent technical review: root and /root/architecture_check accepted the narrow plan and then inspected the actual fresh-main seven-file extraction. Reviewer accepted preserved credential/proxy/redirect/TLS semantics and necessary fake/network-guard migrations, with no combined REL14/15 drift. After reading paired warm results, reviewer accepted the measured 0–1.2ms median overhead without adding a global cache. Root authorized focused, affected and selector-required full in the exclusive slot; no live scope inferred.

**Approvals:**
Approved by user 2026-10-12: "Okay, the point was to make sure we don't have any performance issues. We need to find, analyze, find all our performance problems and make sure we handle everything. The service should function optimized without any bottlenecks." (direct human source0742db7b-c8f4-4ecb-9ca8-a046a4bc6741 relayed by root). Root explicitly delegates this independent fix and publication/merge preparation; installed hook changes require separate exact scope handled by root.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Recovery state

Existing managed codex-enrollment-recovery checkout reused on fix/hook-lazy-tls from clean freshly verified cf558114. Stage1 c33de5c6 and Stage2 3edac09a branches/evidence retained. Known supported integration config files were checked narrowly for this checkout reference; none found, no config contents or secrets emitted. No active owned process or live changes. Source-owner extraction patch SHA2561267374F3F4228467ACB94DBB122497849735850E2DA8F41DFBE3153C7465ADC inspected, but combined context requires narrow main-base adaptation.

## Extraction and focused evidence

WR-only checkpoint 39498bc60a4cd8b625fa261ec25958441a324720 was committed before code edits; its application source equals fresh origin/main cf558114. Narrow adaptation changed exactly seven source/test files, 220 additions and 14 deletions. Both common copies contain only the reviewed lazy helper and four generic/two Claude credential callsite replacements. Necessary existing mocks/bootstrap guards migrated; twelve boundary cases ported. Combined temporary observer migrations are absent on main and were omitted. No whole-file copy, REL14/15 mutation, storage change or diagnostics was ported. No apply_patch fallback.

Genuine original-code RED: six failures in 3.96s, private eb99c371d86b48739c5f994ce05be799, stdout SHA256 C7FA73136734876221713EBC2D3529AEABA66517D45CA43B9E6766F2207D2268. All actual HTTP success/error/redirect results and cleanup passed; each failure is the unnecessary HTTPS initializer call on plain HTTP. Both original sources were temporarily restored from the WR-only base and candidate bytes restored/hash-checked in finally.

Candidate GREEN: fourteen passes in 6.36s (twelve boundary cases plus two private paired timing cases), private 4e20812f86df464b99e9453a49917666, stdout SHA256 E474F510EB519D32204170492DBCD2679D88BEAE93A782C1F8191EE7DE2729CE. Both runs had empty guard/stderr logs and all three tracked identities drained. Candidate common hashes: Claude 4AA0581CDB25C596FCF2DC1FB0F0A65E9BBC0CA56EFB64D6ED3530874FEF95D2; Codex 7F1765418F13295B0E1EF7A3F9385EBD097C00F5F56072BA9D80E19C5FD98FD1.

Ten alternating private loopback pairs per copy: Claude standard-warm median/max14.646/20.930ms versus local-lazy15.776/16.607ms, paired median delta+1.168ms; cold57.921 versus17.121ms. Codex standard-warm15.879/16.290ms versus local-lazy15.999/17.009ms, paired median delta−0.003ms; cold29.050 versus16.208ms. This small sample includes HTTP transport/scheduler variation, not universal savings or live concurrency qualification. Reviewer accepted the tradeoff; no cache added. Original threaded50 performance failure remains separate.

Whole-change selector requires python -m pytest tests/ -x -q. Root authorized the existing guarded eight-file affected run, then exactly one configured non-slow full on this independent main-base candidate. Affected GREEN: 667 passed in 148.77s, private 363f465039cb4179a7dad83ec95f1572, stdout SHA256 91D4B0D89107D4DB0AFC38A5D6FA120610A195EBD91FBF0747C1B78566FF1646; guards/stderr empty and all eight tracked identities drained. Full GREEN: 6629 passed, 45 skipped, two xfailed in 442.25s, private a2a78ec3aa294f4bad483acba2651bd4, stdout SHA256 EAD88FB4C025B382AB3E3A91F6FEC6DF04B774FB9951298BE4E3FE4F60FBCDC8; empty guards/stderr and all 85 tracked identities drained. Same frozen seven-file candidate throughout. Static import-linter exited0 and fresh Redline is advisory with passed boundaries. No duplicate local full; heavy slot released. Evidence preserved in shared build/service-performance-20261012/lazy-http-extraction/independent.

## Result review

Agent technical review: /root/architecture_check final actual source/evidence acceptance for publication after inspecting main-base extraction, causal RED, twelve boundary cases, 667 affected successes, full6629 and paired warm tradeoff; no outstanding source finding or further local test requested.
Reviewed revision: frozen seven-file delta on WR-only checkpoint 39498bc60a4cd8b625fa261ec25958441a324720, application base cf5581147d9a1e1ec8ac73e8e8d186fb948a4269; Claude common SHA2564AA0581CDB25C596FCF2DC1FB0F0A65E9BBC0CA56EFB64D6ED3530874FEF95D2 and Codex common SHA2567F1765418F13295B0E1EF7A3F9385EBD097C00F5F56072BA9D80E19C5FD98FD1.
Verification adequacy: real local HTTP regression and request/HTTPS/redirect/initializer-failure boundaries, faithful bootstrap mocks, affected subsystem and one selector-required full qualify this independent transport slice. Warm timing is a small private sample with transport variation. No threaded50, live rollout or broader performance closure claimed. Root owns PR/CI/merge, canonical ledger reconciliation and exact separately described installed scope.

## Rollout boundary

Before the capacity-test edit: diagnostic-head Linux3.13 failed the callback-arrival watchdog in test_codex_operation_tracking_settles_after_event_loop_closes[None]. The first HTTP request includes lazy router preparation and real SQLite before the held callback; exact historical delay is unmeasured. Root and architecture reviewer accepted public invalid-body warmup (422) before the unchanged one-second arrival wait, with no callback/outcome/tracker side effects. Keep real SQLite, HTTP cancellation, loop closure, worker result and drain assertions; record warmup duration privately. This qualifies steady-state lifecycle, not cold-request performance, and does not claim the CI cause identified. No service stub or deadline increase.

Architecture reviewed the actual warmup-only diff and runner: real SQLite and all original one/five-second cancellation/closed-loop/drain controls remain. Initial three cases passed in 0.94s, private fa9c2d403500470fb669438cbb9474e5, stdout SHA256 E0120BE92EF1D8C9CF58CA27F622E28F681B0D9C18464F4B101499F99A9DC53B; guards/stderr empty, three owned identities drained. Local preflight durations were 2.602/1.746/1.907ms, not evidence of historical CI timing.

Root identified hosted visibility risk in tmp_path-only diagnostics. Reviewer accepted bounded captured-stderr metadata (first 32 delayed-HTTP spans plus truncation flag, or one warmup duration), preserving exact hook JSON stdout. Both three-parameter nodes then passed: six cases in 9.69s, private e77475cf54c949fbba9caa14f46e5265, stdout SHA256 411B00B4B9F26E15A1EEF38048E4EDBE51ECC98AFACD6B02C0B8FFADB75A3756; empty guard/stderr logs and all three tracked identities drained. Existing original scope/rollback and historical-cause limits remain. Fresh Redline is GRAY advisory, workflow checker clean; prior review outputs were hash-backed-up before regeneration. Root owns fresh hosted validation and publication; no further local full or live change.

PR313 Linux3.13 follow-up: the delayed real-HTTP wake case reported a 2195ms turn submission-through-return interval and a 2192ms hook timeout before the fixture's subsequent 1.15s response delay. Historical queue/SQLite cause is unknown. Root authorized node-only pass-through worker submission/entry/return, durable turn and forwarding/delay/send metadata before qualification. Preserve real 2s/1.15s boundaries, claim/emission/ACK and negative cases; this is diagnostic evidence, not a production fix. No new local full or CI dispatch by this worker.

Architecture reviewed the actual 42-line pass-through diagnostic and accepted focused execution. All three original cases passed in 8.99s, private c7e3395d9c1d41baa74a9af5d21fffc5, stdout SHA256 F804A35E1CA4DA748EF9F32D80DB86B6FA5634C15FD243903276082C73D965A3; guards/stderr empty and all three owned identities drained. Successful delayed case: forwarding 16.017ms, durable turn 7.649ms, matched durable worker wait 0.066ms, injected delay 1151.022ms. Negative delayed/fragmented cases retained claimed/no-emission/no-ACK assertions. Evidence at build/service-performance-20261012/lazy-http-extraction/independent/delayed-http-diagnostic, manifest SHA256 373792D56FBEC478C081F05B6BFA0A489ED76A446C847FC2BD3C04308104763A. Local green does not establish historical CI cause or a production correction; a recurring failure can now separate worker wait from real turn execution.

The independent main-base slice changes only two production common files and adds no configuration, dependency or persistence format. Installed and primary common baseline bytes are identical: Claude SHA256271D466C0B89C87D0167E0E655E5722A99D38A3432174575D535110CC9E1200C; Codex SHA256EC62792E756EE77694AB2BD80B11278C26992930A0CD47C4E770FB0D706A18FC. Root must preserve the three approved dirty emergency hotfix files during fast-forward; the target main-base slice does not include those hotfixes, so they must never be cleared/reverted to make this update. Proposed backup/rollback scope awaiting human approval is the exact two common code files, preserving all current database/wake/config state and three emergency hashes. Standalone hooks pick up common on invocation; no host/API restart is implied by this code slice. No live backup/write/restart was performed by this worker.
