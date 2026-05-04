from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.models import SourceItem
from core.visibility import visibility_matches_exact


@dataclass(frozen=True)
class ThreadAggregate:
    container_ref: str
    thread_ref: str | None
    source_items: list[SourceItem]
    source_item_ids: list[str]
    latest_occurred_at: datetime | None
    aggregate_text: str
    visibility: str = "private"
    prior_summary: str | None = None


def build_thread_aggregate(
    source_items: list[SourceItem],
    *,
    container_scope: bool = False,
    prior_summary: str | None = None,
) -> ThreadAggregate:
    if not source_items:
        raise ValueError("Thread aggregation requires at least one source item")

    ordered_items = sorted(
        source_items,
        key=lambda item: (
            item.occurred_at or item.created_at,
            item.created_at,
            item.id,
        ),
    )
    first = ordered_items[0]
    if not first.container_ref:
        raise ValueError("Thread aggregation requires container_ref")
    if not container_scope:
        if not first.thread_ref:
            raise ValueError("Thread aggregation requires thread_ref (use container_scope=True for container-level)")
        if any(
            not visibility_matches_exact(item.visibility, first.visibility)
            for item in ordered_items[1:]
        ):
            raise ValueError("Thread aggregation requires exact visibility match")

    latest_item = ordered_items[-1]
    aggregate_text = "\n".join(
        f"{item.role or 'unknown'}/{item.artifact_kind or 'unknown'}: {item.content.strip()}"
        for item in ordered_items
        if item.content.strip()
    )

    return ThreadAggregate(
        container_ref=first.container_ref,
        thread_ref=None if container_scope else first.thread_ref,
        source_items=ordered_items,
        source_item_ids=[item.id for item in ordered_items],
        latest_occurred_at=latest_item.occurred_at or latest_item.created_at,
        aggregate_text=aggregate_text,
        visibility=first.visibility,
        prior_summary=prior_summary,
    )