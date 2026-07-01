"""W5 PR 2 — typed one-pass shadow extractor.

Single LLM call, strict-JSON output, five named arrays. Produces
``TypedShadowExtraction`` objects that the persistence layer (PR 1's
``insert_shadow_extraction``) writes to ``memory_objects_shadow``.

**Contract — never raises.** ``run_typed_shadow_extraction`` catches
every kind of LLM/parse error and returns a well-formed
``TypedShadowExtraction`` with ``parse_status`` set to
``"llm_error"`` or ``"schema_failure"``. The caller in
``core/processing.py`` (PR 3) additionally wraps the call in a
``try/except`` regardless. This is the load-bearing property for
the "zero effect on live retrieval" guarantee: nothing the shadow
does can break the live extraction path.

**Zero live-path imports.** This module MUST NOT import from
`storage.*` (aside from the shadow-record type it emits),
`core.routing`, `core.query`, `core.service`, or any live-extractor
module (`semantic.llm_agent_memory`, `semantic.agent_conversation_memory`).
Enforced by :mod:`tests.test_extraction_typed_shadow_isolation`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from core.models import SourceItem, new_id, utc_now
from providers.llm.base import LLMCallMetadata, LLMProvider, LLMProviderError

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Prompt version + schema description                                         #
# --------------------------------------------------------------------------- #

TYPED_SHADOW_PROMPT_VERSION: Final[str] = "typed_shadow_v1"

# Bound on combined system+user prompt length; enforced by test.
MAX_PROMPT_BYTES: Final[int] = 12 * 1024

# Length caps on individual extracted fields to prevent runaway payloads.
MAX_SUBJECT_LEN: Final[int] = 200
MAX_STATEMENT_LEN: Final[int] = 2000
MAX_RATIONALE_LEN: Final[int] = 2000
MAX_EVIDENCE_LEN: Final[int] = 4000
MAX_ARTIFACT_LEN: Final[int] = 500
MAX_COMMAND_FAMILY_LEN: Final[int] = 80
MAX_ITEMS_PER_ARRAY: Final[int] = 8
MAX_SUPERSESSION_ITEMS: Final[int] = 4


_SCHEMA_DESCRIPTION: Final[str] = """\
Return a JSON object with EXACTLY these five arrays. Every array must
be present (empty arrays are legal). Do not include any other keys.

Schema:

{
  "decisions": [
    {
      "subject": str (<=200 chars),
      "statement": str (<=2000 chars),
      "rationale": str | null (<=2000 chars),
      "evidence_span": str (<=4000 chars),
      "alternatives_rejected": [str] (optional, max 8 items)
    }
  ] (max 8 items),
  "investigations": [
    {
      "subject": str,
      "hypothesis": str (<=1000 chars),
      "outcome": "confirmed" | "ruled_out" | "inconclusive",
      "resolution": str | null (<=2000 chars),
      "evidence_span": str
    }
  ] (max 8 items),
  "constraints": [
    {
      "subject": str,
      "modality": "prohibit" | "prefer" | "require",
      "action": "use_surface" | "use_source" | "perform_step",
      "statement": str,
      "evidence_span": str
    }
  ] (max 8 items),
  "operational_facts": [
    {
      "command_family": str (<=80 chars),
      "subject": str,
      "artifact": str (<=500 chars),
      "outcome": "success" | "failure" | null,
      "evidence_span": str
    }
  ] (max 8 items),
  "supersessions": [
    {
      "subject": str,
      "supersedes_statement": str,
      "new_statement": str,
      "evidence_span": str
    }
  ] (max 4 items)
}

Extract each array only when the source item genuinely contains
that kind of information. Prefer empty arrays over speculative or
low-confidence entries. Every non-empty item must cite an
evidence_span verbatim from the source content.
"""


_SYSTEM_PROMPT: Final[str] = (
    "You are a typed memory extractor. Read the source item and return "
    "EXACTLY one JSON object matching the schema below. Do not add prose, "
    "do not add commentary, do not include arrays outside the five named. "
    "If you are uncertain whether an item belongs to a type, omit it.\n\n"
    + _SCHEMA_DESCRIPTION
)


# --------------------------------------------------------------------------- #
# Public dataclasses                                                          #
# --------------------------------------------------------------------------- #


ParseStatus = Literal["ok", "schema_failure", "llm_error"]


@dataclass(frozen=True)
class TypedShadowDecision:
    subject: str
    statement: str
    evidence_span: str
    rationale: str | None = None
    alternatives_rejected: tuple[str, ...] = ()


@dataclass(frozen=True)
class TypedShadowInvestigation:
    subject: str
    hypothesis: str
    outcome: Literal["confirmed", "ruled_out", "inconclusive"]
    evidence_span: str
    resolution: str | None = None


@dataclass(frozen=True)
class TypedShadowConstraint:
    subject: str
    modality: Literal["prohibit", "prefer", "require"]
    action: Literal["use_surface", "use_source", "perform_step"]
    statement: str
    evidence_span: str


@dataclass(frozen=True)
class TypedShadowOperationalFact:
    command_family: str
    subject: str
    artifact: str
    evidence_span: str
    outcome: Literal["success", "failure"] | None = None


@dataclass(frozen=True)
class TypedShadowSupersession:
    subject: str
    supersedes_statement: str
    new_statement: str
    evidence_span: str


@dataclass(frozen=True)
class TypedShadowExtraction:
    """Result of running the shadow extractor on one source item.

    ``parse_status``:
      - ``"ok"`` — LLM returned well-formed JSON matching the schema.
      - ``"schema_failure"`` — JSON returned but did not match the
        schema. Individual malformed items are dropped; the arrays
        contain only the well-formed items (which may all be empty).
      - ``"llm_error"`` — the LLM call itself failed (timeout,
        rate-limit, connection). Every array is empty.
    """

    decisions: tuple[TypedShadowDecision, ...] = ()
    investigations: tuple[TypedShadowInvestigation, ...] = ()
    constraints: tuple[TypedShadowConstraint, ...] = ()
    operational_facts: tuple[TypedShadowOperationalFact, ...] = ()
    supersessions: tuple[TypedShadowSupersession, ...] = ()
    prompt_version: str = TYPED_SHADOW_PROMPT_VERSION
    llm_call_metadata: LLMCallMetadata | None = None
    parse_status: ParseStatus = "ok"
    parse_error: str | None = None
    shadow_run_id: str = field(default_factory=new_id)

    def total_items(self) -> int:
        return (
            len(self.decisions)
            + len(self.investigations)
            + len(self.constraints)
            + len(self.operational_facts)
            + len(self.supersessions)
        )


# --------------------------------------------------------------------------- #
# Public entry point — never raises                                           #
# --------------------------------------------------------------------------- #


def run_typed_shadow_extraction(
    source_item: SourceItem,
    *,
    provider: LLMProvider,
    prompt_version: str = TYPED_SHADOW_PROMPT_VERSION,
) -> TypedShadowExtraction:
    """Extract typed memories from a source item via one LLM call.

    Pure semantic operation — no I/O apart from the LLM call itself
    (which the provider owns). Never raises: LLM errors and schema
    violations are captured in the returned ``TypedShadowExtraction``'s
    ``parse_status`` field.

    ``prompt_version`` is a caller-visible override, primarily for
    testing prompt evolution; production callers should pass the
    module-level constant.
    """
    user_prompt = _build_user_prompt(source_item)

    try:
        response = provider.generate_json(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema_description=_SCHEMA_DESCRIPTION,
        )
    except LLMProviderError as exc:
        logger.warning(
            "shadow_extraction_llm_error",
            extra={
                "source_item_id": source_item.id,
                "error": str(exc)[:500],
            },
        )
        return TypedShadowExtraction(
            prompt_version=prompt_version,
            parse_status="llm_error",
            parse_error=str(exc)[:500],
        )
    except Exception as exc:  # noqa: BLE001 -- shadow must never propagate
        logger.warning(
            "shadow_extraction_unexpected_error",
            extra={
                "source_item_id": source_item.id,
                "error": repr(exc)[:500],
            },
        )
        return TypedShadowExtraction(
            prompt_version=prompt_version,
            parse_status="llm_error",
            parse_error=repr(exc)[:500],
        )

    return _parse_response(
        response.parsed_json,
        prompt_version=prompt_version,
        llm_call_metadata=response.metadata,
    )


# --------------------------------------------------------------------------- #
# Prompt building                                                             #
# --------------------------------------------------------------------------- #


def _build_user_prompt(source_item: SourceItem) -> str:
    """Build the user-visible portion of the prompt.

    Keeps the source content bounded so the combined system+user
    prompt stays under :data:`MAX_PROMPT_BYTES`.
    """
    # Reserve space for the system prompt (already large) + header text.
    system_len = len(_SYSTEM_PROMPT.encode("utf-8"))
    header = f"Source item: {source_item.source_type}/{source_item.source_id}\n"
    header += f"Container: {source_item.container_ref or 'none'}\n"
    header += f"Thread: {source_item.thread_ref or 'none'}\n"
    header += f"Role: {source_item.role or 'none'}\n"
    header += f"Content:\n---\n"

    budget = MAX_PROMPT_BYTES - system_len - len(header.encode("utf-8")) - 32
    if budget <= 0:
        budget = 1024
    content = source_item.content or ""
    if len(content.encode("utf-8")) > budget:
        content = content.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
        content += "\n...[truncated]"
    return header + content + "\n---\n"


# --------------------------------------------------------------------------- #
# Parsing — schema-faithful, drops bad items rather than raising              #
# --------------------------------------------------------------------------- #


def _parse_response(
    parsed_json: Any,
    *,
    prompt_version: str,
    llm_call_metadata: LLMCallMetadata | None,
) -> TypedShadowExtraction:
    if not isinstance(parsed_json, dict):
        return TypedShadowExtraction(
            prompt_version=prompt_version,
            llm_call_metadata=llm_call_metadata,
            parse_status="schema_failure",
            parse_error=f"top-level not an object; got {type(parsed_json).__name__}",
        )

    errors: list[str] = []

    decisions = _parse_array(
        parsed_json.get("decisions"),
        _parse_decision,
        MAX_ITEMS_PER_ARRAY,
        "decisions",
        errors,
    )
    investigations = _parse_array(
        parsed_json.get("investigations"),
        _parse_investigation,
        MAX_ITEMS_PER_ARRAY,
        "investigations",
        errors,
    )
    constraints = _parse_array(
        parsed_json.get("constraints"),
        _parse_constraint,
        MAX_ITEMS_PER_ARRAY,
        "constraints",
        errors,
    )
    operational_facts = _parse_array(
        parsed_json.get("operational_facts"),
        _parse_operational_fact,
        MAX_ITEMS_PER_ARRAY,
        "operational_facts",
        errors,
    )
    supersessions = _parse_array(
        parsed_json.get("supersessions"),
        _parse_supersession,
        MAX_SUPERSESSION_ITEMS,
        "supersessions",
        errors,
    )

    total = (
        len(decisions)
        + len(investigations)
        + len(constraints)
        + len(operational_facts)
        + len(supersessions)
    )
    parse_status: ParseStatus = "ok"
    parse_error: str | None = None
    if errors:
        parse_status = "schema_failure"
        parse_error = "; ".join(errors)[:2000]

    return TypedShadowExtraction(
        decisions=tuple(decisions),
        investigations=tuple(investigations),
        constraints=tuple(constraints),
        operational_facts=tuple(operational_facts),
        supersessions=tuple(supersessions),
        prompt_version=prompt_version,
        llm_call_metadata=llm_call_metadata,
        parse_status=parse_status,
        parse_error=parse_error,
    )


def _parse_array(
    raw: Any,
    parser,
    max_items: int,
    field_name: str,
    errors: list[str],
) -> list[Any]:
    if raw is None:
        errors.append(f"{field_name}: missing")
        return []
    if not isinstance(raw, list):
        errors.append(f"{field_name}: not a list ({type(raw).__name__})")
        return []
    result: list[Any] = []
    for i, item in enumerate(raw[:max_items]):
        parsed = parser(item, errors, f"{field_name}[{i}]")
        if parsed is not None:
            result.append(parsed)
    if len(raw) > max_items:
        errors.append(f"{field_name}: truncated ({len(raw)} → {max_items})")
    return result


def _clean_str(value: Any, max_len: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) > max_len:
        return stripped[:max_len]
    return stripped


def _clean_required_str(
    value: Any,
    max_len: int,
    where: str,
    errors: list[str],
) -> str | None:
    result = _clean_str(value, max_len)
    if result is None:
        errors.append(f"{where}: missing or empty")
        return None
    return result


def _parse_decision(item: Any, errors: list[str], where: str):
    if not isinstance(item, dict):
        errors.append(f"{where}: not an object")
        return None
    subject = _clean_required_str(item.get("subject"), MAX_SUBJECT_LEN, f"{where}.subject", errors)
    statement = _clean_required_str(item.get("statement"), MAX_STATEMENT_LEN, f"{where}.statement", errors)
    evidence = _clean_required_str(item.get("evidence_span"), MAX_EVIDENCE_LEN, f"{where}.evidence_span", errors)
    if not subject or not statement or not evidence:
        return None
    rationale = _clean_str(item.get("rationale"), MAX_RATIONALE_LEN)
    alts_raw = item.get("alternatives_rejected") or []
    alts: list[str] = []
    if isinstance(alts_raw, list):
        for a in alts_raw[:MAX_ITEMS_PER_ARRAY]:
            cleaned = _clean_str(a, MAX_STATEMENT_LEN)
            if cleaned:
                alts.append(cleaned)
    return TypedShadowDecision(
        subject=subject,
        statement=statement,
        evidence_span=evidence,
        rationale=rationale,
        alternatives_rejected=tuple(alts),
    )


def _parse_investigation(item: Any, errors: list[str], where: str):
    if not isinstance(item, dict):
        errors.append(f"{where}: not an object")
        return None
    subject = _clean_required_str(item.get("subject"), MAX_SUBJECT_LEN, f"{where}.subject", errors)
    hypothesis = _clean_required_str(item.get("hypothesis"), MAX_STATEMENT_LEN, f"{where}.hypothesis", errors)
    outcome_raw = item.get("outcome")
    if outcome_raw not in ("confirmed", "ruled_out", "inconclusive"):
        errors.append(f"{where}.outcome: invalid enum {outcome_raw!r}")
        return None
    evidence = _clean_required_str(item.get("evidence_span"), MAX_EVIDENCE_LEN, f"{where}.evidence_span", errors)
    if not subject or not hypothesis or not evidence:
        return None
    resolution = _clean_str(item.get("resolution"), MAX_STATEMENT_LEN)
    return TypedShadowInvestigation(
        subject=subject,
        hypothesis=hypothesis,
        outcome=outcome_raw,  # type: ignore[arg-type]
        evidence_span=evidence,
        resolution=resolution,
    )


def _parse_constraint(item: Any, errors: list[str], where: str):
    if not isinstance(item, dict):
        errors.append(f"{where}: not an object")
        return None
    subject = _clean_required_str(item.get("subject"), MAX_SUBJECT_LEN, f"{where}.subject", errors)
    modality_raw = item.get("modality")
    if modality_raw not in ("prohibit", "prefer", "require"):
        errors.append(f"{where}.modality: invalid enum {modality_raw!r}")
        return None
    action_raw = item.get("action")
    if action_raw not in ("use_surface", "use_source", "perform_step"):
        errors.append(f"{where}.action: invalid enum {action_raw!r}")
        return None
    statement = _clean_required_str(item.get("statement"), MAX_STATEMENT_LEN, f"{where}.statement", errors)
    evidence = _clean_required_str(item.get("evidence_span"), MAX_EVIDENCE_LEN, f"{where}.evidence_span", errors)
    if not subject or not statement or not evidence:
        return None
    return TypedShadowConstraint(
        subject=subject,
        modality=modality_raw,  # type: ignore[arg-type]
        action=action_raw,  # type: ignore[arg-type]
        statement=statement,
        evidence_span=evidence,
    )


def _parse_operational_fact(item: Any, errors: list[str], where: str):
    if not isinstance(item, dict):
        errors.append(f"{where}: not an object")
        return None
    family = _clean_required_str(item.get("command_family"), MAX_COMMAND_FAMILY_LEN, f"{where}.command_family", errors)
    subject = _clean_required_str(item.get("subject"), MAX_SUBJECT_LEN, f"{where}.subject", errors)
    artifact = _clean_required_str(item.get("artifact"), MAX_ARTIFACT_LEN, f"{where}.artifact", errors)
    evidence = _clean_required_str(item.get("evidence_span"), MAX_EVIDENCE_LEN, f"{where}.evidence_span", errors)
    if not family or not subject or not artifact or not evidence:
        return None
    outcome_raw = item.get("outcome")
    outcome: Literal["success", "failure"] | None
    if outcome_raw in ("success", "failure"):
        outcome = outcome_raw  # type: ignore[assignment]
    elif outcome_raw is None:
        outcome = None
    else:
        errors.append(f"{where}.outcome: invalid enum {outcome_raw!r}")
        outcome = None
    return TypedShadowOperationalFact(
        command_family=family,
        subject=subject,
        artifact=artifact,
        evidence_span=evidence,
        outcome=outcome,
    )


def _parse_supersession(item: Any, errors: list[str], where: str):
    if not isinstance(item, dict):
        errors.append(f"{where}: not an object")
        return None
    subject = _clean_required_str(item.get("subject"), MAX_SUBJECT_LEN, f"{where}.subject", errors)
    old = _clean_required_str(item.get("supersedes_statement"), MAX_STATEMENT_LEN, f"{where}.supersedes_statement", errors)
    new = _clean_required_str(item.get("new_statement"), MAX_STATEMENT_LEN, f"{where}.new_statement", errors)
    evidence = _clean_required_str(item.get("evidence_span"), MAX_EVIDENCE_LEN, f"{where}.evidence_span", errors)
    if not subject or not old or not new or not evidence:
        return None
    return TypedShadowSupersession(
        subject=subject,
        supersedes_statement=old,
        new_statement=new,
        evidence_span=evidence,
    )


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #

__all__ = [
    "TYPED_SHADOW_PROMPT_VERSION",
    "MAX_PROMPT_BYTES",
    "TypedShadowDecision",
    "TypedShadowInvestigation",
    "TypedShadowConstraint",
    "TypedShadowOperationalFact",
    "TypedShadowSupersession",
    "TypedShadowExtraction",
    "ParseStatus",
    "run_typed_shadow_extraction",
]
