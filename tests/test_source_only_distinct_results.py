from __future__ import annotations

import pytest

from core.models import EvidenceReference, QueryResultItem
from core.query import _collapse_source_duplicates
from retrieval.common import build_source_content_fingerprint


def _item(source_id: str, content: str, **kwargs: str | None) -> QueryResultItem:
    source_type = kwargs.get("source_type", "chat")
    role = kwargs.get("role", "user")
    actor_ref = kwargs.get("actor_ref", "actor")
    container_ref = kwargs.get("container_ref", "container")
    thread_ref = kwargs.get("thread_ref", "thread")
    evidence = EvidenceReference(
        source_item_id=source_id,
        source_type=source_type or "chat",
        source_id=source_id,
        role=role,
        actor_ref=actor_ref,
        container_ref=container_ref,
        thread_ref=thread_ref,
    )
    return QueryResultItem(
        result_kind="source_hit",
        source_item_id=source_id,
        source_type=source_type,
        role=role,
        actor_ref=actor_ref,
        container_ref=container_ref,
        thread_ref=thread_ref,
        excerpt=content,
        source_content_fingerprint=build_source_content_fingerprint(content),
        score=1,
        evidence=[evidence],
    )


def test_normalized_equivalence_keeps_first_and_merges_provenance() -> None:
    first = _item("a", "Use  the café today safely!", score=1)
    second = _item("b", "USE  the café today safely!", score=2)
    out = _collapse_source_duplicates([first, second])
    assert [item.source_item_id for item in out] == ["a"]
    assert [e.source_item_id for e in out[0].evidence] == ["a", "b"]
    assert out[0].score == 1


def test_duplicate_fills_freed_slot_and_order_is_stable() -> None:
    items = [_item(str(i), "same text repeated for this test") for i in range(4)] + [
        _item("distinct", "other answer")
    ]
    out = _collapse_source_duplicates(items)
    assert [item.source_item_id for item in out] == ["0", "distinct"]


@pytest.mark.parametrize("count", [0, 1, 3, 6])


def test_empty_one_max_and_over_max_are_bounded(count: int) -> None:
    items = [_item(str(i), f"content {i}") for i in range(count)]
    out = _collapse_source_duplicates(items)
    assert [item.source_item_id for item in out] == [str(i) for i in range(count)]


def test_non_exact_unicode_cross_script_and_different_context_remain_distinct() -> None:
    items = [
        _item("latin", "same text"),
        _item("cyrillic", "саме текст"),
        _item("actor", "same text", actor_ref="other"),
        _item("thread", "same text", thread_ref="other-thread"),
        _item("role", "same text", role="assistant"),
        _item("kind", "same text", source_type="tool"),
    ]
    out = _collapse_source_duplicates(items)
    assert [item.source_item_id for item in out] == [
        "latin",
        "cyrillic",
        "actor",
        "thread",
        "role",
        "kind",
    ]


def test_memory_and_different_decision_are_unchanged() -> None:
    source = _item("source", "use item event time")
    memory = QueryResultItem(
        result_kind="memory_hit", memory_object_id="m", score=9, evidence=[]
    )
    different = _item("different", "use arrival time")
    out = _collapse_source_duplicates([source, memory, different])
    assert out == [source, memory, different]


def test_punctuation_boundaries_do_not_merge_identifiers() -> None:
    items = [
        _item("version", "v1.2"),
        _item("compact", "v12"),
        _item("plus", "C++"),
        _item("hash", "C#"),
        _item("letter", "C"),
        _item("hyphen", "a-b"),
        _item("space", "a b"),
    ]
    out = _collapse_source_duplicates(items)
    assert [item.source_item_id for item in out] == [
        "version",
        "compact",
        "plus",
        "hash",
        "letter",
        "hyphen",
        "space",
    ]


def test_sentence_punctuation_normalizes_without_joining_identifier_parts() -> None:
    punctuation_variants = [
        _item("a", "Decision, use the stable queue for retries today."),
        _item("b", "Decision use the stable queue for retries today"),
    ]
    identifiers = [
        _item("version", "Decision uses API v1.2 for all stable clients today."),
        _item("compact", "Decision uses API v12 for all stable clients today."),
    ]
    items = punctuation_variants + identifiers

    out = _collapse_source_duplicates(items)

    assert [item.source_item_id for item in out] == ["a", "version", "compact"]

def test_nfkc_case_and_whitespace_normalize() -> None:
    items = [
        _item("a", "ＡＬＰＨＡ  beta gamma delta today"),
        _item("b", " alpha beta gamma delta today "),
    ]
    out = _collapse_source_duplicates(items)
    assert [item.source_item_id for item in out] == ["a"]

def test_short_common_repeats_remain_distinct() -> None:
    items = [_item("a", "yes"), _item("b", "YES")]
    out = _collapse_source_duplicates(items)
    assert [item.source_item_id for item in out] == ["a", "b"]
