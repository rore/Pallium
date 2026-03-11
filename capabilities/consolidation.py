from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from core.contracts import ProcessResult
from core.models import EvidenceReference, MemoryObject
from storage.base import StorageProvider


DEFAULT_CONSOLIDATION_STRATEGIES = (
    "thread_local_carry_forward",
    "container_topic_window",
    "thread_summary_anchored",
)
ELIGIBLE_INPUT_TYPES = {"thread_summary", "decision", "investigation_outcome"}
CONSOLIDATION_STOPWORDS = {
    "a",
    "an",
    "and",
    "avoid",
    "conversation",
    "decided",
    "decision",
    "during",
    "for",
    "found",
    "from",
    "investigation",
    "later",
    "prior",
    "recorded",
    "summary",
    "that",
    "the",
    "thread",
    "to",
    "use",
    "user",
    "was",
    "were",
}


@dataclass(frozen=True)
class ConsolidationPolicy:
    enabled_strategies: tuple[str, ...] = DEFAULT_CONSOLIDATION_STRATEGIES
    default_strategy: str = "thread_summary_anchored"
    max_candidates_per_run: int = 24
    max_group_size: int = 4
    same_container_required: bool = True
    time_window_hours: int = 168
    lexical_overlap_threshold: int = 2


@dataclass(frozen=True)
class ConsolidationCandidate:
    memory_object: MemoryObject
    evidence: tuple[EvidenceReference, ...]
    text_view: str
    tokens: frozenset[str]
    container_ref: str | None
    thread_ref: str | None
    session_ref: str | None
    latest_occurred_at: datetime


@dataclass(frozen=True)
class ConsolidationGroup:
    strategy_name: str
    strategy_version: str
    group_key: str
    candidates: tuple[ConsolidationCandidate, ...]
    container_ref: str | None
    thread_ref: str | None
    session_ref: str | None
    latest_occurred_at: datetime
    merge_rationale: dict[str, object] = field(default_factory=dict)

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(candidate.memory_object.id for candidate in self.candidates)

    @property
    def supporting_source_ids(self) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for candidate in self.candidates:
            for evidence in candidate.evidence:
                if evidence.source_item_id in seen:
                    continue
                seen.add(evidence.source_item_id)
                ordered.append(evidence.source_item_id)
        return tuple(ordered)


@dataclass(frozen=True)
class ConsolidationRunGroupResult:
    strategy_name: str
    strategy_version: str
    group_key: str
    selected_candidate_ids: tuple[str, ...]
    selected_source_item_ids: tuple[str, ...]
    candidate_thread_refs: tuple[str | None, ...]
    created_pattern_memory_ids: tuple[str, ...]
    superseded_pattern_memory_ids: tuple[str, ...]
    merge_rationale: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ConsolidationRunResult:
    package_name: str
    strategy_name: str
    strategy_version: str
    candidate_count: int
    selected_candidate_ids: tuple[str, ...]
    groups: tuple[ConsolidationRunGroupResult, ...]


class ConsolidationStrategy(ABC):
    name: str
    version: str = "v1"

    @abstractmethod
    def select_candidates(
        self,
        candidates: list[ConsolidationCandidate],
        policy: ConsolidationPolicy,
    ) -> list[ConsolidationCandidate]:
        raise NotImplementedError

    @abstractmethod
    def group_candidates(
        self,
        candidates: list[ConsolidationCandidate],
        policy: ConsolidationPolicy,
    ) -> list[ConsolidationGroup]:
        raise NotImplementedError


class ThreadLocalCarryForwardStrategy(ConsolidationStrategy):
    name = "thread_local_carry_forward"

    def select_candidates(self, candidates: list[ConsolidationCandidate], policy: ConsolidationPolicy) -> list[ConsolidationCandidate]:
        return _limit_candidates(candidates, policy.max_candidates_per_run)

    def group_candidates(self, candidates: list[ConsolidationCandidate], policy: ConsolidationPolicy) -> list[ConsolidationGroup]:
        grouped: dict[tuple[str | None, str | None], list[ConsolidationCandidate]] = {}
        for candidate in candidates:
            if not candidate.thread_ref:
                continue
            key = (candidate.container_ref, candidate.thread_ref)
            grouped.setdefault(key, []).append(candidate)

        groups: list[ConsolidationGroup] = []
        for (container_ref, thread_ref), members in grouped.items():
            ordered = _sort_candidates(members)
            if not _group_has_pattern_signal(ordered):
                continue
            selected = tuple(ordered[: policy.max_group_size])
            latest = max(candidate.latest_occurred_at for candidate in selected)
            session_ref = _representative_session_ref(selected)
            group_key = f"{self.name}:{container_ref or 'none'}:{thread_ref or 'none'}"
            groups.append(
                ConsolidationGroup(
                    strategy_name=self.name,
                    strategy_version=self.version,
                    group_key=group_key,
                    candidates=selected,
                    container_ref=container_ref,
                    thread_ref=thread_ref,
                    session_ref=session_ref,
                    latest_occurred_at=latest,
                    merge_rationale={
                        "grouping_mode": "same_thread",
                        "container_ref": container_ref,
                        "thread_ref": thread_ref,
                        "candidate_types": [candidate.memory_object.type for candidate in selected],
                        "pattern_signal": "thread_local_pattern_signal",
                    },
                )
            )
        return groups


class ContainerTopicWindowStrategy(ConsolidationStrategy):
    name = "container_topic_window"

    def select_candidates(self, candidates: list[ConsolidationCandidate], policy: ConsolidationPolicy) -> list[ConsolidationCandidate]:
        selected = [candidate for candidate in candidates if candidate.container_ref or not policy.same_container_required]
        return _limit_candidates(selected, policy.max_candidates_per_run)

    def group_candidates(self, candidates: list[ConsolidationCandidate], policy: ConsolidationPolicy) -> list[ConsolidationGroup]:
        remaining = _sort_candidates(candidates)
        groups: list[ConsolidationGroup] = []
        consumed: set[str] = set()

        for anchor in remaining:
            if anchor.memory_object.id in consumed:
                continue
            group_members = [anchor]
            anchor_threads = {anchor.thread_ref}
            overlap_scores: dict[str, int] = {}
            for candidate in remaining:
                if candidate.memory_object.id == anchor.memory_object.id or candidate.memory_object.id in consumed:
                    continue
                if policy.same_container_required and candidate.container_ref != anchor.container_ref:
                    continue
                if _hours_between(anchor.latest_occurred_at, candidate.latest_occurred_at) > policy.time_window_hours:
                    continue
                overlap_score = _lexical_overlap(anchor.tokens, candidate.tokens)
                if overlap_score < policy.lexical_overlap_threshold:
                    continue
                if len(group_members) >= policy.max_group_size:
                    break
                group_members.append(candidate)
                anchor_threads.add(candidate.thread_ref)
                overlap_scores[candidate.memory_object.id] = overlap_score

            if len(group_members) < 2 or len({item.thread_ref for item in group_members if item.thread_ref}) < 2:
                continue
            if not _group_has_pattern_signal(group_members):
                continue

            ordered = tuple(_sort_candidates(group_members))
            for member in ordered:
                consumed.add(member.memory_object.id)
            latest = max(candidate.latest_occurred_at for candidate in ordered)
            group_key = f"{self.name}:{ordered[0].container_ref or 'none'}:{'|'.join(sorted(candidate.memory_object.id for candidate in ordered))}"
            groups.append(
                ConsolidationGroup(
                    strategy_name=self.name,
                    strategy_version=self.version,
                    group_key=group_key,
                    candidates=ordered,
                    container_ref=ordered[0].container_ref,
                    thread_ref=None,
                    session_ref=_representative_session_ref(ordered),
                    latest_occurred_at=latest,
                    merge_rationale={
                        "grouping_mode": "container_topic_window",
                        "anchor_memory_id": anchor.memory_object.id,
                        "grouped_thread_refs": sorted({candidate.thread_ref for candidate in ordered if candidate.thread_ref}),
                        "overlap_scores": overlap_scores,
                        "time_window_hours": policy.time_window_hours,
                        "lexical_overlap_threshold": policy.lexical_overlap_threshold,
                    },
                )
            )

        return groups


class ThreadSummaryAnchoredStrategy(ConsolidationStrategy):
    name = "thread_summary_anchored"

    def select_candidates(self, candidates: list[ConsolidationCandidate], policy: ConsolidationPolicy) -> list[ConsolidationCandidate]:
        thread_summaries = [candidate for candidate in candidates if candidate.memory_object.type == "thread_summary"]
        typed = [candidate for candidate in candidates if candidate.memory_object.type in {"decision", "investigation_outcome"}]
        return _limit_candidates(_sort_candidates(thread_summaries) + _sort_candidates(typed), policy.max_candidates_per_run)

    def group_candidates(self, candidates: list[ConsolidationCandidate], policy: ConsolidationPolicy) -> list[ConsolidationGroup]:
        anchors = [candidate for candidate in candidates if candidate.memory_object.type == "thread_summary"]
        typed = [candidate for candidate in candidates if candidate.memory_object.type in {"decision", "investigation_outcome"}]
        groups: list[ConsolidationGroup] = []

        for anchor in _sort_candidates(anchors):
            members = [anchor]
            overlap_scores: dict[str, int] = {}
            for candidate in _sort_candidates(typed):
                if candidate.container_ref != anchor.container_ref and policy.same_container_required:
                    continue
                if _hours_between(anchor.latest_occurred_at, candidate.latest_occurred_at) > policy.time_window_hours:
                    continue
                overlap_score = _lexical_overlap(anchor.tokens, candidate.tokens)
                if overlap_score < policy.lexical_overlap_threshold:
                    continue
                if len(members) >= policy.max_group_size:
                    break
                members.append(candidate)
                overlap_scores[candidate.memory_object.id] = overlap_score

            if len(members) < 2 or not _group_has_pattern_signal(members):
                continue

            ordered = tuple(_sort_candidates(members))
            latest = max(candidate.latest_occurred_at for candidate in ordered)
            group_key = f"{self.name}:{anchor.container_ref or 'none'}:{anchor.memory_object.id}"
            groups.append(
                ConsolidationGroup(
                    strategy_name=self.name,
                    strategy_version=self.version,
                    group_key=group_key,
                    candidates=ordered,
                    container_ref=anchor.container_ref,
                    thread_ref=anchor.thread_ref,
                    session_ref=_representative_session_ref(ordered),
                    latest_occurred_at=latest,
                    merge_rationale={
                        "grouping_mode": "thread_summary_anchored",
                        "anchor_memory_id": anchor.memory_object.id,
                        "anchor_thread_ref": anchor.thread_ref,
                        "attached_candidate_ids": [candidate.memory_object.id for candidate in ordered if candidate.memory_object.id != anchor.memory_object.id],
                        "overlap_scores": overlap_scores,
                        "lexical_overlap_threshold": policy.lexical_overlap_threshold,
                    },
                )
            )

        return groups


class ConsolidationCapability:
    def __init__(self) -> None:
        self._strategies: dict[str, ConsolidationStrategy] = {
            strategy.name: strategy
            for strategy in (
                ThreadLocalCarryForwardStrategy(),
                ContainerTopicWindowStrategy(),
                ThreadSummaryAnchoredStrategy(),
            )
        }

    def resolve_strategy(self, strategy_name: str) -> ConsolidationStrategy:
        if strategy_name not in self._strategies:
            raise KeyError(f"Unknown consolidation strategy: {strategy_name}")
        return self._strategies[strategy_name]

    def select_candidates(
        self,
        *,
        storage: StorageProvider,
        plugin,
        strategy: ConsolidationStrategy,
        policy: ConsolidationPolicy,
    ) -> list[ConsolidationCandidate]:
        memory_objects = storage.list_memory_objects(memory_types=list(ELIGIBLE_INPUT_TYPES), lifecycle="active")
        candidates = [
            self._build_candidate(storage, memory_object)
            for memory_object in memory_objects
            if plugin.supports_consolidation(memory_object)
        ]
        candidates = [candidate for candidate in candidates if candidate is not None]
        return strategy.select_candidates(candidates, policy)

    def group_candidates(
        self,
        *,
        strategy: ConsolidationStrategy,
        candidates: list[ConsolidationCandidate],
        policy: ConsolidationPolicy,
    ) -> list[ConsolidationGroup]:
        return strategy.group_candidates(candidates, policy)

    def synthesize_group(
        self,
        *,
        plugin,
        group: ConsolidationGroup,
    ) -> ProcessResult:
        return plugin.build_pattern_memory(group)

    def _build_candidate(self, storage: StorageProvider, memory_object: MemoryObject) -> ConsolidationCandidate | None:
        evidence = tuple(storage.get_evidence_for_memory_object(memory_object.id))
        container_ref = _derive_container_ref(memory_object, evidence)
        thread_ref = _derive_thread_ref(memory_object, evidence)
        session_ref = _derive_session_ref(memory_object, evidence)
        latest_occurred_at = _derive_latest_occurred_at(memory_object, evidence)
        text_view = _derive_text_view(memory_object)
        tokens = frozenset(_tokenize(text_view))
        if not text_view.strip():
            return None
        return ConsolidationCandidate(
            memory_object=memory_object,
            evidence=evidence,
            text_view=text_view,
            tokens=tokens,
            container_ref=container_ref,
            thread_ref=thread_ref,
            session_ref=session_ref,
            latest_occurred_at=latest_occurred_at,
        )


def _limit_candidates(candidates: list[ConsolidationCandidate], limit: int) -> list[ConsolidationCandidate]:
    return _sort_candidates(candidates)[:limit]


def _sort_candidates(candidates: Iterable[ConsolidationCandidate]) -> list[ConsolidationCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (candidate.latest_occurred_at, candidate.memory_object.created_at, candidate.memory_object.id),
        reverse=True,
    )


def _group_has_pattern_signal(candidates: Iterable[ConsolidationCandidate]) -> bool:
    types = {candidate.memory_object.type for candidate in candidates}
    return ("thread_summary" in types and len(types.intersection({"decision", "investigation_outcome"})) >= 1) or len(types.intersection({"decision", "investigation_outcome"})) >= 2


def _representative_session_ref(candidates: Iterable[ConsolidationCandidate]) -> str | None:
    for candidate in candidates:
        if candidate.session_ref:
            return candidate.session_ref
    return None


def _lexical_overlap(left: frozenset[str], right: frozenset[str]) -> int:
    return len(left.intersection(right))


def _hours_between(left: datetime, right: datetime) -> float:
    delta = left - right if left >= right else right - left
    return delta / timedelta(hours=1)


def _derive_container_ref(memory_object: MemoryObject, evidence: tuple[EvidenceReference, ...]) -> str | None:
    payload = memory_object.payload
    if isinstance(payload.get("container_ref"), str):
        return payload["container_ref"]
    for item in evidence:
        if item.container_ref:
            return item.container_ref
    return None


def _derive_thread_ref(memory_object: MemoryObject, evidence: tuple[EvidenceReference, ...]) -> str | None:
    payload = memory_object.payload
    if isinstance(payload.get("thread_ref"), str):
        return payload["thread_ref"]
    for item in evidence:
        if item.thread_ref:
            return item.thread_ref
    return None


def _derive_session_ref(memory_object: MemoryObject, evidence: tuple[EvidenceReference, ...]) -> str | None:
    payload = memory_object.payload
    if isinstance(payload.get("session_ref"), str):
        return payload["session_ref"]
    for item in evidence:
        if item.session_ref:
            return item.session_ref
    return None


def _derive_latest_occurred_at(memory_object: MemoryObject, evidence: tuple[EvidenceReference, ...]) -> datetime:
    payload = memory_object.payload
    latest = payload.get("latest_occurred_at")
    if isinstance(latest, str) and latest:
        try:
            parsed = datetime.fromisoformat(latest.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            pass
    occurred = [item.occurred_at for item in evidence if item.occurred_at is not None]
    if occurred:
        return max(occurred)
    created = memory_object.created_at
    if created.tzinfo is None:
        return created.replace(tzinfo=timezone.utc)
    return created


def _derive_text_view(memory_object: MemoryObject) -> str:
    payload = memory_object.payload
    if memory_object.type == "thread_summary":
        conclusion_parts = [
            conclusion.get("text", "")
            for conclusion in payload.get("conclusions", [])
            if isinstance(conclusion, dict)
        ]
        return " ".join(part for part in [payload.get("summary", ""), *conclusion_parts] if part)
    if memory_object.type == "decision":
        return " ".join(part for part in [payload.get("decision", ""), payload.get("rationale", "")] if part)
    if memory_object.type == "investigation_outcome":
        return " ".join(part for part in [payload.get("investigation_outcome", ""), payload.get("rationale", "")] if part)
    return str(payload.get("summary", ""))


def _tokenize(text: str) -> list[str]:
    tokens = []
    for token in ''.join(character.lower() if character.isalnum() else ' ' for character in text).split():
        if len(token) < 3:
            continue
        if token in CONSOLIDATION_STOPWORDS:
            continue
        tokens.append(token)
    return tokens




