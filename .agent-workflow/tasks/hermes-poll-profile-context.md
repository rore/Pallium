# Hermes profile-context polling repair

<!-- agent-workflow:start -->
**Outcome:**
Hermes named-profile Relay polling retains the initiating profile and admits pending replies without a manual recipient turn.

**Target:**
Pallium Hermes native plugin.

**Scope:**
integrations/hermes/__init__.py poller thread creation and focused caller-surface tests in tests/test_hermes_relay_plugin.py.

**Constraints:**
No profile/config/data/host changes without exact approval; no desktop control, forced turn, resend, manual receive or ACK; preserve scope, identity, profile-change and uncertain-delivery fences; use existing contextvars, with no dependency or API change.

**Completion criteria:**
After a named-profile foreground hook ends, polling reads that same profile, injects the exact pending delivery and admits its full payload through existing hooks/middleware; sibling/default profile state is isolated and changed owned configuration remains rejected.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Hermes named-profile Relay polling retains the initiating profile and admits pending replies without a manual recipient turn.","scope":"integrations/hermes/__init__.py poller thread creation and focused caller-surface tests in tests/test_hermes_relay_plugin.py.","constraints":"No profile/config/data/host changes without exact approval; no desktop control, forced turn, resend, manual receive or ACK; preserve scope, identity, profile-change and uncertain-delivery fences; use existing contextvars, with no dependency or API change.","completion_criteria":"After a named-profile foreground hook ends, polling reads that same profile, injects the exact pending delivery and admits its full payload through existing hooks/middleware; sibling/default profile state is isolated and changed owned configuration remains rejected."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":["https://github.com/rore/Pallium/pull/363"]}

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
Gray integration runtime path; preserve profile isolation across a background-thread boundary. No schema, public API, admission policy or host modification.

**Discovery:**
Live Astra reply relay-delivery-d5553ca452614c7f97225ce68288acfe is pending attempts0, correct Hermesendpointaf98e95a. Live pending-candidate exposes it; no persisted wake exists. Installed plugin hashes match source. Named Pelican profile enables plugin; default root does not. Installed Hermes Python3.14 has thread_inherit_context=0; direct read-only host helper demonstration resolves Pelican on caller thread, default on ordinary child thread, Pelican under copied context. Poller's profile_ok calls load_config_readonly and returns before reading candidates on default config. Existing fixture uses process-global config and misses this boundary.

**Material assumptions:**
A copied context preserves public Hermes profile resolution without freezing mutable configuration; falsify with focused regression and unchanged scope/config rejection tests. This establishes a reproduced mechanism consistent with live evidence; installed repair still needs exact scoped approval and actual original reply receipt. Canonical feature add-wake-first-relay-delivery remains owned by manager.

**Plan:**
Reuse existing contextvars.copy_context().run for the poller thread target, copying at validated ensure_poller startup. Add a ContextVar-aware profile config fixture in a focused test, revert foreground context before waiting, then drive pending candidate, marker injection, hook/middleware admission and read-path ACK. Assert later config mutation still fences and default/sibling profile sees no payload. Existing uncertain-delivery fencing remains unchanged. No new recovery subsystem or background retry rules.

**Verification plan:**
Named profile retention and full delivery -> focused caller-surface regression fails before fix and passes after.
Profile privacy/mutation and existing wake/ACK behavior -> affected Hermes plugin tests plus relevant integration checks.
Delivery -> independent technical review, existing governance checks and required hosted CI; exact approved installed-plugin update/reload then inspect the original pending reply without forced receive/turn.
Emergency scope -> no redundant broad local suite; required hosted full CI remains merge gate.

**Plan review:**
Agent technical review: astra-reviewer, independent non-implementer, turn01a178ab-08c1-7f01-83aa-609fa1fdd811 at2026-10-26T14:44:47Z. GO for copying profile context at poller thread startup while rereading current mutable configuration. Required regression: full delivery, sibling/default isolation and changed-owned-config rejection. No host changes approved by this review.

**Approvals:**
Isolated bugfix/PR/green merge already authorized. No new Hermes installed/plugin reload approval inferred. Not required at this risk level.

**Exceptions:**
—

**State:**
Blocked
<!-- agent-workflow:end -->

## Implementation

2026-10-26: Read-only diagnosis confirmed current installed native profile plugin in C:/Users/I347041/AppData/Local/hermes/profiles/pelican; no live files changed. Separate isolated branch feat/hermes-poll-profile-context from main4a546362; previous Codex repair/notes remain preserved on feat/retained-reregister-repair. Exact intended edits are listed in Scope. Manager reports this chat remains sole investigator; current owner receipt requested through Relay. Ordinary implementation authorized by user's continuing emergency repair task.

## Evidence

Implementation: the existing poller Thread target now uses contextvars.copy_context().run with the already imported standard library. Two caller-surface cases reset foreground scope to default/sibling before sending a candidate, then drive injection, claim, full payload observation and ACK through existing callbacks/read path, and reject a later owned-scope mutation. Both failed before the fix and passed after. No wake fences, claim/ACK logic or host API changed.

Focused isolated verification: tests/test_hermes_relay_plugin.py:203 passed in143.89s; tests/test_hermes_history.py and tests/test_hermes_role_attribution.py:52 passed in26.73s. Baseline/after logs are build/hermes-profile-{before,after}.log; affected-file logs are build/hermes-profile-{focused,related}.log. Live URL disabled; private task PALLIUM_HOME. Whole-change selector reports full lane; human emergency instruction omits redundant broad local suite while required hosted full CI remains a merge gate. Installed plugin is still unchanged.

Read-only Hermes helper experiment: caller_home=Pelican, ordinary poller_home=default root, copied_home=Pelican, thread_inherit_context=0. Profile config reads output only enabled/injection booleans, no secrets. Original reply unclaimed; no wake fence/state present to reset. Runtime and installation untouched.

## Result review

Agent technical review: astra-reviewer, independent non-implementer. Initial1931a902 review confirmed the production fix and203+52 logs; one coverage finding required attempting marker admission under default/sibling before restoring named scope. Added pre_llm_call refusal and exact unchanged unclaimed snapshot; both changed cases passed in1.97s, build/hermes-profile-review-delta.log. Final turn01a178b5-1af5-7490-b234-161bb1d7cbaa endorsed this delta: GO, no remaining findings. Production unchanged.

Reviewed revision: b8f659e8c1e2b1709b8c4cc596614e245a990b42.

Verification adequacy:203 plugin plus52 History/role tests and two strengthened delta cases verify profile-context retention, wrong-profile refusal, complete payload/ACK and mutable-config fencing through caller surfaces. Installed reply receipt is not yet verified. Required hosted full CI remains the merge gate. No live change approval is implied by technical review.

## Installed application and remaining acceptance

PR363 merged2026-10-26T15:09:09Z at39d216232a3bfbeb0b112b412da70ffb2756c216, required CI/Windows smoke/Linux3.12+3.13/governance/CodeRabbit all green; no unresolved review threads. Human approved the exact three-file Pelican update and supported profile-only reload: "Approve this exact plugin update and reload". No broader restart/configuration/state edits authorized by that approval.

Applied only profile plugins/pallium-hermes-relay/__init__.py plus plugin/skill .pallium-package.json fingerprints. Backup C:/Users/I347041/.pallium/backups/hermes-profile-context-20261026. Initial staging preflight stopped before live writes on Git-vs-Windows checkout line endings; staging was corrected to the exact merged Git blob. Existing configuration/skill file hashes and all three old file hashes were checked before writes. Hermes active_agents=0; supported reload_gateway_plugins accepted only Pelican and rewired2 adapters; gatewayPID23388 unchanged, Pallium loaded. No app, gateway or Pallium service restart; stable service checkout unchanged under this profile-only scope. Plugin fingerprints verified after reload; profile config and local SKILL.md edit stayed byte-identical. Existing SKILL.md fingerprint mismatch predates this update; preserve it and report general installer status still detects it rather than silently normalizing ownership.

Original reply relay-delivery-d5553ca452614c7f97225ce68288acfe still pending attempts0 after reload. Current plugin starts its poller on a foreground conversation hook and has no cold-reload session rehydration; no new wake metadata exists. Human asked to continue Hermes normally once to initialize the updated plugin; that manual warm-up must NOT count as automatic-recovery acceptance. Keep the original target, then qualify a later unattended reply separately. Manager notified via relaydev-pr363-profile-reload-result-20261026; no duplicate activation requested. Broad canonical feature add-wake-first-relay-delivery remains active; original receipt and cold-reload limitation remain open. Retain isolated checkout for this acceptance follow-up.

