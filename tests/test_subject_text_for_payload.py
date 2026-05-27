"""Unit tests for core.subject.subject_text_for_payload."""
from __future__ import annotations

from core.subject import subject_text_for_payload


def test_returns_empty_for_none_payload():
    assert subject_text_for_payload("decision", None) == ""


def test_returns_empty_for_empty_payload():
    assert subject_text_for_payload("decision", {}) == ""


def test_generic_subject_key_wins_across_types():
    assert subject_text_for_payload("decision", {"subject": "alpha", "decision": "beta"}) == "alpha"
    assert subject_text_for_payload("note", {"subject": "alpha", "title": "beta"}) == "alpha"


def test_generic_title_falls_through_when_no_subject():
    assert subject_text_for_payload("note", {"title": "the title"}) == "the title"


def test_decision_uses_decision_field():
    assert subject_text_for_payload("decision", {"decision": "ship the gate"}) == "ship the gate"


def test_investigation_outcome_dispatch():
    assert subject_text_for_payload(
        "investigation_outcome", {"investigation_outcome": "root cause is X"}
    ) == "root cause is X"
    assert subject_text_for_payload("investigation_outcome", {"outcome": "X"}) == "X"
    assert subject_text_for_payload("investigation_outcome", {"finding": "Y"}) == "Y"
    assert subject_text_for_payload("investigation_outcome", {"summary": "Z"}) == "Z"


def test_task_checkpoint_uses_summary_or_task():
    assert subject_text_for_payload("task_checkpoint", {"summary": "doing X"}) == "doing X"
    assert subject_text_for_payload("task_checkpoint", {"task": "do Y"}) == "do Y"


def test_thread_summary_uses_summary():
    assert subject_text_for_payload("thread_summary", {"summary": "thread about X"}) == "thread about X"


def test_constraint_memory_uses_constraint_text():
    assert subject_text_for_payload(
        "constraint_memory", {"constraint_text": "no LLM in hot path"}
    ) == "no LLM in hot path"


def test_note_uses_title_then_content():
    assert subject_text_for_payload("note", {"title": "remember X"}) == "remember X"
    assert subject_text_for_payload("note", {"content": "the content"}) == "the content"


def test_atomic_fact_uses_statement():
    assert subject_text_for_payload(
        "atomic_fact", {"statement": "monorepo has parallel topics"}
    ) == "monorepo has parallel topics"


def test_unknown_type_falls_back_to_generic_keys():
    assert subject_text_for_payload("unknown_type", {"subject": "x"}) == "x"
    assert subject_text_for_payload("unknown_type", {"title": "y"}) == "y"
    assert subject_text_for_payload("unknown_type", {"task": "z"}) == "z"
    assert subject_text_for_payload("unknown_type", {"statement": "w"}) == "w"


def test_unknown_type_with_no_generic_key_returns_empty():
    assert subject_text_for_payload("unknown_type", {"random_key": "value"}) == ""


def test_strips_whitespace():
    assert subject_text_for_payload("decision", {"decision": "  spaced  "}) == "spaced"


def test_truncates_at_200_chars():
    long = "x" * 500
    assert len(subject_text_for_payload("decision", {"decision": long})) == 200


def test_non_string_values_ignored():
    assert subject_text_for_payload(
        "decision", {"decision": 42, "subject": ["not", "a", "string"]}
    ) == ""


def test_none_type_with_generic_key():
    assert subject_text_for_payload(None, {"subject": "x"}) == "x"
