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
        assert runtime["candidate"]


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
    assert set(transitions["natural_turn_claim"]) == {
        "pending/not_eligible",
        "pending/fallback",
    }
    assert set(transitions["natural_ack"]) == {
        "claimed/not_eligible",
        "claimed/fallback",
    }
    assert transitions["wake_admission"] == {
        "pending/triggered": "delivered/admitted"
    }
    expirable = {
        state
        for state in valid
        if state.startswith(("pending/", "claimed/"))
    }
    assert set(transitions["message_expired"]) == expirable
    assert "delivered/admitted" not in transitions["message_expired"]