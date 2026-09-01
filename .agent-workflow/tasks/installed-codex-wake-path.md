<!-- agent-workflow:start -->
**Outcome:** Installed Windows Pallium services can wake an unloaded exact Codex Relay session even when the service process did not inherit Codex's versioned CLI directory on `PATH`.

**Target:** `app/codex_wake.py` executable resolution and focused wake regressions.

**Scope:** Resolve one Codex executable once per wake/queue attempt using stdlib-only runtime discovery; reuse it for both `exec resume` and `queue`; add focused tests and repeat the real installed-service no-ping round trip. No Relay schema, delivery, addressing, profile, service-launcher, or other-runtime changes.

**Constraints:** Preserve durable next-turn fallback on every launch failure; preserve hidden vector-argv subprocesses, exact-target validation, strict active-writer fallback, and the narrow `pallium-relay` profile. Do not add dependencies or machine-specific committed paths.

**Completion criteria:** With Codex absent from simulated `PATH`, a Windows local-install candidate resolves and both wake commands use it; missing candidates remain fail-safe; the installed service changes a new exact Relay delivery from pending to delivered and receives an exact `hello` reply without an app ping.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Redline classifies `app/codex_wake.py` gray/watch with no boundary violation or checkpoint. Elevated because this changes installed runtime process resolution; Simple because one shared helper and focused tests cover both callers.

**Discovery:** The first post-restart installed-service live test left `relay-msg-39ec238a1d0043f38c5f95bf0787206c` pending with zero claim attempts while `relaydev` remained unloaded. The earlier acceptance service was launched interactively. The adapter passes bare `codex.exe`; the installed task launches independently of the Codex app, while the CLI is stored under `%LOCALAPPDATA%/OpenAI/Codex/bin/<version-hash>/codex.exe`. Launch failures are intentionally fail-safe and therefore left no delivery-state evidence.

**Material assumptions:** The installed-service PATH difference is the blocker; disproved if runtime-owned executable discovery still leaves a fresh delivery pending, in which case stop and add bounded wake diagnostics rather than broadening the resolver. The newest valid local Codex binary is the correct candidate; disproved by a strict profile parse or live resume failure.

**Plan:** Add one stdlib resolver used by both resume and queue: explicit `CODEX_CLI_PATH` when it names a file, normal `shutil.which`, then on Windows the newest valid `%LOCALAPPDATA%/OpenAI/Codex/bin/*/codex.exe`; otherwise retain the bare command so existing fail-safe handling is unchanged. Add focused resolver and shared-command assertions. Run focused suites, workflow/redline checks, restart only through the wrapper, and repeat the exact installed-service Relay round trip without an app ping.

**Verification plan:** Resolver precedence and empty/missing candidates -> unit tests; both subprocess paths use the same resolved executable and remain hidden/vector argv -> existing plus focused wake tests; no regression in MCP/setup -> focused integration suite; installed service admission and reply -> Relay message status plus model-visible exact reply; service health -> `/health`, `/status`, `/debug/queue/health`.

**Plan review:** Clean-context review `/root/redline_classify` approved the bounded resolver precedence, shared executable reuse, fail-safe fallback, and installed-service verification with no corrections.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-09-01: Installed-service live test reproduced pending/no-claim while the target remained unloaded. Pre-edit redline: gray/watch for `app/codex_wake.py`, blue tests/record, no boundary violation or checkpoint; classified Elevated/Simple.
- 2026-09-01: Added stdlib executable resolution shared by resume and queue: explicit valid `CODEX_CLI_PATH`, normal PATH, then newest valid Windows local-install candidate. Focused syntax and regression checks pass: 80 tests. `apply_patch` hit the documented Windows 1327 failure, so the exact two-file change used deterministic replacements.
