from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Visibility = Literal["public", "container", "private"]


@dataclass(frozen=True)
class VisibilityExclusion:
    reason: str
    count: int = 1


@dataclass(frozen=True)
class QueryVisibilityTrace:
    query_visibility: str | None
    query_container_ref: str | None
    excluded_candidates: tuple[VisibilityExclusion, ...] = ()
    fail_closed_reason: str | None = None


def is_visible(
    candidate_visibility: str | None,
    candidate_container_ref: str | None,
    query_container_ref: str | None,
    candidate_actor_ref: str | None = None,
    query_visibility: str | None = None,
) -> bool:
    if query_container_ref is None:
        return True
    # Public query context: only see public memories, regardless of container.
    if query_visibility == "public":
        return candidate_visibility == "public" and candidate_actor_ref is None
    # Container query context: see public + same-container non-private memories.
    if query_visibility == "container":
        if candidate_visibility == "public" and candidate_actor_ref is None:
            return True
        if candidate_container_ref == query_container_ref and candidate_visibility != "private":
            return True
        return False
    # Private query context (or unspecified): see everything in same container.
    if candidate_container_ref is not None and candidate_container_ref == query_container_ref:
        return True
    # Cross-container: only public shared memories (actor_ref=null).
    if candidate_visibility == "public" and candidate_actor_ref is None:
        return True
    return False


def visibility_matches_exact(left: str | None, right: str | None) -> bool:
    return left == right


def visibility_label(visibility: str | None) -> str:
    return visibility or "missing"