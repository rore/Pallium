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
    _diff_with_band,
    _scripted_contamination_handler,
    _trial_tag,
    classify_answer,
    classify_answer_leading,
    compute_metrics,
    load_case,
    load_scenarios,
    references_history,
    run_harness,
    run_trial,
)

_AMBIGUOUS_PATH = "evals/pull_contamination/scenarios_ambiguous.json"
_APPLICABILITY_PATH = "evals/pull_contamination/scenarios_applicability.json"
_SUPERSEDED_PATH = "evals/pull_contamination/scenarios_superseded.json"


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


def test_leading_detector_uses_first_marker_on_decision_first_answers() -> None:
    # The real failure mode found in the ambiguous run: a decisive answer that
    # names the rejected option to justify itself. Strict scores it ambiguous;
    # leading recovers the true (decision-first) choice.
    a, b = "UUIDv7", "auto-?increment"
    decisive = "UUIDv7. An auto-increment integer would bottleneck on a central sequence."
    assert classify_answer(decisive, a, b) == "ambiguous"          # strict under-reports
    assert classify_answer_leading(decisive, a, b) == "chose_A"    # leading recovers it
    # Symmetric: leads with B, mentions A.
    other = "Auto-increment is fine here; UUIDv7 would waste space."
    assert classify_answer_leading(other, a, b) == "chose_B"
    # Single marker / neither behave like the strict detector.
    assert classify_answer_leading("UUIDv7 all the way.", a, b) == "chose_A"
    assert classify_answer_leading("It depends on the write pattern.", a, b) == "ambiguous"


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
# Ambiguous-task scenario set (phase 2) — invariants
# ---------------------------------------------------------------------------


def test_ambiguous_case_label() -> None:
    assert load_case(_AMBIGUOUS_PATH) == "ambiguous-task"
    # The original set predates the field and defaults to explicit-task.
    assert load_case() == "explicit-task"


def test_ambiguous_scenarios_shape_and_taxonomy() -> None:
    scenarios = load_scenarios(_AMBIGUOUS_PATH)
    assert len(scenarios) == 10, "expected 10 ambiguous scenarios"
    ids = {s.id for s in scenarios}
    assert len(ids) == len(scenarios), "ids must be unique"
    from collections import Counter

    taxonomy = {
        "two-reasonable-patterns",
        "old-decision-pre-architecture-change",
        "similar-subsystem-different-constraint",
        "investigation-not-transferable",
        "user-preference-non-universal",
    }
    counts = Counter(s.taxonomy_type for s in scenarios)
    assert set(counts) == taxonomy, f"unexpected taxonomy: {set(counts)}"
    assert all(counts[t] == 2 for t in taxonomy), f"expected 2 per type: {counts}"


def test_ambiguous_scenario_marker_invariants() -> None:
    # Unlike the explicit set, EVERY ambiguous contaminating_history genuinely
    # argues B (matches marker_b) — there is no benign-irrelevant negative control
    # here. So the full four-way containment invariant must hold for every scenario:
    # marker_a in relevant only; marker_b in contaminating only.
    import re

    for s in load_scenarios(_AMBIGUOUS_PATH):
        assert re.search(s.marker_a, s.relevant_history, re.IGNORECASE), (
            f"{s.id}: marker_a should match relevant_history"
        )
        assert re.search(s.marker_a, s.contaminating_history, re.IGNORECASE) is None, (
            f"{s.id}: marker_a leaked into contaminating_history"
        )
        assert re.search(s.marker_b, s.contaminating_history, re.IGNORECASE), (
            f"{s.id}: marker_b should match contaminating_history"
        )
        assert re.search(s.marker_b, s.relevant_history, re.IGNORECASE) is None, (
            f"{s.id}: marker_b leaked into relevant_history"
        )
        # The two histories classify cleanly in opposite directions.
        assert classify_answer(s.relevant_history, s.marker_a, s.marker_b) == "chose_A", s.id
        assert classify_answer(s.contaminating_history, s.marker_a, s.marker_b) == "chose_B", s.id


# ---------------------------------------------------------------------------
# Applicability-judgment scenario set (phase 3) — invariants
# ---------------------------------------------------------------------------


def test_applicability_case_label() -> None:
    assert load_case(_APPLICABILITY_PATH) == "applicability-judgment"


def test_applicability_scenarios_shape_and_taxonomy() -> None:
    scenarios = load_scenarios(_APPLICABILITY_PATH)
    assert len(scenarios) == 10, "expected 10 applicability scenarios"
    assert len({s.id for s in scenarios}) == 10, "ids must be unique"
    from collections import Counter

    taxonomy = {
        "scope-version",
        "scope-project",
        "scope-subsystem",
        "scope-superseded",
        "scope-client",
    }
    counts = Counter(s.taxonomy_type for s in scenarios)
    assert set(counts) == taxonomy, f"unexpected taxonomy: {set(counts)}"
    assert all(counts[t] == 2 for t in taxonomy), f"expected 2 per type: {counts}"


def test_applicability_scenario_marker_and_scope_invariants() -> None:
    import re

    for s in load_scenarios(_APPLICABILITY_PATH):
        # Same four-way marker containment as the ambiguous set: A in relevant only,
        # B in contaminating only. Every contaminating_history argues B (no benign here).
        assert re.search(s.marker_a, s.relevant_history, re.IGNORECASE), s.id
        assert re.search(s.marker_a, s.contaminating_history, re.IGNORECASE) is None, s.id
        assert re.search(s.marker_b, s.contaminating_history, re.IGNORECASE), s.id
        assert re.search(s.marker_b, s.relevant_history, re.IGNORECASE) is None, s.id
        # The convention value must NOT be recoverable from the task text alone —
        # otherwise it degrades to the ambiguous/explicit case. The task names both
        # options (it asks "A or B"), but neither marker may resolve to a single
        # choice there; classify_answer on the task must be 'ambiguous'.
        assert classify_answer(s.current_task, s.marker_a, s.marker_b) == "ambiguous", (
            f"{s.id}: task text resolves the convention; baseline would not be uncertain"
        )


def test_focused_superseded_scenarios_are_multi_case_and_detection_clean() -> None:
    scenarios = load_scenarios(_SUPERSEDED_PATH)
    assert load_case(_SUPERSEDED_PATH) == "applicability-judgment"
    assert len(scenarios) >= 2
    assert len({scenario.id for scenario in scenarios}) == len(scenarios)
    assert {scenario.taxonomy_type for scenario in scenarios} == {"scope-superseded"}
    for scenario in scenarios:
        assert classify_answer(scenario.current_task, scenario.marker_a, scenario.marker_b) == "ambiguous"
        assert classify_answer(scenario.relevant_history, scenario.marker_a, scenario.marker_b) == "chose_A"
        assert classify_answer(scenario.contaminating_history, scenario.marker_a, scenario.marker_b) == "chose_B"


def test_leading_is_primary_for_non_explicit_cases() -> None:
    # The CLI/report primary-detector rule: strict for explicit-task, leading for
    # every other case. Verified through the case label the report would carry.
    assert load_case() == "explicit-task"                       # strict primary
    assert load_case(_AMBIGUOUS_PATH) == "ambiguous-task"       # leading primary
    assert load_case(_APPLICABILITY_PATH) == "applicability-judgment"  # leading primary


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
# Differential metrics (the AMBIGUOUS-task headline)
# ---------------------------------------------------------------------------


def test_diff_with_band_empty_safe() -> None:
    d = _diff_with_band(0, 0, 0, 0)
    assert d["diff"] is None and d["wilson_95"] is None and d["excludes_zero"] is None
    d2 = _diff_with_band(3, 5, 0, 0)
    assert d2["diff"] is None


def test_diff_with_band_sign_and_zero_exclusion() -> None:
    # Big, well-separated proportions -> positive diff whose band excludes 0.
    d = _diff_with_band(20, 20, 2, 20)  # 1.0 vs 0.1
    assert d["diff"] == 1.0 - 0.1
    lo, hi = d["wilson_95"]
    assert lo > 0 and hi > 0 and d["excludes_zero"] is True
    # Equal proportions -> zero diff, band spans 0.
    d0 = _diff_with_band(10, 20, 10, 20)
    assert d0["diff"] == 0.0 and d0["excludes_zero"] is False
    lo0, hi0 = d0["wilson_95"]
    assert lo0 < 0 < hi0
    # Negative direction is reported as negative.
    dn = _diff_with_band(2, 20, 20, 20)
    assert dn["diff"] < 0 and dn["excludes_zero"] is True


def test_differential_block_present_and_directional() -> None:
    from evals.pull_contamination.harness import Trial

    def mk(condition: str, classification: str) -> Trial:
        return Trial(
            scenario_id="s", taxonomy_type="t", seed=0, condition=condition,
            classification=classification, used_history=False, answer_preview="",
        )

    # Ambiguous-style shape: baseline split, relevant lifts A, contaminating lifts B.
    trials = [
        mk(CONDITION_NO_HISTORY, "chose_A"), mk(CONDITION_NO_HISTORY, "chose_B"),
        mk(CONDITION_RELEVANT, "chose_A"), mk(CONDITION_RELEVANT, "chose_A"),
        mk(CONDITION_CONTAMINATING, "chose_B"), mk(CONDITION_CONTAMINATING, "chose_B"),
    ]
    m = compute_metrics(trials)
    diff = m["differential"]
    # relevant A-rate 1.0 vs baseline 0.5 -> positive lift.
    assert diff["relevant_lift"]["diff"] == 0.5
    # contaminating B-rate 1.0 vs baseline B-rate 0.5 -> positive harm.
    assert diff["contamination_harm"]["diff"] == 0.5


def test_differential_empty_safe() -> None:
    m = compute_metrics([])
    diff = m["differential"]
    assert diff["relevant_lift"]["diff"] is None
    assert diff["contamination_harm"]["diff"] is None
    # leading_choice block is present and also empty-safe.
    assert m["leading_choice"]["differential"]["relevant_lift"]["diff"] is None


def test_leading_choice_block_reads_decision_first_field() -> None:
    from evals.pull_contamination.harness import Trial

    # Strict says ambiguous (both markers), leading says chose_A (decision-first).
    trials = [
        Trial(
            scenario_id="s", taxonomy_type="t", seed=i, condition=CONDITION_NO_HISTORY,
            classification="ambiguous", used_history=False, answer_preview="",
            classification_leading="chose_A",
        )
        for i in range(4)
    ]
    m = compute_metrics(trials)
    # Strict headline sees no A; leading headline sees all A.
    assert m["baseline_choose_A_rate"]["rate"] == 0.0
    assert m["leading_choice"]["baseline_choose_A_rate"]["rate"] == 1.0


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
