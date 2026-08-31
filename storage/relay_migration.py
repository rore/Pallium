"""Uncalled Relay-only migration prototype for B1 review."""

from sqlalchemy import text


def migrate_relay_commit_sequences(connection, *, fail_at: str | None = None) -> None:
    """Atomically add DB-owned Relay commit-sequence allocation on SQLite."""
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(relay_messages)"))}
        if "commit_seq" not in columns:
            connection.execute(text("ALTER TABLE relay_messages ADD COLUMN commit_seq INTEGER NOT NULL DEFAULT 0"))
        if fail_at == "ddl":
            raise RuntimeError("injected ddl fault")
        connection.execute(text("CREATE TABLE IF NOT EXISTS relay_commit_counters (key TEXT PRIMARY KEY, next_seq INTEGER NOT NULL)"))
        counter = int(connection.execute(text("SELECT COALESCE(MAX(next_seq), 0) FROM relay_commit_counters WHERE key='relay'")).scalar() or 0)
        existing = int(connection.execute(text("SELECT COALESCE(MAX(commit_seq), 0) FROM relay_messages WHERE commit_seq > 0")).scalar() or 0)
        start = max(counter, existing)
        rows = connection.execute(text("SELECT id FROM relay_messages WHERE commit_seq <= 0 ORDER BY created_at, id")).fetchall()
        for sequence, row in enumerate(rows, start=start + 1):
            connection.execute(text("UPDATE relay_messages SET commit_seq=:sequence WHERE id=:id"), {"sequence": sequence, "id": row[0]})
        if fail_at == "backfill":
            raise RuntimeError("injected backfill fault")
        highest = max(start, int(connection.execute(text("SELECT COALESCE(MAX(commit_seq), 0) FROM relay_messages")).scalar() or 0))
        connection.execute(text("INSERT INTO relay_commit_counters(key, next_seq) VALUES ('relay', :highest) ON CONFLICT(key) DO UPDATE SET next_seq=MAX(next_seq, excluded.next_seq)"), {"highest": highest})
        if fail_at == "seed":
            raise RuntimeError("injected seed fault")
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_relay_messages_commit_seq ON relay_messages(commit_seq) WHERE commit_seq > 0"))
        connection.execute(text("CREATE TRIGGER IF NOT EXISTS relay_reject_explicit_commit_seq BEFORE INSERT ON relay_messages WHEN NEW.commit_seq > 0 BEGIN SELECT RAISE(ABORT, 'commit_seq is database assigned'); END"))
        connection.execute(text("CREATE TRIGGER IF NOT EXISTS relay_assign_commit_seq AFTER INSERT ON relay_messages WHEN NEW.commit_seq <= 0 BEGIN UPDATE relay_commit_counters SET next_seq=next_seq+1 WHERE key='relay'; UPDATE relay_messages SET commit_seq=(SELECT next_seq FROM relay_commit_counters WHERE key='relay') WHERE id=NEW.id; END"))
        if fail_at == "index":
            raise RuntimeError("injected index fault")
        connection.exec_driver_sql("COMMIT")
    except BaseException:
        connection.exec_driver_sql("ROLLBACK")
        raise
