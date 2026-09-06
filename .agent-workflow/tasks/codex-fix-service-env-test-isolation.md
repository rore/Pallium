<!-- agent-workflow:start -->
**Outcome:** The Windows full suite is order-independent: the in-process service-run test cannot leak Pallium runtime environment into later config tests.

**Target:** Pallium test suite.

**Scope:** `tests/test_service.py` and this Work Record only.

**Constraints:** Production service environment behavior and config precedence remain unchanged; no sleeps, timeout changes, or suite-wide cleanup fixture.

**Completion criteria:** Running the service-home test immediately before the TOML vector-config test passes in one pytest worker, and the focused modules plus hosted Windows-full 3.12/3.13 pass.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Redline clean-context verdict BLUE; both files are explicit blue-zone test/workflow metadata with no boundary or checkpoint impact.

**Approach:** Wrap the in-process service-run call in the already-imported stdlib `patch.dict(os.environ)` context so every environment mutation is restored on exit.

**Verification:** Exact two-test reproducer; `tests/test_service.py tests/test_vector_startup.py -n 0`; redline/workflow/diff gates; hosted Windows-full 3.12/3.13.

**State:** Ready for review
<!-- agent-workflow:end -->

## Discovery

- The failure reproduces locally only when `TestStartWindows.test_run_uses_explicit_unicode_home_for_runtime_state` precedes `TestVectorIndexConfig.test_vector_index_config_from_toml` in one worker.
- `_cmd_run` intentionally calls `_apply_home_env`, whose `setdefault` mutations belong to the daemon process. The test invokes that path in-process without registering the mutated keys for teardown.
- Production code is correct; isolation belongs to the caller-surface test.

## Implementation

- The first key-by-key `monkeypatch.delenv(..., raising=False)` attempt failed: pytest records nothing when a key is already absent, so later additions survived teardown. Replaced it with scoped `patch.dict(os.environ)`, which snapshots and restores the full mapping while preserving production behavior during the call.

## Evidence

- Before fix: exact two-test sequence yields 1 passed, 1 failed because the second test reads the first test's Unicode-home vector path.
- Main run `34026504032`: restart-service serial slices pass on both Python versions; Windows-full 3.13 then exposes this independent environment leak at 92%.
- After fix: exact two-test sequence passes 2/2; both affected modules pass 57 with 1 Windows-independent skip.
- Main run `34026504032`: both Windows-full 3.12 and 3.13 expose the same environment leak after their serial restart-service slices pass.

## Result review

- Clean-context agent `/root/ci_env_leak_redline`: APPROVE. The scoped environment snapshot preserves in-call production behavior, restores every mutation even on exceptions, matches scope/risk, and needs no additional test.
