from pathlib import Path

import pytest
from sqlalchemy import text

from storage.sqlite import SQLiteStorageProvider


def _dispose(*stores):
    for store in stores:
        store._engine.dispose()
        if store._relay_engine is not store._engine:
            store._relay_engine.dispose()


def test_isolated_relay_schema_and_legacy_import_are_idempotent(tmp_path: Path) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    legacy = SQLiteStorageProvider(f"sqlite:///{main}")
    legacy.relay_turn(runtime="a", session_ref="s", container_ref="c", actor_ref="u", title=None, max_chars=100, max_messages=1, lease_seconds=1)
    split = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    reopened = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    with split._relay_engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert {"relay_sessions", "relay_messages", "relay_deliveries", "relay_migration_metadata"} <= tables
    assert "memory_objects" not in tables
    assert reopened.relay_list_sessions(container_ref="c", actor_ref="u", runtime=None, include_inactive=True, recent_seconds=1)
    _dispose(legacy, split, reopened)


def test_post_marker_missing_legacy_id_fails_closed(tmp_path: Path) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    legacy = SQLiteStorageProvider(f"sqlite:///{main}")
    legacy.relay_turn(runtime="a", session_ref="s", container_ref="c", actor_ref="u", title=None, max_chars=100, max_messages=1, lease_seconds=1)
    split = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    split._engine.dispose()
    split._relay_engine.dispose()
    with pytest.raises(RuntimeError, match="marker"): 
        SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{tmp_path / 'different.db'}")
    _dispose(legacy)