# Hook HTTP transport: lazy TLS initialization

<!-- agent-workflow:start -->
**Outcome:**
Plain HTTP hook requests avoid unnecessary TLS trust-store initialization while HTTPS retains standard certificate verification and existing request semantics.

**Target:**
Standalone Claude Code and Codex hook HTTP clients; roadmap/features/add-wake-first-relay-delivery.md incident ledger owned by root.

**Scope:**
integrations/claude-code/hooks/common.py; integrations/codex/hooks/common.py; tests/test_agent_relay_hooks.py; tests/test_codex_integration.py; tests/test_codex_wake.py; tests/test_hook_deadline_safety.py; tests/test_hook_common_parity.py; this Work Record.

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
Agent technical review: root and /root/architecture_check accepted the narrow reviewed lazyTLS plan and requested actual isolated extraction review against fresh origin/main before qualification. Actual diff review pending; no production edit extends that approved helper/callsite scope.

**Approvals:**
Approved by user 2026-10-12: "Okay, the point was to make sure we don't have any performance issues. We need to find, analyze, find all our performance problems and make sure we handle everything. The service should function optimized without any bottlenecks." (direct human source0742db7b-c8f4-4ecb-9ca8-a046a4bc6741 relayed by root). Root explicitly delegates this independent fix and publication/merge preparation; installed hook changes require separate exact scope handled by root.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Recovery state

Existing managed codex-enrollment-recovery checkout reused on fix/hook-lazy-tls from clean freshly verified cf558114. Stage1 c33de5c6 and Stage2 3edac09a branches/evidence retained. Known supported integration config files were checked narrowly for this checkout reference; none found, no config contents or secrets emitted. No active owned process or live changes. Source-owner extraction patch SHA2561267374F3F4228467ACB94DBB122497849735850E2DA8F41DFBE3153C7465ADC inspected, but combined context requires narrow main-base adaptation.
