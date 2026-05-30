"""SQLite-backed implementation of :class:`capabilities.workstreams.WorkstreamStore`.

Pure storage adapter — no cascade logic. Idempotent inserts use
``INSERT OR IGNORE`` against the composite primary keys.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from capabilities.workstreams import WorkstreamStore


def _to_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        # SQLAlchemy core text() returns datetimes as strings in some adapters.
        try:
            value = datetime.fromisoformat(value.replace(" ", "T").replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class SQLiteWorkstreamStore(WorkstreamStore):
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def list_open_workstreams(self, *, container_ref: str, visibility: str) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT id, container_ref, visibility, kind, signature_blob, "
                    "       opened_at, last_touched_at, closed_at, closed_reason, canonical_id "
                    "FROM workstreams "
                    "WHERE container_ref = :container_ref "
                    "  AND visibility = :visibility "
                    "  AND closed_at IS NULL "
                    "  AND kind = 'resolved'"
                ),
                {"container_ref": container_ref, "visibility": visibility},
            ).fetchall()
        return [
            {
                "id": row[0],
                "container_ref": row[1],
                "visibility": row[2],
                "kind": row[3],
                "signature_blob": row[4],
                "opened_at": _to_utc(row[5]),
                "last_touched_at": _to_utc(row[6]),
                "closed_at": _to_utc(row[7]),
                "closed_reason": row[8],
                "canonical_id": row[9],
            }
            for row in rows
        ]

    def upsert_workstream(
        self,
        *,
        workstream_id: str,
        container_ref: str,
        visibility: str,
        kind: str,
        signature_blob: str,
        opened_at: datetime,
        last_touched_at: datetime,
        created_by: str,
    ) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                text(
                    "INSERT INTO workstreams ("
                    "  id, container_ref, visibility, kind, signature_blob, "
                    "  opened_at, last_touched_at, created_by"
                    ") VALUES ("
                    "  :id, :container_ref, :visibility, :kind, :signature_blob, "
                    "  :opened_at, :last_touched_at, :created_by"
                    ") ON CONFLICT(id) DO UPDATE SET "
                    "  signature_blob = excluded.signature_blob, "
                    "  last_touched_at = excluded.last_touched_at"
                ),
                {
                    "id": workstream_id,
                    "container_ref": container_ref,
                    "visibility": visibility,
                    "kind": kind,
                    "signature_blob": signature_blob,
                    "opened_at": _to_utc(opened_at),
                    "last_touched_at": _to_utc(last_touched_at),
                    "created_by": created_by,
                },
            )

    def insert_source_item_workstream(
        self,
        *,
        source_item_id: str,
        workstream_id: str,
        watermark: str,
        assigned_at: datetime,
    ) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                text(
                    "INSERT OR IGNORE INTO source_item_workstreams ("
                    "  source_item_id, workstream_id, watermark, assigned_at"
                    ") VALUES ("
                    "  :source_item_id, :workstream_id, :watermark, :assigned_at"
                    ")"
                ),
                {
                    "source_item_id": source_item_id,
                    "workstream_id": workstream_id,
                    "watermark": watermark,
                    "assigned_at": _to_utc(assigned_at),
                },
            )

    def insert_memory_workstream(
        self,
        *,
        memory_object_id: str,
        workstream_id: str,
        assigned_at: datetime,
    ) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                text(
                    "INSERT OR IGNORE INTO memory_workstreams ("
                    "  memory_object_id, workstream_id, assigned_at"
                    ") VALUES ("
                    "  :memory_object_id, :workstream_id, :assigned_at"
                    ")"
                ),
                {
                    "memory_object_id": memory_object_id,
                    "workstream_id": workstream_id,
                    "assigned_at": _to_utc(assigned_at),
                },
            )

    def get_memory_workstream_id(self, memory_object_id: str) -> str | None:
        with self._session_factory() as session:
            row = session.execute(
                text(
                    "SELECT workstream_id FROM memory_workstreams "
                    "WHERE memory_object_id = :mid "
                    "ORDER BY assigned_at DESC LIMIT 1"
                ),
                {"mid": memory_object_id},
            ).fetchone()
        return row[0] if row else None

    def get_latest_source_item_workstream_id(self, source_item_id: str) -> str | None:
        with self._session_factory() as session:
            row = session.execute(
                text(
                    "SELECT workstream_id FROM source_item_workstreams "
                    "WHERE source_item_id = :sid "
                    "ORDER BY watermark DESC, assigned_at DESC LIMIT 1"
                ),
                {"sid": source_item_id},
            ).fetchone()
        return row[0] if row else None

    # ---- helpers used by audit-log writes (batch lookup) ----

    def get_memory_workstream_ids(self, memory_object_ids: list[str]) -> dict[str, str]:
        if not memory_object_ids:
            return {}
        ids_tuple = list(dict.fromkeys(memory_object_ids))
        with self._session_factory() as session:
            placeholders = ",".join(f":id{i}" for i in range(len(ids_tuple)))
            params = {f"id{i}": v for i, v in enumerate(ids_tuple)}
            rows = session.execute(
                text(
                    "SELECT memory_object_id, workstream_id "
                    "FROM memory_workstreams "
                    f"WHERE memory_object_id IN ({placeholders})"
                ),
                params,
            ).fetchall()
        # Take the first hit per memory_object_id (composite PK can have multiple).
        out: dict[str, str] = {}
        for row in rows:
            if row[0] not in out:
                out[row[0]] = row[1]
        return out
