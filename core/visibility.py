from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


VisibilityKind = Literal["public", "limited", "user"]


@dataclass(frozen=True)
class VisibilityContext:
    kind: VisibilityKind
    id: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "public":
            if self.id is not None:
                raise ValueError("public visibility_context must use id=None")
            return
        if not self.id:
            raise ValueError(f"{self.kind} visibility_context requires a non-empty id")


@dataclass(frozen=True)
class VisibilityExclusion:
    reason: str
    count: int = 1


@dataclass(frozen=True)
class QueryVisibilityTrace:
    query_visibility_context: VisibilityContext | None
    expanded_visibility_contexts: tuple[VisibilityContext, ...]
    excluded_candidates: tuple[VisibilityExclusion, ...] = ()
    fail_closed_reason: str | None = None


PUBLIC_VISIBILITY = VisibilityContext(kind="public", id=None)


def expand_visibility_context(query_visibility_context: VisibilityContext) -> tuple[VisibilityContext, ...]:
    if query_visibility_context.kind == "public":
        return (PUBLIC_VISIBILITY,)
    return (PUBLIC_VISIBILITY, query_visibility_context)


def visibility_context_matches_exact(
    left: VisibilityContext | None,
    right: VisibilityContext | None,
) -> bool:
    return left == right


def visibility_context_is_visible(
    candidate_visibility_context: VisibilityContext | None,
    visible_contexts: tuple[VisibilityContext, ...] | None,
) -> bool:
    if visible_contexts is None:
        return True
    if candidate_visibility_context is None:
        return False
    return candidate_visibility_context in visible_contexts


def visibility_context_label(visibility_context: VisibilityContext | None) -> str:
    if visibility_context is None:
        return "missing"
    if visibility_context.kind == "public":
        return "public"
    return f"{visibility_context.kind}:{visibility_context.id}"
