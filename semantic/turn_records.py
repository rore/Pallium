"""Shared structural turn/command records for the operational_fact family.

`CommandRecord` and `TurnRecord` are the neutral evidence types read by
both :mod:`semantic.operational_fact` (the derivation predicate) and
:mod:`semantic.reconnaissance` (the reconnaissance-verb detector). They
live here — in a sibling module that depends on neither — so the two
consumers do not form an import cycle (import-linter "semantic siblings
acyclic"). Both are frozen dataclasses with no internal dependencies.

`semantic.operational_fact` re-exports these names for backward
compatibility, so existing `from semantic.operational_fact import
CommandRecord, TurnRecord` call sites keep working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandRecord:
    """One command extracted from ``agent_work_trace_turn.commands``."""

    cmd: str
    exit_code: int | None = None
    output_tail: str = ""
    failure_class: str = ""


@dataclass(frozen=True)
class TurnRecord:
    """A single turn's structural evidence.

    The predicate reads nothing else: no LLM output, no thread text, no
    routing context.
    """

    turn_index: int
    source_item_id: str
    timestamp: str = ""
    commands: tuple[CommandRecord, ...] = ()
    files_read: tuple[str, ...] = ()
    files_modified: tuple[str, ...] = ()
    grep_patterns: tuple[str, ...] = ()
