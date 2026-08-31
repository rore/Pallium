"""Uncalled Relay-only migration prototype for B1 review."""

from sqlalchemy import text

_REQUEST_COLUMNS = {
    "container_ref", "actor_ref", "sender_runtime", "sender_session_ref",
    "operation_kind", "parent_delivery_key", "request_id", "message_id",
    "recipient_selector", "payload_hash", "redacted", "in_reply_to",
    "expires_in_seconds", "retention_until",
}
_REQUEST_KEY = [
    "container_ref", "actor_ref", "sender_runtime", "sender_session_ref",
    "operation_kind", "parent_delivery_key", "request_id",
]


def _validate_request_table(connection) -> None:
    columns = {row[1]: row for row in connection.execute(text("PRAGMA table_info(relay_requests)"))}
    primary_key = [row[1] for row in sorted(columns.values(), key=lambda row: row[5]) if row[5]]
    types = {
        "container_ref": "TEXT", "actor_ref": "TEXT", "sender_runtime": "TEXT",
        "sender_session_ref": "TEXT", "operation_kind": "TEXT", "parent_delivery_key": "TEXT",
        "request_id": "TEXT", "message_id": "TEXT", "recipient_selector": "TEXT",
        "payload_hash": "TEXT", "redacted": "INTEGER", "in_reply_to": "TEXT",
        "expires_in_seconds": "INTEGER", "retention_until": "DATETIME",
    }
    indexes = connection.execute(text("PRAGMA index_list(relay_requests)")).fetchall()
    valid = (
        set(columns) == _REQUEST_COLUMNS
        and primary_key == _REQUEST_KEY
        and all(columns[name][2].upper() == column_type for name, column_type in types.items())
        and all(columns[name][3] == 1 for name in _REQUEST_COLUMNS - {"in_reply_to"})
        and columns["in_reply_to"][3] == 0
        and all(columns[name][4] is None for name in _REQUEST_COLUMNS)
        and any(index[2] == 1 and index[3] == "pk" for index in indexes)
    )
    if not valid:
        raise RuntimeError("existing relay_requests table has an unsupported B1 shape")


def migrate_relay_commit_sequences(connection, *, fail_at: str | None = None) -> None:
    """Atomically add DB-owned Relay commit-sequence allocation on SQLite."""
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(relay_messages)"))}
        if "commit_seq" not in columns:
            connection.execute(text("ALTER TABLE relay_messages ADD COLUMN commit_seq INTEGER NOT NULL DEFAULT 0"))
        if "payload_format" not in columns:
            connection.execute(text("ALTER TABLE relay_messages ADD COLUMN payload_format TEXT NOT NULL DEFAULT 'text_v1'"))
        if fail_at == "ddl":
            raise RuntimeError("injected ddl fault")
        connection.execute(text("CREATE TABLE IF NOT EXISTS relay_commit_counters (key TEXT PRIMARY KEY, next_seq INTEGER NOT NULL)"))
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS relay_requests (
                container_ref TEXT NOT NULL, actor_ref TEXT NOT NULL,
                sender_runtime TEXT NOT NULL, sender_session_ref TEXT NOT NULL,
                operation_kind TEXT NOT NULL, parent_delivery_key TEXT NOT NULL,
                request_id TEXT NOT NULL, message_id TEXT NOT NULL,
                recipient_selector TEXT NOT NULL, payload_hash TEXT NOT NULL,
                redacted INTEGER NOT NULL, in_reply_to TEXT,
                expires_in_seconds INTEGER NOT NULL, retention_until DATETIME NOT NULL,
                PRIMARY KEY (container_ref, actor_ref, sender_runtime, sender_session_ref,
                    operation_kind, parent_delivery_key, request_id)
            )
        """))
        _validate_request_table(connection)
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


def migrate_relay_batch_claims(connection, *, fail_at: str | None = None) -> None:
    """Explicit, uncalled B2 migration; legacy tables and writers stay unchanged."""
    migrate_relay_commit_sequences(connection)
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS relay_batch_claims (
                delivery_id TEXT PRIMARY KEY,
                claim_generation INTEGER NOT NULL DEFAULT 0,
                publication_started_at DATETIME,
                publication_digest TEXT,
                publication_chars INTEGER,
                publication_bytes INTEGER,
                uncertain_at DATETIME,
                uncertain_reason TEXT,
                blocked_reason TEXT
            )
        """))
        if fail_at == "ddl":
            raise RuntimeError("injected B2 ddl fault")
        connection.execute(text("CREATE TABLE IF NOT EXISTS relay_batch_protocol (version INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT OR IGNORE INTO relay_batch_protocol(version) VALUES (2)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS idx_relay_batch_claims_publication ON relay_batch_claims(publication_started_at, claim_generation)"))
        if fail_at == "index":
            raise RuntimeError("injected B2 index fault")
        connection.exec_driver_sql("COMMIT")
    except BaseException:
        connection.exec_driver_sql("ROLLBACK")
        raise