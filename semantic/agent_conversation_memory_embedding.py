from __future__ import annotations

from core.models import MemoryObject, SourceItem


EMBEDDABLE_MEMORY_TYPES = {
    "decision",
    "investigation_outcome",
    "thread_summary",
    "task_checkpoint",
    "pattern_memory",
    "continuity_memory",
}

# Placeholder constants — replaced with real provider values in Part 6.
VECTOR_EMBEDDING_PROVIDER_NAME = "embedding"
VECTOR_EMBEDDING_PROVIDER_VERSION = "pending"


def build_embedding_text(memory_object: MemoryObject) -> str | None:
    """Build one retrieval-oriented text view per memory type.

    Uses selected payload fields in natural language (not normalize_for_index).
    Returns None if type is not embeddable.
    """
    memory_type = memory_object.type
    payload = memory_object.payload

    if memory_type not in EMBEDDABLE_MEMORY_TYPES:
        return None

    builders = {
        "decision": _build_decision_text,
        "investigation_outcome": _build_investigation_outcome_text,
        "thread_summary": _build_thread_summary_text,
        "task_checkpoint": _build_task_checkpoint_text,
        "pattern_memory": _build_pattern_memory_text,
        "continuity_memory": _build_continuity_memory_text,
    }
    builder = builders.get(memory_type)
    if builder is None:
        return None
    text = builder(payload)
    return text if text and len(text) >= 40 else None


def _build_decision_text(payload: dict) -> str:
    """Decision: decision_text + rationale_text."""
    parts: list[str] = []
    decision = payload.get("decision")
    if decision:
        parts.append(f"Decision: {decision}")
    rationale = payload.get("rationale")
    if rationale:
        parts.append(f"Rationale: {rationale}")
    return " ".join(parts) if parts else ""


def _build_investigation_outcome_text(payload: dict) -> str:
    """Investigation outcome: investigation_text + key_finding_text + rationale_text."""
    parts: list[str] = []
    investigation = payload.get("investigation_outcome")
    if investigation:
        parts.append(f"Investigation outcome: {investigation}")
    key_finding = payload.get("key_finding_text")
    if key_finding:
        parts.append(f"Key finding: {key_finding}")
    rationale = payload.get("rationale")
    if rationale:
        parts.append(f"Rationale: {rationale}")
    return " ".join(parts) if parts else ""


def _build_thread_summary_text(payload: dict) -> str:
    """Thread summary: summary + conclusion texts."""
    parts: list[str] = []
    summary = payload.get("summary")
    if summary:
        parts.append(summary)
    conclusions = payload.get("conclusions") or []
    for conclusion in conclusions:
        text = conclusion.get("text") if isinstance(conclusion, dict) else None
        if text:
            parts.append(text)
    return " ".join(parts) if parts else ""


def _build_task_checkpoint_text(payload: dict) -> str:
    """Task checkpoint: task + current_state + blocker_state + next_step + key_findings."""
    parts: list[str] = []
    task = payload.get("task")
    if task:
        parts.append(f"Task: {task}")
    current_state = payload.get("current_state")
    if current_state:
        parts.append(f"Current state: {current_state}")
    blocker_state = payload.get("blocker_state")
    if blocker_state:
        parts.append(f"Blocker: {blocker_state}")
    next_step = payload.get("next_step")
    if next_step:
        parts.append(f"Next step: {next_step}")
    key_findings = payload.get("key_findings") or []
    for finding in key_findings:
        if finding:
            parts.append(f"Finding: {finding}")
    return " ".join(parts) if parts else ""


def _build_pattern_memory_text(payload: dict) -> str:
    """Pattern memory: summary + conclusion texts."""
    parts: list[str] = []
    summary = payload.get("summary")
    if summary:
        parts.append(summary)
    conclusions = payload.get("conclusions") or []
    for conclusion in conclusions:
        text = conclusion.get("text") if isinstance(conclusion, dict) else None
        if text:
            parts.append(text)
    return " ".join(parts) if parts else ""


def _build_continuity_memory_text(payload: dict) -> str:
    """Continuity memory: continuity_question + carry_forward_answer + summary."""
    parts: list[str] = []
    question = payload.get("continuity_question")
    if question:
        parts.append(f"Question: {question}")
    answer = payload.get("carry_forward_answer")
    if answer:
        parts.append(f"Answer: {answer}")
    summary = payload.get("summary")
    if summary:
        parts.append(summary)
    return " ".join(parts) if parts else ""


def source_item_embedding_text(source_item: SourceItem) -> str | None:
    """agent_conversation_memory policy: embed user messages and assistant outputs >= 40 chars."""
    if source_item.artifact_kind not in ("message", "assistant_output"):
        return None
    if len(source_item.content) < 40:
        return None
    return source_item.content
