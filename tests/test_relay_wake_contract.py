import json
from pathlib import Path


CONTRACT = json.loads(
    (Path(__file__).parent / "fixtures" / "relay_wake" / "contract.json").read_text(
        encoding="utf-8"
    )
)


def test_no_runtime_is_promoted_without_the_complete_phase_zero_proof() -> None:
    for runtime in CONTRACT["runtimes"].values():
        assert runtime["version"]
        assert runtime["classification"] == "passive-only"
        assert "candidate" in runtime

    assert CONTRACT["runtimes"]["codex"]["candidate"] is None


def test_transition_matrix_covers_every_required_event_in_every_wake_state() -> None:
    states = set(CONTRACT["wake_states"])
    events = set(CONTRACT["events"])
    assert set(CONTRACT["matrix"]) == states
    for transitions in CONTRACT["matrix"].values():
        assert set(transitions) == events

    matrix = CONTRACT["matrix"]
    assert matrix["triggering"]["begin_external_call"] == "triggered"
    assert matrix["triggered"]["natural_turn_claim"] == "reject"
    assert matrix["triggered"]["pallium_restart"] == "wait_deadline"
    assert matrix["triggered"]["runtime_restart"] == "wait_deadline"
    assert matrix["triggered"]["admission_deadline"] == "fallback"
    assert matrix["triggered"]["wake_callback"] == "admitted"
    assert matrix["admitted"]["message_expired"] == "admitted"
    assert matrix["fallback"]["wake_callback"] == "reject"
    assert matrix["fallback"]["natural_turn_claim"] == "claim"


def test_delivery_and_wake_state_combinations_have_complete_terminal_rules() -> None:
    valid = set(CONTRACT["valid_combined_states"])
    transitions = CONTRACT["delivery_transitions"]
    assert set(CONTRACT["delivery_states"]) == {"pending", "claimed", "delivered", "expired"}
    assert transitions["natural_turn_claim"] == {
        "pending/not_eligible": "claimed/not_eligible",
        "pending/fallback": "claimed/fallback",
    }
    assert transitions["natural_ack"] == {
        "claimed/not_eligible": "delivered/not_eligible",
        "claimed/fallback": "delivered/fallback",
    }
    assert transitions["claim_lease_expired"] == {
        "claimed/not_eligible": "pending/not_eligible",
        "claimed/fallback": "pending/fallback",
    }
    assert transitions["wake_admission"] == {
        "pending/triggered": "delivered/admitted"
    }
    expirable = {
        state
        for state in valid
        if state.startswith(("pending/", "claimed/"))
    }
    assert transitions["message_expired"] == {
        state: "expired/*" for state in expirable
    }
    assert "delivered/admitted" not in transitions["message_expired"]

from core.codex_wake import CodexWakeRegistry
from core.relay_activation import ActivationAttemptResult, relay_activation_snapshot


ENDPOINT = "relay-session-" + "a" * 32
BASE_SESSION = {
    "endpoint_id": ENDPOINT,
    "runtime": "codex",
    "session_ref": "session-東京",
    "container_ref": "git:example/東京",
    "state": "recent",
    "destination_health": "active",
}


def test_activation_projection_maps_supported_passive_and_inflight_without_turn_started() -> None:
    codex = relay_activation_snapshot(
        BASE_SESSION, platform="windows", codex_reserved=True,
    )
    assert (codex["behavior"], codex["qualification"], codex["availability"]) == (
        "busy_queue", "qualified", "attempt_inflight",
    )
    assert codex["fallback"] == "next_natural_turn"
    assert codex["supported_evidence"] == [
        "submission_attempted", "transport_accepted", "payload_admitted",
    ]
    assert "turn_started" not in str(codex)

    claude = relay_activation_snapshot(
        {**BASE_SESSION, "runtime": "claude-code"},
        platform="linux", claude_state="idle",
    )
    assert (claude["behavior"], claude["availability"]) == ("idle_wake", "ready")

    passive = relay_activation_snapshot(
        {**BASE_SESSION, "runtime": "opencode"}, platform="windows",
    )
    assert (passive["behavior"], passive["qualification"]) == (
        "passive", "unqualified",
    )
    assert passive["supported_evidence"] == ["payload_admitted"]

    unsupported = relay_activation_snapshot(BASE_SESSION, platform="macos")
    assert unsupported["qualification"] == "unqualified"
    assert unsupported["fallback"] == "next_natural_turn"


def test_activation_projection_fails_closed_for_stale_closed_malformed_and_conflicting_rows() -> None:
    stale = relay_activation_snapshot(
        {**BASE_SESSION, "state": "dormant"}, platform="windows",
    )
    closed = relay_activation_snapshot(
        {**BASE_SESSION, "state": "closed"}, platform="windows",
    )
    malformed = relay_activation_snapshot(
        {**BASE_SESSION, "endpoint_id": "bad"}, platform="windows",
    )
    conflicting = relay_activation_snapshot(
        {**BASE_SESSION, "recipient_runtime": "claude-code"},
        platform="windows",
    )
    for projection in (stale, malformed, conflicting):
        assert projection["qualification"] == "unknown"
        assert projection["availability"] == "unknown"
        assert projection["fallback"] == "unknown"
        assert projection["supported_evidence"] == []
    assert closed["availability"] == "closed"
    assert closed["qualification"] == "unknown"


def test_attempt_result_rejects_unbounded_or_unsupported_evidence() -> None:
    for kwargs in (
        {"outcome": "accepted", "reason": "x" * 129},
        {"outcome": "accepted", "reason": "ok", "evidence": ("turn_started",)},
    ):
        try:
            ActivationAttemptResult(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid attempt evidence must fail closed")


def test_codex_reservations_survive_restart_and_release_only_exact_delivery(tmp_path) -> None:
    registry = CodexWakeRegistry(tmp_path)
    reservation = registry.reserve(
        recipient_endpoint_id=ENDPOINT, delivery_id="delivery-1",
        session_ref="session-東京", container_ref="git:example/東京",
        still_pending=lambda: True,
    )
    assert reservation is not None
    assert registry.record_outcome(reservation, "accepted")
    restarted = CodexWakeRegistry(tmp_path)
    assert restarted.snapshot(ENDPOINT).outcome == "accepted"
    assert restarted.release_delivery("other") is None
    assert restarted.reserved(ENDPOINT)
    assert restarted.release_delivery("delivery-1") is not None
    assert not CodexWakeRegistry(tmp_path).reserved(ENDPOINT)


def test_codex_reservation_corruption_write_capacity_and_stale_candidate_fail_closed(
    tmp_path, monkeypatch,
) -> None:
    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    (corrupt / "reservations.json").write_text("{", encoding="utf-8")
    broken = CodexWakeRegistry(corrupt)
    assert not broken.usable
    assert broken.reserve(
        recipient_endpoint_id=ENDPOINT, delivery_id="delivery",
        session_ref="session", container_ref="container",
    ) is None

    write_failed = CodexWakeRegistry(tmp_path / "write")
    monkeypatch.setattr(write_failed, "_write_locked", lambda *_: False)
    assert write_failed.reserve(
        recipient_endpoint_id=ENDPOINT, delivery_id="delivery",
        session_ref="session", container_ref="container",
    ) is None
    assert not write_failed.usable

    assert CodexWakeRegistry().reserve(
        recipient_endpoint_id=ENDPOINT, delivery_id="stale",
        session_ref="session", container_ref="container",
        still_pending=lambda: False,
    ) is None

    import core.codex_wake as codex_core
    monkeypatch.setattr(codex_core, "MAX_RESERVATIONS", 1)
    capacity = CodexWakeRegistry()
    assert capacity.reserve(
        recipient_endpoint_id=ENDPOINT, delivery_id="one",
        session_ref="one", container_ref="container",
    ) is not None
    assert capacity.reserve(
        recipient_endpoint_id="relay-session-" + "b" * 32,
        delivery_id="two", session_ref="two", container_ref="container",
    ) is None