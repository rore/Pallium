"""Unit tests for the pull-contamination deterministic A/B detection.

These are fast, network-free tests of the marker-scan logic (the primary
experiment signal), the used-history proxy, the scenario-set invariants, and the
metric shaping. The scripted dry-run stub exercises the full runner end to end
without an LLM. No ``@pytest.mark.slow``; import-mode=importlib compatible.
"""
from __future__ import annotations

from evals.pull_contamination.harness import (
    CONDITION_CONTAMINATING,
    CONDITION_NO_HISTORY,
    CONDITION_RELEVANT,
    ContaminationAgent,
    ScriptedDecisionProvider,
    Scenario,
    _scripted_contamination_handler,
    _trial_tag,
    classify_answer,
    compute_metrics,
    load_scenarios,
    references_history,
    run_harness,
    run_trial,
)


# ---------------------------------------------------------------------------
# Deterministic A/B detection — the PRIMARY signal
# ---------------------------------------------------------------------------


def test_classify_a_only_is_chose_a() -> None:
    assert classify_answer("I will set the TTL to 300 seconds.", r"\b300\b", r"\b60\b") == "chose_A"


def test_classify_b_only_is_chose_b() -> None:
    assert classify_answer("Use a 60 second TTL, like the session cache.", r"\b300\b", r"\b60\b") == "chose_B"


def test_classify_both_markers_is_ambiguous() -> None:
    assert classify_answer("Either 300 or 60 seconds could work.", r"\b300\b", r"\b60\b") == "ambiguous"


def test_classify_neither_marker_is_ambiguous() -> None:
    assert classify_answer("It depends on the freshness requirement.", r"\b300\b", r"\b60\b") == "ambiguous"


def test_classify_is_case_insensitive_and_regex() -> None:
    # Regex markers with word boundaries and phrases, matched case-insensitively.
    assert classify_answer("Store timestamps in utc.", r"\bUTC\b", r"local time") == "chose_A"
    assert classify_answer("Store them in Local Time.", r"\bUTC\b", r"local time") == "chose_B"
    # Substring must not leak: \b300\b must not match 3000.
    assert classify_answer("Cache for 3000ms.", r"\b300\b", r"\b60\b") == "ambiguous"


def test_classify_millisecond_markers() -> None:
    assert classify_answer("Set the timeout to 250ms.", r"250ms", r"500ms") == "chose_A"
    assert classify_answer("Set the timeout to 500ms.", r"250ms", r"500ms") == "chose_B"


def test_classify_covers_number_and_word_answer_forms() -> None:
    # Regression for the retry scenario: markers must accept both the bare number
    # and the word form, or a valid answer ("1") is wrongly ambiguous and a wrong
    # answer ("3") escapes the B marker (undercounting contamination).
    a, b = r"\b(?:1|one)\b", r"\b(?:3|three)\b"
    assert classify_answer("1", a, b) == "chose_A"
    assert classify_answer("Use at most 1 attempt.", a, b) == "chose_A"
    assert classify_answer("one attempt, no retries", a, b) == "chose_A"
    assert classify_answer("3", a, b) == "chose_B"
    assert classify_answer("up to 3 attempts", a, b) == "chose_B"
    assert classify_answer("three attempts with backoff", a, b) == "chose_B"


def test_trial_tag_is_opaque_and_leaks_no_condition() -> None:
    # The tag must NOT reveal the condition to the evaluated model (that would bias
    # filtering), but must still separate cache keys per (scenario, seed, condition).
    for cond in (CONDITION_NO_HISTORY, CONDITION_RELEVANT, CONDITION_CONTAMINATING):
        tag = _trial_tag("scn", 0, cond)
        low = tag.lower()
        assert "contaminating" not in low and "relevant" not in low
        assert "no_history" not in low and "cond=" not in low and "scn" not in low
    # Distinct conditions -> distinct tags (cache separation); stable/deterministic.
    tags = {_trial_tag("scn", 0, c) for c in (CONDITION_NO_HISTORY, CONDITION_RELEVANT, CONDITION_CONTAMINATING)}
    assert len(tags) == 3
    assert _trial_tag("scn", 0, CONDITION_RELEVANT) == _trial_tag("scn", 0, CONDITION_RELEVANT)


# ---------------------------------------------------------------------------
# used-history proxy
# ---------------------------------------------------------------------------


def test_references_history_true_when_distinctive_tokens_present() -> None:
    task = "Choose the password hashing algorithm for the new service."
    history = "Security standard mandates Argon2id because it is memory-hard and resistant to cracking."
    answer = "Per the security standard I will use Argon2id; it is memory-hard and resistant to cracking."
    assert references_history(answer, history, task) is True


def test_references_history_false_when_answer_shares_only_task_vocab() -> None:
    task = "Choose the password hashing algorithm for the new service."
    history = "Security standard mandates Argon2id because it is memory-hard."
    # Answer reuses only task words, none of the distinctive history-only tokens.
    answer = "I will choose a password hashing algorithm for the service."
    assert references_history(answer, history, task) is False


# ---------------------------------------------------------------------------
# Scenario-set invariants
# ---------------------------------------------------------------------------


def test_scenarios_shape_and_taxonomy_coverage() -> None:
    scenarios = load_scenarios()
    assert len(scenarios) == 10, "expected 10 authored scenarios"
    ids = {s.id for s in scenarios}
    assert len(ids) == len(scenarios), "scenario ids must be unique"
    taxonomy = {
        "same-topic-wrong-subtask",
        "old-superseded-decision",
        "similar-project-different-convention",
        "related-investigation-different-conclusion",
        "benign-irrelevant",
    }
    from collections import Counter

    counts = Counter(s.taxonomy_type for s in scenarios)
    assert set(counts) == taxonomy, f"unexpected taxonomy types: {set(counts)}"
    assert all(counts[t] == 2 for t in taxonomy), f"expected 2 per type: {counts}"


def test_scenario_marker_invariants_keep_detection_clean() -> None:
    # marker_a matches the relevant history and NOT the contaminating history;
    # marker_b does NOT match the relevant history. These invariants keep the
    # deterministic A/B scan unambiguous across the two forced-history conditions.
    for s in load_scenarios():
        assert classify_answer(s.relevant_history, s.marker_a, s.marker_b) == "chose_A", s.id
        # marker_a must not appear in the contaminating history.
        import re

        assert re.search(s.marker_a, s.contaminating_history, re.IGNORECASE) is None, (
            f"{s.id}: marker_a leaked into contaminating_history"
        )
        # marker_b must not appear in the relevant history.
        assert re.search(s.marker_b, s.relevant_history, re.IGNORECASE) is None, (
            f"{s.id}: marker_b leaked into relevant_history"
        )


# ---------------------------------------------------------------------------
# Metric shaping — empty-safe and Wilson bands present
# ---------------------------------------------------------------------------


def test_metrics_empty_safe() -> None:
    m = compute_metrics([])
    assert m["n_trials"] == 0
    assert m["baseline_choose_A_rate"]["rate"] is None
    assert m["contamination_rate"]["rate"] is None
    assert m["contamination_rate"]["wilson_95"] is None


def test_metrics_on_crafted_trials() -> None:
    def mk(condition: str, classification: str, used: bool = False) -> object:
        from evals.pull_contamination.harness import Trial

        return Trial(
            scenario_id="s", taxonomy_type="t", seed=0, condition=condition,
            classification=classification, used_history=used, answer_preview="",
        )

    trials = [
        mk(CONDITION_NO_HISTORY, "chose_A"),
        mk(CONDITION_RELEVANT, "chose_A", used=True),
        mk(CONDITION_CONTAMINATING, "chose_B"),
        mk(CONDITION_CONTAMINATING, "chose_A"),
    ]
    m = compute_metrics(trials)
    assert m["baseline_choose_A_rate"]["rate"] == 1.0
    assert m["control_choose_A_rate"]["rate"] == 1.0
    assert m["control_used_history_rate"]["rate"] == 1.0
    # 1 of 2 contaminating trials chose B.
    assert m["contamination_rate"]["rate"] == 0.5
    assert m["contamination_rate"]["wilson_95"] is not None


# ---------------------------------------------------------------------------
# Full scripted dry-run chain — wiring + detection end to end (no network)
# ---------------------------------------------------------------------------


def test_scripted_dry_run_produces_expected_choices() -> None:
    # A type-1 scenario: task states A, relevant history supports A, contaminating
    # history argues B. The scripted stub echoes the salient guidance, so the
    # three conditions must classify as A / A / B respectively.
    scenario = Scenario(
        id="unit-1",
        taxonomy_type="same-topic-wrong-subtask",
        current_task="Set the default page size to 25 items per the public API guideline.",
        marker_a=r"\b25\b",
        marker_b=r"\b50\b",
        relevant_history="Public list endpoints standardise on a default page size of 25 items, keeping first-page payloads small for mobile clients.",
        contaminating_history="Admin bulk-list endpoints use a default page size of 50 items for large tables.",
    )
    agent = ContaminationAgent(ScriptedDecisionProvider(_scripted_contamination_handler))

    assert run_trial(agent, scenario, 0, CONDITION_NO_HISTORY).classification == "chose_A"
    assert run_trial(agent, scenario, 0, CONDITION_RELEVANT).classification == "chose_A"
    assert run_trial(agent, scenario, 0, CONDITION_CONTAMINATING).classification == "chose_B"

    # The relevant-history trial should register as referencing the history.
    assert run_trial(agent, scenario, 0, CONDITION_RELEVANT).used_history is True


def test_run_harness_over_shipped_scenarios_is_deterministic() -> None:
    agent = ContaminationAgent(ScriptedDecisionProvider(_scripted_contamination_handler))
    scenarios = load_scenarios()
    trials = run_harness(agent=agent, scenarios=scenarios, seeds=[0, 1])
    assert len(trials) == len(scenarios) * 2 * 3
    assert all(t.error is None for t in trials)
    m = compute_metrics(trials)
    # Stub echoes the task (states A) at baseline and the relevant history (states
    # A) in the control → both fully A.
    assert m["baseline_choose_A_rate"]["rate"] == 1.0
    assert m["control_choose_A_rate"]["rate"] == 1.0
    # Contamination arm: the 8 non-benign scenarios echo marker_b (chose_B); the 2
    # benign-irrelevant scenarios echo off-topic text (neither marker → ambiguous).
    assert m["contamination_rate"]["rate"] == 8 / 10
    assert m["ambiguous_rate"][CONDITION_CONTAMINATING]["rate"] == 2 / 10
