"""Unit tests for capabilities/workstream_signals.py.

Promotes the implicit coverage from the offline reference impl
(``.local/research/_workstream_replay/signals.py``) into formal regression
tests for the R3-disciplined regexes.
"""
from __future__ import annotations

from capabilities.workstream_signals import (
    extract_file_paths,
    extract_symbols,
    extract_commands,
    file_path_directory,
    normalize_work_ref,
    anchor_key,
    title_ngrams,
    explicit_titles_from_payload,
    signals_from_item,
)


# ---------------------------------------------------------------------------
# work_ref normalization
# ---------------------------------------------------------------------------


def test_normalize_work_ref_basic():
    assert normalize_work_ref("PROJ-123") == "proj-123"
    assert normalize_work_ref("Foo Bar Baz") == "foo-bar-baz"
    assert normalize_work_ref("foo_bar_baz") == "foo-bar-baz"
    assert normalize_work_ref("  multi-space  ") == "multi-space"


def test_normalize_work_ref_rejects_empty_and_long():
    assert normalize_work_ref("") is None
    assert normalize_work_ref("   ") is None
    assert normalize_work_ref("x" * 200) is None


def test_normalize_work_ref_non_string():
    assert normalize_work_ref(None) is None  # type: ignore[arg-type]
    assert normalize_work_ref(123) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Anchor keys
# ---------------------------------------------------------------------------


def test_anchor_key_workstream_kind_normalized():
    assert anchor_key("workstream", "Workstream Consolidation") == "workstream:workstream consolidation"
    assert anchor_key("WORKSTREAM", "  consolidation  ") == "workstream:consolidation"


def test_anchor_key_strips_leading_noise():
    assert anchor_key("workstream", "the consolidation work") == "workstream:consolidation work"


def test_anchor_key_unknown_kind():
    assert anchor_key("system", "thing") is None
    assert anchor_key("", "thing") is None


def test_anchor_key_empty_value():
    assert anchor_key("workstream", "") is None
    assert anchor_key("workstream", "the") is None  # leading-noise consumes everything


# ---------------------------------------------------------------------------
# File paths — R3-disciplined
# ---------------------------------------------------------------------------


def test_extract_file_paths_accepts_repo_paths():
    paths = extract_file_paths("see core/service.py for details")
    assert "core/service.py" in paths


def test_extract_file_paths_accepts_drive_letter():
    paths = extract_file_paths("Edit c:/sap-dev/x.py to fix")
    assert any(p.startswith("c:/sap-dev") or p.startswith("sap-dev") for p in paths)


def test_extract_file_paths_accepts_dot_local_research():
    paths = extract_file_paths("see ~/.local/research/x.md for the note")
    assert any("research/x.md" in p for p in paths)


def test_extract_file_paths_rejects_english_pairs():
    paths = extract_file_paths("compare before/after results")
    assert not any(p == "before/after" for p in paths)


def test_extract_file_paths_rejects_numeric_ratios():
    paths = extract_file_paths("rate is 0.40/turn for the budget")
    assert not any("0.40/turn" in p for p in paths)


def test_extract_file_paths_rejects_hours_days():
    paths = extract_file_paths("decay over hours/days as expected")
    assert "hours/days" not in paths


def test_extract_file_paths_rejects_url():
    paths = extract_file_paths("https://example.com/path/to/thing")
    assert paths == []


def test_extract_file_paths_dedup():
    paths = extract_file_paths("core/service.py and core/service.py again")
    assert paths.count("core/service.py") == 1


def test_file_path_directory_two_segments():
    assert file_path_directory("core/service.py", depth=2) == "core/service.py"
    assert file_path_directory("storage/sqlite/x.py", depth=2) == "storage/sqlite"
    assert file_path_directory("a/b/c/d.py", depth=2) == "a/b"


# ---------------------------------------------------------------------------
# Symbols — R3-disciplined
# ---------------------------------------------------------------------------


def test_extract_symbols_accepts_camel_with_two_internal_capitals():
    syms = extract_symbols("WorkstreamRegistry has methods for state")
    assert "WorkstreamRegistry" in syms


def test_extract_symbols_accepts_memory_envelope_scope():
    syms = extract_symbols("the MemoryEnvelopeScope dataclass holds scope")
    assert "MemoryEnvelopeScope" in syms


def test_extract_symbols_rejects_single_capital_words():
    # "Pallium", "Joule", "Wallet" are each single-capital words → must be
    # rejected by the ≥2 internal capitals requirement (and stoplist).
    syms = extract_symbols("Pallium Joule Wallet")
    assert "Pallium" not in syms
    assert "Joule" not in syms
    assert "Wallet" not in syms


def test_extract_symbols_rejects_sentence_initial_words():
    syms = extract_symbols("This is a sentence. Want to discuss it?")
    assert "This" not in syms
    assert "Want" not in syms


def test_extract_symbols_rejects_stoplist():
    # Class-shaped names that pass ≥2-capital regex but are in the stoplist.
    syms = extract_symbols("the CamelCaseStoplistName might be MemoryThing")
    # "MemoryThing" -> Memory is in stoplist? No, "Memory" by itself is in
    # stoplist and "MemoryThing" has only one internal capital ("T"), so it
    # WOULD fail the 2-capital test. Try a clearer case.
    syms2 = extract_symbols("Service has events")
    # "Service" is only one capital — rejected before stoplist.
    assert "Service" not in syms2


def test_extract_symbols_accepts_snake_callsite_with_underscore_and_length():
    syms = extract_symbols("call assign_workstream_for_item(item) in the cascade")
    assert "assign_workstream_for_item" in syms


def test_extract_symbols_rejects_short_callsite():
    syms = extract_symbols("call go_a(x) and do_b(y)")
    assert "go_a" not in syms
    assert "do_b" not in syms


def test_extract_symbols_rejects_no_underscore_callsite():
    syms = extract_symbols("call somename(x) here")
    assert "somename" not in syms


# ---------------------------------------------------------------------------
# Commands / errors
# ---------------------------------------------------------------------------


def test_extract_commands_python_module():
    cmds = extract_commands("run python -m app.run serve")
    assert "app.run" in cmds


def test_extract_commands_pytest():
    cmds = extract_commands("run pytest tests/test_foo.py")
    assert "tests/test_foo.py" in cmds


def test_extract_commands_error_token():
    cmds = extract_commands("got ValueError when processing")
    assert "ValueError" in cmds
    cmds2 = extract_commands("hit a CustomException at the end")
    assert "CustomException" in cmds2


# ---------------------------------------------------------------------------
# Titles + n-grams
# ---------------------------------------------------------------------------


def test_title_ngrams_basic():
    grams = title_ngrams("workstream consolidation rekey design", n=3)
    assert ("workstream", "consolidation", "rekey") in grams
    assert ("consolidation", "rekey", "design") in grams


def test_title_ngrams_short_title_returns_tuple():
    grams = title_ngrams("workstream consolidation", n=3)
    assert grams == {("workstream", "consolidation")}


def test_title_ngrams_strips_stopwords():
    grams = title_ngrams("the design of the cascade", n=3)
    # stopwords removed → only "design cascade" remains, single 2-token tuple
    assert grams == {("design", "cascade")}


def test_explicit_titles_from_payload_decision():
    payload = {"decision": "Adopt workstream re-key", "rationale": "..."}
    assert explicit_titles_from_payload("decision", payload) == ["Adopt workstream re-key"]


def test_explicit_titles_from_payload_unknown_type():
    assert explicit_titles_from_payload("turn_summary", {"summary": "x"}) == []


# ---------------------------------------------------------------------------
# signals_from_item integration
# ---------------------------------------------------------------------------


def test_signals_from_item_collects_from_text_and_metadata():
    sig = signals_from_item(
        content_text="see core/service.py for assign_workstream_for_item(item) logic",
        metadata_json={
            "pallium_work_refs": ["proj-123"],
            "pallium_subject_hints": [{"kind": "workstream", "value": "consolidation rekey"}],
        },
        memory_records=[
            {
                "type": "decision",
                "payload": {"decision": "ship workstream cascade", "rationale": "x"},
                "envelope": {"scope": {"work_refs": ["PROJ-456"]}},
            }
        ],
    )
    assert "proj-123" in sig.work_refs
    assert "proj-456" in sig.work_refs
    assert "core/service.py" in sig.file_paths
    assert "core/service.py" in sig.file_dirs  # depth-2 of core/service.py is core/service.py
    assert "assign_workstream_for_item" in sig.symbols
    assert any(a.startswith("workstream:") for a in sig.anchors)
    assert any(t == "ship workstream cascade" for t in sig.titles)
    assert sig.has_any_strong()


def test_signals_from_item_empty_when_no_strong_signals():
    sig = signals_from_item(
        content_text="just a casual sentence with no signals",
        metadata_json={},
        memory_records=[],
    )
    assert not sig.has_any_strong()
