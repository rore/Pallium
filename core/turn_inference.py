"""Infer turn_kind and session_has_sufficient_local_context from thread state in storage.

When the integrating agent omits runtime_context fields, Pallium derives them
from item counts and timestamps already in SQLite for the queried thread.
Caller-provided values always take precedence — inference only fills None slots.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from core.models import QueryRuntimeContext, TurnKind

if TYPE_CHECKING:
    from storage.base import StorageProvider

# Seconds of inactivity after which a thread is considered "resumed" rather than "continued".
CONTINUATION_THRESHOLD_SECONDS = 30 * 60  # 30 minutes


@dataclass(frozen=True)
class ThreadStats:
    """Lightweight stats for a single thread_ref in storage."""
    item_count: int
    latest_created_at: datetime | None


@dataclass(frozen=True)
class InferredRuntimeContext:
    turn_kind: TurnKind | None
    session_has_sufficient_local_context: bool | None


def infer_from_thread_stats(
    stats: ThreadStats,
    now: datetime,
) -> InferredRuntimeContext:
    """Derive turn_kind and local_context from thread item stats.

    Produces 3 of the 5 ``TurnKind`` values:

    - ``new_thread`` — no prior items in the thread.
    - ``same_thread_continuation`` — recent activity within the threshold.
    - ``resumed_session`` — stale activity beyond the threshold.

    ``same_thread`` and ``new_session`` are never inferred because a time-gap
    heuristic cannot distinguish them from ``same_thread_continuation`` and
    ``new_thread`` respectively.  The routing code treats each pair identically
    (always grouped in the same ``in {...}`` checks), so inference covers the
    routing-relevant equivalence classes.

    ``stats`` should already exclude the just-ingested item when called from
    the /item-and-query flow.
    """
    if stats.item_count == 0:
        return InferredRuntimeContext(
            turn_kind="new_thread",
            session_has_sufficient_local_context=False,
        )

    if stats.latest_created_at is None:
        # Defensive: item_count > 0 but no timestamp should not happen.
        # Fall back to new_thread rather than crashing on the query hot path.
        return InferredRuntimeContext(
            turn_kind="new_thread",
            session_has_sufficient_local_context=False,
        )

    latest = stats.latest_created_at
    # SQLite may store naive datetimes (UTC by convention); normalize for subtraction.
    if latest.tzinfo is None and now.tzinfo is not None:
        latest = latest.replace(tzinfo=now.tzinfo)
    elif latest.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=latest.tzinfo)
    gap_seconds = (now - latest).total_seconds()

    if gap_seconds < CONTINUATION_THRESHOLD_SECONDS:
        return InferredRuntimeContext(
            turn_kind="same_thread_continuation",
            session_has_sufficient_local_context=True,
        )

    return InferredRuntimeContext(
        turn_kind="resumed_session",
        session_has_sufficient_local_context=False,
    )


def resolve_runtime_context(
    storage: StorageProvider,
    thread_ref: str | None,
    runtime_context: QueryRuntimeContext | None,
    *,
    exclude_item_id: str | None = None,
    now: datetime | None = None,
) -> QueryRuntimeContext | None:
    """Fill missing turn_kind / local_context from thread state in storage.

    Caller-provided values always win.  Returns the original ``runtime_context``
    unchanged when both fields are already set, when ``thread_ref`` is ``None``,
    or when inference is not possible.

    ``exclude_item_id`` is for the /item-and-query flow where the just-ingested
    item should not count as prior thread history.
    """
    from core.models import utc_now

    needs_turn_kind = runtime_context is None or runtime_context.turn_kind is None
    needs_local_context = runtime_context is None or runtime_context.session_has_sufficient_local_context is None

    if not needs_turn_kind and not needs_local_context:
        return runtime_context

    if thread_ref is None:
        return runtime_context

    stats = storage.get_thread_stats(thread_ref, exclude_item_id=exclude_item_id)
    inferred = infer_from_thread_stats(stats, now=now or utc_now())

    if runtime_context is None:
        return QueryRuntimeContext(
            turn_kind=inferred.turn_kind,
            session_has_sufficient_local_context=inferred.session_has_sufficient_local_context,
        )

    return QueryRuntimeContext(
        turn_kind=runtime_context.turn_kind if runtime_context.turn_kind is not None else inferred.turn_kind,
        session_has_sufficient_local_context=(
            runtime_context.session_has_sufficient_local_context
            if runtime_context.session_has_sufficient_local_context is not None
            else inferred.session_has_sufficient_local_context
        ),
        evidence_request=runtime_context.evidence_request,
    )
