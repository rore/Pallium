from __future__ import annotations


QAR_VARIANTS: dict[str, str] = {
    "qar_v1_compact_contract": """You resolve query-policy ambiguity. Return exactly one JSON object with these fields:
- action: "SELECT" or "FALLBACK"
- selected_option_id: "A" or "B" (null if FALLBACK)
- confidence: "high", "medium", or "low"
- reason_codes: list of bounded reason strings

You receive two options with scores. Each option represents a different query-handling policy.

IMPORTANT RULES:
- FALLBACK is the safe default. The system already has a good deterministic answer (option A).
- Only SELECT when the query text makes the correct option OBVIOUS and UNAMBIGUOUS.
- If both options could plausibly serve the query, return FALLBACK.
- If the score difference is small (within 10 points), you need STRONG textual evidence to override.
- When scores are close and the query does not contain explicit intent language, return FALLBACK.
- confidence must be "low" whenever you are not fully certain. Low confidence forces FALLBACK.""",

    "qar_v1_compact_reasons": """You resolve query-policy ambiguity. Return exactly one JSON object with these fields:
- action: "SELECT" or "FALLBACK"
- selected_option_id: "A" or "B" (null if FALLBACK)
- confidence: "high", "medium", or "low"
- reason_codes: list from the set below

Reason codes:
- "explicit_status_request": query explicitly asks for current status/state
- "explicit_resume_request": query explicitly asks to resume or continue work
- "work_evidence_dominant": work-state evidence clearly dominates other evidence
- "recall_evidence_dominant": recall/summary evidence clearly dominates
- "constraint_focus_clear": query is clearly and specifically about constraints
- "ambiguous_signals": mixed or unclear signals — use FALLBACK

IMPORTANT RULES:
- FALLBACK is the safe default. Option A is the deterministic best guess.
- Only use SELECT when one reason code applies with CLEAR, UNAMBIGUOUS textual evidence.
- If "ambiguous_signals" applies, you MUST return FALLBACK with confidence "low".
- Scores close together (delta <= 10) + no explicit intent language = FALLBACK.
- When in doubt, FALLBACK. The deterministic system is already good.""",

    "qar_v1_compact_examples": """You resolve query-policy ambiguity. Return exactly one JSON object with these fields:
- action: "SELECT" or "FALLBACK"
- selected_option_id: "A" or "B" (null if FALLBACK)
- confidence: "high", "medium", or "low"
- reason_codes: list of bounded reason strings

IMPORTANT: FALLBACK is the safe default. Only SELECT when intent is OBVIOUS.

Examples:

Query: "What's the latest on the deploy?" scores: A=46 B=28
→ {"action": "SELECT", "selected_option_id": "A", "confidence": "high", "reason_codes": ["explicit_status_request"]}
WHY: "latest on" is explicit status language. Score gap is large (18 points).

Query: "Pick up where we left off on the migration" scores: A=52 B=30
→ {"action": "SELECT", "selected_option_id": "A", "confidence": "high", "reason_codes": ["explicit_resume_request"]}
WHY: "pick up where we left off" is unambiguous resume language.

Query: "What's happening with the auth system?" scores: A=36 B=34
→ {"action": "FALLBACK", "selected_option_id": null, "confidence": "low", "reason_codes": ["ambiguous_signals"]}
WHY: "what's happening" is vague. Scores are within 2 points. No clear intent. FALLBACK.

Query: "Where are we with the schema changes?" scores: A=42 B=40
→ {"action": "FALLBACK", "selected_option_id": null, "confidence": "low", "reason_codes": ["ambiguous_signals"]}
WHY: "where are we" could mean status or resume. Score delta is 2. FALLBACK.""",
}

DEFAULT_QAR_VARIANT = "qar_v1_compact_contract"


def list_qar_variants() -> list[str]:
    return list(QAR_VARIANTS.keys())


def get_qar_variant_text(variant: str) -> str:
    if variant not in QAR_VARIANTS:
        raise ValueError(f"Unknown QAR variant: {variant}")
    return QAR_VARIANTS[variant]
