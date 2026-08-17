"""Tests for SQLite auto_vacuum default + incremental free-page reclaim.

Covers the three things most likely to silently break:
- a NEW DB is born with auto_vacuum=INCREMENTAL (the pragma must precede WAL);
- reclaim_free_pages() actually drops the freelist after deletions;
- a LEGACY (auto_vacuum=NONE) DB is a harmless no-op, not an error.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from storage.sqlite import SQLiteStorageProvider


def _auto_vacuum(path: str) -> int:
    con = sqlite3.connect(path)
    try:
        return int(con.execute("PRAGMA auto_vacuum").fetchone()[0])
    finally:
        con.close()


def _path(test_db_url: str) -> str:
    return test_db_url.replace("sqlite:///", "")


def test_new_db_is_born_incremental_auto_vacuum(test_db_url: str) -> None:
    # Creating the provider initialises the schema; the connect hook must have
    # set auto_vacuum=INCREMENTAL (2) BEFORE journal_mode=WAL wrote the header.
    SQLiteStorageProvider(test_db_url)
    assert _auto_vacuum(_path(test_db_url)) == 2  # 0=NONE, 1=FULL, 2=INCREMENTAL


def test_reclaim_free_pages_shrinks_freelist_after_deletions(test_db_url: str) -> None:
    provider = SQLiteStorageProvider(test_db_url)
    # Grow the file with a scratch table (recursive CTE — always available), then
    # delete everything to create a sizeable freelist.
    with provider._engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE _scratch (id INTEGER PRIMARY KEY, blob TEXT)")
        conn.exec_driver_sql(
            "INSERT INTO _scratch (blob) "
            "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 4000) "
            "SELECT hex(randomblob(2000)) FROM c"
        )
        conn.exec_driver_sql("DELETE FROM _scratch")

    result = provider.reclaim_free_pages()
    assert result["freelist_before"] > 0, "expected a non-empty freelist after mass deletion"
    assert result["freelist_after"] < result["freelist_before"]
    assert result["reclaimed_pages"] == result["freelist_before"] - result["freelist_after"]
    assert result["reclaimed_pages"] > 0


def test_reclaim_is_noop_on_legacy_none_auto_vacuum(tmp_path: Path) -> None:
    # Pre-create the file with auto_vacuum=NONE and a committed header, so the
    # provider's connect-hook INCREMENTAL pragma is (correctly) ignored.
    db_path = tmp_path / "legacy.db"
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA auto_vacuum=NONE")
    con.execute("CREATE TABLE seed (id INTEGER PRIMARY KEY)")  # commits the header
    con.commit()
    con.close()
    assert _auto_vacuum(str(db_path)) == 0

    provider = SQLiteStorageProvider(f"sqlite:///{db_path}")
    # Still NONE — the persisted mode only changes via a one-time VACUUM.
    assert _auto_vacuum(str(db_path)) == 0
    # Reclaim must not error and reclaims nothing on a NONE database.
    assert provider.reclaim_free_pages()["reclaimed_pages"] == 0


def test_reclaim_free_pages_empty_freelist_is_zero(test_db_url: str) -> None:
    provider = SQLiteStorageProvider(test_db_url)
    assert provider.reclaim_free_pages()["reclaimed_pages"] == 0
