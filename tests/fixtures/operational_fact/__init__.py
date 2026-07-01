"""Test fixtures for the operational_fact derivation predicate.

Public helpers for building synthetic ``TurnRecord`` objects. Real
live-DB samples (when they land) go in this same directory as JSON,
anonymized by ``scripts/extract_operational_fact_fixture.py``.
"""

from __future__ import annotations

from typing import Iterable

from semantic.operational_fact import CommandRecord, TurnRecord


def make_turn(
    turn_index: int,
    *,
    source_item_id: str | None = None,
    timestamp: str = "2026-07-01T00:00:00Z",
    commands: Iterable[tuple[str, int] | tuple[str, int, str]] = (),
    files_read: Iterable[str] = (),
    files_modified: Iterable[str] = (),
    grep_patterns: Iterable[str] = (),
) -> TurnRecord:
    """Build a ``TurnRecord`` with sane defaults.

    ``commands`` is a sequence of ``(cmd, exit_code)`` or
    ``(cmd, exit_code, output_tail)`` tuples.
    """
    cmd_records: list[CommandRecord] = []
    for entry in commands:
        if len(entry) == 2:
            cmd, exit_code = entry
            output_tail = ""
        else:
            cmd, exit_code, output_tail = entry
        cmd_records.append(
            CommandRecord(cmd=cmd, exit_code=exit_code, output_tail=output_tail)
        )
    return TurnRecord(
        turn_index=turn_index,
        source_item_id=source_item_id or f"src-{turn_index:05d}",
        timestamp=timestamp,
        commands=tuple(cmd_records),
        files_read=tuple(files_read),
        files_modified=tuple(files_modified),
        grep_patterns=tuple(grep_patterns),
    )


def make_bash_turn(
    turn_index: int,
    cmd: str,
    exit_code: int = 0,
    *,
    output_tail: str = "",
    **kwargs,
) -> TurnRecord:
    """Shortcut: one bash command per turn."""
    return make_turn(
        turn_index,
        commands=[(cmd, exit_code, output_tail)],
        **kwargs,
    )


def fake_scope_resolver(container_ref: str, artifact_path: str | None):
    """Deterministic scope resolver for unit tests.

    Absolute-looking paths → machine_repo with a fixed test hash so
    tests never touch the real ``socket.gethostname``.
    """
    if artifact_path and (
        (len(artifact_path) >= 2 and artifact_path[1] == ":")
        or artifact_path.startswith("/")
        or artifact_path.startswith("~")
    ):
        return ("machine_repo", f"{container_ref}@machine:testhash")
    return ("repo", container_ref)


__all__ = ["make_turn", "make_bash_turn", "fake_scope_resolver"]
