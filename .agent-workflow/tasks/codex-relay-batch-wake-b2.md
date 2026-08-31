<!-- agent-workflow:start -->
**Outcome:** Codex Relay can passively claim and publish bounded whole batches through one regular-turn/hook and MCP-recovery ownership path, while wake remains disabled until G2/G3 evidence.

**Target:** Pallium Relay milestone 1, B2 passive batch delivery.

**Scope:** Implementation and disposable-environment verification of complete-batch FIFO/budgets, claim generation/publication fencing and uncertain lifecycle, hook/MCP recovery parity, protocol capability/scope/deduplication corrections, and deterministic HTTP/MCP/hook E2E/fault coverage. Intended guarded targets: `api/schemas.py`, `api/routes.py`, `core/relay.py`, `storage/sqlite_schema.py`, `storage/sqlite_relay.py`, `storage/relay_codec.py`, `app/mcp/client.py`, `app/mcp/server.py`, Codex integration guidance/hook path, and their focused tests.

**Constraints:** B1 foundation is accepted at `c3dd006`; do not reopen it. No guarded B2 edit before manager review. No C/Claude/OpenCode wake adapter, public multipart/keyed-MCP activation, startup migration, installer/service/configuration/live-DB action, deployment, app ping as a delivery mechanism, manual hook receive/ACK, raw Relay HTTP, or `uv.lock` change.

**Completion criteria:** Reviewed B2 candidate implementation and deterministic HTTP/MCP/hook E2E cover whole-batch FIFO/budgets, publication ownership/fencing/uncertainty, capability/scope/dedupe and migration compatibility. Record exact activation order and outstanding G2/G3 evidence. Both new passive-batch and wake activation remain disabled pending qualification.

**Risk:** High

**Complexity:** Large

**Reason:** The intended scope includes red API contracts and persisted schema plus durable claim/publication lifecycle and runtime identity behavior. It spans storage, core, MCP, hook integration, and independently verifiable fault evidence.

**Discovery:** B1 is an unactivated persistence/codec/request foundation (`c3dd006`). The approved design `docs/designs/relay-batch-codex-wake.md` requires one FIFO whole-batch claim path shared by ordinary and notification turns and MCP recovery; publication starts are generation-fenced, incomplete admission is uncertain rather than replayed, and G2/G3 remain release evidence. The existing hook fixtures are historical and require replacement or explicit historical labelling when B2 changes the contract.

**Material assumptions:** (1) The current hook and explicit MCP recovery can share one storage-owned claim/admission contract; prove by symmetric integration E2E or stop for design review. (2) A claim generation can fence a stale publisher before output; prove by controlled claim replacement/fault tests or retain no automatic replay. (3) Full-envelope runtime admission evidence and actual context headroom are not currently proven; G2/G3 failure keeps wake disabled and capacity/passive status visible. (4) Pre-edit redline review has no boundary violation; any finding stops guarded edits.

**Plan:** (1) Obtain clean-context redline classification and manager review before guarded edits. (2) Define the smallest storage/core/API contract that selects complete FIFO batches up to existing design budgets, records claim generation/lease/final digest and length, and refuses stale publication. (3) Route hook and MCP recovery through that same claim/render/admit operation; natural-prompt dedupe cannot suppress inbox draining and the fast path emits current exact Pallium scope with the full attributed envelope. (4) Add capability/status fields and protocol-compatibility blocking without enabling public multipart/keyed-MCP or C queue dispatch. (5) Add HTTP/MCP/hook E2E for FIFO/budget boundaries, concurrent claim/recovery ordering, publication interruption/replacement, uncertain reconciliation, scope/dedupe, restart/expiry and compatibility failures. Stop if a change needs a second payload path, crosses API/storage boundaries, requires live migration. G2/G3 are activation gates, not blockers to deterministic implementation.

**Verification plan:** When a turn claims eligible batches, it shall select complete FIFO batches within the published 8-batch/16,384-code-point/65,536-byte budget without skipping the oldest fitting policy → disposable SQLite HTTP/MCP/hook E2E. When a claim is replaced or publication began without admission, stale output shall be rejected and the outcome remain uncertain rather than replayed → generation/fault-injection E2E. When hook and explicit recovery contend, exactly one owner shall render the same whole batch and current scope → paired hook/MCP race E2E. When a recipient is incompatible, over capacity, expired, or has invalid stored data, status shall expose the block without disclosure or partial delivery → HTTP/MCP lifecycle E2E. G2 requires installed full-envelope immutable context-commit plus stale-publisher evidence; G3 requires measured 64-delivery/context headroom. Neither deterministic test substitutes for either gate.

**Plan review:** Clean-context redline review (`/root/b2_redline`, 2026-08-31) classified the intended scope as MIXED → High: red API and schema surfaces require API and persistence review; gray guarded runtime/storage surfaces require architecture/runtime review; security review remains an explicit B gate. No inherent boundary violation was found. Manager approved bounded B2 implementation; see Manager plan review below for API/persistence/runtime/security constraints and activation gates.

**Approvals:** Approved by user 2026-08-31: "i approve everything the architect tells you to do". Manager B2 implementation approval is recorded below under that standing authorization; live activation remains prohibited.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-08-31: Created on `codex/relay-batch-wake-b2` from accepted B1 commit `c3dd006`. This is planning only. Next action is manager review of the clean-context classification and this bounded plan; no guarded B2 source, service, configuration, installer, or live database action has occurred.

## Plan review

- 2026-08-31 clean-context review (`/root/b2_redline`): **MIXED → High**. `api/schemas.py` and `api/routes.py` require API review; `storage/sqlite_schema.py` requires persistence review. `core/relay.py`, `storage/sqlite_relay.py`, `storage/relay_codec.py`, and MCP client/server are guarded gray surfaces. No boundary violation is inherent if API imports only core, storage never imports app/capabilities, and runtime adapter composition remains outside core. Architecture/runtime and security review remain explicit B gates. G2/G3 are qualification evidence, not approval substitutes.
## Manager plan review — 2026-08-31

Approved to implement B2 against disposable databases and integration fixtures,
under the existing user authorization and approved batch design. This is API,
persistence, architecture/runtime and security review of that execution scope;
it does not authorize deployment, installation or live probes. Retain the
clean-context High/no-boundary classification. B1 remains closed.

The following execution constraints resolve ambiguities in the proposed plan:

1. G2/G3 are activation gates for the NEW PASSIVE BATCH PATH as well as wake.
   Missing runtime evidence is not a reason to stop deterministic implementation;
   it is a reason not to activate or describe it as durable delivery. Existing
   supported legacy traffic must remain usable. Do not enable public multipart,
   keyed MCP, new runtime registration or migration implicitly during startup.
2. Use one generation-bound owner for regular turns, notification turns and MCP
   recovery. Claim whole FIFO batches; no partial batch on budget exhaustion.
   Count the final attributed, escaped envelope and current scope in both byte
   and code-point budgets. Test oldest-too-large, backlog arrivals and explicit
   blocked reasons; do not hide accepted pending work behind empty counts.
3. Publication-start is a transactional ownership transition before any output.
   Only a never-published expired generation can be replaced automatically.
   Once publication may have started, missing confirmation means uncertain.
   A stale pre-publication owner cannot publish; an already-started late publisher
   cannot be assumed stopped. Never reset uncertain to pending merely on timeout.
   Keep database transactions out of stdout, network and model execution.
4. Specify claim, publication and admission request/response fields in the
   implementation checkpoint: scope, runtime-owned recipient, delivery/generation,
   complete-envelope digest and lengths, private proof and public status.
   Private publication authority must not enter model-visible envelopes/logs.
   Existing receipt ACK must not be relabelled durable hook-admission evidence.
   Wrong scope/identity/generation/digest must reject without exposing content.
5. G2 evidence is full attributed envelope plus ordered parts and terminal marker,
   bound to the actual attempt in exact-session runtime history or an equivalent
   verified context-commit event. Positive readback can establish admission;
   absent history cannot prove non-admission. Use fixtures for deterministic
   tests and provide a separate controlled qualification recipe; no live action
   is authorized now. Expiry/clock ambiguity stays explicit.
6. Capability negotiation is fail-closed across old/new hook, MCP, API and schema
   combinations. Legacy clients never see raw parts JSON or new states they
   cannot interpret. Fixtures may explicitly activate the candidate path; default
   startup must not expose it. All schema changes use explicit reviewed migration,
   not incompatible ORM initialization side effects. No service-role framework.
7. Preserve known fixes: drain inbox independently of prompt-ingestion dedupe;
   include fresh current scope on fast-path emission; no simultaneous hook/MCP
   manual receive; no per-part ACK. Test send/reply/retry/cleanup on this same path.
   Public docs/skill/schema changes stay consistent with what is actually enabled.
8. Stage work as complete contract plus tests, then hook/MCP parity and fault
   matrix.Send one consolidated code review when deterministic B2 coverage is
   complete; progress reports do not block continuation. Stop for a concrete
   contract contradiction, second payload path, unsafe live dependency or scope
   expansion. Do not send periodic approval requests for unchanged design.

Completion for this implementation slice means reviewed candidate code and
deterministic HTTP/MCP/hook E2E, not installed success. Report outstanding G2/G3,
migration repair, integration rollout and activation gates explicitly.
No C notification coordinator or Claude/OpenCode wake is in scope.

- 2026-08-31: Manager approval received through hook delivery `relay-delivery-f350f61a2d7c4327908a36cca9f8f871`. Implementation starts from `85ded92`. Planned files before the first code edit: `core/relay.py`, `storage/sqlite_relay.py`, `storage/sqlite_schema.py`, `api/schemas.py`, `api/routes.py`, `app/mcp/client.py`, `app/mcp/server.py`, `app/cli/setup_codex.py`, Relay guidance, and focused Relay HTTP/MCP/hook E2E tests. The candidate is explicitly fixture-only; default legacy turn delivery stays unchanged and G2/G3 keep passive batch activation disabled.- 2026-08-31: Implemented the unactivated B2 candidate behind an explicit service fixture opt-in plus uncalled `migrate_relay_batch_claims`; legacy ORM models and default routes remain unchanged. Candidate state is isolated in `relay_batch_claims`, preserving old-schema reads. One FIFO claim path records generation and scope-bearing envelope digest/length, requires a pre-output publication fence, rejects stale publication, and turns unconfirmed published lease expiry into visible `uncertain` rather than replay. Codex hook and MCP recovery invoke that same fence; candidate hook output never auto-ACKs. Prompt dedupe now runs after the Relay drain. Disposable proof: `tests/test_relay_b2_candidate_e2e.py` 5 passed (four existing warnings); `tests/test_agent_relay_hooks.py tests/test_mcp_client.py` 40 passed. The initial wider hook run exposed the standalone-hook package-import failure under parallel pytest; tests now use the existing file loader, so that path is exercised without altering integration packaging.
- 2026-08-31: Final candidate review corrected active-lease FIFO handling: an earlier active claim now stops the batch rather than permitting a later message to bypass it. The protocol fields are explicit: exact scope (`container_ref`, runtime-owned `thread_ref`, `actor_ref`, `agent_ref`, private visibility), `delivery_id`, claim generation, terminal complete-envelope digest and code-point/byte lengths; the claim token remains private and never enters the envelope. Publication is a pre-output generation/digest/token fence; status exposes publication, `uncertain`, and `blocked` reasons without content. `migrate_relay_batch_claims` is explicit and uncalled; default service construction remains legacy-only. Evidence: `uv run pytest -q tests/test_agent_relay_hooks.py tests/test_relay_mcp_lifecycle.py tests/test_mcp_client.py tests/test_agent_relay_e2e.py tests/test_relay_b2_candidate_e2e.py` → 103 passed, 4 pre-existing Pydantic warnings; `uv run python -m py_compile` on all changed Python files and `git diff --check` passed. Workflow validation has no blocking findings; its only advisory is the historical parent-branch Work Record commit-order signal. Activation order remains: independent code review and full deterministic rerun; controlled G2 context-commit/stale-publisher qualification; measured G3 64-delivery headroom; then separate manager authorization for passive activation. Wake, migration rollout, and live service actions remain out of scope.
- 2026-08-31 correction pass: architect review reproduced five contract failures through disposable HTTP/hook probes—formatter rejected genuine newline envelopes; legacy entry points bypassed candidate ownership; publication/receipt paths accepted invalid pre-admission states; and uncertainty failed to hold FIFO. The singleton raw-payload envelope is therefore insufficient for the approved multipart contract. Correction scope remains within the existing B2 plan and targets `storage/sqlite_relay.py`, `storage/relay_codec.py`, `core/relay.py`, `api/routes.py`, `api/schemas.py`, `app/mcp/client.py`, Codex hook common/prompt path, and focused HTTP/MCP/hook E2E. The material assumption is revised: every entrypoint must apply the candidate lifecycle barrier once a delivery has B2 state, and the candidate envelope must render typed ordered parts safely; default legacy-only service behavior and all activation prohibitions remain unchanged.
- 2026-08-31 correction implementation: replaced the raw singleton candidate envelope with the existing canonical parts codec and an escaped, part-counted envelope; fixed candidate formatter newline/surrogate handling; and moved candidate ownership/expiry reconciliation into the storage boundary used by turns, status, publication, raw ACK, receipt ACK, and atomic reply. A B2-owned delivery is a legacy and candidate FIFO barrier. Publication requires a live unexpired generation; `relay_admit` is an explicit fixture-only full-envelope witness that marks delivery delivered. Receipt/raw ACK and reply reject unwitnessed candidates. Budget blocks remain pending with a durable reason so a later eligible budget can retry the same delivery. Multipart HTTP forms are accepted only by the disposable `batch_candidate_enabled` service; default Relay rejects them and no startup/live migration is introduced.

## E01–E18 correction disposition

- E01 — partial: exact-one-form API validation and six-part fixture send/reply are tested; full malformed/form matrix remains incomplete.
- E02 — implemented/tested for final envelope chars/bytes, newline/surrogate rejection and aggregate separator accounting; G3 64-backlog/context-headroom qualification remains a gate.
- E03 — partial: parts are quoted so markers cannot forge structure; cross-part redaction is codec-covered, but no dedicated B2 E2E secret matrix yet.
- E04 — partial: retryable SQLite busy and fresh-service restart recovery are tested; disk-full, concurrent same-key and alias-movement fault matrix remains incomplete.
- E05 — partial: scope/token/digest checks and stale generation rejection are tested; full alias/close/reopen matrix remains incomplete.
- E06 — partial: reply rejects unwitnessed and expired candidate claims and depth over four; sibling/retry matrix remains incomplete.
- E07 — implemented/tested: six-part HTTP → candidate claim → real hook formatter, plus MCP/hook focused suite; contention race expansion remains incomplete.
- E08 — implemented/tested in fixtures: publication fence, stale generation, expiry, uncertainty and admission witness; actual full-envelope runtime readback is G2.
- E09 — qualification-only: no wake implementation is authorized.
- E10 — partial: FIFO active/uncertain/budget barriers and backlog arrival are tested; broader starvation/concurrent-final-ACK matrix remains incomplete.
- E11 — partial: fresh-service restart preserves unpublished reclaim and published uncertainty; clock-skew and full outstanding-window matrix remains incomplete.
- E12 — partial: before/publication expiry, uncertainty, wrong evidence and matching late positive evidence are tested; safe negative evidence and full clock timing remain incomplete.
- E13 — partial: fixture-only protocol capability, mixed-fan-out rejection and per-recipient 64-pending capacity are tested; independent recipient completion remains incomplete.
- E14 — qualification-only: wake capability remains disabled.
- E15 — partial: bounded parts, depth, capacity, visible budget/invalid states and orphan claim cleanup are enforced; burst/rate matrix remains incomplete.
- E16 — partial: default legacy behavior after explicit B2 migration is tested; installer upgrade/downgrade is out of scope.
- E17 — partial: fixture envelope declares part count and terminal marker; agent-only usability run remains incomplete.
- E18 — qualification-only: no live architect/developer or wake exchange is authorized.
- 2026-08-31 verification after correction: independent focused run `uv run pytest -q tests/test_relay_b2_candidate_e2e.py tests/test_agent_relay_hooks.py tests/test_mcp_client.py tests/test_relay_mcp_lifecycle.py tests/test_agent_relay_e2e.py` → **108 passed**, four existing `IncompleteFieldDefinitionWarning` warnings.`uv run python -m py_compile` passed for the changed B2 storage/core/API/hook/test surfaces and `git diff --check` is clean. This proves deterministic fixture behavior only; the E01–E18 matrix above retains G2/G3 and incomplete scenarios explicitly.
- 2026-08-31 Relay usability follow-up (discovered while returning the consolidated checkpoint): `pallium_relay_reply` surfaced a raw HTTP 422 when a valid review report exceeded the service's 1,500-character legacy singleton payload limit. This is not a B2 lifecycle change and is not fixed in this High-risk correction pass. Follow-up task: make Relay reply tooling preflight the codec/render limit and return a clear local actionable error (or, after separate review, support explicit multipart reply submission) without silently truncating or retrying.
Manager correction review (b3c592d/80d815d): 108 focused tests independently pass,
but disposable HTTP probes reproduce pre-claim legacy multipart exposure,
non-idempotent/unreconcilable admission, acceptance of permanently oversized
batches, payload-format retry collision and over-budget MCP projection.
See docs/designs/relay-batch-b2-candidate-review.md, correction-review section.
Continue already-approved deterministic implementation/regressions; B2 is not
accepted and G2/G3/live activation remain gated. No new plan approval is needed.

- 2026-08-31 second correction pass: architect review `7746585` reproduced five remaining deterministic B2 failures in the approved scope: pre-claim legacy parts exposure, non-idempotent/unreconcilable admission, accepted permanently oversized escaped batches, payload-format-blind retry matching, and duplicate MCP payload/envelope projection. Planned corrections stay within `storage/sqlite_relay.py`, `core/relay.py`, `app/mcp/client.py`/server projection if needed, Codex hook accounting, and focused HTTP/MCP/hook E2E. No new runtime authority, live migration, activation, wake, or B1 reopening is needed. The revised assumption is that payload format and final rendered envelope are immutable canonical inputs at every acceptance/read/retry boundary, while fixture evidence remains distinct from G2.
- 2026-08-31 second correction verification: pre-claim legacy parts are blocked and status projects decoded content; payload format participates in request-key and message-ID comparisons; multipart acceptance preflights the final escaped per-recipient envelope; matching admission callbacks are idempotent and resolve a published uncertain delivery without replay; MCP candidate receive retains only the final envelope. Independent focused suite `tests/test_relay_b2_candidate_e2e.py tests/test_agent_relay_hooks.py tests/test_mcp_client.py tests/test_relay_mcp_lifecycle.py tests/test_agent_relay_e2e.py` → **112 passed**, four existing Pydantic warnings.Syntax and whitespace checks pass. E02 is now fixture-implemented for permanently impossible escaped-envelope rejection and MCP de-duplication; E05 includes pre-claim legacy format blocking and format-aware retry conflicts; E08 includes matching admission retry and late-positive fixture reconciliation. These remain deterministic fixture evidence, not G2/G3 qualification. The broader E01/E03–E18 incompletes listed above remain honest outstanding work.
- 2026-08-31: Second correction review 94bef4e reopens implementation under existing authorization. In progress: one shared candidate acceptance validator for send/reply; safe status/read and truthful FIFO-barrier projections; actual hook/MCP final-output budgeting and witnessed receipt lifecycle; deterministic capability/fan-out, reconciliation timing, restart/crash/contention, capacity/depth/cleanup matrix.No activation, live migration, runtime registration, or wake work is authorized.

- 2026-08-31: Ongoing 94bef4e correction implementation: send and atomic reply now share final rendered candidate acceptance; every status/read projection decodes parts safely and legacy barriers report remaining backlog; candidate fixture turns register only an explicit B2 capability record, and candidate acceptance fails atomically for incompatible mixed fan-out, recipient budget, 64 nonterminal-delivery capacity, or reply depth over four. MCP reserves and verifies final JSON before publication, returns an envelope-only candidate projection, and server guards the serialized bound. Focused independent verification: 117 passed, 4 existing Pydantic warnings.Candidate remains fixture-only and this is not final B2 acceptance; restart/crash/contention, cleanup/retry-window, full actual MCP witness-to-ACK/reply, and G2/G3 remain in the recorded deterministic/qualification matrix.

- 2026-08-31: Real disposable MCP lifecycle regression now uses httpx.ASGITransport against the fixture app: max_chars=1000 yields a bounded no-publication result when the complete envelope cannot fit; a separate fitting receive renders the complete envelope, a private fixture status observation supplies the witness token, admission succeeds, and receipt-based atomic reply succeeds without exposing that token in MCP output. Independent focused suite: 118 passed, 4 existing Pydantic warnings.

- 2026-08-31: Relayarch continuation received through normal hook delivery. Resuming remaining deterministic B2 work: restart/reclaim and post-publication reconciliation windows, busy contention, retention cleanup/tombstone behavior, and bounded HTTP/MCP/hook edge cases. Current discovery: retention cleanup removes deliveries/messages but not their B2 claim side-table rows; the storage cleanup boundary is the smallest safe fix.

- 2026-08-31: Deterministic lifecycle matrix expanded and independently verified: fresh candidate service instances reclaim an unpublished expired generation while retaining a published expiry as uncertain; candidate busy transactions surface the existing retryable 503 contract; retention cleanup removes orphaned B2 claim rows only after delivery cleanup; wrong admission digest leaves the claim unchanged, and matching late positive evidence after publication expiry resolves it to delivered. Focused suite: 121 passed, 4 existing Pydantic warnings.

- 2026-08-31: Candidate contention coverage added: two simultaneous disposable HTTP turns against the same recipient produce exactly one generation-one delivery and leave truthful backlog on the competing turn. Focused suite: 122 passed, 4 existing Pydantic warnings.

- 2026-08-31 supplemental correction evidence: expired unexposed candidate rows are reconciled before the 64-delivery admission count; a first MCP or hook publication refusal stops its FIFO suffix; retention preserves published/unadmitted uncertain rows; and cleanup remains compatible with B1-only databases. Candidate admission now records an observable `admitted_at` observation plus `admission_timing` (`before_expiry` or `after_expiry`); a wrong digest leaves it unset, while a verified late witness is explicit. File-backed provider disposal/reopen reclaims an unpublished expired generation, and a separate provider holding `BEGIN IMMEDIATE` produces the retryable busy contract. The B2-only depth limit no longer changes legacy reply chains. The established legacy MCP `max_chars=0` drain-all behavior is intentionally unchanged; B2 remains fixture-only, so no activation-facing MCP ceiling change is made. Independent focused verification: `uv run pytest -q tests/test_relay_b2_candidate_e2e.py tests/test_agent_relay_hooks.py tests/test_mcp_client.py tests/test_relay_mcp_lifecycle.py tests/test_agent_relay_e2e.py` → **128 passed**, 4 existing `IncompleteFieldDefinitionWarning` warnings. Candidate remains unactivated; G2/G3, activation, migration rollout, wake, and live service actions remain out of scope.
- 2026-08-31 architect semantic correction received through recovered Relay delivery `relay-delivery-09404aa63c4c4b40aac7c1d027c661c6` and ACKed. The prior admission timing inferred actual admission from witness observation time. Within approved E12 scope, observed time is separate from optional proven admission time; no proof produces `unknown`, proof is bounded by the publication attempt, and retries cannot rewrite evidence. No activation, live migration, wake, or service action.

Manager closure review of df894c7: runnable acceptance tests in tests/test_relay_b2_architect_acceptance.py reproduce three remaining failures (maximum accepted MCP no-progress, negative callback retry, expiry after proven non-admission). Ordinary six-part control passes; eight-part control added. These are intentionally red, not accepted implementation. Continue existing scope; no live activation. See candidate review document.
