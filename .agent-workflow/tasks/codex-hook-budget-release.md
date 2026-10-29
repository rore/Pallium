# Release the reviewed Codex hook budget repair

This fresh branch carries the reviewed hook repair and fixture corrections from PR #376 without copying its redacted Work Record or rewriting its history. Historical privacy remediation remains open separately. The existing coordinator agreed to the replacement draft route after installed recovery qualification; this record preserves the repair requirements and limitations.

<!-- agent-workflow:start -->
**Outcome:** Codex hooks preserve prompt capture and emit available Relay and scope context within the existing process budget when optional enrichment is slow or fails.

**Target:** Codex SessionStart and UserPromptSubmit hooks.

**Scope:** The two Codex hook entry points and their existing caller-surface tests: tests/test_agent_relay_hooks.py, tests/test_codex_integration.py, tests/test_codex_wake.py, tests/test_hook_deadline_safety.py, tests/test_relay_redelivery_envelope.py, tests/test_role_history.py, tests/behavior_contracts/test_codex_busy_wake.py, and this Work Record. Carry these nine code/test files byte-for-byte from the reviewed repair; leave the historical Work Record unchanged.

**Constraints:** Preserve the eight-second process limit and host/emission/ACK reserves, hook-owned claim/emission/ACK, scope provenance, one combined capture request, capture metadata and idempotency. Do not cancel or replay capture to obtain enrichment. Keep optional enrichment inside its cutoff and drain only the same worker within remaining safe time. Do not extend deadlines, weaken assertions, rewrite history, change installed files/settings, or claim that pre-Python launch time or historical physical stalls are fixed.

**Completion criteria:** Copy the exact reviewed payload, verify its hashes and caller-surface coverage, preserve real installed lost-response/ACK/scope-move/restart evidence and its limits, pass required current-head CI and independent result review before any merge decision. A native notification lost before hook entry remains a separate unqualified boundary.

**Requirement baseline:** {"source":"task-owner-approved-codex-hook-repair","outcome":"Codex hooks preserve prompt capture and emit available Relay and scope context within the existing process budget when optional enrichment is slow or fails.","scope":"The two Codex hook entry points and their existing caller-surface tests: tests/test_agent_relay_hooks.py, tests/test_codex_integration.py, tests/test_codex_wake.py, tests/test_hook_deadline_safety.py, tests/test_relay_redelivery_envelope.py, tests/test_role_history.py, tests/behavior_contracts/test_codex_busy_wake.py, and this Work Record. Carry these nine code/test files byte-for-byte from the reviewed repair; leave the historical Work Record unchanged.","constraints":"Preserve the eight-second process limit and host/emission/ACK reserves, hook-owned claim/emission/ACK, scope provenance, one combined capture request, capture metadata and idempotency. Do not cancel or replay capture to obtain enrichment. Keep optional enrichment inside its cutoff and drain only the same worker within remaining safe time. Do not extend deadlines, weaken assertions, rewrite history, change installed files/settings, or claim that pre-Python launch time or historical physical stalls are fixed.","completion_criteria":"Copy the exact reviewed payload, verify its hashes and caller-surface coverage, preserve real installed lost-response/ACK/scope-move/restart evidence and its limits, pass required current-head CI and independent result review before any merge decision. A native notification lost before hook entry remains a separate unqualified boundary."}

**Behavior changes:** [{"target":"repository-contract","path":"tests/behavior_contracts/test_codex_busy_wake.py","classification":"equivalent","before":"Each simulated hook invocation exercises the existing busy, single-flight and competing-claim requirements.","after":"Each simulated hook invocation resets its import-time origin to model a fresh process while exercising the same busy, single-flight and competing-claim requirements.","reason":"The production origin now includes import time. Repeated in-process fixtures must model separate process starts; all behavior assertions remain unchanged."}]

**Risk:** High

**Complexity:** Moderate

**Reason:** Hook scope, capture persistence, deadline handling and delivery acknowledgment affect identity and durable user data despite a bounded integration change.

**Discovery:** The synchronous combined capture/enrichment request can consume the scope-emission reserve. The reviewed repair issues that same request once in a bounded worker, accepts enrichment only before its cutoff, emits context once, and drains the same worker within remaining time. Both entry points count import time; SessionStart optional fallback retrieval keeps the emission reserve. This does not account for startup before Python entry.

**Material assumptions:** The nine payload files remain identical to the reviewed repair. Existing source, test and installed evidence is reused only for matching content; failed or missing evidence remains explicit. New task provenance does not remediate the historical record or authorize changing its protected fields.

**Plan:** Commit this valid initial Work Record and obtain independent plan review before copying source. Carry the exact nine reviewed files from the preserved repair revision, with no historical-record edit or consumer-harness update. Reuse valid review and test evidence, run the whole-change selector and required affected/current-head checks, then publish a replacement draft. Link the old PR as superseded only after the replacement exists.

**Verification plan:** Byte identity for all nine files and installed hook hashes; relevant hook lifecycle, deadline, capture and scope tests, including tests/behavior_contracts/test_codex_busy_wake.py through configured verification identifier test in the existing PR job; whole-change selector and required full validation with evidence reuse scoped honestly; Redline and history-aware workflow checks; required Linux/Windows CI. Actual native proofs cover original and later-message receipts after loaded/unloaded claim loss, scope movement, an ACK request suppressed before commit and service restart, without manual receive/ACK/resend. Post-commit ACK-response loss was not qualified. Keep simulated, native and historical evidence separate.

**Plan review:** Agent technical review: independent non-implementer recovery_diagnostics_review confirmed PLAN GO at 8f74a48f5081c8035689814158f4b1bf140aca69 for the exact nine-file carry from 2d71b117. Preserve all capture/deadline requirements, equivalent fresh-process fixtures, evidence provenance and open qualification boundaries. No historical-record, consumer-harness or installed-file edit is planned.

**Approvals:** Approved by user 2026-10-29: "yes, i approve, and no need to ask every time - i approve all the work to get this bug fixed". The coordinator agreed to the fresh replacement draft with a new privacy-safe record. No merge, installation, history rewrite, requirement weakening or unrelated environment change is authorized by that coordination instruction.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Evidence carried forward

The prior repair's source reviews, focused hook controls and native receipts remain available privately. The reviewed nine-file payload is now carried byte-for-byte from 2d71b117; both hook hashes also match the previously approved installed payload. Git checkout initially normalized one fixture's line endings; an exact file copy restored byte identity, and every Git blob and raw hash was verified. The historical record remains unchanged. A fresh required full serial run is underway with isolated temporary storage and retained output. This record does not assert a passing full run.

Earlier remote validation was not green: both Python jobs failed an aged in-process busy-wake fixture, and Windows smoke failed its cached startup-origin expectation. The carried fixture corrections model fresh hook processes without weakening assertions; a local 25-case run passed, but does not replace full validation. Earlier targeted artifacts cover 534 unique nodes without a complete source-byte manifest. They are supporting evidence, not proof of this fresh payload's whole-suite result. The unrelated PR #377 full run does not qualify these changed hooks. Historical physical stalls, startup before Python entry and notification loss before hook entry remain unresolved.
