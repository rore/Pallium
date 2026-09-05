<!-- agent-workflow:start -->
**Outcome:**
Every normal hook-injected Relay delivery can be replied to atomically in the same turn under exact integration-owned scope.

**Target:**
Pallium Relay hook delivery and MCP reply contract.

**Scope:**
`integrations/codex/hooks/user_prompt_submit.py`; `integrations/claude-code/hooks/{user_prompt_submit,session_start,stop}.py`; focused hook/wake tests; Relay roadmap. OpenCode is verification-only because it already composes the same scope block.

**Constraints:**
Never accept model-supplied runtime/session identity. Preserve hook-owned ACK behavior and the separation between hook delivery and MCP receive. Fail closed on missing or conflicting trusted scope. Coordinate live hook/setup refresh with vnext-dev.

**Completion criteria:**
(1) Hook-injected deliveries expose or bind the exact trusted container and actor scope needed for same-turn reply. (2) Atomic reply succeeds once without a receipt; ACK-only remains reply-free. (3) Wrong/missing/conflicting scope fails closed. (4) Caller-surface E2E covers Codex and Claude plus installed-state drift where applicable. (5) Roadmap/docs match verified behavior.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Relay scope is a cross-runtime trust boundary and the defect was reproduced during live dogfood. The smallest shared fix must preserve fail-closed identity and ACK semantics.

**Discovery:**
Live vNext dogfood reported that a hook-injected delivery lacked visible trusted scope, so pallium_relay_reply rejected it and the agent attempted an out-of-band fallback. Trace confirms Codex and Claude Relay branches emit, ACK, and exit before their existing scope-only `format_injection` runs. OpenCode already composes Relay output with that scope block. The MCP resolver correctly fails closed when the paired scope is absent or conflicts. A second dogfood defect was reproduced during coordination: recipient discovery listed alias `claude_arch`, alias send returned 404, and exact-session send succeeded; RW-013 will own that separately.

**Material assumptions:** The defect is the missing model-visible handoff, not storage or MCP reply behavior. Existing `format_injection` is the canonical sanitizer/renderer. The Relay message section and exact scope block are independently bounded at 2,400 characters; the maximum schema-valid escaped scope is 2,155 characters, so no valid delivery payload is truncated or starved to fit scope.

**Plan:** Reuse `format_injection([], exact scope)` before claim in each Python Relay-emission branch, as OpenCode already does. Emit and ACK only when that trusted scope block renders; otherwise leave the delivery pending or its claim lease-recoverable. Extend the real Codex and Claude hook journeys to parse the injected scope and complete receiptless atomic replies. Add focused exact-scope assertions for Codex UserPromptSubmit and Claude UserPromptSubmit, SessionStart, and Stop, preserving Unicode, notices, ACK-only guidance, invalid-scope refusal, and the independent 2,400-character bounds. Update RW-012, then coordinate install and run one bounded live Claude reply witness.

**Verification plan:** Exact same-turn scope, fail-closed invalid scope, receiptless reply, output integrity, and cross-runtime lifecycle → focused Python caller-surface suites, OpenCode integration suite, import-linter, workflow/redline gates, and one installed Claude witness.

**Plan review:** Claude architecture review confirmed the root cause, reuse of `format_injection`, fail-closed scope handling, payload integrity, and focused caller-surface coverage. Its suggestion to omit scope from Stop was rejected because Stop stderr plus exit 2 is the actual native-wake continuation input; omitting scope there would preserve RW-012 for the primary Claude wake path. No additional Claude ping-pong is needed.

**Approvals:** Approved by user 2026-09-05T22:47:09.9831044Z: "you don't need to ask every time, you have a constant approval to get what you're working on to a done state"

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-06: Created RW-012 from the live hook-scope reply failure and traced the missing Python hook composition; OpenCode already implements the intended pattern.
- 2026-09-06: Relay alias coordination also reproduced a separate discovery/send inconsistency (`claude_arch` listed, alias send 404, exact-session send accepted); queued as RW-013, not folded into this scope.
- 2026-09-06: A queued vNext report plus local reproduction identified oversized recipient listings returning only a generic response-budget error; queued separately as RW-014.
- 2026-09-06: Bounded Claude architecture review accepted; implementation started with the existing formatter and no new abstraction.
- 2026-09-06: `apply_patch` hit the known Windows 1327 sandbox failure; all edits used exact one-occurrence PowerShell replacements limited to named files.
- 2026-09-06: Initial Linux CI exposed one stale SessionStart assertion that assumed the Relay notice was the final output; updated it to assert the independently bounded Relay section plus the exact appended scope.

## Evidence

- Added `investigate-cross-repository-relay-coordination` behind RW-012/013/014 with explicit opt-in membership and a transport-only boundary.
- Local verification: 200 affected Python tests passed with 2 intentional skips and 4 pre-existing Pydantic warnings; OpenCode 45 passed with 6 platform skips; import-linter clean.
- CI regression verification: `tests/test_claude_wake_registration.py` plus `tests/test_agent_relay_hooks.py` passed 80 tests after the stale output-shape assertion was corrected.
- Installed Windows witness: Relay message `relay-msg-55e630f56d0842d1ab39c31ee2b5b1e7` auto-woke Claude session `3c4744b9-1b2e-4bcb-820e-0f16f3ce685a`; the hook claimed and delivered in under one second, and Claude returned `rw012-installed-pass` by receiptless atomic reply six seconds after send, without a manual turn or MCP receive. Codex and Claude setups point at this checkout; service health, status, and queue-health endpoints passed after wrapper restart.

## Result review

- Clean-context Luna final review found no correctness, security, lifecycle, ACK, scope, budget, roadmap, or documentation blockers; its focused run passed 97 tests with 2 skips. The installed automatic Claude wake/reply witness passed. Remaining merge gates are refreshed CI and an actual CodeRabbit review after its rate-limit window.
