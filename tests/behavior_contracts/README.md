# Behavioral contracts

Only accepted, caller-visible Pallium requirements belong here. Existing implementation tests remain outside this directory. A protected test must have a documented product source, a concrete regression witness, and a deterministic PR run. Changes to these files are classified through the Work Record once workflow protection is activated; a failing test is visible in CI but GitHub merge is not blocked.

## RW-022 — accepted busy Codex wake stays single-flight

- Requirement: For a loaded, busy Codex task, once Pallium accepts one native queue submission for a pending Relay delivery, periodic recovery must not submit that non-idempotent wake again. The later admitted hook turn emits and ACKs the delivery once; an overtaken wake trigger stops before an empty model turn.
- Authority and original failure: [wake-first Relay delivery, RW-022](../../roadmap/features/add-wake-first-relay-delivery.md) records at least fourteen accepted submissions and thirty empty task starts before the single-flight fix.
- Protected regression: `test_codex_busy_wake.py::test_busy_queue_recovery_stays_single_flight_and_competing_hook_blocks_overtaken_wake`.
- Caller surface and observation: HTTP send and message-status reads, six recovery windows, and the Codex UserPromptSubmit hook with its emitted context and final HTTP delivery state. The native queue process is stubbed deterministically.
- Regression witness: on current code the test passes; in a disposable checkout, releasing the accepted wake reservation immediately after native submission reproduces six queue calls and fails the protected one-call assertion.
- Boundary: This does not claim that an unloaded Codex task wakes automatically, that Codex itself admits a queued turn, or that all runtime/platform combinations are qualified.