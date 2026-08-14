"""Decision-making agent for the history-pull harness.

The agent is given two tools — ``pallium_search_history`` (a source-only search
over prior agent work) and ``pallium_expand_source`` (neighbor-context expansion
around a retrieved turn) — and DECIDES ON ITS OWN, per scenario, whether to use
them. The pulls are agent-chosen, never scripted by the harness, which is what
makes the resulting lookup / unprompted-pull numbers non-circular.

Tools are modelled as a JSON decision protocol over ``LLMProvider.generate_json``
(provider-agnostic, mirroring ``app/agent_simulation_model.ThinAgentModel`` and
``evals/historical_lookup_judge.py``) rather than native tool-use, so any
configured provider works and a deterministic stub can stand in for CI.

Deliberately neutral, tool-description-only guidance (design 015 Experiment 1
notes this vs. stronger skill guidance as a lever). We do NOT tell the agent
whether relevant history exists — that is the behaviour under measurement.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from providers.llm.base import LLMJsonResponse, LLMProvider

# ---------------------------------------------------------------------------
# Prompts + schemas
# ---------------------------------------------------------------------------

SEARCH_SYSTEM_PROMPT = """\
You are a software engineering assistant working on a task. You have access to a
tool that searches YOUR OWN prior work and conversations:

  pallium_search_history(query): returns excerpts of relevant past turns from
  earlier work in this project. Use it when you believe prior decisions,
  conventions, or context from past work would help you do the current task
  correctly and consistently.

Not every task needs it. A fully self-contained task (one that depends on no
prior project decisions or conventions) does not require a history search.

Decide, for the task below, whether to call pallium_search_history. If yes,
provide the search query you would run. Return exactly the JSON schema.
"""

SEARCH_SCHEMA = '{"search":"boolean","query":"string","reason":"string"}'

AFTER_SYSTEM_PROMPT = """\
You searched your prior work and got back the excerpts below. You also have a
second tool:

  pallium_expand_source(result_index): expands one retrieved excerpt into its
  surrounding conversation turns, when the excerpt alone is not enough context.

Decide whether to expand one of the results for more context (give its index,
starting at 0), then write your final answer to the task, using whatever
retrieved history is genuinely relevant. If none of the results are relevant,
set expand to false and answer from your own general knowledge. Return exactly
the JSON schema.
"""

AFTER_SCHEMA = '{"expand":"boolean","expand_index":"integer","answer":"string"}'


# ---------------------------------------------------------------------------
# Decision types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchDecision:
    search: bool
    query: str
    reason: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class AfterDecision:
    expand: bool
    expand_index: int | None
    answer: str
    raw: dict[str, Any]


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1"}


def _coerce_index(value: Any) -> int | None:
    try:
        idx = int(value)
    except (TypeError, ValueError):
        return None
    return idx if idx >= 0 else None


def _seed_tag(scenario_id: str, seed: int, step: str) -> str:
    """Inert trailing tag. Carries no decision signal but makes the prompt (and
    therefore any disk cache key) unique per (scenario, seed, step) so a cached
    provider yields independent draws per seed instead of collapsing onto one."""
    return f"\n\n[trial: {scenario_id} seed={seed} step={step}]"


def _render_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return "(the search returned no results)"
    lines = []
    for i, r in enumerate(results):
        excerpt = (r.get("excerpt") or "").replace("\n", " ").strip()[:400]
        lines.append(f"[{i}] {excerpt}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class DecisionAgent:
    """Wraps an ``LLMProvider`` and turns tasks into pull decisions."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def decide_search(self, *, scenario_id: str, task: str, seed: int) -> SearchDecision:
        user_prompt = f"Task:\n{task}{_seed_tag(scenario_id, seed, 'search')}"
        response = self._provider.generate_json(
            system_prompt=SEARCH_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema_description=SEARCH_SCHEMA,
        )
        parsed = response.parsed_json if isinstance(response.parsed_json, dict) else {}
        query = str(parsed.get("query") or "").strip()
        search = _coerce_bool(parsed.get("search")) and bool(query)
        return SearchDecision(
            search=search,
            query=query,
            reason=str(parsed.get("reason") or "").strip(),
            raw=parsed,
        )

    def decide_after_results(
        self,
        *,
        scenario_id: str,
        task: str,
        results: list[dict[str, Any]],
        seed: int,
    ) -> AfterDecision:
        user_prompt = (
            f"Task:\n{task}\n\nRetrieved history:\n{_render_results(results)}"
            f"{_seed_tag(scenario_id, seed, 'after')}"
        )
        response = self._provider.generate_json(
            system_prompt=AFTER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema_description=AFTER_SCHEMA,
        )
        parsed = response.parsed_json if isinstance(response.parsed_json, dict) else {}
        expand = _coerce_bool(parsed.get("expand"))
        idx = _coerce_index(parsed.get("expand_index")) if expand else None
        # Guard the index against the actual result set.
        if idx is not None and idx >= len(results):
            idx = 0 if results else None
            expand = idx is not None
        return AfterDecision(
            expand=expand,
            expand_index=idx,
            answer=str(parsed.get("answer") or "").strip(),
            raw=parsed,
        )


# ---------------------------------------------------------------------------
# Deterministic stub provider (no network) — for CI / --dry-run
# ---------------------------------------------------------------------------


class ScriptedDecisionProvider(LLMProvider):
    """A no-network ``LLMProvider`` for the deterministic self-test / dry-run.

    Delegates to a handler that maps a ``(system_prompt, user_prompt)`` pair onto
    a decision dict. The default handler drives a full search+expand chain for
    every task so the funnel-persistence path is exercised end to end without an
    LLM.
    """

    def __init__(self, handler: Callable[[str, str], dict[str, Any]] | None = None) -> None:
        self._handler = handler or _default_scripted_handler

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, schema_description: str
    ) -> LLMJsonResponse:
        import json

        payload = self._handler(system_prompt, user_prompt)
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def _default_scripted_handler(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Always search (query = a fixed lexical stub), then expand result 0.

    Keyed only off the step tag embedded in the user prompt, so it is stable and
    order-independent. The query is intentionally generic; the self-test seeds
    turns that lexically match it.
    """
    if "step=search" in user_prompt:
        return {
            "search": True,
            "query": "prior decision convention policy",
            "reason": "scripted: always search",
        }
    # after-results step
    return {
        "expand": True,
        "expand_index": 0,
        "answer": "Scripted answer incorporating the retrieved prior decision.",
    }
