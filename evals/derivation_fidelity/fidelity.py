"""Pure fidelity scoring for the source-episode derivation eval.

Where a derived object exists, we ask an offline judge how faithful it is to the
RAW turns it was derived from. Four axes:

- ``completeness`` — does the derived text capture the salient content of the
  linked source turns? (0..1, judged)
- ``unsupported_by_context`` — does the derived text assert anything NOT supported
  by ANY provided turn? (judged). NOTE the axis name: the judge is shown the
  explicitly-linked evidence turns PLUS a bounded same-thread neighbor window, and
  scores against that provided context. It is therefore *unsupported-by-provided-
  context*, deliberately NOT a raw hallucination rate — a claim grounded in an
  adjacent turn we included as context is not a false positive.
- ``drift`` — did the subject/scope shift away from the source? (judged bool)
- ``compression_ratio`` — source_chars / derived_chars (DETERMINISTIC, no LLM).

Judge variance (~20pp, docs/context/lessons.md) is handled by running the judge N
times and aggregating. Because ``CachedLLMProvider``'s cache key has no sample
slot, each sample embeds a distinct ordinal in its prompt so the N calls get
distinct cache keys — genuinely independent draws, still reproducible per
(prompt, ordinal). Single-sample numbers are never treated as ground truth.

Pure functions only — no DB, no provider. The runner supplies turns + derived text
and invokes the judge; aggregation and compression live here.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

FIDELITY_SCHEMA = (
    '{"completeness_score": <float 0..1>, "unsupported_by_context": <bool>, '
    '"unsupported_snippets": [<string>, ...], "drift": <bool>, '
    '"drift_reason": <string>, "notes": <string>}'
)

FIDELITY_SYSTEM_PROMPT = """You are an offline evaluator scoring how faithfully a DERIVED memory object represents the RAW conversation turns it was derived from. You are NOT judging usefulness — only fidelity to the source.

You are given:
- LINKED turns: the source turns explicitly cited as the derived object's evidence.
- CONTEXT turns: nearby turns from the same conversation, provided only so a claim grounded in an adjacent turn is not mistaken for unsupported.
- DERIVED text: the memory object's rendered content.

Score four things:
1. completeness_score (0..1): how much of the salient information in the LINKED turns the DERIVED text preserves. 1.0 = nothing important lost.
2. unsupported_by_context (bool): true if the DERIVED text asserts anything not supported by ANY provided turn (linked or context). List the offending fragments in unsupported_snippets. Judge only against the provided turns; do not use outside knowledge.
3. drift (bool): true if the DERIVED text's subject or scope has shifted away from what the source turns are about. Give drift_reason.
4. notes: one short sentence, optional.

Return exactly one JSON object matching the schema. Ignore any evaluation-pass marker in the input; it does not change your judgement."""


@dataclass(frozen=True)
class FidelitySample:
    completeness_score: float | None
    unsupported_by_context: bool | None
    drift: bool | None
    unsupported_snippets: tuple[str, ...] = ()
    drift_reason: str | None = None
    notes: str | None = None
    parse_ok: bool = True


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"


def build_fidelity_prompt(
    *,
    linked_turns: list[str],
    context_turns: list[str],
    derived_text: str,
    sample_ordinal: int,
    turn_truncate: int = 800,
    derived_truncate: int = 2000,
) -> str:
    """Render the judge user prompt.

    ``sample_ordinal`` is embedded verbatim so that N samples of the same case get
    distinct cache keys under ``CachedLLMProvider`` (whose key hashes the prompt).
    """
    lines: list[str] = [f"<!-- evaluation pass {sample_ordinal} -->", "", "LINKED turns:"]
    if linked_turns:
        for i, t in enumerate(linked_turns, 1):
            lines.append(f"  [{i}] {_truncate(t, turn_truncate)}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("CONTEXT turns:")
    if context_turns:
        for i, t in enumerate(context_turns, 1):
            lines.append(f"  [{i}] {_truncate(t, turn_truncate)}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("DERIVED text:")
    lines.append(_truncate(derived_text, derived_truncate))
    lines.append("")
    lines.append(f"Return one JSON object matching: {FIDELITY_SCHEMA}")
    return "\n".join(lines)


def compression_ratio(source_chars: int, derived_chars: int) -> float | None:
    """Deterministic source/derived length ratio. None when derived is empty."""
    if derived_chars <= 0:
        return None
    return source_chars / derived_chars


# Derived-text field priority — mirrors the write-time corpus builders so the
# judge sees the same "main text" a consumer would.
_DERIVED_TEXT_FIELDS = (
    "decision", "statement", "summary", "investigation_outcome", "rationale",
    "constraint", "text", "interest_text", "outcome", "next_step", "blocker",
)


def derived_text_of(payload: dict | None) -> str:
    """Extract the primary rendered text from a memory object payload."""
    if not isinstance(payload, dict):
        return ""
    for key in _DERIVED_TEXT_FIELDS:
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    import json as _json
    try:
        return _json.dumps(payload, default=str)
    except (TypeError, ValueError):
        return ""


def extract_derivation_version(memory_object) -> dict:
    """Pull the recorded derivation provenance off a MemoryObject.

    Returns schema/prompt-variant/producer-role from ``envelope.derivation`` when
    present, falling back to the object's own schema fields. The concrete model id
    is NOT recorded per object (only the logical ``model_role``); the runner stamps
    the report-time model separately with that caveat.
    """
    env = getattr(memory_object, "envelope", None)
    deriv = getattr(env, "derivation", None) if env is not None else None
    return {
        "memory_type": getattr(memory_object, "type", None),
        "schema_id": getattr(memory_object, "schema_id", None),
        "schema_version": getattr(memory_object, "schema_version", None),
        "producer_kind": getattr(deriv, "producer_kind", None),
        "producer_schema_id": getattr(deriv, "producer_schema_id", None),
        "producer_schema_version": getattr(deriv, "producer_schema_version", None),
        "prompt_variant": getattr(deriv, "prompt_variant", None),
        "model_role": getattr(deriv, "model_role", None),
    }


def parse_fidelity_response(parsed_json: dict | None) -> FidelitySample:
    """Normalize a judge JSON object into a FidelitySample. Tolerant of junk."""
    if not isinstance(parsed_json, dict):
        return FidelitySample(None, None, None, parse_ok=False)

    def _as_float(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, f))

    def _as_bool(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in {"true", "yes", "1"}
        return None

    snippets = parsed_json.get("unsupported_snippets")
    snippets_t = tuple(str(s) for s in snippets) if isinstance(snippets, list) else ()
    return FidelitySample(
        completeness_score=_as_float(parsed_json.get("completeness_score")),
        unsupported_by_context=_as_bool(parsed_json.get("unsupported_by_context")),
        drift=_as_bool(parsed_json.get("drift")),
        unsupported_snippets=snippets_t,
        drift_reason=(str(parsed_json["drift_reason"]) if parsed_json.get("drift_reason") else None),
        notes=(str(parsed_json["notes"]) if parsed_json.get("notes") else None),
        parse_ok=True,
    )


def _majority_bool(values: list[bool]) -> bool | None:
    if not values:
        return None
    trues = sum(1 for v in values if v)
    return trues * 2 > len(values)  # strict majority; tie → False


def aggregate_fidelity(samples: list[FidelitySample]) -> dict:
    """Aggregate N genuinely-independent judge samples. Empty-data-safe.

    Booleans → strict majority; completeness → mean + median. Also reports how
    many samples agreed, to expose residual judge variance rather than hide it.
    """
    valid = [s for s in samples if s.parse_ok]
    n = len(valid)
    scores = [s.completeness_score for s in valid if s.completeness_score is not None]
    unsupported = [s.unsupported_by_context for s in valid if s.unsupported_by_context is not None]
    drift = [s.drift for s in valid if s.drift is not None]

    return {
        "n_samples": n,
        "n_parse_failures": sum(1 for s in samples if not s.parse_ok),
        "completeness_mean": (statistics.fmean(scores) if scores else None),
        "completeness_median": (statistics.median(scores) if scores else None),
        "unsupported_by_context": _majority_bool(unsupported),
        "unsupported_agreement": (sum(unsupported) / len(unsupported) if unsupported else None),
        "drift": _majority_bool(drift),
        "drift_agreement": (sum(drift) / len(drift) if drift else None),
    }
