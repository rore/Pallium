"""Validate all relay wake adapter fixture files against the adapter outcome contract."""
from __future__ import annotations

import json
from pathlib import Path

FIXTURES_ROOT = Path(__file__).parent / "relay" / "wake" / "fixtures"
ADAPTER_CONTRACT = json.loads((FIXTURES_ROOT / "contract.json").read_text(encoding="utf-8"))
VALID_OUTCOMES = set(ADAPTER_CONTRACT["adapter_outcomes"])
RUNTIMES = ["codex", "opencode", "claude_code"]


def _load_runtime_fixtures(runtime: str) -> list[dict]:
    d = FIXTURES_ROOT / runtime
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(d.glob("*.json"))]


def _extract_outcome(fixture: dict) -> str | None:
    # Only check top-level expected_outcome; step-level fields describe wake states, not adapter outcomes
    return fixture.get("expected_outcome")


def test_all_fixture_files_parse() -> None:
    for runtime in RUNTIMES:
        fixtures = _load_runtime_fixtures(runtime)
        assert len(fixtures) == 7, f"{runtime}: expected 7 fixtures, got {len(fixtures)}"


def test_all_expected_outcomes_are_valid() -> None:
    for runtime in RUNTIMES:
        for fixture in _load_runtime_fixtures(runtime):
            if fixture.get("case") == "identify_session":
                continue  # resolver probe — outcome is session_resolved, not an adapter outcome
            outcome = _extract_outcome(fixture)
            assert outcome is not None, (
                f"{runtime}/{fixture.get('case')}: missing top-level expected_outcome"
            )
            assert outcome in VALID_OUTCOMES, (
                f"{runtime}/{fixture.get('case')}: unexpected outcome {outcome!r}"
            )
            # Validate nested outcomes in states[] (session_states case)
            for state in fixture.get("states", []):
                nested = state.get("expected_outcome")
                if nested is not None:
                    assert nested in VALID_OUTCOMES, (
                        f"{runtime}/{fixture.get('case')}/states: unexpected outcome {nested!r}"
                    )


def test_all_phase0_cases_covered_per_runtime() -> None:
    required = set(ADAPTER_CONTRACT["phase0_cases"])
    for runtime in RUNTIMES:
        found = {f["case"] for f in _load_runtime_fixtures(runtime) if "case" in f}
        assert found >= required, f"{runtime}: missing cases {required - found}"


def test_busy_queue_outcome_is_capability_specific() -> None:
    """idle_wake-only adapters must yield unavailable; busy_queue adapters must yield triggered."""
    for runtime in RUNTIMES:
        for fixture in _load_runtime_fixtures(runtime):
            if fixture.get("case") != "busy_queue":
                continue
            capability = (fixture.get("input") or {}).get("capability")
            outcome = _extract_outcome(fixture)
            assert capability is not None, (
                f"{runtime}/busy_queue: input.capability must be set to make this test non-vacuous"
            )
            if capability == "idle_wake":
                assert outcome == "unavailable", (
                    f"{runtime}/busy_queue with idle_wake capability must yield unavailable, got {outcome!r}"
                )
            elif capability == "busy_queue":
                assert outcome == "triggered", (
                    f"{runtime}/busy_queue with busy_queue capability must yield triggered, got {outcome!r}"
                )


def test_ambiguous_retry_not_issued() -> None:
    """Adapters without proven idempotency must not issue a retry on ambiguous. retry_issued must be present in at least one step."""
    for runtime in RUNTIMES:
        for fixture in _load_runtime_fixtures(runtime):
            if fixture.get("case") != "ambiguous_retry":
                continue
            steps = fixture.get("expected_protocol_sequence", [])
            assert steps, f"{runtime}/ambiguous_retry: expected_protocol_sequence must not be empty"
            retry_steps = [s for s in steps if "retry_issued" in s]
            assert retry_steps, (
                f"{runtime}/ambiguous_retry: no step has 'retry_issued' field — "
                f"test would be vacuous without it"
            )
            for step in retry_steps:
                assert step["retry_issued"] is False, (
                    f"{runtime}/ambiguous_retry: retry_issued must be false "
                    f"without proven idempotency"
                )


def test_nested_protocol_contract() -> None:
    """session_states entries must have state+expected_outcome; restart scenarios must have expected_behavior."""
    for runtime in RUNTIMES:
        for fixture in _load_runtime_fixtures(runtime):
            case = fixture.get("case", "")
            for state in fixture.get("states", []):
                assert "state" in state, f"{runtime}/{case}: states[] entry missing 'state'"
                assert "expected_outcome" in state, f"{runtime}/{case}: states[] entry missing 'expected_outcome'"
            for scenario in fixture.get("scenarios", []):
                assert "expected_behavior" in scenario or "expected_recovery" in scenario, (
                    f"{runtime}/{case}: scenarios[] entry missing 'expected_behavior' or 'expected_recovery'"
                )
