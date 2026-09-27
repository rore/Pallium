<!-- agent-workflow:start -->
**Outcome:** Cleanup of an older Claude wake intent cannot discard a newer scoped wake intent.
**Target:** Pallium.
**Scope:** core/claude_wake.py; integrations/claude-code/hooks/common.py; tests/test_claude_wake_dispatch.py; tests/test_claude_code_integration.py; docs/claude-code-integration.md; .agent-workflow/tasks/claude-intent-race.md.
**Constraints:** Preserve exact runtime/session/container isolation, intent identity validation, bounded fail-closed hook behavior, closed-state fencing and existing caller contracts. No dependency, schema, scheduler, public endpoint, live-service operation, paid journey, protected-test edit or participant-count change.
**Completion criteria:** When older cleanup and newer scoped publication overlap, the newer registration remains recoverable and its busy/idle/closed transition is not lost; contention or publisher failure returns within the existing hook budget without corrupting durable intent; existing recovery and restart journeys remain valid on Windows and POSIX.
**Requirement baseline:**
{"source":"user:3c78e64e-f364-443b-bf36-518d3425ffa6; pallium-manager accepted runtime-fix ownership assignment 2026-09-27","outcome":"Cleanup of an older Claude wake intent cannot discard a newer scoped wake intent.","scope":"core/claude_wake.py; integrations/claude-code/hooks/common.py; tests/test_claude_wake_dispatch.py; tests/test_claude_code_integration.py; docs/claude-code-integration.md; .agent-workflow/tasks/claude-intent-race.md.","constraints":"Preserve exact runtime/session/container isolation, intent identity validation, bounded fail-closed hook behavior, closed-state fencing and existing caller contracts. No dependency, schema, scheduler, public endpoint, live-service operation, paid journey, protected-test edit or participant-count change.","completion_criteria":"When older cleanup and newer scoped publication overlap, the newer registration remains recoverable and its busy/idle/closed transition is not lost; contention or publisher failure returns within the existing hook budget without corrupting durable intent; existing recovery and restart journeys remain valid on Windows and POSIX."}
**Risk:** High
**Complexity:** Moderate
**Reason:** Exact runtime ownership and durable credential handoff are persistence/security-sensitive despite gray production paths. Cross-process Windows/POSIX synchronization has meaningful failure and timing interactions.
**Discovery:** Prior isolated deterministic probe proves older compare/delete removes a newer atomically published intent and the new register fails. Exact CI restart-failure causality remains unproved. Fresh intended-path Redline classification is GRAY, no reported boundary violations; raise risk by judgment. Production discovery continues only within this scope.
**Material assumptions:** A bounded shared platform lock can coordinate the standalone hook publisher and service without crossing import boundaries or changing public formats. Validate against existing helpers/callers and budget behavior; if invalid, return to planning before implementation.
**Plan:** Pending focused discovery and independent review. First implementation step: invoke /agent-workflow and validate this Work Record/risk/reviews before any code edit. No production implementation authorized by this planning record.
**Verification plan:** Deterministic real-hook publication plus HTTP registration/recovery interleaving; busy-to-idle, idle-to-busy and closed transitions; Unicode and exact-scope independence; lock contention/failure and lifecycle/restart coverage; focused affected files, whole-change selector, required full non-slow suite and fresh import boundaries; independent smart result review and CI before delivery.
**Plan review:** Pending clean-context technical review of a concrete plan.
**Approvals:** Pending separate review of the concrete High-risk plan through the designated manager; do not ask duplicate questions or treat broad authorization as an unseen plan review.
**Exceptions:** None.
**State:** Blocked
<!-- agent-workflow:end -->

## Ownership and recovery

2026-09-27: User directs continuation with minimap-manager and Pallium coordination with pallium-manager, exact source 3c78e64e-f364-443b-bf36-518d3425ffa6. Pallium manager accepted coordination and assigned the existing willing reproducer, pall-arc, a separate isolated runtime fix beginning with prospective plan/risk/independent review. Minimap manager retains combined delivery and result-approval coordination. No competing Claude runtime owner reported.

Branch feat/claude-intent-race, managed isolated checkout C:\Users\I347041\.codex\worktrees\claude-intent-race\Pallium, clean base 62a4cf5edf7b5cb873595888d0f46cf5d8ec24ff. Participant PR253 remains separate at remote 5302e61c / local 254011d7. PR252 at d88adb80 isolates one Codex test clock; reconcile that existing narrow fix with participant fixture repair rather than duplicating or merging unrelated product work. No production files edited in this task.

## Evidence

Read-only Sol diagnosis /root/busy_wake_ci_diagnosis ran one isolated temp-only probe using real ClaudeWakeRegistry and hook _write_wake_intent. It intercepted Path.unlink after old intent validation, published newer busy intent with normal os.replace, then allowed old unlink. Observed old registration True, new publication True, newer intent survived False, newer registration False, registry retained stale idle. Reproducible code sent to minimap-manager in relay-msg-1b70f5561add415e8c0aff7ae46a48f2. This proves the production race, not the historical full-suite failure cause.

Fresh base import-boundary report contains no violations. Whole intended scope is non-exempt because it includes runtime and hook paths; ordinary documentation exemption does not apply. Next: inspect existing cross-process lock/publication helpers and every intent-delete caller, propose the smallest correct bounded synchronization, get independent review and route any genuinely required exact plan consent through one manager.
