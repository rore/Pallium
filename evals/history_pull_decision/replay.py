"""Deterministic MCP navigation replay; no model or downstream-task scoring."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from time import perf_counter
from typing import Any


def _payload(response: Any) -> dict:
    """Accept FastMCP call_tool's (text blocks, metadata) response."""
    if isinstance(response, tuple):
        response = response[0]
    if isinstance(response, dict):
        return response
    if isinstance(response, str):
        return json.loads(response)
    return json.loads("".join(block.text for block in response if hasattr(block, "text")))


async def run_navigation_replay(
    call_tool: Callable[[str, dict], Awaitable[Any]],
    *,
    queries: Sequence[str],
    search_arguments: dict,
    required_evidence: Sequence[str],
    policy: str,
    max_chars: int = 4000,
) -> dict:
    """Replay at most three queries, expanding every returned anchor.

    Returned characters count decoded expansion content, including repeats,
    rather than JSON syntax or search excerpts. Empty terminal probes count as
    attempts but not delivered evidence pages. Latency is observational only.
    """
    if policy not in {"restart", "ledger"}:
        raise ValueError("policy must be 'restart' or 'ledger'")
    started = perf_counter()
    counts = Counter({
        name: 0 for name in (
            "searches", "search_result_pages", "candidate_occurrences",
            "expansion_attempts", "successfully_delivered_expansion_pages",
            "repeated_delivered_expansion_pages", "returned_characters",
        )
    })
    candidates: set[str] = set()
    delivered: set[tuple[str, str, int]] = set()
    sources: dict[str, dict] = {}
    stale_sources: Counter[str] = Counter()
    scope = {
        key: search_arguments[key]
        for key in ("container_ref", "thread_ref", "actor_ref", "visibility")
        if key in search_arguments
    }

    async def request(name: str, arguments: dict) -> dict | None:
        for attempt in range(3):
            if name == "pallium_expand_source":
                counts["expansion_attempts"] += 1
            try:
                result = _payload(await call_tool(name, dict(arguments)))
            except (OSError, TimeoutError):
                if attempt == 2:
                    return None
                continue
            untyped_delivery_error = set(result) == {"error"}
            if (
                (result.get("retryable") or untyped_delivery_error)
                and ("error" in result or "error_kind" in result)
                and result.get("error_kind") not in {
                    "stale_result_revision", "stale_content_revision",
                }
            ):
                if attempt == 2:
                    return None
                continue
            return result
        return None

    async def expand(source: str, parent: str) -> None:
        if stale_sources[source] > 2:
            return
        if policy == "restart" or source not in sources:
            sources[source] = {"offset": 0, "revision": None, "text": "", "complete": False}
        state = sources[source]
        while True:
            offset, revision = state["offset"], state["revision"]
            arguments = {
                **scope, "source_item_id": source, "parent_lookup_id": parent,
                "before": 0, "after": 0, "max_chars": max_chars,
                "content_offset": offset,
            }
            if revision is not None:
                arguments["content_revision"] = revision
            result = await request("pallium_expand_source", arguments)
            if result is None:
                state["complete"] = False
                return
            changed = (
                revision is not None
                and result.get("content_revision") is not None
                and result["content_revision"] != revision
            )
            if result.get("error_kind") == "stale_content_revision" or changed:
                stale_sources[source] += 1
                state.update(offset=0, revision=None, text="", complete=False)
                if stale_sources[source] > 2:
                    return
                # Offset zero can successfully return a new revision (including
                # empty -> nonempty). Consume that page instead of rereading it.
                if not changed or result.get("content_offset") != 0:
                    continue
            if "error" in result or "error_kind" in result:
                # An unavailable source must not keep contributing old evidence.
                state.update(offset=0, revision=None, text="", complete=False)
                return
            if "content_revision" not in result:
                state.update(offset=0, revision=None, text="", complete=False)
                return
            revision = result["content_revision"]
            page_offset = result.get("content_offset", 0)
            items = result.get("items") or []
            anchor = next((item for item in items if item.get("is_anchor")), None)
            content = (anchor or {}).get("content") or ""
            counts["returned_characters"] += sum(len(item.get("content") or "") for item in items)
            if state["complete"] and not content and revision == state["revision"]:
                return
            key = (source, revision, page_offset)
            counts["successfully_delivered_expansion_pages"] += 1
            counts["repeated_delivered_expansion_pages"] += int(key in delivered)
            delivered.add(key)
            state["revision"] = revision
            state["text"] += content
            if not result.get("has_more"):
                state.update(complete=True, offset=result["content_total_chars"])
                return
            next_offset = result.get("next_offset")
            if not isinstance(next_offset, int) or next_offset <= page_offset:
                return
            state["offset"] = next_offset

    for query in queries[:3]:
        counts["searches"] += 1
        offset, revision, stale_restarts = 0, None, 0
        seen_pages: set[tuple[str, int]] = set()
        while True:
            arguments = {**search_arguments, "query": query, "result_offset": offset}
            arguments.pop("result_revision", None)
            if revision is not None:
                arguments["result_revision"] = revision
            result = await request("pallium_search_history", arguments)
            if result is None:
                break
            if result.get("error_kind") == "stale_result_revision":
                stale_restarts += 1
                if stale_restarts > 2:
                    break
                offset, revision = 0, None
                continue
            if "error" in result or "error_kind" in result:
                break
            counts["search_result_pages"] += 1
            revision = result.get("result_revision")
            page = (revision, result.get("result_offset", offset))
            hits = result.get("results") or []
            counts["candidate_occurrences"] += len(hits)
            candidates.update(hit["source_item_id"] for hit in hits)
            if page not in seen_pages:
                seen_pages.add(page)
                for hit in hits:
                    await expand(hit["source_item_id"], result["lookup_event_id"])
            if not result.get("has_more"):
                break
            next_offset = result.get("next_offset")
            if not isinstance(next_offset, int) or next_offset <= offset:
                break
            offset = next_offset

    recovered = [
        evidence for evidence in required_evidence
        if any(
            state["complete"] and evidence in state["text"]
            for state in sources.values()
        )
    ]
    return {
        "policy": policy,
        "measurement_layer": "navigation/presentation",
        **counts,
        "unique_candidates": len(candidates),
        "exact_repeat_candidates": counts["candidate_occurrences"] - len(candidates),
        "required_evidence_recovered": len(recovered) == len(required_evidence),
        "recovered_required_evidence": recovered,
        "elapsed_latency_seconds": perf_counter() - started,
    }


async def compare_navigation_policies(
    call_tool: Callable[[str, dict], Awaitable[Any]], **arguments: Any,
) -> dict:
    """Run both policies against the supplied identical fixture/query sequence."""
    return {
        policy: await run_navigation_replay(call_tool, policy=policy, **arguments)
        for policy in ("restart", "ledger")
    }
