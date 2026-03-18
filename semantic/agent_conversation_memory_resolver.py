from __future__ import annotations

import json
from dataclasses import dataclass

from semantic.agent_conversation_memory_resolver_prompts import get_qar_variant_text


@dataclass(frozen=True)
class ResolverPacket:
    normalized_query_text: str
    turn_kind: str | None
    ambiguity_pair_type: str
    option_a_summary: dict[str, object]
    option_b_summary: dict[str, object]
    candidate_cards: list[dict[str, object]]


@dataclass(frozen=True)
class ResolverResult:
    action: str  # "SELECT" or "FALLBACK"
    selected_option_id: str | None  # "A", "B", or None
    confidence: str  # "high", "medium", "low"
    reason_codes: tuple[str, ...]
    latency_ms: float = 0.0

    @property
    def is_valid_selection(self) -> bool:
        return (
            self.action == "SELECT"
            and self.selected_option_id in {"A", "B"}
            and self.confidence in {"high", "medium"}
        )


FALLBACK_RESULT = ResolverResult(
    action="FALLBACK",
    selected_option_id=None,
    confidence="low",
    reason_codes=("deterministic_fallback",),
)


def resolve_query_ambiguity(
    *,
    provider: object,
    model: str | None,
    prompt_variant: str,
    resolver_packet: ResolverPacket,
    timeout_ms: int = 800,
) -> ResolverResult:
    """Resolve query ambiguity via LLM call. Falls back on any failure."""
    import time

    start = time.monotonic()
    try:
        result = _invoke_resolver(
            provider=provider,
            model=model,
            prompt_variant=prompt_variant,
            packet=resolver_packet,
            timeout_ms=timeout_ms,
        )
        elapsed = (time.monotonic() - start) * 1000
        if not result.is_valid_selection:
            return ResolverResult(
                action="FALLBACK",
                selected_option_id=None,
                confidence=result.confidence,
                reason_codes=result.reason_codes + ("invalid_selection_fallback",),
                latency_ms=elapsed,
            )
        return ResolverResult(
            action=result.action,
            selected_option_id=result.selected_option_id,
            confidence=result.confidence,
            reason_codes=result.reason_codes,
            latency_ms=elapsed,
        )
    except Exception:
        elapsed = (time.monotonic() - start) * 1000
        return ResolverResult(
            action="FALLBACK",
            selected_option_id=None,
            confidence="low",
            reason_codes=("provider_failure",),
            latency_ms=elapsed,
        )


def _invoke_resolver(
    *,
    provider: object,
    model: str | None,
    prompt_variant: str,
    packet: ResolverPacket,
    timeout_ms: int,
) -> ResolverResult:
    """Invoke the LLM provider for ambiguity resolution with timeout enforcement."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

    from providers.llm.base import LLMProvider

    if not isinstance(provider, LLMProvider):
        return FALLBACK_RESULT

    system_prompt = get_qar_variant_text(prompt_variant)
    user_prompt = _build_resolver_user_prompt(packet)
    schema_description = '{"action":"SELECT|FALLBACK","selected_option_id":"A|B|null","confidence":"high|medium|low","reason_codes":["string"]}'

    timeout_seconds = timeout_ms / 1000.0

    def _call():
        return provider.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_description=schema_description,
        )

    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(_call)
    try:
        response = future.result(timeout=timeout_seconds)
    except FuturesTimeoutError:
        future.cancel()
        pool.shutdown(wait=False)
        return ResolverResult(
            action="FALLBACK",
            selected_option_id=None,
            confidence="low",
            reason_codes=("timeout",),
        )
    pool.shutdown(wait=False)
    return _parse_resolver_response(response.parsed_json)


def _build_resolver_user_prompt(packet: ResolverPacket) -> str:
    parts = [
        f"Query: {packet.normalized_query_text}",
    ]
    if packet.turn_kind:
        parts.append(f"Turn kind: {packet.turn_kind}")
    parts.append(f"Ambiguity type: {packet.ambiguity_pair_type}")
    parts.append("")

    score_a = packet.option_a_summary.get("score", "?")
    score_b = packet.option_b_summary.get("score", "?")
    parts.append(f"Option A ({packet.option_a_summary.get('query_policy_family', '?')}): score={score_a}")
    parts.append(f"  Allowed intents: {packet.option_a_summary.get('allowed_query_intents', [])}")
    parts.append(f"Option B ({packet.option_b_summary.get('query_policy_family', '?')}): score={score_b}")
    parts.append(f"  Allowed intents: {packet.option_b_summary.get('allowed_query_intents', [])}")

    try:
        delta = abs(int(score_a) - int(score_b))
        parts.append(f"Score delta: {delta} points")
    except (TypeError, ValueError):
        pass

    if packet.candidate_cards:
        parts.append("")
        parts.append("Candidate evidence:")
        for card in packet.candidate_cards:
            parts.append(f"  - [{card.get('layer')}] {card.get('summary', '')} (support: {card.get('support_score', 0)})")
    return "\n".join(parts)


def _parse_resolver_response(parsed: dict) -> ResolverResult:
    action = str(parsed.get("action", "FALLBACK")).upper()
    if action not in {"SELECT", "FALLBACK"}:
        action = "FALLBACK"

    selected = parsed.get("selected_option_id")
    if selected is not None:
        selected = str(selected).upper()
        if selected not in {"A", "B"}:
            selected = None

    confidence = str(parsed.get("confidence", "low")).lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"

    raw_codes = parsed.get("reason_codes", [])
    if isinstance(raw_codes, list):
        reason_codes = tuple(str(c) for c in raw_codes[:5])
    else:
        reason_codes = ()

    return ResolverResult(
        action=action,
        selected_option_id=selected,
        confidence=confidence,
        reason_codes=reason_codes,
    )


def build_resolver_packet(
    *,
    query_text: str,
    turn_kind: str | None,
    ambiguity_pair_type: str,
    option_a: dict[str, object],
    option_b: dict[str, object],
    candidates: list[dict[str, object]],
) -> ResolverPacket:
    """Build a bounded resolver request packet with exactly 2-3 candidate cards."""
    option_a_summary = {
        "option_id": "A",
        "query_policy_family": option_a.get("query_policy_family"),
        "allowed_query_intents": option_a.get("allowed_query_intents"),
        "score": option_a.get("score"),
    }
    option_b_summary = {
        "option_id": "B",
        "query_policy_family": option_b.get("query_policy_family"),
        "allowed_query_intents": option_b.get("allowed_query_intents"),
        "score": option_b.get("score"),
    }

    # Select candidate cards: 1 for option A, 1 for option B, 1 shared tie-break
    card_a = _select_exemplar_card(candidates, option_a)
    card_b = _select_exemplar_card(candidates, option_b)
    cards = []
    if card_a:
        cards.append(card_a)
    if card_b and card_b.get("result_id") != (card_a or {}).get("result_id"):
        cards.append(card_b)

    used_ids = {c.get("result_id") for c in cards}
    tie_break = _select_tie_break_card(candidates, used_ids)
    if tie_break:
        cards.append(tie_break)

    return ResolverPacket(
        normalized_query_text=query_text,
        turn_kind=turn_kind,
        ambiguity_pair_type=ambiguity_pair_type,
        option_a_summary=option_a_summary,
        option_b_summary=option_b_summary,
        candidate_cards=cards[:3],
    )


OPTION_FAMILY_PREFERRED_LAYERS: dict[str, tuple[str, ...]] = {
    "resume_work": ("task_checkpoint", "source_evidence"),
    "latest_status": ("thread_summary", "discussion_summary", "continuity_memory", "pattern_memory"),
    "check_constraints": ("constraint_memory", "task_checkpoint"),
    "recall_fact": ("pattern_memory", "investigation_outcome", "decision", "continuity_memory"),
}


def _select_exemplar_card(
    candidates: list[dict[str, object]],
    option: dict[str, object],
) -> dict[str, object] | None:
    """Select the highest-support candidate whose layer aligns with the option's preferred family."""
    family = str(option.get("query_policy_family", ""))
    preferred_layers = OPTION_FAMILY_PREFERRED_LAYERS.get(family, ())

    # First pass: prefer candidates on a preferred layer for this option
    best = None
    best_support = -1
    for c in candidates:
        layer = str(c.get("layer", ""))
        support = int(c.get("support_score", 0))
        if layer in preferred_layers and support > best_support:
            best_support = support
            best = c

    # Fallback: if no preferred-layer match, take global best
    if best is None:
        for c in candidates:
            support = int(c.get("support_score", 0))
            if support > best_support:
                best_support = support
                best = c

    if best is None:
        return None
    return {
        "result_id": best.get("result_id"),
        "layer": best.get("layer"),
        "memory_type": best.get("memory_type"),
        "support_score": best.get("support_score"),
        "summary": _truncate(str(best.get("summary", "")), 200),
    }


def _select_tie_break_card(
    candidates: list[dict[str, object]],
    used_ids: set[object],
) -> dict[str, object] | None:
    """Select the highest-support candidate not already used."""
    best = None
    best_support = -1
    for c in candidates:
        if c.get("result_id") in used_ids:
            continue
        support = int(c.get("support_score", 0))
        if support > best_support:
            best_support = support
            best = c
    if best is None:
        return None
    return {
        "result_id": best.get("result_id"),
        "layer": best.get("layer"),
        "memory_type": best.get("memory_type"),
        "support_score": best.get("support_score"),
        "summary": _truncate(str(best.get("summary", "")), 200),
    }


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."
