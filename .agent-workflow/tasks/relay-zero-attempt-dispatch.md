<!-- agent-workflow:start -->
**Outcome:** Determine why a Relay delivery could remain pending with zero attempts and no activation trace while its recipient appeared idle, and correct any Pallium-owned scheduling defect without unsafe native retries.

**Target:** Pallium Relay.

**Scope:** Relay activation scheduling, durable Codex wake reservations, exact delivery trace/status behavior, focused tests, and roadmap alignment if the reliability claim changes.

**Constraints:** Preserve busy-turn safety, reservation idempotence, delivery/session/container identity, TTL, claim/ACK semantics, recipient scope, model and effort; never infer native admission or retry an uncertain native submission.

**Completion criteria:** The zero-attempt/no-trace path has an evidence-backed root cause; if Pallium-owned, the shared path is fixed with caller-surface regression coverage proving no duplicate native submissions, while external ambiguity is recorded precisely if no safe internal fix exists.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Pre-edit redline classification is GRAY because intended production paths are watched runtime/core/storage surfaces. Moderate complexity reflects uncertainty across scheduling, durable reservations, and evidence projection.

**Discovery:** The exact pending delivery matches the session, container, and endpoint of retained uncertain delivery `relay-delivery-5c6de3ac9d1e4a698690f4fc3834da38`. Its version-2 durable reservation remains `uncertain`; the original bounded trace still contains one exact prepared/completed attempt. `schedule_codex_relay_wake` retains the fence but can emit `associated` only from a process-local attempt map, which is empty after restart, leaving the later delivery at attempts=0 with no trace. Existing tests cover in-process association and duplicate-wake prevention, not restart-loaded association.

**Material assumptions:** Bounded trace is diagnostic and may be missing; durable association is emitted only when the retained reservation and new delivery have the exact same endpoint, session, and container and a direct prior attempt event is available. Missing, conflicting, or legacy evidence preserves the current unknown state. Any need to change API, schema/codec, core service/routing, security, or governance returns this task to planning and reclassification.

**Plan:** Add one bounded helper in `app/codex_wake.py` for the restart-only fallback. It may return an attempt ID only when the retained reservation outcome is `uncertain`; the old and new endpoint/session/container match exactly; the retained delivery snapshot matches the reservation; trace is current, complete, unpaginated, unpruned, untruncated, and non-legacy; and the latest direct completed attempt has a matching direct prepared event, outcome `uncertain`, and `native_retry_safe=false`. Reuse that ID only to emit `associated`; preserve the in-memory fast path and never release, replace, or retry the reservation. Add an HTTP caller-surface restart regression plus bounded negative cases for scope mismatch, missing/legacy/gapped/paginated/conflicting evidence, accepted/reserved outcomes, and retry-safe evidence. Update the Relay roadmap claim. Stop and re-plan if exact linkage requires schema or API changes.

**Verification plan:** When a retained uncertain fence survives restart, a later exact-scope delivery shall remain pending with attempts=0, perform no second native submission, and expose the shared uncertain outcome through HTTP trace → focused end-to-end regression. Scope mismatch; missing, legacy, gapped, paginated, pruned, truncated, or conflicting evidence; accepted/reserved outcomes; and retry-safe completion shall emit no association and no native submission → parameterized unit regression. Existing busy-sweep and trace projection regressions shall remain green → affected test files. Final diff shall pass workflow/redline/import checks and `tests/ -x -q` before review.

**Plan review:** Clean-context review `/root/plan_review_trace_link`; initial plan blocked, strict uncertain-only identity/evidence rules incorporated below.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

Authoritative request source: `ff5d1534-0191-47f6-b586-95dd3c980476`.

## Implementation

- Work Record initialized before code inspection or edits. Pre-edit redline verdict: GRAY; no required checkpoint and no boundary risk in the intended scope.
- Discovery established a post-restart diagnostic-linkage gap, not a safe-retry opportunity: the exact durable uncertain fence matches the later delivery scope, while only the process-local attempt map was lost.
- Clean-context code-path review: `/root/trace_zero_attempt_path`; independent incident inspection: `/root/inspect_incident_state` (its runtime-DB uncertainty was resolved by the exact durable reservation file plus installed trace surface).
- Implemented an uncertain-only restart fallback in `app/codex_wake.py`. Review found the delegated first HTTP test did not recreate registry/process state and the matcher lacked strict runtime/direct-event checks; both were corrected before acceptance.
- Added one real HTTP restart regression and parameterized fail-closed evidence cases in `tests/test_codex_wake.py`; no retry, reservation, delivery, scope, model, or effort behavior changed.

## Evidence

- Strict helper and HTTP restart nodes: `uv run --all-extras python -m pytest tests/test_codex_wake.py::test_restart_trace_association_rejects_ambiguous_evidence tests/test_codex_wake.py::test_restart_trace_association_is_http_visible_without_second_native_submission -q -n 0` → `22 passed`.
- Full Codex wake file: `uv run --all-extras python -m pytest tests/test_codex_wake.py -q -n 0` → `109 passed in 27.97s`.
- `apply_patch` failed with Windows `CreateProcessWithLogonW failed: 1327`; the permitted deterministic narrow fallback was used. Repository formatter `ruff` was unavailable; `git diff --check` is clean.

## Result review

- Pending independent result review after affected and full-suite verification.
## Plan review

Clean-context reviewer `/root/plan_review_trace_link` blocked generic latest-attempt lookup because shared trace rows and absent scope generation could misassociate an older or cross-scope attempt. The revised plan limits fallback linkage to exact-scope retained `uncertain` reservations with complete direct prepared/completed evidence and `native_retry_safe=false`. All ambiguity fails closed: no association, no retry, and no fence mutation. No blocking finding remains after incorporating those constraints.