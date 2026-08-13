"""Representation-quality judge prompt/schema + pure aggregation.

The axis is QUERY-CONDITIONED: holding information and retrieval constant, is the
rendered DERIVED text a correct, non-misleading answer surface FOR THIS LOOKUP vs
the retrieved RAW turns? This is DELIBERATELY DISTINCT from the query-agnostic
source-fidelity axis in ``evals/derivation_fidelity`` (which asks "is the derived
text faithful to the turns it was derived from?"). This eval does NOT re-publish a
source-fidelity unsupported rate; it measures retrieval-conditioned usability /
misleadingness relative to the turns the RAW arm actually retrieved.

The judge is shown the FULL retrieved RAW turns (generously per-turn-capped), NEVER
the token-budget-truncated set — otherwise a claim grounded in a turn we truncated
away would be a false "unsupported". The token-budget axis lives in ``arms.py`` and
is a separate report field.

Judge variance (~20pp, docs/context/lessons.md) is handled by N independent samples.
Because ``CachedLLMProvider``'s cache key hashes the prompt with no sample slot, each
sample embeds a distinct ordinal so the N calls get distinct cache keys — genuinely
independent draws, still reproducible per (prompt, ordinal).

Pure functions only — no DB, no provider. The runner supplies query + turns + derived
text and invokes the judge; aggregation lives here.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

# Re-export so the runner + tests can stamp derivation provenance from one place.
from evals.derivation_fidelity.fidelity import extract_derivation_version  # noqa: F401

REPRESENTATION_SCHEMA = (
    '{"misleading": <bool>, "unsupported": <bool>, "usability_score": <float 0..1>, '
    '"reason": <string>, "notes": <string>}'
)

REPRESENTATION_SYSTEM_PROMPT = """You are an offline evaluator scoring whether a DERIVED memory object is a good ANSWER SURFACE for a specific lookup, compared to the RAW conversation turns that the same lookup retrieved. You are NOT judging fidelity to the turns the object was originally derived from — only whether, for THIS query, the derived text is a correct and non-misleading stand-in for the retrieved RAW turns.

You are given:
- QUERY: the lookup the agent issued.
- RAW turns: the full source turns the RAW arm retrieved for this query.
- DERIVED text: the rendered memory object being evaluated as the answer surface.

Score four things, all relative to the QUERY and the provided RAW turns:
1. misleading (bool): true if the DERIVED text would lead the agent to a WRONG or distorted understanding of the answer to the query, relative to the RAW turns (contradiction, wrong subject, stale/overstated claim).
2. unsupported (bool): true if the DERIVED text asserts something not supported by ANY provided RAW turn. Judge only against the provided turns; do not use outside knowledge.
3. usability_score (0..1): how well the DERIVED text alone answers the query, assuming the RAW turns are the ground truth. 1.0 = fully answers correctly; 0.0 = useless or wrong.
4. reason: one short sentence justifying misleading/unsupported. notes: optional.

Return exactly one JSON object matching the schema. Ignore any evaluation-pass marker in the input; it does not change your judgement."""


@dataclass(frozen=True)
class RepresentationSample:
    misleading: bool | None
    unsupported: bool | None
    usability_score: float | None
    reason: str | None = None
    notes: str | None = None
    parse_ok: bool = True


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"


def build_representation_prompt(
    query: str,
    raw_turns: list[str],
    derived_text: str,
    *,
    sample_ordinal: int,
    turn_truncate: int = 800,
    derived_truncate: int = 2000,
) -> str:
    """Render the judge user prompt.

    ``raw_turns`` are the FULL retrieved RAW turns (per-turn-capped at
    ``turn_truncate``), NOT the token-budget-truncated set. ``sample_ordinal`` is
    embedded verbatim so N samples of the same case get distinct cache keys under
    ``CachedLLMProvider`` (whose key hashes the prompt).
    """
    lines: list[str] = [f"<!-- evaluation pass {sample_ordinal} -->", "", "QUERY:"]
    lines.append(f"  {_truncate(query, turn_truncate)}")
    lines.append("")
    lines.append("RAW turns (full retrieved set for this query):")
    if raw_turns:
        for i, t in enumerate(raw_turns, 1):
            lines.append(f"  [{i}] {_truncate(t, turn_truncate)}")
    else:
        lines.append("  (none retrieved)")
    lines.append("")
    lines.append("DERIVED text:")
    lines.append(_truncate(derived_text, derived_truncate))
    lines.append("")
    lines.append(f"Return one JSON object matching: {REPRESENTATION_SCHEMA}")
    return "\n".join(lines)


def parse_representation_response(parsed_json: dict | None) -> RepresentationSample:
    """Normalize a judge JSON object into a RepresentationSample. Tolerant of junk."""
    if not isinstance(parsed_json, dict):
        return RepresentationSample(None, None, None, parse_ok=False)

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

    return RepresentationSample(
        misleading=_as_bool(parsed_json.get("misleading")),
        unsupported=_as_bool(parsed_json.get("unsupported")),
        usability_score=_as_float(parsed_json.get("usability_score")),
        reason=(str(parsed_json["reason"]) if parsed_json.get("reason") else None),
        notes=(str(parsed_json["notes"]) if parsed_json.get("notes") else None),
        parse_ok=True,
    )


def _majority_bool(values: list[bool]) -> bool | None:
    if not values:
        return None
    trues = sum(1 for v in values if v)
    return trues * 2 > len(values)  # strict majority; tie → False


def aggregate_representation(samples: list[RepresentationSample]) -> dict:
    """Aggregate N genuinely-independent judge samples. Empty-data-safe.

    Booleans → strict majority; usability → mean + median. Also reports per-boolean
    agreement so residual judge variance is exposed rather than hidden.
    """
    valid = [s for s in samples if s.parse_ok]
    n = len(valid)
    scores = [s.usability_score for s in valid if s.usability_score is not None]
    misleading = [s.misleading for s in valid if s.misleading is not None]
    unsupported = [s.unsupported for s in valid if s.unsupported is not None]

    return {
        "seam": "representation_quality",
        "n_samples": n,
        "n_parse_failures": sum(1 for s in samples if not s.parse_ok),
        "usability_mean": (statistics.fmean(scores) if scores else None),
        "usability_median": (statistics.median(scores) if scores else None),
        "misleading": _majority_bool(misleading),
        "misleading_agreement": (sum(misleading) / len(misleading) if misleading else None),
        "unsupported": _majority_bool(unsupported),
        "unsupported_agreement": (sum(unsupported) / len(unsupported) if unsupported else None),
    }
