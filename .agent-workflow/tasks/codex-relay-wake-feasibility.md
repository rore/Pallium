<!-- agent-workflow:start -->
**Outcome:** Pallium has reproducible evidence and a reviewed protocol contract deciding whether each installed runtime can safely support wake-first Relay delivery.

**Target:** Pallium.

**Scope:** Decision record under `docs/designs/`, redacted protocol fixtures and contract tests under `tests/`, this Work Record, and the existing wake roadmap item's evidence/status links.

**Constraints:** No production, runtime-config, installer, schema, API, core, storage, or integration changes. No undocumented runtime protocol dependency. Minimize live model turns and never target a user's active work session.

**Completion criteria:** Claude Code, Codex, and OpenCode are each classified supported/passive-only/blocked with installed-version evidence; the trigger-to-admission handshake and full cross-state transition table are explicit; deterministic fixtures/checks cover the normalized contract; remaining work is re-estimated.

**Risk:** Routine

**Complexity:** Moderate

**Reason:** Redline classified every intended path blue with no boundary or surface findings. Moderate complexity because three evolving runtime protocols and concurrent lifecycle transitions require independent evidence.

**Discovery:** Installed versions are Claude Code 2.1.217, Codex CLI 0.149.1, and OpenCode 1.18.19. Installed Codex exposes `queue --thread --message`; OpenCode documents `/session/status` and `/session/:id/prompt_async`; Claude Channels are supported from 2.1.80 and push into an open session. Existing Pallium integrations pull/ack only on natural turns. Enqueue/transport success is not yet proof of model-context admission.

**Material assumptions:** (1) Disposable sessions can exercise idle/busy wake without touching user work; disproved by inability to isolate a session → stop live testing and classify the surface unproven. (2) Each supported runtime exposes an observable, delivery-correlatable admission event; disproved by only transport acknowledgement → classify passive-only. (3) Public/runtime-generated schemas and traces can be redacted into stable fixtures; disproved by unstable or secret-bearing payloads → document evidence without committing raw traces.

**Plan:** 1. Inspect installed public commands, generated schemas, and primary runtime docs. 2. Use disposable sessions to test idle, busy, admission correlation, stale/closed behavior, restart behavior, and ambiguous retry semantics, stopping at the first decisive unsupported contract. 3. Normalize redacted evidence into minimal fixtures. 4. Publish the supported/passive-only/blocked matrix, exact per-runtime handshake, complete transition table, and re-estimate. 5. Add deterministic contract checks and link the evidence from the roadmap. Key convention: runtime evidence remains integration-specific while the normalized state machine is product-generic. Target files are this Work Record, `docs/designs/016-relay-wake-feasibility.md`, `tests/fixtures/relay_wake/**`, one focused `tests/test_relay_wake_contract.py` if executable fixtures add value, and the roadmap item. Stop before any production edit or when a runtime lacks a safe public admission primitive.

**Verification plan:** Each runtime classification → primary-doc + installed-command evidence and disposable-session trace where safe. Trigger/admission contract → deterministic fixture assertions. Every lifecycle race → transition-table completeness check. Repository integrity → focused pytest, roadmap parser, workflow checker, and `git diff --check`.

**Plan review:** Self-review: scope is blue and evidence-only; live tests are isolated and explicitly stop before unsafe or undocumented control paths.

**Approvals:** Not required at this risk level

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Establish/Discover: constrained PR 1 to evidence and contracts; found new public Codex `queue`, OpenCode async prompt, and Claude Channels surfaces, none yet sufficient without admission correlation.
- Assess risk/Plan: redline BLUE, Routine/Moderate; self-reviewed evidence-only plan with explicit stop conditions.

## Evidence

Pending.

## Result review

Pending.
