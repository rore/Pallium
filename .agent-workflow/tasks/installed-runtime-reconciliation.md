# Installed runtime source reconciliation

<!-- agent-workflow:start -->
**Outcome:** Reconcile the genuine deployed runtime fixes into current main, preserving current main behavior and every deployed fix, so a separately authorized installed update can later use clean main without losing those fixes.

**Target:** Current-main runtime source reconciliation.

**Scope:** Isolated source reconciliation of runtime hunks in the preserved deployed snapshot, their necessary existing caller-facing tests and this Work Record. Map each hunk to already-main behavior, an existing relevant PR or a genuine remaining delta; compose only the needed delta on the main revision that includes the merged OpenCode fix. Package skills, private roadmaps, governance/reporting drift and unrelated reliability work are excluded.

**Constraints:** Never alter the installed tree or its preserved source. No installed changes, source-copy hotfix, service/host restart, installs, local tests/setup, repository/application imports, live data/database reads, config/model/effort/cwd changes, new worker/guardian/framework or manual helper dispatch. Preserve the paused CI checkout and its three uncommitted files without edits/commit/push. Preserve maintained/imported skill drift and scripts/agent-redline-report.py separately. Do not overwrite other PR branches, duplicate patches blindly, silently discard questionable changes or treat unrelated PR failures as gates. Keep private paths, identities, session pointers and operational evidence out of public artifacts. Manager owns architect handoff, result review, main merge and separately authorized activation; source and test execution use existing review/publication/ordinary-CI gates.

**Completion criteria:** Every runtime hunk has an exact main/PR/remaining-delta disposition. The source candidate preserves newer main filtering/batching/payload budgets, trace-writer lifecycle and deployed managed-expiry/retention/vector/diagnostic fixes, including the complete cleaner/supervisor/CLI/restart wiring. Caller-facing coverage and source-matched reused evidence are identified; necessary independent review and actual focused/ordinary-CI results precede merge. Obsolete/unsafe/questionable hunks have explicit owner disposition, not silent deletion. No installed activation or full-source preservation loss is claimed from source work.

**Requirement baseline:** {"source":"manager priority assignment for the direct human deployed-runtime reconciliation task","outcome":"Reconcile the genuine deployed runtime fixes into current main, preserving current main behavior and every deployed fix, so a separately authorized installed update can later use clean main without losing those fixes.","scope":"Isolated source reconciliation of runtime hunks in the preserved deployed snapshot, their necessary existing caller-facing tests and this Work Record. Map each hunk to already-main behavior, an existing relevant PR or a genuine remaining delta; compose only the needed delta on the main revision that includes the merged OpenCode fix. Package skills, private roadmaps, governance/reporting drift and unrelated reliability work are excluded.","constraints":"Never alter the installed tree or its preserved source. No installed changes, source-copy hotfix, service/host restart, installs, local tests/setup, repository/application imports, live data/database reads, config/model/effort/cwd changes, new worker/guardian/framework or manual helper dispatch. Preserve the paused CI checkout and its three uncommitted files without edits/commit/push. Preserve maintained/imported skill drift and scripts/agent-redline-report.py separately. Do not overwrite other PR branches, duplicate patches blindly, silently discard questionable changes or treat unrelated PR failures as gates. Keep private paths, identities, session pointers and operational evidence out of public artifacts. Manager owns architect handoff, result review, main merge and separately authorized activation; source and test execution use existing review/publication/ordinary-CI gates.","completion_criteria":"Every runtime hunk has an exact main/PR/remaining-delta disposition. The source candidate preserves newer main filtering/batching/payload budgets, trace-writer lifecycle and deployed managed-expiry/retention/vector/diagnostic fixes, including the complete cleaner/supervisor/CLI/restart wiring. Caller-facing coverage and source-matched reused evidence are identified; necessary independent review and actual focused/ordinary-CI results precede merge. Obsolete/unsafe/questionable hunks have explicit owner disposition, not silent deletion. No installed activation or full-source preservation loss is claimed from source work."}

**Behavior changes:** []

**Relationships:** {"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** High

**Complexity:** Large

**Reason:** The intended scope includes persisted Relay delivery/expiry lifecycle in storage/sqlite_relay.py (persistence-review), API diagnostics (api-review), runtime lifecycle and several distinct deployed fix groups. The persistence/contract surfaces require High risk; no boundary or governance relaxation is proposed.

**Discovery:** Existing independent architect source assessment identifies two substantive composition points: storage/sqlite_relay.py and app/main.py. Several Codex/queue hunks are already upstream despite whole-file differences. Managed expiry must remain a complete storage/cleaner/supervisor/CLI/restart group. The preserved source has no schema-definition delta according to that assessment; no live database is inspected.

**Material assumptions:** The preserved source snapshot is authoritative for deployed changes and was freshly byte-matched by the manager. Disposition is hunk-level, not inferred from whole-file hashes. Runtime edits wait only for applicable exact review/approval coverage; source comparison and isolated preparation continue. Existing source reviews/evidence are reusable only where exact correspondence is established. Installed activation is not authorized.

**Plan:** First implementation step: invoke the /agent-workflow skill to create this Work Record and classify risk before any code edit (completed through the documented native-host fallback). Start from the supplied main revision; inventory every runtime hunk against installed base/current main/relevant PR heads, preserve non-runtime drift separately, trace both composition definitions and all callers, then prepare the smallest coherent source delta with existing/new focused contracts. Reuse the standing architect assessment; manager routes only new concrete composition/review decisions. Run no local application/test code; obtain actual tests through authorized ordinary CI after applicable publication gates.

**Verification plan:** Source identities and paused-CI byte fingerprints; complete runtime hunk/PR correspondence and no-loss coverage; AST/static checks only locally. Identify original tests/source-matched evidence for managed expiry, trace startup/failure cleanup, retention/FTS snapshots, vector save locking and retained diagnostics. Existing ordinary CI supplies actual focused tests and the selected full non-slow lane when required; no unrelated failure or helper qualification is a prerequisite. Recheck all accepted source bytes and public disclosures before any publication.

**Plan review:** Agent technical review: standing architect TECHNICAL PLAN GO for the conservative source-reconciliation approach, reviewed record/head 890b606d1acc72ea583dc6b170970ae63637230a over main d7ecc2b2b89624ef8444934e0332f930b9894f84. Existing source comparison is reused, with explicit six-call expiry mapping and combined trace/expiry initialization/cleanup decisions below. No remaining generic architecture or human-scope blocker. Independent implementation-result acceptance and publication gates remain separate.

**Approvals:** Approved by user 2026-11-12: "that's top priority". Genuine context, relayed and adopted by the manager: the human had been presented identifying/preserving deployed local fixes, reconciling them into main with focused review/verification, then updating the installed service WITHOUT losing fixes. This consent covers the conservative source approach; it is not a fabricated yes/approve response, an agent substitution or a waiver. It does not authorize removing fixes, materially new behavior, migrations or any installed/live operation. Manager releases source implementation; result review/publication/main merge and separately authorized activation retain their existing owners and gates.

**Exceptions:** —

**State:** Ready to implement

<!-- agent-workflow:end -->

## Ownership and starting evidence

Branch `fix/installed-runtime-reconciliation` starts at main `d7ecc2b2b89624ef8444934e0332f930b9894f84`, including the merged OpenCode fix. The preserved deployed source base is `9d01176483d7a353d1f88de7830a31e409c5959b`. The prior CI source assignment is paused unchanged and is not a prerequisite. Exact private preservation/archive/pause provenance is retained outside versioned artifacts. No canonical tracker source tuple was supplied; do not invent one.

## Implementation checkpoint

Agent Workflow, configuration, expanded template and risk/plan-review rules were read before this record and before any runtime/test code edit. The isolated checkout was created from the supplied main. Initial broad tracked-diff status timed out; it is not evidence of cleanliness or a runtime failure. This was the historical discovery-only checkpoint, before the now-recorded source implementation release. The prior missing-approval wording is superseded by genuine consent and independent technical PLAN GO above; State now permits source implementation.

Intended runtime source paths (subject to hunk disposition, not a blind-copy allowlist):

- `api/routes.py`
- `app/cli/service.py`
- `app/cli/setup_codex.py`
- `app/codex_bridge_pipe.py`
- `app/codex_wake.py`
- `app/config.py`
- `app/dashboard.py`
- `app/main.py`
- `app/mcp/codex_desktop_bridge.py`
- `app/relay_expiry_cleaner.py`
- `app/run.py`
- `app/supervisor.py`
- `app/worker.py`
- `core/codex_wake.py`
- `core/errors.py`
- `integrations/codex/hooks/common.py`
- `integrations/codex/hooks/hooks.json`
- `integrations/codex/hooks/session_start.py`
- `integrations/codex/hooks/user_prompt_submit.py`
- `scripts/restart-service.ps1`
- `storage/sqlite.py`
- `storage/sqlite_queue.py`
- `storage/sqlite_relay.py`
- `storage/sqlite_retention.py`
- `storage/vector_index.py`

## First bounded source checkpoint

The frozen snapshot contains 34 original source files: 25 runtime paths and nine excluded package-skill/governance paths. All 129 runtime context hunks are retained in a private no-loss matrix with before/after spans and digests. Initial exact evidence identifies 19 already-main hunks, eight context hunks corresponding to existing PRs, 18 on the two known composition surfaces, and 84 still requiring semantic disposition; none of those unmatched hunks is called unique or discarded. A finer individual-edit comparison identifies five exact edit blocks from PR380 and eleven from PR381; these are different units from context hunks and are not added to the hunk totals. No exact installed edit-block correspondence was established for PR375/377; sharing a file is not treated as equivalence.

Exact current PR heads were read without checking out or changing their branches. Existing PR380 checkpoint/rollback and PR381 compact/vector source/test evidence were found; PR381 records the matching vector working-source digest and 138 focused passes, which remain a narrow reuse candidate pending dependency/context verification. New composed behavior is not qualified by that evidence. Main trace-lifecycle tests were located, including constructor, shutdown and route-construction failure cleanup. No tests, repository modules, services or data were executed/read.

Concrete next slice: preserve main claim filtering/batching/payload fitting while carrying checkpoint diagnostics at all six call sites, and compose managed-expiry initialization/factory forwarding into main trace-writer resource ownership. Keep the cleaner/supervisor/CLI/storage/restart group indivisible. The subsequent standing-architect technical PLAN GO and genuine human plan-consent evidence are now recorded above; no generic pre-edit approval blocker remains. Manager owns independent source-result review and publication release. Source implementation and unresolved-hunk disposition continue; no unrelated PR failure, CI helper qualification or installed activation is a gate.

## Governed source seam decisions

Expiry call mapping, before code edits: before acquisition -> `before_acquisition`; inside acquired transaction -> `after_acquisition`; post-flush/precommit -> `post_flush_precommit`; empty-response early return -> `pre_claim_mutation`; metadata-scan iteration guard -> `pre_claim_mutation`; final selected-delivery mutation guard -> `pre_claim_mutation`. All six main guards stay in their original execution positions, using the existing diagnostic stage vocabulary. Keep main runtime/session/container filtering, exact-trigger order, batching and payload fitting; add managed-expiry suppression and diagnostic observation around that logic, not the older query.

Combined ownership order: build storage/service, initialize the trace-owner slot before the common idempotent `close_resources`, enable managed expiry when explicitly supplied, then construct/use the trace writer under that same ownership. Any expiry-init failure closes resources already acquired and re-raises the original failure. Normal/failed lifecycle closes/drains trace work before service and storage disposal; duplicate close remains harmless. Production factory forwards the private expiry keyword only in supervised configured mode, preserving the default factory path. Retain cleaner/storage/supervisor/CLI/run/worker/restart wiring together.

Named checks: `test_impossible_turn_budget_preserves_expiry_rollback`, `test_claim_expiry_rolls_back_waits_mutation_and_early_returns`, `test_claim_supplied_expiry_during_metadata_scan_rolls_back`, `test_partial_app_construction_closes_trace_before_storage`, `test_app_trace_drains_before_storage_on_every_lifecycle_exit`, and `test_trace_constructor_failure_keeps_http_available`. Extend/reuse their assertions for the combined paths and add only missing managed-expiry failure/factory interactions. Existing source/evidence is not a pass on changed composition. New tests are authored before the corresponding source changes; no local execution is authorized.

Service-default compatibility composition: retain main's existing `prepare_codex_wake_start` under the held owner lock; its fresh-SQLite initialization already precedes supervisor maintenance validation. Forward the deployed managed-expiry flag for SQLite service configuration only, preserving main's non-SQLite service mode without applying SQLite-only validation to it. This retains existing behavior rather than adding bootstrap/migration work. Extend `test_fresh_service_run_initializes_under_existing_owner_lock_before_supervisor` for both backends.

First-slice handoff correction: the developer's final mutation warning identified an ambiguous-context patch that had not landed. The manager inspected the actual test file and original attempted patch, then applied the same authored invalid-schema, stop-before-open and failure-cleanup/privacy controls with unique context. No production code or accepted test assertion was changed by this correction. Static parsing and source review are separate from still-unrun test execution; this is not a claimed pass or completed reconciliation.

## First-slice independent source review

Agent technical review: the independent standing architect reviewed the corrected first managed-expiry/lifecycle source slice over `890b606d1acc72ea583dc6b170970ae63637230a` and main `d7ecc2b2b89624ef8444934e0332f930b9894f84`, including both new files in full. Source identity was verified before and after review. The verdict is **SOURCE HOLD**, not completed reconciliation, merge approval or installed acceptance.

Mandatory connected corrections:

- Carry the deployed connection-acquisition cleanup in `storage/sqlite_queue.py` used by the new maintenance window. If acquiring the connection fails, close the created session and preserve the original failure. Add the cleaner/window regression and unchanged-delivery-state readback.
- Exercise `run_supervisor` with the managed-cleaner flag using its existing injectable seams: validation-before-spawn, cleaner startup failure/immediate exit, API failure/cancellation cleanup, restart environment preservation/clearing, and cleaner restart-budget exhaustion.
- Add continuous cleaner recovery/retry-budget controls and the delivery-state interactions: claimed expiry rejects the old receipt; acknowledged and durable deliveries remain unchanged. Preserve cursor, closure and sanitized logging behavior.

The review accepted the six expiry-guard positions/labels, preservation of main's claim algorithm, combined initialization and trace-before-storage ownership, existing-file-only validation and the corrected error-path test tail. It identified no new public disclosure in this slice. It did not qualify the still-unimplemented runtime groups or claim any test execution.

Verification adequacy: AST/static source checks are useful but insufficient for runtime acceptance. A genuine import-linter run on the candidate reported no boundary violations; the whole-change selector requires the full non-slow lane. Local tests remain unrun. The reviewer explicitly permits an **incomplete, findings-recorded DRAFT for ordinary CI** after metadata gates; meaningful test-first RED is allowed and GREEN is not a prerequisite to that draft. The findings must be corrected and the candidate independently reviewed and actually tested before merge. Separate human result review and separately authorized live activation remain outstanding.
