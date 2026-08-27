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
            if outcome is not None:
                assert outcome in VALID_OUTCOMES, (
                    f"{runtime}/{fixture.get('case')}: unexpected outcome {outcome!r}"
                )


def test_all_phase0_cases_covered_per_runtime() -> None:
    required = set(ADAPTER_CONTRACT["phase0_cases"])
    for runtime in RUNTIMES:
        found = {f["case"] for f in _load_runtime_fixtures(runtime) if "case" in f}
        assert found >= required, f"{runtime}: missing cases {required - found}"


def test_busy_queue_outcome_is_capability_specific() -> None:
    """idle_wake-only adapters must yield unavailable, not triggered/admitted."""
    for runtime in RUNTIMES:
        for fixture in _load_runtime_fixtures(runtime):
            if fixture.get("case") != "busy_queue":
                continue
            capability = (fixture.get("input") or {}).get("capability")
            outcome = _extract_outcome(fixture)
            if capability == "idle_wake":
                assert outcome == "unavailable", (
                    f"{runtime}/busy_queue with idle_wake capability must yield "
                    f"unavailable, got {outcome!r}"
                )


def test_ambiguous_retry_not_issued() -> None:
    """Adapters without proven idempotency must not issue a retry on ambiguous."""
    for runtime in RUNTIMES:
        for fixture in _load_runtime_fixtures(runtime):
            if fixture.get("case") != "ambiguous_retry":
                continue
            for step in fixture.get("expected_protocol_sequence", []):
                if "retry_issued" in step:
                    assert step["retry_issued"] is False, (
                        f"{runtime}/ambiguous_retry: retry_issued must be false "
                        f"without proven idempotency"
                    )
