"""Pure arm assembly + candidate-recovery + equal-token-budget scoring.

Everything here is a pure function over small in-memory structs — no DB, no LLM —
so it is trivially unit-testable. The runner (``runner.py``) replays each query
through the shipped retrieval stack and maps the results onto these structs.

Three seams live here:

- **arm assembly + RAW purity** — a RAW arm is candidate-level source-only; it must
  contain NO memory objects (guaranteed by ``target_kind="source_item"`` at query
  time, re-asserted here so the invariant is enforced, not assumed).
- **evidence-link candidate-recovery** — the OBJECTIVE, judge-free, SYMMETRIC recovery
  signal: for each derived object (episode), did its linked source turns enter the
  RAW arm AND did the object enter the DERIVED arm?
- **equal-token-budget** — deterministic ``ceil(len/4)`` truncation AT ITEM
  BOUNDARIES (drop whole items that don't fit, never split one), so RAW (many-small)
  vs DERIVED (few-dense) is compared at the same context budget. This axis is NEVER
  fed to the representation judge.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Arm names.
RAW = "RAW"
DERIVED = "DERIVED"
HYBRID = "HYBRID"

# Candidate kinds (mirror the retrieval provider's ``target_kind`` values).
KIND_SOURCE = "source_item"
KIND_MEMORY = "memory_object"

# Arm name -> ``target_kind`` passed to ``retrieval.query`` (None = HYBRID/mixed).
TARGET_KIND: dict[str, str | None] = {
    RAW: KIND_SOURCE,
    DERIVED: KIND_MEMORY,
    HYBRID: None,
}


@dataclass(frozen=True)
class Candidate:
    """One retrieved candidate, reduced to what the arm seams need.

    ``rank`` is 1-based within the arm; ``score`` is the fusion score reported by
    the retrieval stack (stored so a RAW arm is reconstructable)."""

    kind: str  # KIND_SOURCE | KIND_MEMORY
    id: str
    rank: int
    score: float


@dataclass(frozen=True)
class Arm:
    """A candidate set produced by one replay of the query at a given target_kind."""

    name: str
    target_kind: str | None
    candidates: tuple[Candidate, ...] = ()

    def ids_of_kind(self, kind: str) -> set[str]:
        return {c.id for c in self.candidates if c.kind == kind}

    def to_dict(self) -> dict:
        return {
            "arm": self.name,
            "target_kind": self.target_kind,
            "candidate_count": len(self.candidates),
            "candidates": [
                {"kind": c.kind, "id": c.id, "rank": c.rank, "fusion_score": c.score}
                for c in self.candidates
            ],
        }


@dataclass(frozen=True)
class DerivedObjectEvidence:
    """A derived object (episode) reduced to what evidence-link recovery needs.

    ``source_item_ids`` are the object's linked ``supported_by`` source turns;
    ``entered_derived_arm`` records whether the object was retrieved into the DERIVED
    arm for this query."""

    memory_object_id: str
    source_item_ids: tuple[str, ...]
    entered_derived_arm: bool


def partition_candidates(name: str, candidates: list[Candidate]) -> Arm:
    """Assemble an arm, enforcing RAW purity.

    RAW is candidate-level source-only: a memory object must never appear in it. The
    query-time ``target_kind="source_item"`` filter guarantees this; we re-assert it
    here so a leak is a hard error, not a silently confounded metric.
    """
    if name not in TARGET_KIND:
        raise ValueError(f"unknown arm name: {name!r}")
    if name == RAW:
        leaked = [c for c in candidates if c.kind != KIND_SOURCE]
        if leaked:
            raise ValueError(
                f"RAW arm purity violation: {len(leaked)} non-source candidate(s) "
                f"(e.g. {leaked[0].kind}:{leaked[0].id}) — RAW must be source-only."
            )
    return Arm(name=name, target_kind=TARGET_KIND[name], candidates=tuple(candidates))


def _recovery_label(source_recovered: bool, object_recovered: bool) -> str:
    if source_recovered and object_recovered:
        return "both"
    if source_recovered and not object_recovered:
        return "raw_only"
    if object_recovered and not source_recovered:
        return "derived_only"
    return "neither"


def evidence_link_recovery(
    raw_source_ids: set[str],
    derived_objs_with_evidence: list[DerivedObjectEvidence],
) -> dict:
    """Objective, judge-free, SYMMETRIC candidate-recovery over derived episodes.

    For each derived object, resolve whether (a) its linked source turns entered the
    RAW arm and (b) the object itself entered the DERIVED arm, then label the episode
    RAW-only / DERIVED-only / both / neither. This is a correspondence over the SAME
    underlying episode, so RAW-vs-DERIVED is not confounded by different content.

    Empty-data-safe. Never mixes in ``memory_feedback`` (a DERIVED-only signal with
    no source column) as a recovery label — that stays a secondary signal in the
    runner report.
    """
    counts = {"both": 0, "raw_only": 0, "derived_only": 0, "neither": 0}
    no_evidence = 0
    objects: list[dict] = []
    n_with_evidence = 0
    for obj in derived_objs_with_evidence:
        object_recovered = obj.entered_derived_arm
        if not obj.source_item_ids:
            # No linked source turns → RAW recovery is undefined for this episode.
            # Segregate it rather than counting it toward the four labels, so the
            # RAW-vs-DERIVED comparison isn't distorted by objects that structurally
            # cannot have a RAW correspondence.
            no_evidence += 1
            objects.append(
                {
                    "memory_object_id": obj.memory_object_id,
                    "linked_source_count": 0,
                    "source_recovered_in_raw": None,
                    "object_recovered_in_derived": object_recovered,
                    "label": "no_evidence",
                }
            )
            continue
        n_with_evidence += 1
        source_recovered = any(sid in raw_source_ids for sid in obj.source_item_ids)
        label = _recovery_label(source_recovered, object_recovered)
        counts[label] += 1
        objects.append(
            {
                "memory_object_id": obj.memory_object_id,
                "linked_source_count": len(obj.source_item_ids),
                "source_recovered_in_raw": source_recovered,
                "object_recovered_in_derived": object_recovered,
                "label": label,
            }
        )
    return {
        "seam": "candidate_recovery",
        "n_objects": len(derived_objs_with_evidence),
        "n_with_evidence": n_with_evidence,
        "no_evidence": no_evidence,
        "counts": counts,
        "objects": objects,
    }


def estimate_tokens(text: str) -> int:
    """Repo token model (no tiktoken): ``ceil(len/4)``. Duplicated locally by design;
    there is no shared helper to import (see WR Discovery)."""
    return math.ceil(len(text or "") / 4)


def equal_token_budget(items: list[str], budget: int) -> dict:
    """Deterministic equal-token-budget truncation AT ITEM BOUNDARIES.

    Walks the rendered items in order; retains each whole item that still fits in the
    remaining budget and drops (never splits) any that does not. Returns the retained
    item count + total retained tokens, so RAW (many-small items) vs DERIVED
    (few-dense items) can be compared at the SAME context budget. Empty-safe.

    This is the context-cost axis ONLY — it is never fed to the representation judge,
    which always sees the FULL retrieved RAW turns.
    """
    retained = 0
    total = 0
    per_item: list[dict] = []
    for text in items:
        tokens = estimate_tokens(text)
        fits = total + tokens <= budget
        if fits:
            retained += 1
            total += tokens
        per_item.append({"tokens": tokens, "retained": fits})
    return {
        "budget": budget,
        "considered_items": len(items),
        "retained_items": retained,
        "dropped_items": len(items) - retained,
        "total_tokens": total,
        "per_item": per_item,
    }
