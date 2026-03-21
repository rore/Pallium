"""Bounded multilingual query-signal classifier.

Separate contract from the pairwise query_ambiguity_resolution resolver.
This classifier answers ONE binary question: is the user asking for evidence,
proof, or source provenance?

Only invoked when:
- Tier 1 structural derivation didn't set evidence_request
- Source hits exist in candidates
- No higher-priority hard route (work_resumption, constraint) already won
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class SignalClassificationPacket:
    normalized_query_text: str
    turn_kind: str | None
    candidate_layer_summary: dict[str, int]
    dominant_memory_layer: str | None
    has_constraint_memory: bool
    has_source_evidence: bool
    source_evidence_ratio: float


@dataclass(frozen=True)
class SignalClassificationResult:
    primary_signal: str
    confidence: str
    reason_codes: tuple[str, ...]
    latency_ms: float = 0.0

    @property
    def is_resolved(self) -> bool:
        return self.primary_signal != "unresolved" and self.confidence in {"high", "medium"}


SIGNAL_CLASSIFICATION_PROMPT_VARIANTS = {
    "qsc_v1_evidence_request": (
        "You are classifying a user query for a memory sidecar.\n"
        "The sidecar stores decisions, investigation outcomes, task checkpoints, "
        "pattern memory, continuity memory, and source evidence.\n\n"
        "Query: {query_text}\n"
        "Available memory types: {candidate_summary}\n"
        "Session context: {turn_kind}\n\n"
        "Answer ONE question: Is the user asking for evidence, proof, source "
        "provenance, or to see what backs up a claim?\n\n"
        "Respond with JSON:\n"
        '{{"signal": "evidence_request" or "unresolved", '
        '"confidence": "high" or "medium" or "low", '
        '"reason": "brief explanation"}}\n\n'
        "If uncertain, return unresolved. It is always safe to return unresolved."
    ),
}


def build_signal_classification_packet(
    *,
    query_text: str,
    candidate_evidence: dict[str, object],
    runtime_context=None,
) -> SignalClassificationPacket:
    per_layer = candidate_evidence.get("per_layer_support", {})
    layer_summary = {
        layer: int(info.get("count", 0))
        for layer, info in per_layer.items()
        if isinstance(info, dict) and int(info.get("count", 0)) > 0
    }
    return SignalClassificationPacket(
        normalized_query_text=query_text,
        turn_kind=runtime_context.turn_kind if runtime_context else None,
        candidate_layer_summary=layer_summary,
        dominant_memory_layer=str(candidate_evidence.get("dominant_memory_layer") or ""),
        has_constraint_memory=bool(candidate_evidence.get("constraint_memory_present")),
        has_source_evidence=int(candidate_evidence.get("source_hit_count", 0)) > 0,
        source_evidence_ratio=float(candidate_evidence.get("source_hit_ratio", 0)),
    )


def classify_evidence_request(
    *,
    packet: SignalClassificationPacket,
    provider=None,
    prompt_variant: str = "qsc_v1_evidence_request",
    timeout_ms: int = 600,
) -> SignalClassificationResult:
    """Classify whether a query is an evidence/proof request.

    Currently a stub that returns UNRESOLVED. When a live LLM provider is
    wired, this will invoke the provider with the prompt variant and parse
    the bounded JSON response.
    """
    # TODO: Wire live LLM provider call when signal_classifier_enabled and provider available
    return SignalClassificationResult(
        primary_signal="unresolved",
        confidence="low",
        reason_codes=("stub_implementation",),
        latency_ms=0.0,
    )
