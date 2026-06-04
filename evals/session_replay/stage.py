"""Failure-stage classification.

Given a decoded audit row (candidates + injected blocks) and optional
memory lifecycle data, label the turn with one of:

  ``injected_ok``       memory was injected
  ``no_audit_match``    no query_audit_log row matched this turn at all
  ``not_ingested``      audit row exists but candidate_scores is empty
  ``superseded``        rank-1 candidate exists but is lifecycle=superseded
  ``routing_suppressed``one or more top candidates were dropped by a named
                        routing-stage code (suppression / exclusion /
                        post-routing-drop)
  ``retrieval_low_score``decision_reason is ``no_relevant_memory`` or
                        ``low_score`` and no top candidate has a
                        non-trivial routing_score
  ``unknown``           none of the above — emit for manual review

Only ``injected_ok`` and ``no_audit_match`` are decided without inspecting
candidate scores; everything else uses the scored-candidate diagnostics
written by the production routing pipeline.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Candidate normalization
# ---------------------------------------------------------------------------

def candidate_brief(c: dict) -> dict:
    """Project a candidate_scores_json entry to the fields the runner
    surfaces in miss_cases.jsonl (kept narrow to keep rows readable)."""
    return {
        "memory_id": c.get("memory_object_id"),
        "type": c.get("memory_type"),
        "rank": c.get("routing_rank"),
        "routing_score": c.get("routing_score"),
        "lexical_score": c.get("lexical_score"),
        "vector_score": c.get("vector_score"),
        "layer": c.get("layer"),
        "support_grade": c.get("support_grade"),
        "suppression_reason": c.get("suppression_reason_code"),
        "excluded_reason": c.get("excluded_reason_code"),
        "drop_reason": c.get("post_routing_drop_reason"),
        "injected": c.get("injected"),
    }


# ---------------------------------------------------------------------------
# Stage classifier
# ---------------------------------------------------------------------------

def _has_named_drop_code(c: dict) -> bool:
    """A candidate carries a *named* routing-stage drop reason."""
    return bool(
        c.get("suppression_reason_code")
        or c.get("excluded_reason_code")
        or c.get("post_routing_drop_reason")
    )


def _routing_score(c: dict) -> float:
    v = c.get("routing_score")
    return float(v) if isinstance(v, (int, float)) else 0.0


def classify_stage(
    audit: dict | None,
    candidates: list[dict],
    injected: list[dict],
    lifecycles: dict[str, str] | None = None,
) -> dict:
    """Classify the failure stage and return ``{stage, evidence, top_candidates}``.

    ``audit`` may be None (no_audit_match). ``lifecycles`` is an optional
    map memory_id → lifecycle used to detect superseded top candidates.
    """
    lifecycles = lifecycles or {}
    top = [candidate_brief(c) for c in candidates[:5]]

    if audit is None:
        return {
            "stage": "no_audit_match",
            "evidence": "no query_audit_log row matched this turn",
            "top_candidates": [],
        }

    if audit.get("should_inject") and injected:
        return {
            "stage": "injected_ok",
            "evidence": f"{len(injected)} block(s) injected",
            "top_candidates": top,
        }

    if not candidates:
        return {
            "stage": "not_ingested",
            "evidence": (
                "candidate_scores_json empty — no memory retrieved "
                "(likely never ingested or scope mismatch)"
            ),
            "top_candidates": [],
        }

    # Superseded check on the rank-1 candidate
    rank1 = candidates[0]
    rank1_id = rank1.get("memory_object_id")
    if rank1_id and lifecycles.get(rank1_id) == "superseded":
        return {
            "stage": "superseded",
            "evidence": (
                f"rank-1 candidate {rank1_id} has lifecycle=superseded "
                f"(routing_score={rank1.get('routing_score')})"
            ),
            "top_candidates": top,
        }

    # Routing suppression: top candidate had a non-trivial score and a
    # named drop code. We look at the top 5 to be tolerant of ties — if
    # any of them carry a named code we attribute to routing.
    top_scored = [c for c in candidates[:5] if _routing_score(c) > 0]
    if top_scored and any(_has_named_drop_code(c) for c in top_scored):
        codes = _collect_codes(candidates)
        ev = (
            f"reason={audit.get('decision_reason')}; "
            f"top routing_score={top_scored[0].get('routing_score')}; "
            f"codes={codes}"
        )
        return {"stage": "routing_suppressed", "evidence": ev, "top_candidates": top}

    reason = (audit.get("decision_reason") or "").lower()
    if "low" in reason or "no_relevant" in reason:
        max_score = top_scored[0].get("routing_score") if top_scored else 0
        return {
            "stage": "retrieval_low_score",
            "evidence": (
                f"reason={audit.get('decision_reason')}; "
                f"max routing_score={max_score}"
            ),
            "top_candidates": top,
        }

    return {
        "stage": "unknown",
        "evidence": (
            f"reason={audit.get('decision_reason')}; "
            f"n_candidates={len(candidates)}; "
            "no named drop code on top candidates"
        ),
        "top_candidates": top,
    }


def _collect_codes(candidates: list[dict]) -> dict[str, list[str]]:
    """Roll up the named drop codes across all candidates, ignoring None."""
    excl = [c.get("excluded_reason_code") for c in candidates]
    sup = [c.get("suppression_reason_code") for c in candidates]
    drop = [c.get("post_routing_drop_reason") for c in candidates]
    return {
        "excluded": [c for c in excl if c],
        "suppressed": [c for c in sup if c],
        "dropped": [c for c in drop if c],
    }
