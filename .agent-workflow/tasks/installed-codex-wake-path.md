<!-- agent-workflow:start -->
**Outcome:** Installed Pallium services wake an unloaded exact Codex Relay session reliably, using the agreed payload-free signal and coalescing a short same-session message burst into one wake turn.

**Target:** `app/codex_wake.py` executable resolution, wake signal, same-session burst coalescing, and focused regressions.

**Scope:** Resolve one Codex executable once per wake/queue attempt using stdlib-only runtime discovery; reuse it for both `exec resume` and `queue`; use the agreed static wake instruction; debounce a short burst for the same session so one hook turn receives the batch; add focused tests and repeat the real installed-service no-ping round trip. No Relay schema, delivery, addressing, profile, service-launcher, MCP identity, or other-runtime changes.

**Constraints:** Preserve durable next-turn fallback on every launch failure; preserve hidden vector-argv subprocesses, exact-target validation, strict active-writer fallback, and the narrow `pallium-relay` profile. Do not add dependencies or machine-specific committed paths.

**Completion criteria:** With Codex absent from simulated `PATH`, a Windows local-install candidate resolves and both wake commands use it; missing candidates remain fail-safe; both launch paths use the agreed static signal; two near-simultaneous exact deliveries to one session produce one wake attempt and one hook turn; the installed service completes a no-ping `hello` round trip without an empty follow-up wake.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Redline classifies `app/codex_wake.py` gray/watch with no boundary violation or checkpoint. Elevated because this changes installed runtime process launch timing and resolution; Simple because one adapter and focused tests cover the behavior.

**Discovery:** The first installed-service live test left `relay-msg-39ec238a1d0043f38c5f95bf0787206c` pending with zero claim attempts while `relaydev` remained unloaded. Executable resolution fixed that. Two replies sent 733 ms apart then woke the target twice: the first turn injected and ACKed both, while the second showed an empty generic prompt. The implementation still used the superseded placeholder. Recovery receive also lacked runtime-owned MCP thread identity; that remains a separate security-preserving follow-up, not a model-supplied identity workaround.

**Material assumptions:** A one-second trailing debounce covers ordinary multi-part sends while preserving durable next-turn fallback; disproved if a controlled same-session burst still creates an empty second turn or leaves a delivery pending. The newest valid local Codex binary is the correct candidate; disproved by a strict profile parse or live resume failure.

**Plan:** Keep the completed stdlib executable resolver. Replace the placeholder with the agreed payload-free instruction for both resume and queue. Add a one-second trailing, per-session debounce ahead of the existing wake function: the newest delivery generation in a short burst owns the single wake; superseded workers may discard only their own delivery bookkeeping and must never clear newer session state; the owning worker releases state in `finally` on every launch outcome; later deliveries still schedule normally. Add focused signal, stale-worker ordering, failure-then-later-delivery, and coalescing assertions; run focused suites and workflow/redline checks; restart only through the wrapper; repeat a two-message exact-session no-ping round trip. Then handle the MCP recovery-identity defect as a separate recorded slice after tracing a runtime-owned source.

**Verification plan:** Resolver precedence and empty/missing candidates -> unit tests; both subprocess paths use the same resolved executable, agreed signal, and hidden/vector argv -> focused wake tests; two same-session deliveries inside the debounce window invoke `_wake` once, a stale worker cannot clear the newest generation, and a launch failure cannot block a later delivery -> deterministic unit tests; no regression in MCP/setup -> focused integration suite; installed two-message burst -> one model-visible turn containing both messages and no empty follow-up; service health -> `/health`, `/status`, `/debug/queue/health`.

**Plan review:** Clean-context re-review `/root/redline_classify` approved Elevated/Simple with one incorporated correction: generation-safe ownership/finally cleanup plus stale-worker and failure-then-later-delivery regressions.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-01: Installed-service live test reproduced pending/no-claim while the target remained unloaded. Pre-edit redline: gray/watch for `app/codex_wake.py`, blue tests/record, no boundary violation or checkpoint; classified Elevated/Simple.
- 2026-09-01: Added stdlib executable resolution shared by resume and queue: explicit valid `CODEX_CLI_PATH`, normal PATH, then newest valid Windows local-install candidate. Focused syntax and regression checks pass: 80 tests. `apply_patch` hit the documented Windows 1327 failure, so the exact two-file change used deterministic replacements.
- 2026-09-01: Installed-service no-ping round trip succeeded, but a two-reply burst exposed stale wake wording and a redundant empty second wake. Returned to planning for bounded signal/coalescing correction; MCP recovery identity remains a separate security-sensitive follow-up.
- 2026-09-01: Implemented the exact wake instruction `Pallium Relay delivery pending. Process the attributed Relay messages injected by the turn hook. If none are present, stop without taking action.` for resume and queue, plus one-second trailing per-session generation-safe debounce. Stale workers release only their own delivery ID; the owning worker cleans session state in `finally` across launch failures. `apply_patch` was unavailable with Windows 1327, so deterministic replacements were used only in `app/codex_wake.py` and `tests/test_codex_wake.py`.
- 2026-09-01: Verification: `.venv\\Scripts\\python.exe -m pytest tests/test_codex_wake.py -q` -> 15 passed (2 existing pydantic warnings).
- 2026-09-01: Consolidated verification: wake + Codex integration + MCP suites -> 83 passed; workflow check and `git diff --check` clean. Final self-review found no scope drift or unresolved correctness finding; skill-feedback triggers all false.
