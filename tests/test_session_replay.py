"""Tests for evals.session_replay.

Uses synthesized fixtures so the tests do not depend on any real Pallium
DB, real Claude Code session, or real Codex session. Where DB behavior is
exercised, an in-memory SQLite DB is built with the relevant subset of
the production schema.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from evals.session_replay.audit_join import (
    decode_candidates,
    fetch_memory_lifecycles,
    find_audit_rows,
    resolve_db_path,
)
from evals.session_replay.parse import parse, turns
from evals.session_replay.runner import RunnerConfig, run, scan_session_transcript
from evals.session_replay.signals import (
    detect_future_oracle,
    detect_recall_intent,
    detect_repeated_work,
    is_boilerplate_only,
    turn_pallium_blocks,
)
from evals.session_replay.stage import classify_stage


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _wrap_msg(role: str, content) -> dict:
    return {
        "type": "user" if role == "user" else "assistant",
        "message": {"role": role, "content": content},
        "timestamp": "2026-06-04T10:00:00.000Z",
        "sessionId": "test-session-1",
        "cwd": "C:/Dev/rore/Pallium",
    }


def _claude_attachment(stdout: str, hook_event: str = "UserPromptSubmit") -> dict:
    return {
        "type": "attachment",
        "attachment": {
            "type": "hook_success",
            "hookEvent": hook_event,
            "stdout": stdout,
        },
        "timestamp": "2026-06-04T10:00:00.000Z",
        "sessionId": "test-session-1",
        "cwd": "C:/Dev/rore/Pallium",
    }


def _codex_envelope(payload_type: str, payload_extra: dict) -> dict:
    return {
        "timestamp": "2026-06-04T10:00:00.000Z",
        "type": "response_item",
        "payload": {"type": payload_type, **payload_extra},
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )


def _claude_session(tmp_path: Path) -> Path:
    """Build a Claude Code transcript covering: SessionStart system prompt,
    a user prompt with an attached Pallium injection, an assistant turn
    that does Read+Grep, then a continuation-style user prompt with no
    Pallium injection but two more discovery calls (future_oracle hit).
    """
    rows: list[dict] = []
    rows.append({
        "type": "attachment",
        "attachment": {
            "type": "hook_additional_context",
            "hookEvent": "SessionStart",
            "content": ["session bootstrap text"],
        },
        "timestamp": "2026-06-04T09:59:00Z",
        "sessionId": "test-session-1",
        "cwd": "C:/Dev/rore/Pallium",
    })
    rows.append(_wrap_msg("user", "Investigate the parser please."))
    rows.append(_claude_attachment(
        '[Pallium memory — container: git:test/repo]\n\n'
        '[Decision | ref:abc123] We use the bracketed format. [+expand]\n\n'
        '[End Pallium memory]'
    ))
    rows.append(_wrap_msg("assistant", [
        {"type": "text", "text": "Looking..."},
        {"type": "tool_use", "id": "tu-1", "name": "Read",
         "input": {"file_path": "evals/session_replay/parse.py"}},
    ]))
    rows.append(_wrap_msg("user", [
        {"type": "tool_result", "tool_use_id": "tu-1", "content": "file content here"}
    ]))
    rows.append(_wrap_msg("assistant", [
        {"type": "tool_use", "id": "tu-2", "name": "Grep",
         "input": {"pattern": "Pallium memory", "path": "evals/"}},
    ]))
    rows.append(_wrap_msg("user", [
        {"type": "tool_result", "tool_use_id": "tu-2", "content": "matches"}
    ]))
    # Vague continuation user prompt → discovery only
    rows.append(_wrap_msg("user", "continue please"))
    rows.append(_wrap_msg("assistant", [
        {"type": "tool_use", "id": "tu-3", "name": "Read",
         "input": {"file_path": "evals/session_replay/parse.py"}},
        {"type": "tool_use", "id": "tu-4", "name": "Grep",
         "input": {"pattern": "Pallium memory", "path": "evals/"}},
    ]))
    rows.append(_wrap_msg("user", [
        {"type": "tool_result", "tool_use_id": "tu-3", "content": "x"},
        {"type": "tool_result", "tool_use_id": "tu-4", "content": "y"},
    ]))
    fp = tmp_path / "claude.jsonl"
    _write_jsonl(fp, rows)
    return fp


def _codex_session(tmp_path: Path) -> Path:
    """Build a Codex rollout covering session_meta, user message, function_call+output,
    a continuation prompt, and another discovery pair.
    """
    rows: list[dict] = []
    rows.append({
        "timestamp": "2026-06-04T09:59:00Z",
        "type": "session_meta",
        "payload": {
            "id": "test-codex-1",
            "cwd": "C:/Dev/rore/Pallium",
            "originator": "codex_vscode",
        },
    })
    rows.append(_codex_envelope("message", {
        "role": "user",
        "content": [{"type": "input_text", "text": "continue with the runner please"}],
    }))
    rows.append(_codex_envelope("message", {
        "role": "developer",
        "content": [{"type": "input_text", "text":
            "[Pallium memory — container: git:test/repo]\n\n"
            "[Decision | ref:codex-ref-1] codex-side context. [+expand]\n\n"
            "[End Pallium memory]"
        }],
    }))
    rows.append(_codex_envelope("function_call", {
        "name": "shell",
        "call_id": "c-1",
        "arguments": json.dumps({"command": ["cat", "runner.py"]}),
    }))
    rows.append(_codex_envelope("function_call_output", {
        "call_id": "c-1",
        "output": "file content",
    }))
    # Continuation
    rows.append(_codex_envelope("message", {
        "role": "user",
        "content": [{"type": "input_text", "text": "continue"}],
    }))
    rows.append(_codex_envelope("function_call", {
        "name": "shell",
        "call_id": "c-2",
        "arguments": json.dumps({"command": ["rg", "Pallium memory"]}),
    }))
    rows.append(_codex_envelope("function_call_output", {
        "call_id": "c-2", "output": "matches",
    }))
    rows.append(_codex_envelope("function_call", {
        "name": "shell",
        "call_id": "c-3",
        "arguments": json.dumps({"command": ["cat", "runner.py"]}),
    }))
    rows.append(_codex_envelope("function_call_output", {
        "call_id": "c-3", "output": "more content",
    }))
    fp = tmp_path / "codex.jsonl"
    _write_jsonl(fp, rows)
    return fp


def _build_audit_db(tmp_path: Path) -> Path:
    """Build a minimal Pallium DB containing query_audit_log + memory_objects.

    Schema mirrors the columns the runner reads — we keep this narrow on
    purpose: the production schema lives in storage/sqlite_schema.py and the
    runner's only contract with it is the column names below.
    """
    db = tmp_path / "test-pallium.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE query_audit_log (
            id TEXT PRIMARY KEY,
            created_at TEXT,
            container_ref TEXT,
            query_text TEXT,
            should_inject INTEGER,
            decision_reason TEXT,
            injected_blocks_json TEXT,
            candidate_scores_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE memory_objects (
            id TEXT PRIMARY KEY,
            lifecycle TEXT
        )
    """)

    # An injected_ok case
    conn.execute(
        "INSERT INTO query_audit_log VALUES (?,?,?,?,?,?,?,?)",
        (
            "audit-injected",
            "2026-06-04T10:00:00Z",
            "git:test/repo",
            "Investigate the parser please.",
            1,
            "carry_forward_available",
            json.dumps([{"memory_object_id": "mem-A", "title": "T", "text": "..."}]),
            json.dumps([{
                "memory_object_id": "mem-A",
                "memory_type": "decision",
                "routing_score": 800,
                "lexical_score": 90.0,
                "vector_score": 900,
                "routing_rank": 1,
                "layer": "decision",
                "support_grade": "strong",
                "suppression_reason_code": None,
                "excluded_reason_code": None,
                "post_routing_drop_reason": None,
                "injected": True,
            }]),
        ),
    )
    # A routing_suppressed case keyed by the continuation prompt
    conn.execute(
        "INSERT INTO query_audit_log VALUES (?,?,?,?,?,?,?,?)",
        (
            "audit-suppressed",
            "2026-06-04T10:01:00Z",
            "git:test/repo",
            "continue please",
            0,
            "same_thread_context_sufficient",
            json.dumps([]),
            json.dumps([{
                "memory_object_id": "mem-B",
                "memory_type": "task_checkpoint",
                "routing_score": 700,
                "lexical_score": 80.0,
                "vector_score": 880,
                "routing_rank": 1,
                "layer": "task_checkpoint",
                "support_grade": "strong",
                "suppression_reason_code": None,
                "excluded_reason_code": "displaced_by_cross_thread_checkpoint_suppression",
                "post_routing_drop_reason": None,
                "injected": False,
            }]),
        ),
    )
    conn.execute("INSERT INTO memory_objects VALUES (?, ?)", ("mem-A", "active"))
    conn.execute("INSERT INTO memory_objects VALUES (?, ?)", ("mem-B", "active"))
    # And a superseded memory that we'll wire into a third audit row
    conn.execute("INSERT INTO memory_objects VALUES (?, ?)", ("mem-C", "superseded"))
    conn.execute(
        "INSERT INTO query_audit_log VALUES (?,?,?,?,?,?,?,?)",
        (
            "audit-superseded",
            "2026-06-04T10:02:00Z",
            "git:test/repo",
            "continue with the runner please",
            0,
            "no_relevant_memory",
            json.dumps([]),
            json.dumps([{
                "memory_object_id": "mem-C",
                "memory_type": "task_checkpoint",
                "routing_score": 600,
                "lexical_score": 70.0,
                "vector_score": 850,
                "routing_rank": 1,
                "layer": "task_checkpoint",
                "support_grade": "strong",
                "suppression_reason_code": None,
                "excluded_reason_code": None,
                "post_routing_drop_reason": None,
                "injected": False,
            }]),
        ),
    )
    conn.commit()
    conn.close()
    return db


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def test_parse_claude_extracts_messages_and_tools(tmp_path: Path):
    fp = _claude_session(tmp_path)
    events = parse(str(fp))
    kinds = [e["kind"] for e in events]
    # SessionStart attachment + first user_msg + Pallium attachment +
    # assistant text + tool_call + tool_result + assistant tool_call +
    # tool_result + user_msg "continue" + 2 tool_calls + 2 tool_results
    assert "system_inject" in kinds
    assert kinds.count("user_msg") == 2
    assert kinds.count("tool_call") == 4
    assert kinds.count("tool_result") == 4
    assert all(e["source_format"] == "claude" for e in events)


def test_parse_claude_pallium_block_is_extracted(tmp_path: Path):
    fp = _claude_session(tmp_path)
    events = parse(str(fp))
    inj = [e for e in events if e["kind"] == "system_inject" and e.get("pallium_blocks")]
    assert inj, "expected at least one system_inject with parsed Pallium blocks"
    refs = [b["ref"] for ev in inj for b in ev["pallium_blocks"]]
    assert "abc123" in refs


def test_parse_codex_extracts_messages_and_tools(tmp_path: Path):
    fp = _codex_session(tmp_path)
    events = parse(str(fp))
    assert all(e["source_format"] == "codex" for e in events)
    assert any(e["kind"] == "session_meta" for e in events)
    assert any(e["kind"] == "system_inject" and e.get("pallium_blocks") for e in events)
    tool_calls = [e for e in events if e["kind"] == "tool_call"]
    assert len(tool_calls) == 3
    # call_id pairing visible at the event level
    ids = {e["tool_id"] for e in tool_calls}
    assert ids == {"c-1", "c-2", "c-3"}


def test_turns_groups_user_prompts_and_attaches_injections(tmp_path: Path):
    fp = _claude_session(tmp_path)
    events = parse(str(fp))
    grouped = turns(events)
    assert len(grouped) == 2
    # First turn has the Pallium attachment as a post_inject
    first_blocks = turn_pallium_blocks(grouped[0])
    assert len(first_blocks) == 1
    assert first_blocks[0]["ref"] == "abc123"
    # Second turn has no Pallium injection
    assert turn_pallium_blocks(grouped[1]) == []


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def test_recall_intent_matches_continuation_prompts():
    assert detect_recall_intent({"user_text": "continue with the spec"}) is not None
    assert detect_recall_intent({"user_text": "what did we decide"}) is not None
    assert detect_recall_intent({"user_text": "summarize the changes"}) is not None
    # Negative
    assert detect_recall_intent({"user_text": "implement a parser"}) is None


def test_future_oracle_requires_vague_prompt_and_discovery_only():
    turn_ok = {
        "user_text": "continue",
        "events": [
            {"kind": "tool_call", "tool_name": "Read",
             "tool_input": {"file_path": "x.py"}},
            {"kind": "tool_call", "tool_name": "Grep",
             "tool_input": {"pattern": "foo"}},
        ],
    }
    assert detect_future_oracle(turn_ok) is not None

    # Same calls but a non-vague prompt → no hit
    assert detect_future_oracle({**turn_ok, "user_text": "implement detailed feature X for the parser"}) is None

    # Has a productive call → no hit
    turn_with_edit = {
        **turn_ok,
        "events": [
            *turn_ok["events"],
            {"kind": "tool_call", "tool_name": "Edit",
             "tool_input": {"file_path": "x.py"}},
        ],
    }
    assert detect_future_oracle(turn_with_edit) is None


def test_repeated_work_detects_cross_turn_repetition():
    turns_ = [
        {"events": [
            {"kind": "tool_call", "tool_name": "Read",
             "tool_input": {"file_path": "FOO.py"}}]},
        {"events": [
            {"kind": "tool_call", "tool_name": "Read",
             "tool_input": {"file_path": "foo.py"}}]},
    ]
    hits = detect_repeated_work(turns_)
    assert any(h["kind"] == "repeated_read" for h in hits)
    # Single-turn (within-turn) repetition should NOT fire
    only_once = [
        {"events": [
            {"kind": "tool_call", "tool_name": "Read",
             "tool_input": {"file_path": "foo.py"}},
            {"kind": "tool_call", "tool_name": "Read",
             "tool_input": {"file_path": "foo.py"}},
        ]}
    ]
    assert detect_repeated_work(only_once) == []


def test_boilerplate_only_filters_system_seed_lines():
    text = (
        "<INSTRUCTIONS>\n"
        "<!-- pallium:start --> long boilerplate "
        "</INSTRUCTIONS>\n"
        "<EXTREMELY_IMPORTANT>more</EXTREMELY_IMPORTANT>"
    )
    assert is_boilerplate_only(text) is True
    assert is_boilerplate_only("ok continue with the spec discussion") is False
    assert is_boilerplate_only("") is True
    # Short *real* prompts (no boilerplate tags) must NOT be filtered —
    # they're the prompts we most want recall-intent to flag.
    assert is_boilerplate_only("continue") is False
    assert is_boilerplate_only("go") is False


# ---------------------------------------------------------------------------
# Stage classifier
# ---------------------------------------------------------------------------

def test_classify_no_audit_match():
    res = classify_stage(None, [], [], None)
    assert res["stage"] == "no_audit_match"
    assert res["top_candidates"] == []


def test_classify_injected_ok():
    audit = {"should_inject": True, "decision_reason": "carry_forward_available"}
    candidates = [{"memory_object_id": "m1", "routing_score": 800,
                   "routing_rank": 1, "injected": True}]
    injected = [{"memory_object_id": "m1"}]
    res = classify_stage(audit, candidates, injected, {"m1": "active"})
    assert res["stage"] == "injected_ok"


def test_classify_routing_suppressed_by_named_code():
    audit = {"should_inject": False, "decision_reason": "no_relevant_memory"}
    candidates = [
        {"memory_object_id": "m1", "routing_score": 700, "routing_rank": 1,
         "excluded_reason_code": "displaced_by_cross_thread_checkpoint_suppression"},
        {"memory_object_id": "m2", "routing_score": 600, "routing_rank": 2,
         "excluded_reason_code": "lower_routing_score_than_selected_limit"},
    ]
    res = classify_stage(audit, candidates, [], {"m1": "active", "m2": "active"})
    assert res["stage"] == "routing_suppressed"
    assert "displaced_by_cross_thread_checkpoint_suppression" in res["evidence"]


def test_classify_superseded_overrides_routing_when_top1_is_superseded():
    audit = {"should_inject": False, "decision_reason": "no_relevant_memory"}
    candidates = [
        {"memory_object_id": "m1", "routing_score": 700, "routing_rank": 1,
         "excluded_reason_code": "lower_routing_score_than_selected_limit"},
    ]
    res = classify_stage(audit, candidates, [], {"m1": "superseded"})
    assert res["stage"] == "superseded"


def test_classify_not_ingested_when_candidates_empty():
    audit = {"should_inject": False, "decision_reason": "no_relevant_memory"}
    res = classify_stage(audit, [], [], {})
    assert res["stage"] == "not_ingested"


def test_classify_retrieval_low_score_when_no_named_codes():
    audit = {"should_inject": False, "decision_reason": "low_score"}
    candidates = [
        {"memory_object_id": "m1", "routing_score": 50, "routing_rank": 1},
    ]
    res = classify_stage(audit, candidates, [], {"m1": "active"})
    assert res["stage"] == "retrieval_low_score"


# ---------------------------------------------------------------------------
# Audit join
# ---------------------------------------------------------------------------

def test_resolve_db_path_prefers_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PALLIUM_DB_PATH", "/env/path.db")
    assert resolve_db_path("/explicit.db") == "/explicit.db"
    assert resolve_db_path(None) == "/env/path.db"
    monkeypatch.delenv("PALLIUM_DB_PATH")
    assert resolve_db_path(None).endswith("pallium.db")


def test_audit_join_finds_row_and_decodes_candidates(tmp_path: Path):
    db = _build_audit_db(tmp_path)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cur = conn.cursor()
    rows = find_audit_rows(cur, "Investigate the parser please.")
    assert rows and rows[0]["audit_id"] == "audit-injected"
    cs, inj = decode_candidates(rows[0])
    assert len(cs) == 1 and cs[0]["memory_object_id"] == "mem-A"
    assert len(inj) == 1


def test_fetch_memory_lifecycles(tmp_path: Path):
    db = _build_audit_db(tmp_path)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cur = conn.cursor()
    out = fetch_memory_lifecycles(cur, ["mem-A", "mem-C", "missing"])
    assert out == {"mem-A": "active", "mem-C": "superseded"}


# ---------------------------------------------------------------------------
# Runner end-to-end
# ---------------------------------------------------------------------------

def test_runner_end_to_end_claude(tmp_path: Path):
    fp = _claude_session(tmp_path)
    db = _build_audit_db(tmp_path)
    cfg = RunnerConfig(
        out_dir=tmp_path / "out",
        db_path=str(db),
    )
    result = run([str(fp)], cfg)
    assert result["n_sessions"] == 1
    assert result["n_rows"] >= 1

    miss_path = Path(result["miss_cases_path"])
    rows = [json.loads(l) for l in miss_path.read_text(encoding="utf-8").splitlines()]
    signals = {r["miss_signal"] for r in rows}
    assert "recall_intent" in signals
    assert "future_oracle" in signals or "repeated_read" in signals
    # The continuation prompt "continue" should pivot to the suppressed audit row
    suppressed = [r for r in rows if r.get("audit_match", {}) and
                  r["audit_match"].get("audit_id") == "audit-suppressed"]
    assert suppressed
    assert any(r["failure_stage"] == "routing_suppressed" for r in suppressed)

    summary_path = Path(result["summary_path"])
    summary = summary_path.read_text(encoding="utf-8")
    assert "session_replay summary" in summary
    assert "routing_suppressed" in summary


def test_runner_handles_missing_db(tmp_path: Path):
    fp = _claude_session(tmp_path)
    cfg = RunnerConfig(
        out_dir=tmp_path / "out",
        db_path=str(tmp_path / "does-not-exist.db"),
    )
    result = run([str(fp)], cfg)
    assert result["db_used"] is False
    rows = [json.loads(l) for l in
            Path(result["miss_cases_path"]).read_text(encoding="utf-8").splitlines()]
    assert all(r["failure_stage"] == "no_audit_match" for r in rows)


def test_runner_codex_pivots_to_superseded_top_candidate(tmp_path: Path):
    fp = _codex_session(tmp_path)
    db = _build_audit_db(tmp_path)
    cfg = RunnerConfig(
        out_dir=tmp_path / "out-codex",
        db_path=str(db),
    )
    result = run([str(fp)], cfg)
    rows = [json.loads(l) for l in
            Path(result["miss_cases_path"]).read_text(encoding="utf-8").splitlines()]
    superseded = [r for r in rows if r.get("failure_stage") == "superseded"]
    assert superseded, f"expected at least one superseded row, got {rows}"


def test_scan_session_dedups_repeated_reads(tmp_path: Path):
    fp = _claude_session(tmp_path)
    rows, meta = scan_session_transcript(str(fp), enable_signals=("repeated_work",))
    rep = [r for r in rows if r["miss_signal"] == "repeated_read"]
    # Both the first and second turn read evals/session_replay/parse.py
    assert any(r["matched_phrase"].endswith("parse.py") for r in rep)
    assert meta["n_turns"] == 2
