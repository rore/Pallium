<!-- agent-workflow:start -->
**Outcome:** Codex setup replaces Pallium's MCP registration without duplicate tables and refuses invalid generated TOML before writing.

**Target:** Pallium Codex setup.

**Scope:** app/cli/setup_codex.py, its existing CLI setup tests, tests/test_cross_container_relay_e2e.py registration-only preparation, and this Work Record.

**Constraints:** Preserve unrelated TOML, extra string-valued Pallium env entries, and supported custom tool entries. Parse the complete candidate before writing; a parse/validation failure must leave the existing file unchanged. Atomicity after a filesystem write failure is outside this task. Do not touch live config, installed files, or services.

**Completion criteria:** Nested Pallium tables migrate without duplicate TOML; repeated install remains valid; invalid candidate TOML is rejected before the file is written; unrelated sibling tables are preserved; uninstall removes all Pallium child tables.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Codex setup updates Pallium's TOML tables without leaving duplicate tables or damaging the user's config.","scope":"app/cli/setup_codex.py, its existing CLI setup tests, and this Work Record.","constraints":"Preserve unrelated TOML and supported custom Pallium env/tool settings. Validate the complete candidate before writing. Do not touch live config, installed files, or services.","completion_criteria":"Nested Pallium tables migrate without duplicate TOML; repeated setup remains valid; an invalid candidate leaves the original file unchanged; neighboring config remains intact."}

**Behavior changes:**
[{"target":"task-context.outcome","classification":"equivalent","before":"Codex setup updates Pallium's TOML tables without leaving duplicate tables or damaging the user's config.","after":"Codex setup replaces Pallium's MCP registration without duplicate tables and refuses invalid generated TOML before writing.","reason":"Clarifies that the no-damage guarantee applies to invalid generated TOML rejected before write; atomic filesystem-write failure handling was not requested."},{"target":"task-context.constraints","classification":"equivalent","before":"Preserve unrelated TOML and supported custom Pallium env/tool settings. Validate the complete candidate before writing. Do not touch live config, installed files, or services.","after":"Preserve unrelated TOML, extra string-valued Pallium env entries, and supported custom tool entries. Parse the complete candidate before writing; a parse/validation failure must leave the existing file unchanged. Atomicity after a filesystem write failure is outside this task. Do not touch live config, installed files, or services.","reason":"Makes the explicitly requested pre-write validation guarantee precise without changing behavior."},{"target":"task-context.completion_criteria","classification":"coverage-only","before":"Nested Pallium tables migrate without duplicate TOML; repeated setup remains valid; an invalid candidate leaves the original file unchanged; neighboring config remains intact.","after":"Nested Pallium tables migrate without duplicate TOML; repeated install remains valid; invalid candidate TOML is rejected before the file is written; unrelated sibling tables are preserved; uninstall removes all Pallium child tables.","reason":"Adds the shared uninstall removal boundary and caller-visible pre-write validation to the focused verification."}]

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** `app/cli/setup_codex.py` is a gray runtime path that rewrites user configuration. The change must preserve unrelated settings and fail safely before writes.

**Discovery:** Original nested Pallium descendant tables and missing pre-write validation were fixed in child source e457b76. Retained continuation verifies that code unchanged except the reviewed private feature helpers. Controlled isolated lifecycle tests additionally reproduce parse-valid unrelated-data mutation when regex feature selection matches fake headers/keys inside multiline values; the same existing string tracker now protects actual feature boundaries and managed assignments. Current main4b9a54e9 merged cleanly; only the three intended PR paths differ.

**Material assumptions:** Python 3.12+ is required, so stdlib tomllib can parse and validate candidate TOML. It has no writer; preserve surrounding text and comments rather than round-tripping the full config. Existing custom env values are strings and custom tool entries use the supported tool-table shape; reject unsupported shapes before any write instead of silently dropping them.

**Plan:** Replace the Pallium table subtree as a unit while leaving surrounding TOML text untouched. Parse the existing config, preserve extra string-valued env entries and additional supported tool entries, and let generated managed values remain canonical. Make the shared remove helper cover descendant tables for both install and uninstall; recognize table headers only outside TOML multiline strings, including valid four- and five-quote closing runs. Parse the complete resulting document with tomllib before calling the existing writer. Add isolated-home tests through setup_codex.install() for nested migration, repeated install, custom env/tools, multiline-string header text, sibling tables, uninstall cleanup, and unsupported custom setting rejection. Inject malformed generated TOML at the _mcp_env_toml candidate-building seam; assert validation fails, _write_toml is not called, and the original config bytes remain unchanged. Do not add a general TOML serializer or change the writer's atomicity contract. Retained continuation: preserve child commits, merge reviewed main minimally, protect actual feature-section and managed-key selection outside multiline strings with the existing tracker and builtin slice bounds, preserve header/comments and supported boolean policy, then requalify affected setup tests and current hosted full CI before merge.

**Verification plan:** Nested Pallium descendants are replaced while multiline strings and sibling tables remain intact -> isolated setup/reinstall/uninstall regression. Repeated install remains idempotent -> same lifecycle regression compares config bytes after the second install. Invalid generated TOML and unsupported existing env/tool shapes leave source bytes unchanged and skip writing -> isolated fail-closed regressions. Whole change is qualified -> selector and its required full test lane. Continuation preservation -> controlled basic/literal install/reinstall/uninstall RED/GREEN with fake headers/flags before and inside real features, retained comments and complete parsed-note equality; wrong managed feature types -> existing fail-closed no-write test. Current qualification ->88 affected tests, fresh boundary/selector/governance plus same-head hosted full lane; historical counts are not current evidence.

**Plan review:** Agent technical review: /root/role_history_developer/codex_config_plan_review. GO on plan at source 16440107 after reviewing table-preserving replacement, parse-only tomllib validation, supported custom env/tool preservation, shared install/uninstall cleanup, and the isolated invalid-generated-candidate test that asserts no write and byte-for-byte source preservation. Continuation PLAN GO: @astra-reviewer turn01a17a72-83d5-7fe3-bbd3-6d505ce95cd0, with explicit protection of both real section boundaries and managed setting lines outside multiline values. Preserve literal/basic strings, actual header/comment and no-write failure behavior; actual minimal diff and controlledRED/focused/affected evidence remain required.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

- Isolated worktree, branch `fix/codex-setup-nested-toml`, based on fetched `origin/main` at `16440107`.
- `setup_codex` parses the source and assembled candidate with `tomllib`, preserves supported custom string env entries and custom tool approval entries, and rejects unsupported shapes before `_write_toml`.
- The shared Pallium remover tracks TOML multiline strings before recognizing table headers and removes the base table plus descendants for install/uninstall. It preserves sibling text and tables.
- Same reviewer returned source GO after adding multiline-string quote-run handling and unsupported-shape no-write regressions.

## Evidence

- Exact current Relay role is unavailable: `pallium_relay_address` rejected the call because no `container_ref` was injected. No role was guessed.
- Focused command: qualified Python 3.13.14 `-m pytest` on the nested migration/reinstall/uninstall case, malformed generated candidate case, and unsupported nested-setting case; **4 passed in 0.53s**.
- Affected file: `tests/test_codex_integration.py -q -n 0`; **85 passed in 35.44s**.
- Whole-change selector: `python scripts/test-plan.py --base origin/main`; selected `python -m pytest tests/ -x -q` because test files and selection policy apply.
- Whole-change lane: qualified Python 3.13.14 `-m pytest tests/ -x -q`; **8137 passed, 37 skipped, 2 xfailed in 626.03s**.
- One initial focused run had 3 passes and one fixture assertion failure because the multiline string was placed in the replaced Pallium table. The test-only correction moved it to an unrelated sibling table; same reviewer confirmed the correction and the rerun passed.
- The source tree and tests passed AST parsing and `git diff --check`. No live Codex configuration or service was accessed or changed.
- Hosted PR check run `40321568630`: Windows smoke passed (`121567598844`). Linux Python 3.13 failed `tests/test_codex_wake.py::test_http_ack_after_validation_serializes_with_native_start_and_releases_fence[codex]` with `/relay/turn` returning 503 at `setup_deadline` after 1,701 ms in `session_connection` (3,304 passed, 22 skipped, 1 xfailed before `-x` stopped the lane). Linux Python 3.12 failed `tests/test_codex_wake_sqlite.py::test_http_send_restart_exact_claim_ack_preserves_sqlite_fence[ambiguous-uncertain]` with `/relay/turn` returning 503 at `setup_deadline` after 1,114 ms in `session_connection`, and `tests/test_hermes_relay_plugin.py::test_postreply_context_view_obeys_scope_and_lifetime[api-request]` with 503 at `pre_attempt_deadline` (3,025 passed, 16 skipped, 1 xfailed before `-x` stopped the lane). Both failures are outside this PR's changed files. CI setup completed; the Linux command runs `pytest tests/ -x -q` with the repository's default `-n 4`. The acquisition deadlines are consistent with worker contention, but the cause is unproven; no code change or rerun is justified by this evidence.
- Follow-up for those three exact failed parametrized nodes: serial execution with the qualified Python 3.13 runtime, `-q -n 0`, and fresh isolated `--basetemp` passed **3/3 in 2.82s**. The shared test `client` fixture gives each test a `tmp_path`-backed SQLite database, and this PR does not change the fixture, relay acquisition code, routes, or these tests. The serial run shows the CI failures do not reproduce without parallel workers; it does not prove whether runner load or an in-test timing interaction caused them. No unrelated timeout or storage change is warranted.

## Historical child result review

Agent technical review: /root/role_history_developer/codex_config_plan_review; GO on the implementation and corrected test fixture.
Reviewed revision: `16440107` plus the implementation diff in this isolated worktree.
Verification adequacy: focused regressions, affected-file tests, and the selector-required full test lane all passed.


## PR359 retained continuation

Manager accepted source ownership transfer to @pal-dev1 after native child became inactive. Verified retained checkout clean at212430728de3a40b34d1a8eb7bbe2a81065fd13c, branch fix/codex-setup-nested-toml; published draftPR359 still e457b76cc0c725fcd5076c85f0265d4f915db421. The only unpublished change is the two-line historical CI diagnosis in this Work Record. Three intended changed paths remain; no reimplementation. Fresh origin/main4b9a54e9a023caa1679400368cf3d4bdcbab80d9 includes merged PR364. Reconcile it minimally after recording this continuation, preserving child commits and ignored evidence.

Role @pal-dev1 freshly confirmed by exact-self lookup. This older checkout has no roles mapping, ordinary opt-out; reread current mapping after main reconciliation. No AGENTS.local.md exists. Broad History lookup failed delivery_finalization_timeout with retryable=false; no retry or guessed history/identity is used. Existing record plus live Git/PR/check state establish continuity. The setup scope has no separately supplied canonical roadmap identity; manager retains owner-managed roadmap alignment. Earlier wake/OpenCode explicit associations are preserved for their broader ongoing assignments.

New in-scope source finding before edits: a pure in-memory fixture places [features] and hooks=false inside an unrelated TOML multiline notes value. Actual _ensure_feature_flag changes that unrelated text to hooks=true, creates no actual root features table, and _ensure_mcp_server still returns parse-valid TOML. Pre-write parse alone cannot detect this damage. This is an existing feature-selector interaction in the same setup install/uninstall path, not evidence that the original MCP subtree implementation must be rewritten. No live configuration was accessed.

Small continuation plan: reuse the already-added multiline-string tracker when finding the actual features table; return builtin slice bounds and adapt its only two private production callers, preserving actual header text/comments and current hook-flag policy. Extend the existing isolated nested migration lifecycle test with fake features/header/legacy-flag content in a sibling multiline string, compare the complete parsed sibling note through install/reinstall/uninstall and assert actual features.hooks is enabled. Retain invalid/unsupported-candidate no-write assertions. Existing reviewer receives this bounded edge plan before code. Gray app path/BLUEtests preserve Elevated/Moderate risk; no API/schema/dependency/protected/config/installed changes.

Qualification will use an existing READ-ONLY supported interpreter with current-cwd/dependency preflight. Historical4/85/8137 and three serial failure-node results remain tied to their old source/runtime, never current CI or proof of physical cause. Run focused lifecycle/affected CLI tests, fresh selector/boundary/workflow and current-head hosted qualification after review. Do not alter unrelated acquisition deadlines, CI worker policy or user's everyday installation. No extra human approval loop for authorized isolated correction/publication/merge. Retain this child worktree and old build evidence until completion/custody allows cleanup.


## Main reconciliation and edge-plan review

Reviewed main merged cleanly at19700112; task net diff remains only the original three paths. Current roles mapping has no @pal-dev1 entry, ordinary opt-out. Runtime preflight build/pr359-resume-20261027/runtime.json verifies all current declared project bounds and current-checkout imports with Python3.13.14/AnyIO4.14.2/SQLAlchemy2.0.48/FastAPI0.135.1/Starlette0.52.1/pytest8.4.2. The existing private interpreter is borrowed read-only; no package/env/installation change.

Relay plan review was deferred target_not_idle while reviewer worked on325/353. After that turn completed, an authorized app-message fallback resumed the same reviewer without settings override or duplicate Relay send. Astra PLAN GO turn01a17a72 adds a concrete completeness condition: locating the real features table alone is insufficient because current per-body regexes also mutate fake hooks/codex_hooks lines inside a real features multiline value. Protect both boundary selection and managed key selection using the existing string-state tracker. Use stdlib tomllib for line recognition where needed, preserve all unrelated text and actual header/comments, and fail before write for unsupported managed shapes. No general serializer or new framework.

Extend the existing nested setup lifecycle test with fake headers/flags both before and inside the real feature table, basic and literal multiline forms, and a quoted real header/comment. Compare full parsed unrelated note values before/after install/reinstall/uninstall; only the real deprecated key is removed and actual hooks=True. Retain original no-write/custom-env/tools/sibling assertions. Controlled RED precedes the small private-helper correction. File edits use deterministic named-file UTF8 replacements because the previously encountered machine-local apply_patch1385 limitation must not be retried; no repository policy is changed.


## Controlled lifecycle RED and minimal correction

Extended existing lifecycle regression fails both basic/literal cases on actual isolated setup:2failed0.93s, red.{log,xml}. The complete parsed sibling note is changed even though install reports success and resulting TOML parses. Original fixture assertions remain; additional assertions cover actual quoted features header/comment, fake flags/headers inside actual feature notes, real hooks=True, only real legacy key removed and unchanged notes after uninstall.

Implementation reuses _toml_multiline_delimiter for real features-section slice boundaries and for actual managed assignment lines. The private body helper parses only candidate lines with stdlib tomllib, updates supported boolean hook values, removes actual legacy flags and preserves all other text. Only two existing callers change from regex Match to builtin slice; actual header/comment remains. Unsupported recognized managed values fail before the existing writer. No general serializer, dependency, writer atomicity, native deadline or installed state change. Named deterministic UTF8 replacements used, as recorded.


The known-failure rerun passes2cases0.49s/84deselected (green.{log,xml}). Before affected qualification, the same lifecycle also exercises an actual false modern-hooks value with a retained inline comment, and the existing no-write unsupported-settings regression adds both modern/legacy feature values with unsupported types. These validate the new line-level boolean guards without changing the source or writer contract. The full current affected file will bind these final input refinements.


## Current-source local verification

At5e6784829d24f1ebe6a814eed2690879de642e3b, the complete affected tests/test_codex_integration.py passed88tests in37.17s, zero failures/errors/skips (affected.{log,xml}). This includes final basic/literal lifecycle/comment/actualflag changes and all unsupported environment/tool/modern-feature/legacy-feature no-write checks. Prior2fail RED and2pass focused receipts are retained and overlap; counts are not summed. Runtime manifest and hashed XML evidence are in build/pr359-resume-20261027. AST comparison to child publishede457 confirms53 functions unchanged; only _features_section, _ensure_feature_flag and _remove_feature_flag changed, with one new private body helper. Existing native reviewer evidence is reused only for unchanged source.

Import-boundary check passed. Whole-change selector reports exactly three intended paths and requires full application lane. Current incremental Redline is GRAY advisory1, no required checkpoints or boundary violations. Current-source technical result review is accepted below; the normal current-head hosted full CI must pass before merge. No extra local full-suite run or failed-workflow retry is claimed. Original8137 counts and old platform failures remain historical. No installed configuration or service was accessed or changed.


## Result review

Agent technical review: @astra-reviewer turn01a17a7a-c13d-7980-a389-63e5ec4257bb, bounded correction SOURCE/RESULT GO.
Reviewed revision: 5e6784829d24f1ebe6a814eed2690879de642e3b versus merged19700112; unchanged original child source uses its recorded native review only.
Verification adequacy: Reviewer inspected the actual header scanner/slice, managed-key scanner and two private callers plus lifecycle/no-write changes. Quoted real header/comments and complete sibling/features notes remain; only actual managed boolean keys change, unsupported recognized values reject before write. Independently parsed terminal affected XML/log:88passed37.17s, zero failures/errors/skips. Exactly three net-main paths and clean diff confirmed. No blocking finding in the correction. Earlier2-case/historical8137 results are not current full qualification. No extra local tests requested. Proceed through fresh whole-change governance/current-head CI and review threads before merge. This review grants no live-install/config permission and does not assess atomic filesystem writes or concurrent-editor protection, which remain outside this task. Following record-only changes preserve reviewed code bytes.

## Publication and qualification handoff

Publish the reviewed continuation to the existing rore/Pallium PR359 branch fix/codex-setup-nested-toml, mark ready for review, retain current-head full CI and resolve actual review findings before authorized merge. Do not create a replacement PR or alter installations. No roadmap item identity was supplied for this standalone setup fix; manager receives delivered revision/remaining scope for canonical queue alignment. Keep the retained checkout and ignored evidence until merge/current qualification and custody are confirmed; old child commits and failed evidence remain recoverable.


## Current CI prerequisite preparation correction

At published c7d32a9a5a6468224a0f5f6f4036e730bbfe9360, normal full CI40418560199 Python3.12 passed8153/93skipped/2xfailed443.92s; Windows smoke and governance passed. Python3.13 job121906969778 failed first sender registration in test_rejected_legacy_and_runtime_selectors_have_no_delivery_or_wake_side_effects:503 relay_busy, pre_attempt_deadline2085ms, no recorded acquisition phases;3592passed/21skipped/1xfailed406.32s before fail-fast. Old failed CI remains failed, physical delay cause unknown. Private current-ci-terminal.json retains exact evidence. No rerun or installation action was taken.

Manager app continuation explicitly assigns this owner the bounded registration-only preparation correction and says to preserve all real subjects/native defaults; Relaydev was told not to patch this module/PR in parallel. Source inspection of all six _turn callers and roadmap/features/investigate-cross-repository-relay-coordination.md Required validation finds initial registration is prerequisite, while targeting, actor/container identity, alias ownership, rejection/no-side-effects and reply/backlog lifecycle are the subjects. The contract has no first-attempt registration latency requirement; bounded native admission/refusal coverage remains elsewhere unchanged.

Plan: reuse existing audited relay_admission_clock without changing it. Each of six cross-container tests opts into its semantic parameter; scope only initial HTTP registrations with expected_admissions2,3,3,3,3,2 respectively, and the first lifecycle's later sender container-move registration with a separate expected1 scope. All actual send/claim/ACK/reply/name-conflict/takeover/close/reopen/no-delivery/no-wake assertions and native timing outside scopes remain unchanged. No global/autouse clock, HTTP retry, helper, fixture implementation, timeout, product or protected-test change. Four net PR paths; retain original setup source/results and reuse unchanged reviews. Risk/complexity remain Elevated/Moderate.

Verification: run entire changed cross-container module and existing tests/test_client_fixture.py audit serially with current qualified read-only interpreter and isolated temporary files; inspect actual diff for registration-only scope and restoration. Run fresh whole-change selector/governance/diff checks, existing reviewer actual diff/results review, then normal published-head full CI; no local full-suite repeat. State returns to planning pending bounded existing reviewer plan review (paldev1-pr359-registration-plan-review-20261027); no test edit yet.


Bot review now identifies actual source issues before publication: valid nested-array element ["x"] is independently parseable as a table header. Pure in-memory current helpers reproduce duplicate hooks in features and a retained closing array bracket from Pallium subtree removal. _remove_feature_flag also raises for unsupported legacy value but uninstall does not catch it. Four bot threads include these three functional findings plus neutralizing the public record's machine-local path. No user data was accessed or written.

Consolidated bounded source plan for existing reviewer: at each of the two candidate-header sites, use stdlib tomllib to validate the original prefix before treating the line as a header; an unfinished array prefix fails parsing, so nested elements remain values. Keep existing multiline handling and original-content offset in removal; no new general parser or array-depth state machine. For uninstall, parse input and final candidate and catch ValueError before _write_toml or any cleanup. Extend existing isolated lifecycle cases with nested arrays, bracket characters in quotes/comments, multiline string close plus array-bracket suffix, fake headers before/within features and Pallium; include uninstall on such a hand-edited server. Add focused isolated uninstall failure/no-write/no-cleanup regression. Preserve all current baseline assertions. Run controlled RED then affected setup+cross-container module+existing fixture audit; reuse original88 result only for unchanged tests until new affected run. Existing reviewer to approve this uncovered source plan together with registration-only preparation before any implementation edit.
