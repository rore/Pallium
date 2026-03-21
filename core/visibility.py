from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ContainerVisibility = Literal["public", "limited", "private"]


@dataclass(frozen=True)
class VisibilityExclusion:
    reason: str
    count: int = 1


@dataclass(frozen=True)
class QueryVisibilityTrace:
    query_container_visibility: str | None
    query_container_ref: str | None
    excluded_candidates: tuple[VisibilityExclusion, ...] = ()
    fail_closed_reason: str | None = None


def is_visible(
    candidate_visibility: str | None,
    candidate_container_ref: str | None,
    query_container_ref: str | None,
) -> bool:
    if candidate_visibility == "public":
        return True
    return candidate_container_ref is not None and candidate_container_ref == query_container_ref


def visibility_matches_exact(left: str | None, right: str | None) -> bool:
    return left == right


def visibility_label(container_visibility: str | None) -> str:
    return container_visibility or "missing"
