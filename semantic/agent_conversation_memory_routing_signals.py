from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from core.models import QueryFilters, QueryResultItem, QueryRuntimeContext
from semantic.common import normalize_for_index
from semantic.agent_conversation_memory_constraints import (
    CONSTRAINT_MEMORY_TYPE,
)
from semantic.agent_conversation_memory_threads import (
    _classify_work_signal_text as _thread_classify_work_signal_text,
    _parse_string_list,
)
from semantic.agent_conversation_memory_routing_constants import (
    QuerySignalEnvelope,
    POLICY_SUPPORT_THRESHOLD,
    POLICY_WORK_STATE_USEFULNESS_THRESHOLD,
    ROUTING_LOWER_LEVEL_EXACT_TYPES,
    ROUTING_SUMMARY_TYPES,
    WORK_RESUMPTION_SIGNAL_TYPES,
    WORK_RESUMPTION_THIN_CHECKPOINT_PENALTY,
    _result_layer,
)


# ---------------------------------------------------------------------------
# Work-signal helpers (moved alongside signal functions they support)
# ---------------------------------------------------------------------------

def _work_resumption_signal_types(item: QueryResultItem) -> tuple[str, ...]:
    signal_types: set[str] = set()
    if item.result_kind == "source_hit":
        excerpt = str(item.excerpt or "").strip()
        signal_type = _classify_work_signal_text(item.artifact_kind, excerpt)
        if signal_type:
            signal_types.add(signal_type)
        if excerpt:
            signal_types.add("evidence")
        return tuple(signal for signal in WORK_RESUMPTION_SIGNAL_TYPES if signal in signal_types)

    payload = item.payload or {}
    if item.type == "task_checkpoint":
        if str(payload.get("task") or "").strip():
            signal_types.add("task")
        if str(payload.get("current_state") or "").strip():
            signal_types.add("progress_update")
        if _parse_string_list(payload.get("key_findings")):
            signal_types.add("key_finding")
        if str(payload.get("blocker_state") or "").strip():
            signal_types.add("blocker")
        if str(payload.get("next_step") or "").strip():
            signal_types.add("next_step")
        if _parse_string_list(payload.get("evidence")):
            signal_types.add("evidence")
        if str(payload.get("freshness_signal") or "").strip():
            signal_types.add("freshness")
        for artifact in payload.get("selected_work_artifacts", []):
            if not isinstance(artifact, dict):
                continue
            artifact_signal = str(artifact.get("signal_type") or "").strip()
            if artifact_signal in {"progress_update", "blocker", "next_step"}:
                signal_types.add(artifact_signal)
    elif item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        signal_types.add("key_finding")
        if str(payload.get("decision_evidence_text") or payload.get("investigation_evidence_text") or "").strip():
            signal_types.add("evidence")
    elif item.type in ROUTING_SUMMARY_TYPES:
        if str(payload.get("summary") or "").strip():
            signal_types.add("key_finding")
        for artifact in payload.get("selected_work_artifacts", []):
            if not isinstance(artifact, dict):
                continue
            artifact_signal = str(artifact.get("signal_type") or "").strip()
            if artifact_signal in {"progress_update", "blocker", "next_step"}:
                signal_types.add(artifact_signal)
    elif item.type == "continuity_memory":
        if str(payload.get("carry_forward_answer") or "").strip():
            signal_types.add("key_finding")
    elif item.type == "pattern_memory" and str(payload.get("summary") or "").strip():
        signal_types.add("key_finding")
    return tuple(signal for signal in WORK_RESUMPTION_SIGNAL_TYPES if signal in signal_types)

def _classify_work_signal_text(artifact_kind: str | None, text: str) -> str:
    return _thread_classify_work_signal_text(artifact_kind, text)

def _work_resumption_usefulness_score(item: QueryResultItem, signal_types: tuple[str, ...], *, thin_checkpoint_penalty: int | None = None) -> tuple[int, list[str]]:
    signal_set = set(signal_types)
    reasons: list[str] = []
    score = 0
    if item.result_kind == "memory_hit" and item.type == "task_checkpoint":
        payload = item.payload or {}
        if "task" in signal_set:
            score += 6
        if "progress_update" in signal_set:
            score += 8
        if "key_finding" in signal_set:
            score += 6
        if "blocker" in signal_set:
            score += 12
        if "next_step" in signal_set:
            score += 12
        if "evidence" in signal_set:
            score += 10
        if "freshness" in signal_set:
            score += 8
        selected_work_artifacts = payload.get("selected_work_artifacts", [])
        artifact_count = len(selected_work_artifacts) if isinstance(selected_work_artifacts, list) else 0
        score += min(artifact_count, 3) * 2
        if {"blocker", "next_step", "evidence", "freshness"}.issubset(signal_set) and signal_set.intersection({"progress_update", "key_finding"}):
            score += 10
            reasons.append("sharp_checkpoint")
        if _is_thin_task_checkpoint_payload(payload):
            score -= (thin_checkpoint_penalty if thin_checkpoint_penalty is not None else WORK_RESUMPTION_THIN_CHECKPOINT_PENALTY)
            reasons.append("thin_checkpoint")
        return score, reasons

    if item.result_kind == "source_hit":
        if "blocker" in signal_set:
            score += 12
        if "next_step" in signal_set:
            score += 12
        if "progress_update" in signal_set:
            score += 8
        if "evidence" in signal_set:
            score += 4
        return score, reasons

    if item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        if "key_finding" in signal_set:
            score += 10
        if "evidence" in signal_set:
            score += 6
        return score, reasons

    if item.type in ROUTING_SUMMARY_TYPES and signal_set.intersection({"blocker", "next_step", "progress_update"}):
        score += 8
    return score, reasons

def _is_thin_task_checkpoint_payload(payload: dict[str, object]) -> bool:
    explicit_core_fields = sum(
        1
        for key in ("task", "current_state", "blocker_state", "next_step", "freshness_signal")
        if str(payload.get(key) or "").strip()
    )
    has_findings = bool(_parse_string_list(payload.get("key_findings")))
    has_evidence = bool(_parse_string_list(payload.get("evidence")))
    has_operational_state = bool(str(payload.get("blocker_state") or "").strip() or str(payload.get("next_step") or "").strip())
    return explicit_core_fields < 3 or not has_operational_state or (not has_findings and not has_evidence)


# ---------------------------------------------------------------------------
# Signal envelope: derivation, classification, recall mode selection
# ---------------------------------------------------------------------------

def _build_policy_evidence(
    candidates: list[QueryResultItem],
) -> dict[str, object]:
    task_checkpoint_best_work_usefulness = 0
    source_evidence_best_work_usefulness = 0
    strong_task_checkpoint_survives = False
    structured_best_support = 0
    cross_thread_continuity_survives = False
    constraint_best_support = 0
    constraint_best_kind = ""
    constraint_memory_only_support = 0
    structured_layers = {"thread_summary", "discussion_summary", "continuity_memory"}

    for item in candidates:
        layer = _result_layer(item)
        support = _policy_candidate_support_estimate(item, layer)
        if layer == "task_checkpoint":
            signal_types = _work_resumption_signal_types(item)
            usefulness, _ = _work_resumption_usefulness_score(item, signal_types)
            task_checkpoint_best_work_usefulness = max(task_checkpoint_best_work_usefulness, usefulness)
            if support >= POLICY_SUPPORT_THRESHOLD:
                strong_task_checkpoint_survives = True
        elif layer == "source_evidence":
            signal_types = _work_resumption_signal_types(item)
            usefulness, _ = _work_resumption_usefulness_score(item, signal_types)
            source_evidence_best_work_usefulness = max(source_evidence_best_work_usefulness, usefulness)
        if layer in structured_layers:
            structured_best_support = max(structured_best_support, support)
        if layer == "continuity_memory" and item.thread_ref is None:
            if support >= POLICY_SUPPORT_THRESHOLD:
                cross_thread_continuity_survives = True
        if item.result_kind == "memory_hit" and item.type == CONSTRAINT_MEMORY_TYPE:
            if support > constraint_best_support:
                constraint_best_support = support
                constraint_best_kind = CONSTRAINT_MEMORY_TYPE
            constraint_memory_only_support = max(constraint_memory_only_support, support)
        elif item.result_kind == "memory_hit" and item.type in {"task_checkpoint", "thread_summary"}:
            # Structured types can carry constraint signals
            payload = item.payload or {}
            if payload.get("constraint_text") or payload.get("blocker_state"):
                if support > constraint_best_support:
                    constraint_best_support = support
                    constraint_best_kind = item.type

    return {
        "task_checkpoint_best_work_usefulness": task_checkpoint_best_work_usefulness,
        "source_evidence_best_work_usefulness": source_evidence_best_work_usefulness,
        "strong_task_checkpoint_survives": strong_task_checkpoint_survives,
        "structured_best_support": structured_best_support,
        "cross_thread_continuity_survives": cross_thread_continuity_survives,
        "constraint_best_support": constraint_best_support,
        "constraint_best_kind": constraint_best_kind,
        "constraint_memory_only_support": constraint_memory_only_support,
    }


def _policy_candidate_support_estimate(item: QueryResultItem, layer: str) -> int:
    """Lightweight support estimate for policy-level gates without query token overlap."""
    score = min(len(item.evidence), 3) * 8
    if item.result_kind == "source_hit":
        score += 18
        return score
    payload = item.payload or {}
    if layer == "task_checkpoint":
        explicit_fields = sum(1 for f in ("task", "current_state", "blocker_state", "next_step", "key_findings", "evidence") if payload.get(f))
        score += 18 + min(explicit_fields, 5) * 8
        if payload.get("blocker_state") and payload.get("next_step"):
            score += 10
    elif layer in {"decision", "investigation_outcome"}:
        score += 34
        if payload.get("decision_evidence_text") or payload.get("investigation_evidence_text"):
            score += 10
    elif layer == "continuity_memory":
        score += 18
        if payload.get("carry_forward_answer"):
            score += 18
    elif layer in {"thread_summary", "discussion_summary"}:
        score += 8
    elif item.result_kind == "memory_hit" and item.type == CONSTRAINT_MEMORY_TYPE:
        score += 24
        payload = item.payload or {}
        if payload.get("constraint_text"):
            score += 18
        if payload.get("primary_scope_anchor") and payload.get("target_anchor"):
            score += 12
    return score


def _work_state_evidence_gate_passes(policy_evidence: dict[str, object]) -> bool:
    if bool(policy_evidence["strong_task_checkpoint_survives"]):
        return True
    if int(policy_evidence["task_checkpoint_best_work_usefulness"]) >= POLICY_WORK_STATE_USEFULNESS_THRESHOLD:
        return True
    if int(policy_evidence["source_evidence_best_work_usefulness"]) >= POLICY_WORK_STATE_USEFULNESS_THRESHOLD:
        return True
    return False


def _candidate_layer_dominance(
    candidates: list[QueryResultItem],
) -> dict[str, dict[str, object]]:
    """Per-layer: count, best_support_score. Language-agnostic — no query text."""
    layers: dict[str, dict[str, object]] = {}
    for item in candidates:
        layer = _result_layer(item)
        support = _policy_candidate_support_estimate(item, layer)
        if layer not in layers:
            layers[layer] = {"count": 0, "best_support_score": 0}
        layers[layer]["count"] = int(layers[layer]["count"]) + 1
        layers[layer]["best_support_score"] = max(int(layers[layer]["best_support_score"]), support)
    return layers


def _compute_typed_candidate_evidence(
    candidates: list[QueryResultItem],
    query_filters: QueryFilters | None,
) -> dict[str, object]:
    """Language-agnostic candidate summary — no query text or tokens."""
    layer_dom = _candidate_layer_dominance(candidates)
    memory_layers = {
        layer: info for layer, info in layer_dom.items()
        if layer != "source_evidence"
    }
    dominant_memory_layer = max(
        memory_layers,
        key=lambda layer: int(memory_layers[layer]["best_support_score"]),
    ) if memory_layers else None

    checkpoint_best_usefulness = 0
    strong_checkpoint_present = False
    for item in candidates:
        if _result_layer(item) == "task_checkpoint":
            signal_types = _work_resumption_signal_types(item)
            usefulness, _ = _work_resumption_usefulness_score(item, signal_types)
            checkpoint_best_usefulness = max(checkpoint_best_usefulness, usefulness)
            support = _policy_candidate_support_estimate(item, "task_checkpoint")
            if support >= POLICY_SUPPORT_THRESHOLD:
                strong_checkpoint_present = True

    thread_ref = query_filters.thread_ref if query_filters else None
    same_thread_hit_count = sum(
        1 for item in candidates
        if thread_ref and item.thread_ref == thread_ref
    ) if thread_ref else 0

    source_hit_count = sum(1 for item in candidates if item.result_kind == "source_hit")
    total = len(candidates) or 1

    return {
        "per_layer_support": layer_dom,
        "dominant_memory_layer": dominant_memory_layer,
        "checkpoint_best_usefulness": checkpoint_best_usefulness,
        "strong_checkpoint_present": strong_checkpoint_present,
        "source_hit_count": source_hit_count,
        "source_hit_ratio": source_hit_count / total,
        "same_thread_hit_count": same_thread_hit_count,
        "continuity_memory_present": any(item.type == "continuity_memory" for item in candidates if item.result_kind == "memory_hit"),
        "cross_thread_continuity": any(
            item.type == "continuity_memory" and item.thread_ref is None
            for item in candidates if item.result_kind == "memory_hit"
        ),
        "constraint_memory_present": any(
            item.type == CONSTRAINT_MEMORY_TYPE
            for item in candidates if item.result_kind == "memory_hit"
        ),
    }


def _select_recall_mode(candidate_evidence: dict[str, object]) -> str:
    """Select recall-mode preference from candidate evidence. Weight/shaping only.

    Conservative: only switch from default when the dominant layer type is
    unambiguously the sole substantial signal. Mixed candidate sets always
    get default mode, which is safe broad-recall behavior.
    """
    dominant = candidate_evidence.get("dominant_memory_layer")
    per_layer = candidate_evidence.get("per_layer_support", {})

    def _layer_support(layer: str) -> int:
        info = per_layer.get(layer, {})
        return int(info.get("best_support_score", 0)) if isinstance(info, dict) else 0

    def _has_competing_layers(target_layers: set[str]) -> bool:
        """True if any memory layer outside target_layers has multiple candidates.

        Uses candidate count rather than support score because
        _policy_candidate_support_estimate() gives type-specific bonuses that
        make decision/investigation inherently score higher than pattern/continuity,
        which would suppress competing-layer detection for recall-oriented types.
        """
        for layer, info in per_layer.items():
            if layer in target_layers or layer == "source_evidence":
                continue
            if isinstance(info, dict) and int(info.get("count", 0)) >= 2:
                return True
        return False

    # investigation_preference: dominant investigation_outcome, no competing recall layers
    if (
        dominant == "investigation_outcome"
        and _layer_support("investigation_outcome") >= POLICY_SUPPORT_THRESHOLD
        and not _has_competing_layers({"investigation_outcome", "decision"})
    ):
        return "investigation_preference"

    # sharp_fact_preference: dominant decision/investigation, no competing recall layers
    if dominant in {"decision", "investigation_outcome"}:
        combined = _layer_support("decision") + _layer_support("investigation_outcome")
        if combined >= POLICY_SUPPORT_THRESHOLD and not _has_competing_layers({"decision", "investigation_outcome"}):
            return "sharp_fact_preference"

    # continuity_preference: dominant continuity_memory + same-thread, no competing layers
    if (
        dominant == "continuity_memory"
        and int(candidate_evidence.get("same_thread_hit_count", 0)) > 0
        and not _has_competing_layers({"continuity_memory"})
    ):
        return "continuity_preference"

    return "default"


def _derive_query_signal_envelope(
    *,
    text: str,
    query_tokens: tuple[str, ...],
    policy_evidence: dict[str, object],
    candidate_evidence: dict[str, object],
    anchor_prefiltered_candidates: list[QueryResultItem],
    runtime_context: QueryRuntimeContext | None,
) -> QuerySignalEnvelope:
    """Structural signal derivation: typed candidate evidence drives routing."""
    normalized = normalize_for_index(text)

    # Tier 1: structural/typed derivation
    signals: dict[str, bool] = {
        "low_value": False,
        "history_lookup": False,
        "latest_status_request": False,
        "resume_state": False,
        "evidence_request": False,
    }
    derivation: list[str] = []

    # low_value: empty or ultra-short queries (structural guard)
    if not normalized or not normalized.strip():
        signals["low_value"] = True
        derivation.append("empty_query")
    elif len(normalized.strip()) < 3:
        signals["low_value"] = True
        derivation.append("ultra_short_query")

    if not signals["low_value"]:
        dominant = str(candidate_evidence.get("dominant_memory_layer") or "")
        per_layer = candidate_evidence.get("per_layer_support", {})

        # resume_state: requires resumed_session context + candidate-side evidence
        is_resumed = runtime_context is not None and runtime_context.turn_kind == "resumed_session"
        work_gate = _work_state_evidence_gate_passes(policy_evidence)
        if is_resumed and work_gate:
            signals["resume_state"] = True
            derivation.append("resumed_session_with_evidence")
        elif is_resumed and not work_gate:
            # Fallback: resumed session without checkpoint/usefulness evidence.
            # Accept decisions or investigations as proof of active work context —
            # "pick up where I left off" should surface the last decision even when
            # no task_checkpoint was extracted. Uses a lower support threshold than
            # the general policy gate because the integrating agent has already
            # signaled resumed_session confidence via turn_kind.
            #
            # Only fire when query lacks topical signal (no substantive lexical
            # overlap with candidates). Queries like "which repo changed and why?"
            # have specific topic words and should route normally via recall.
            # Guard: lexical_score=None means non-composite retrieval where we
            # can't measure overlap — skip fallback to avoid false reclassification.
            _candidate_lex_scores = [
                int(getattr(item, "lexical_score", 0) or 0)
                for item in anchor_prefiltered_candidates
                if getattr(item, "lexical_score", None) is not None
            ]
            _best_candidate_lex = max(_candidate_lex_scores) if _candidate_lex_scores else None
            _RESUMED_SESSION_SUPPORT_FLOOR = 40
            _has_supported_sharp = (
                _best_candidate_lex is not None
                and _best_candidate_lex < 2
                and any(
                    item.result_kind == "memory_hit"
                    and getattr(item, "type", None) in ("decision", "investigation_outcome")
                    and _policy_candidate_support_estimate(item, _result_layer(item)) >= _RESUMED_SESSION_SUPPORT_FLOOR
                    for item in anchor_prefiltered_candidates
                )
            )
            if _has_supported_sharp:
                signals["resume_state"] = True
                derivation.append("resumed_session_with_supported_decision")

        # evidence_request: NOT derivable from Tier 1 structural signals

        # history_lookup
        history_layers = {"pattern_memory", "continuity_memory"}
        sharp_layers = {"decision", "investigation_outcome"}
        if dominant in history_layers:
            signals["history_lookup"] = True
            derivation.append(f"dominant_{dominant}")
        elif dominant in sharp_layers:
            layer_info = per_layer.get(dominant, {})
            if isinstance(layer_info, dict) and int(layer_info.get("best_support_score", 0)) >= POLICY_SUPPORT_THRESHOLD:
                signals["history_lookup"] = True
                derivation.append(f"strong_{dominant}")

        # latest_status_request: requires dominant fresh state memory
        if not any(signals[s] for s in ("resume_state", "history_lookup")):
            from datetime import timezone as _tz
            _now = datetime.now(_tz.utc)
            for item in anchor_prefiltered_candidates:
                if item.result_kind != "memory_hit":
                    continue
                if item.type not in {"task_checkpoint", "thread_summary"}:
                    continue
                payload = item.payload or {}
                has_state = bool(payload.get("current_state") or payload.get("freshness_signal"))
                if not has_state:
                    continue
                if item.freshness_at and (_now - item.freshness_at).total_seconds() < 86400:
                    layer = _result_layer(item)
                    if layer == dominant:
                        signals["latest_status_request"] = True
                        derivation.append("dominant_fresh_state_memory")
                        break

    # Tier 1 confidence
    active_signals = [s for s, v in signals.items() if v and s != "low_value"]
    if signals["low_value"] or len(active_signals) == 1:
        tier1_confidence = "high"
    elif len(active_signals) > 1:
        tier1_confidence = "medium"
    else:
        tier1_confidence = "low"

    if tier1_confidence in ("high", "medium"):
        return QuerySignalEnvelope(
            **signals,
            source="structural",
            confidence=tier1_confidence,
            semantic_classification_used=False,
            derivation_signals=tuple(derivation),
        )

    # Low confidence: return structural envelope with all signals False.
    # Candidate evidence drives routing through lane narrowing.
    return QuerySignalEnvelope(
        **signals,
        source="structural",
        confidence="low",
        semantic_classification_used=False,
        derivation_signals=tuple(derivation),
    )


def _check_evidence_trace_override(
    *,
    envelope: QuerySignalEnvelope,
    source_ratio: float,
    query_text: str,
    candidates: list[QueryResultItem],
    runtime_context: QueryRuntimeContext | None,
    resolver_config: dict[str, object] | None,
    resolver_fn: Callable[..., bool] | None = None,
) -> QuerySignalEnvelope:
    """Post-envelope evidence_trace override via resolver. Orthogonal to Tier cascade."""
    if envelope.evidence_request:
        return envelope  # already detected
    if envelope.low_value:
        return envelope  # noise/greeting — never invoke resolver
    if source_ratio < 0.3:
        return envelope  # insufficient source presence
    if envelope.resume_state:
        return envelope  # stronger route already won
    if resolver_config is None or not resolver_config.get("resolver_enabled", True):
        return envelope  # resolver not available
    if resolver_fn is None:
        return envelope  # no resolver callable provided

    selected = resolver_fn(
        ambiguity_pair_type="evidence_trace_vs_recall",
        query_text=query_text,
        candidates=candidates,
        runtime_context=runtime_context,
        resolver_config=resolver_config,
        option_a={"query_policy_family": "evidence_trace", "allowed_query_intents": ["evidence_trace"], "score": 0},
        option_b={"query_policy_family": "recall_fact", "allowed_query_intents": ["recall"], "score": 0},
    )
    if selected:
        return QuerySignalEnvelope(
            low_value=envelope.low_value,
            history_lookup=envelope.history_lookup,
            latest_status_request=envelope.latest_status_request,
            resume_state=envelope.resume_state,
            evidence_request=True,
            source="semantic",
            confidence="medium",
            semantic_classification_used=True,
            derivation_signals=envelope.derivation_signals + ("resolver_evidence_override",),
        )
    return envelope


def _policy_family_from_signal_envelope(envelope: QuerySignalEnvelope) -> str:
    """Map signal envelope to coarse route / policy family."""
    if envelope.low_value:
        return "noise"
    if envelope.resume_state:
        return "resume_work"
    if envelope.evidence_request:
        return "recall_fact"  # evidence_trace handled at lane level
    if envelope.latest_status_request:
        return "latest_status"
    return "recall_fact"
