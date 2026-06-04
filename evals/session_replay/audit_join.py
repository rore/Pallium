"""Pivot transcript turns to ``query_audit_log`` rows in the Pallium DB.

The DB is opened read-only. Joins are best-effort — if no audit row exists
(e.g. the transcript predates Pallium being installed, or the prompt was
deduped by the hook layer) the row is left without a match and the runner
classifies the failure stage as ``no_audit_match``.

Production DB location is taken from ``$PALLIUM_DB_PATH`` if set, otherwise
the default ``~/.pallium/data/pallium.db``.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


DEFAULT_DB_PATH = str(Path.home() / ".pallium" / "data" / "pallium.db")


def resolve_db_path(override: str | None = None) -> str:
    """Pick the DB path: explicit override → env var → default."""
    if override:
        return override
    env = os.environ.get("PALLIUM_DB_PATH")
    if env:
        return env
    return DEFAULT_DB_PATH


@contextmanager
def open_audit_db(path: str) -> Iterator[sqlite3.Connection]:
    """Open the Pallium DB read-only via SQLite URI."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        yield conn
    finally:
        conn.close()


def _query_prefix(text: str, n: int = 100) -> str:
    """Take the first ``n`` chars of the user text, stripped of LIKE wildcards."""
    return (text or "").strip()[:n].replace("%", "").replace("_", " ")


def find_audit_rows(
    cur: sqlite3.Cursor,
    user_text: str,
    container_ref: str | None = None,
    limit: int = 3,
) -> list[dict]:
    """Return up to ``limit`` audit rows whose ``query_text`` starts with the
    user-text prefix. Restricts by container_ref when provided."""
    if not user_text or not user_text.strip():
        return []
    like = _query_prefix(user_text) + "%"
    sql = (
        "SELECT id, container_ref, query_text, should_inject, "
        "       decision_reason, injected_blocks_json, "
        "       candidate_scores_json, created_at "
        "FROM query_audit_log "
        "WHERE query_text LIKE ? "
    )
    params: list = [like]
    if container_ref:
        sql += "AND container_ref = ? "
        params.append(container_ref)
    sql += "ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except sqlite3.DatabaseError:
        return []
    return [
        {
            "audit_id": r[0],
            "container_ref": r[1],
            "query_text": r[2],
            "should_inject": bool(r[3]),
            "decision_reason": r[4],
            "injected_blocks_json": r[5],
            "candidate_scores_json": r[6],
            "created_at": r[7],
        }
        for r in rows
    ]


def fetch_memory_lifecycles(
    cur: sqlite3.Cursor,
    memory_ids: list[str],
) -> dict[str, str]:
    """Map memory_object_id → lifecycle for the given ids. Missing ids are
    silently dropped — caller treats them as ``unknown``.
    """
    out: dict[str, str] = {}
    if not memory_ids:
        return out
    # SQLite has a default 999-parameter cap; chunk defensively.
    for i in range(0, len(memory_ids), 200):
        chunk = memory_ids[i : i + 200]
        placeholders = ",".join("?" for _ in chunk)
        try:
            cur.execute(
                f"SELECT id, lifecycle FROM memory_objects WHERE id IN ({placeholders})",
                chunk,
            )
            for row in cur.fetchall():
                out[row[0]] = row[1]
        except sqlite3.DatabaseError:
            continue
    return out


def decode_candidates(audit_row: dict) -> tuple[list[dict], list[dict]]:
    """Decode (candidate_scores_json, injected_blocks_json) into lists.

    Both fields can be missing or invalid JSON in legacy rows; in those
    cases an empty list is returned for that lane. The schema mirrors the
    one written by the production routing pipeline; see
    ``query_audit_log.candidate_scores_json`` for canonical fields.
    """
    cs_raw = audit_row.get("candidate_scores_json")
    inj_raw = audit_row.get("injected_blocks_json")
    cs: list[dict] = []
    inj: list[dict] = []
    if cs_raw:
        try:
            parsed = json.loads(cs_raw)
            if isinstance(parsed, list):
                cs = [c for c in parsed if isinstance(c, dict)]
        except (json.JSONDecodeError, ValueError):
            cs = []
    if inj_raw:
        try:
            parsed = json.loads(inj_raw)
            if isinstance(parsed, list):
                inj = [c for c in parsed if isinstance(c, dict)]
        except (json.JSONDecodeError, ValueError):
            inj = []
    return cs, inj
