<!-- agent-workflow:start -->
**Outcome:** Codex setup replaces Pallium's MCP registration without duplicate tables and refuses invalid generated TOML before writing.

**Target:** Pallium Codex setup.

**Scope:** app/cli/setup_codex.py, its existing CLI setup tests, and this Work Record.

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

**Discovery:** Coordinator reports a reproduction at source `16440107`: removal of `[mcp_servers.pallium]` leaves nested `.env` and `.tools.*` tables, then appending inline tables produces duplicate TOML; candidate TOML is written without validation. Verify this against the branch before editing.

**Material assumptions:** Python 3.12+ is required, so stdlib tomllib can parse and validate candidate TOML. It has no writer; preserve surrounding text and comments rather than round-tripping the full config. Existing custom env values are strings and custom tool entries use the supported tool-table shape; reject unsupported shapes before any write instead of silently dropping them.

**Plan:** Replace the Pallium table subtree as a unit while leaving surrounding TOML text untouched. Parse the existing config, preserve extra string-valued env entries and additional supported tool entries, and let generated managed values remain canonical. Make the shared remove helper cover descendant tables for both install and uninstall; recognize table headers only outside TOML multiline strings, including valid four- and five-quote closing runs. Parse the complete resulting document with tomllib before calling the existing writer. Add isolated-home tests through setup_codex.install() for nested migration, repeated install, custom env/tools, multiline-string header text, sibling tables, uninstall cleanup, and unsupported custom setting rejection. Inject malformed generated TOML at the _mcp_env_toml candidate-building seam; assert validation fails, _write_toml is not called, and the original config bytes remain unchanged. Do not add a general TOML serializer or change the writer's atomicity contract.

**Verification plan:** Nested Pallium descendants are replaced while multiline strings and sibling tables remain intact -> isolated setup/reinstall/uninstall regression. Repeated install remains idempotent -> same lifecycle regression compares config bytes after the second install. Invalid generated TOML and unsupported existing env/tool shapes leave source bytes unchanged and skip writing -> isolated fail-closed regressions. Whole change is qualified -> selector and its required full test lane.

**Plan review:** Agent technical review: /root/role_history_developer/codex_config_plan_review. GO on plan at source 16440107 after reviewing table-preserving replacement, parse-only tomllib validation, supported custom env/tool preservation, shared install/uninstall cleanup, and the isolated invalid-generated-candidate test that asserts no write and byte-for-byte source preservation.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Worktree `C:\Users\I347041\.codex\worktrees\codex-config-toml-1265\Pallium`, branch `fix/codex-setup-nested-toml`, based on fetched `origin/main` at `16440107`.
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

## Result review

Agent technical review: /root/role_history_developer/codex_config_plan_review; GO on the implementation and corrected test fixture.
Reviewed revision: `16440107` plus the implementation diff in this isolated worktree.
Verification adequacy: focused regressions, affected-file tests, and the selector-required full test lane all passed.
