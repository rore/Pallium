<!-- agent-workflow:start -->
**Outcome:** The Windows full suite is order-independent: the in-process service-run test cannot leak Pallium runtime environment into later config tests.

**Target:** Pallium test suite.

**Scope:** `tests/test_service.py` and this Work Record only.

**Constraints:** Production service environment behavior and config precedence remain unchanged; no sleeps, timeout changes, or suite-wide cleanup fixture.

**Completion criteria:** Running the service-home test immediately before the TOML vector-config test passes in one pytest worker, and the focused modules plus hosted Windows-full 3.12/3.13 pass.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Redline clean-context verdict BLUE; both files are explicit blue-zone test/workflow metadata with no boundary or checkpoint impact.

**Approach:** Register the runtime keys with the existing `monkeypatch` fixture before the in-process service-run call so pytest restores their original state at teardown.

**Verification:** Exact two-test reproducer; `tests/test_service.py tests/test_vector_startup.py -n 0`; redline/workflow/diff gates; hosted Windows-full 3.12/3.13.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Discovery

- The failure reproduces locally only when `TestStartWindows.test_run_uses_explicit_unicode_home_for_runtime_state` precedes `TestVectorIndexConfig.test_vector_index_config_from_toml` in one worker.
- `_cmd_run` intentionally calls `_apply_home_env`, whose `setdefault` mutations belong to the daemon process. The test invokes that path in-process without registering the mutated keys for teardown.
- Production code is correct; isolation belongs to the caller-surface test.

## Implementation

- Planned: make the existing test own cleanup of `PALLIUM_SQLITE_URL`, `PALLIUM_RELAY_SQLITE_URL`, and `PALLIUM_VECTOR_INDEX_PATH`.

## Evidence

- Before fix: exact two-test sequence yields 1 passed, 1 failed because the second test reads the first test's Unicode-home vector path.
- Main run `34026504032`: restart-service serial slices pass on both Python versions; Windows-full 3.13 then exposes this independent environment leak at 92%.