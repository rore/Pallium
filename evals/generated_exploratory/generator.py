"""LLM-backed scenario generator for taxonomy-driven exploratory QA.

Generates multi-step conversation scenarios from taxonomy dimension pairs,
producing JSON in the same format consumed by the invariant runner.

Usage:
    # Generate for specific cells
    python -m evals.generated_exploratory.generator \
        --cells thread_relation=cross_thread,visibility=private \
        --count 2 \
        --output evals/generated_exploratory/scenarios/batch.json

    # Generate for all high-risk dimension pairs
    python -m evals.generated_exploratory.generator \
        --high-risk-only --count 1 \
        --output evals/generated_exploratory/scenarios/batch.json

Requires a working LLM provider in pallium.local.toml / .env.local.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.dependencies import build_llm_provider
from evals.generated_exploratory.invariant_derivation import (
    build_generation_metadata,
    derive_invariants,
)
from evals.generated_exploratory.taxonomy import (
    DIMENSIONS,
    high_risk_cells,
    pairwise_cells,
)

logger = logging.getLogger(__name__)

# Default model for scenario generation (quality-critical structured output).
_DEFAULT_MODEL = "claude-sonnet-4-20250514"

# Higher token limit for generation — scenarios with multiple steps and events
# easily exceed the default 1024. The provider's configured max_tokens is
# overridden at call time via the provider's generate_json interface.
_GENERATION_MAX_TOKENS = 4096

# Number of retries on LLM parse failure before giving up on a cell.
_MAX_RETRIES = 1


def _build_provider(
    config: AppConfig,
    *,
    provider_name: str,
    model: str,
    max_tokens: int = _GENERATION_MAX_TOKENS,
) -> Any:
    """Build an LLM provider with an overridden max_tokens for generation.

    Generation needs more tokens than the default extraction config (1024)
    because multi-step scenarios with events are larger.
    """
    provider_config = config.provider_config(provider_name)
    provider_kind = provider_config.kind.lower()

    if provider_kind in {"anthropic_claude", "claude", "anthropic"}:
        from providers.llm.anthropic_claude import AnthropicClaudeLLMProvider

        return AnthropicClaudeLLMProvider(
            provider_name=provider_name,
            model=model,
            base_url=provider_config.base_url,
            api_key=provider_config.api_key,
            timeout_seconds=provider_config.timeout_seconds,
            retry_policy=provider_config.retry_policy,
            auth_style=provider_config.auth_style,
            max_tokens=max_tokens,
        )
    if provider_kind == "openai_compatible":
        from providers.llm.openai_compatible import OpenAICompatibleLLMProvider

        return OpenAICompatibleLLMProvider(
            provider_name=provider_name,
            model=model,
            base_url=provider_config.base_url,
            api_key=provider_config.api_key,
            timeout_seconds=provider_config.timeout_seconds,
            retry_policy=provider_config.retry_policy,
        )
    # Fallback to standard builder (no max_tokens override).
    return build_llm_provider(config, provider_name=provider_name, model=model)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You generate test scenarios for Pallium, a memory system for AI agents.

Each scenario is a multi-step conversation script in JSON format. A scenario has:
- ingest steps: events (chat messages) that create memory
- query steps: questions that test whether memory was stored and retrieved correctly

Rules for the content domain:
- Use ONLY a public library system domain: reservations, catalog sync, book holds, overdue notices, branch operations, interlibrary loans, patron accounts
- container_ref format: "chat:library-<branch>" or "chat:catalog-<topic>"
- thread_ref format: "chat:<container>:thread-<id>"
- actor_ref format: "user:branch-librarian", "user:catalog-admin", "user:patron-services", or "agent:assistant"
- source_id format: "gen-<scenario_id>-msg-<N>"
- source_ref format: "memory://gen/<source_id>"
- All timestamps in ISO 8601 UTC, spaced 1-5 minutes apart starting from 2026-03-20T08:00:00Z
- Content must be realistic: specific technical details, concrete decisions, investigation findings
- Do NOT use generic placeholder content like "some topic" or "something interesting"

You must return valid JSON — a single object with a "scenarios" key containing an array of scenario objects."""

_USER_PROMPT_TEMPLATE = """\
Generate {count} test scenario(s) targeting this taxonomy cell:
{cell_description}

Each scenario must exercise the specific dimension values above through its conversation structure.

{dimension_guidance}

Here is the exact JSON format to follow (one example scenario):

{format_example}

Return a JSON object like {{"scenarios": [...]}} containing {count} scenario(s). Each scenario must have:
- "scenario_id": "gen-<short-descriptive-id>"
- "description": one sentence explaining what the scenario tests
- "steps": array of ingest and query steps as shown in the example

Important structural rules:
- Every ingest event needs: source_type, source_id, content_type ("text/plain"), content, artifact_kind ("message" or "assistant_output"), role ("user" or "assistant"), container_ref, thread_ref, actor_ref, source_ref, occurred_at, visibility
- Every query step needs: text, limit (6), container_ref, visibility
- Each scenario must have at least one ingest step and one query step
- The query step must test whether the ingested memory is correctly handled given the taxonomy cell dimensions"""

# Per-dimension guidance for the LLM.
_DIMENSION_GUIDANCE: dict[str, dict[str, str]] = {
    "thread_relation": {
        "same_thread": "All events and the query use the same thread_ref.",
        "cross_thread": "Ingest in thread-1, query from thread-2 (same container).",
        "cross_session": "Ingest and query use different thread_refs suggesting separate sessions.",
    },
    "container_relation": {
        "same_container": "All events and the query use the same container_ref.",
        "different_container": "Ingest in container-A, query from container-B.",
    },
    "visibility": {
        "private": 'All visibility values are "private".',
        "container": 'All visibility values are "container".',
        "public": 'All visibility values are "public".',
    },
    "actor_count": {
        "single_user": "Only one user actor (plus optionally agent:assistant).",
        "multi_user": "Two different user actors (e.g., user:branch-librarian and user:catalog-admin). Include actor_ref on the query step.",
    },
    "topic_pattern": {
        "single": "All messages are about the same topic.",
        "switch": "Messages start on topic A, then switch to topic B. Query is about topic A.",
        "mixed": "A single message mentions multiple topics.",
        "return_to_prior": "Messages discuss topic A, then B, then return to A. Query is about A.",
    },
    "query_intent": {
        "forward": "Query is forward-looking: 'what should we do next?'",
        "backward_recall": "Query is backward-looking: 'didn't we discuss...?', 'what did we decide?'",
        "summary": "Query asks for a summary: 'what's new?', 'what have we covered?'",
        "ambiguous": "Query is ambiguous: could be interpreted as recall or new question.",
    },
    "source_role": {
        "user": "Only user messages in ingest events (role='user', artifact_kind='message').",
        "assistant": "Include at least one assistant message (role='assistant', artifact_kind='assistant_output').",
        "quoted_user": "A user message quotes or references what another user said.",
    },
    "memory_type_target": {
        "decision": "User message states an explicit decision: 'Decision: we will use X for Y'.",
        "investigation_outcome": "Message describes investigation findings: 'Investigation found that X causes Y'.",
        "thread_summary": "Multiple messages in a thread to generate a thread summary.",
        "task_checkpoint": "Messages about ongoing work with blockers and next steps.",
        "interest": "User expresses interest: 'X sounds interesting, I should check it'. Only works in private containers.",
        "constraint_memory": "User states a constraint: 'Do not use X, only use Y'. Only works in private containers with role=user.",
        "discussion_summary": "General discussion that doesn't match other types.",
        "pattern_memory": "Multiple related discussions across threads to generate pattern memory.",
        "continuity_memory": "Repeated topic across interactions for continuity carry-forward.",
    },
    "injection_outcome": {
        "inject": "Query is on-topic — memory should be injected.",
        "suppress": "Query is off-topic or noise — memory should NOT be injected.",
        "partial_inject": "Some memories are relevant, others are not.",
    },
    "retrieval_path": {
        "lexical": "Query uses exact terms from the ingested content.",
        "vector": "Query is semantically related but uses different vocabulary.",
        "hybrid": "Query has some exact terms and some semantic overlap.",
    },
    "scoring_quality": {
        "idf_discriminating": "Query targets rare domain-specific terms that should rank higher.",
        "common_word_overlap": "Ingest content shares common words with unrelated memories.",
        "mixed": "Both rare and common terms are present.",
    },
}

# Minimal format example (one scenario).
_FORMAT_EXAMPLE = json.dumps([
    {
        "scenario_id": "gen-example-cross-thread-recall",
        "description": "Decision in thread 1 should be recallable from thread 2.",
        "steps": [
            {
                "step_id": "setup",
                "action": "ingest",
                "events": [
                    {
                        "source_type": "chat_message",
                        "source_id": "gen-example-msg-1",
                        "content_type": "text/plain",
                        "content": "Decision: use item event time for reservation ordering to avoid skipped holds during catalog sync delays.",
                        "artifact_kind": "message",
                        "role": "user",
                        "container_ref": "chat:library-downtown",
                        "thread_ref": "chat:library-downtown:thread-001",
                        "actor_ref": "user:branch-librarian",
                        "source_ref": "memory://gen/gen-example-msg-1",
                        "occurred_at": "2026-03-20T08:00:00Z",
                        "visibility": "public",
                    }
                ],
            },
            {
                "step_id": "recall_query",
                "action": "query",
                "query": {
                    "text": "What did we decide about reservation ordering?",
                    "limit": 6,
                    "container_ref": "chat:library-downtown",
                    "thread_ref": "chat:library-downtown:thread-002",
                    "visibility": "public",
                },
            },
        ],
    }
], indent=2)


# ---------------------------------------------------------------------------
# Generator core
# ---------------------------------------------------------------------------

def _build_cell_description(cell: dict[str, str]) -> str:
    """Human-readable description of a taxonomy cell."""
    return "\n".join(f"- {dim}: {level}" for dim, level in sorted(cell.items()))


def _build_dimension_guidance(cell: dict[str, str]) -> str:
    """Build dimension-specific guidance for the prompt."""
    lines = []
    for dim, level in sorted(cell.items()):
        guidance = (_DIMENSION_GUIDANCE.get(dim) or {}).get(level)
        if guidance:
            lines.append(f"- {dim}={level}: {guidance}")
    return "Dimension-specific guidance:\n" + "\n".join(lines) if lines else ""


def _stamp_metadata(
    scenarios: list[dict[str, Any]],
    cell: dict[str, str],
    batch_id: str,
) -> list[dict[str, Any]]:
    """Stamp each scenario with _generation_metadata and invariant assertions."""
    invariant_ids = derive_invariants(cell)
    metadata = build_generation_metadata(cell, invariant_ids)
    metadata["batch_id"] = batch_id

    for scenario in scenarios:
        scenario["_generation_metadata"] = dict(metadata)
        # Stamp invariant assertions on each query step.
        for step in scenario.get("steps", []):
            if step.get("action") == "query":
                step.setdefault("invariant_assertions", list(invariant_ids))
    return scenarios


def generate_scenarios_for_cell(
    *,
    provider: Any,
    cell: dict[str, str],
    count: int = 1,
    batch_id: str | None = None,
    max_retries: int = _MAX_RETRIES,
) -> list[dict[str, Any]]:
    """Generate scenarios for a single taxonomy cell using the LLM.

    Retries up to ``max_retries`` times on LLM parse failures before giving up.
    """
    batch_id = batch_id or uuid.uuid4().hex[:12]

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        count=count,
        cell_description=_build_cell_description(cell),
        dimension_guidance=_build_dimension_guidance(cell),
        format_example=_FORMAT_EXAMPLE,
    )

    last_error: Exception | None = None
    for attempt in range(1 + max_retries):
        try:
            response = provider.generate_json(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                schema_description='{"scenarios": [{"scenario_id": "string", "description": "string", "steps": [...]}]}',
            )
            break
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                logger.warning("  Retry %d/%d after: %s", attempt + 1, max_retries, exc)
            continue
    else:
        raise last_error  # type: ignore[misc]

    # parse_json_object returns a dict. We asked for {"scenarios": [...]}.
    parsed = response.parsed_json
    if "scenarios" in parsed and isinstance(parsed["scenarios"], list):
        scenarios = parsed["scenarios"]
    elif "scenario_id" in parsed:
        # LLM returned a single bare scenario object.
        scenarios = [parsed]
    else:
        logger.warning("Unexpected LLM response shape: keys=%s", list(parsed.keys()))
        scenarios = []

    # Validate basic structure.
    valid = []
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        if "scenario_id" not in s or "steps" not in s:
            logger.warning("Skipping malformed scenario: missing scenario_id or steps")
            continue
        valid.append(s)

    return _stamp_metadata(valid, cell, batch_id)


def generate_batch(
    *,
    provider: Any,
    cells: list[dict[str, str]],
    count_per_cell: int = 1,
    output_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Generate scenarios for multiple taxonomy cells.

    When ``output_path`` is provided, writes each scenario incrementally
    so partial results survive interruption.
    """
    batch_id = uuid.uuid4().hex[:12]
    all_scenarios: list[dict[str, Any]] = []

    # Incremental output: write a JSON array, appending after each cell.
    out_file = None
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out_file = output_path.open("w", encoding="utf-8")
        out_file.write("[\n")

    try:
        for i, cell in enumerate(cells):
            logger.info(
                "Generating %d scenario(s) for cell %d/%d: %s",
                count_per_cell, i + 1, len(cells), cell,
            )
            try:
                scenarios = generate_scenarios_for_cell(
                    provider=provider,
                    cell=cell,
                    count=count_per_cell,
                    batch_id=batch_id,
                )
                all_scenarios.extend(scenarios)
                logger.info("  -> %d scenario(s) generated", len(scenarios))

                # Write incrementally.
                if out_file:
                    for s in scenarios:
                        if len(all_scenarios) > 1:
                            out_file.write(",\n")
                        out_file.write(json.dumps(s, indent=2, default=str))
                    out_file.flush()

            except Exception as exc:
                logger.error("  -> Failed for cell %s: %s", cell, exc)
                continue
    finally:
        if out_file:
            out_file.write("\n]\n")
            out_file.close()

    return all_scenarios


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_cell_spec(spec: str) -> dict[str, str]:
    """Parse 'dim1=level1,dim2=level2' into a dict."""
    cell: dict[str, str] = {}
    for pair in spec.split(","):
        if "=" not in pair:
            raise ValueError(f"Invalid cell spec: {pair!r} (expected dim=level)")
        dim, level = pair.split("=", 1)
        dim, level = dim.strip(), level.strip()
        if dim not in DIMENSIONS:
            raise ValueError(f"Unknown dimension: {dim!r}")
        if level not in DIMENSIONS[dim]:
            raise ValueError(f"Unknown level {level!r} for dimension {dim!r}")
        cell[dim] = level
    return cell


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate exploratory QA scenarios")
    parser.add_argument(
        "--cells", nargs="+",
        help="Taxonomy cells as dim1=level1,dim2=level2 (one per cell)",
    )
    parser.add_argument(
        "--dimensions", nargs=2, metavar=("DIM_A", "DIM_B"),
        help="Generate all pairwise cells for two dimensions",
    )
    parser.add_argument(
        "--high-risk-only", action="store_true",
        help="Generate for high-risk dimension pairs only",
    )
    parser.add_argument(
        "--count", type=int, default=1,
        help="Scenarios per cell (default: 1, min: 1)",
    )
    parser.add_argument(
        "--output", type=str, required=True,
        help="Output JSON file path",
    )
    parser.add_argument(
        "--provider", type=str, default=None,
        help="LLM provider name from pallium.local.toml",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help=f"Model name (default: {_DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=_GENERATION_MAX_TOKENS,
        help=f"Max response tokens for LLM (default: {_GENERATION_MAX_TOKENS})",
    )
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    # Resolve cells.
    if args.count < 1:
        parser.error("--count must be >= 1")

    cells: list[dict[str, str]] = []
    if args.high_risk_only:
        cells = high_risk_cells()
    elif args.dimensions:
        cells = pairwise_cells(args.dimensions[0], args.dimensions[1])
    elif args.cells:
        cells = [_parse_cell_spec(spec) for spec in args.cells]
    else:
        parser.error("Provide --cells, --dimensions, or --high-risk-only")

    logger.info("Generating scenarios for %d cells, %d per cell", len(cells), args.count)

    # Build LLM provider from config.
    config = AppConfig.from_env()
    provider_name = args.provider
    if not provider_name:
        # Use the first configured provider.
        provider_names = list(config.llm_providers.keys()) if hasattr(config, "llm_providers") else []
        if not provider_names:
            pkg_config = config.package_config(config.default_use_case)
            provider_name = pkg_config.provider
        else:
            provider_name = provider_names[0]

    model = args.model or _DEFAULT_MODEL
    provider = _build_provider(config, provider_name=provider_name, model=model, max_tokens=args.max_tokens)
    logger.info("Using provider=%s model=%s max_tokens=%d", provider_name, model, args.max_tokens)

    # Generate with incremental output.
    output_path = Path(args.output)
    scenarios = generate_batch(
        provider=provider,
        cells=cells,
        count_per_cell=args.count,
        output_path=output_path,
    )

    logger.info("Wrote %d scenarios to %s", len(scenarios), output_path)


if __name__ == "__main__":
    main()
