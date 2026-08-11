"""Shadow-only sub-task selector experiment (REPORT6 validation).

This module runs the two FROZEN REPORT6 selector variants (B and C) over
live ``work_resumption == strongly_eligible`` multi-candidate queries and
records their picks to the ``subtask_selector_shadow`` table. It is a pure
observer:

- It runs OFF the hot path (the LLM calls happen on a background executor;
  the caller returns immediately after a cheap in-memory gate check).
- It only ever READS the already-finalized, frozen ``QueryResult`` and
  WRITES to its own side table. It cannot change ``should_inject``,
  ``injectable_blocks``, or anything the agent sees.
- It is gated behind ``observability.shadow_subtask_selector_enabled``
  (default False) and is fully removable: delete this module, the table,
  and the flag and behaviour reverts exactly.

The selector DECISION POLICY is copied verbatim from the frozen REPORT5/6
subagent prompts; only the I/O framing (single query at runtime, one JSON
object out) differs from the offline batch harness. The prompts are NOT
tuned on live data.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

from core.models import new_id, utc_now

logger = logging.getLogger(__name__)

# Bump this when/if the frozen prompts ever change, so rows are distinguishable.
PROMPT_VERSION = "report6_frozen_v1"

# ── FROZEN selector prompts (decision policy verbatim from REPORT5/6) ──────
#
# Only the I/O framing changed: the offline harness read a JSON array and
# wrote a file of {qid: {...}}; at runtime we present ONE query and its
# options and expect ONE JSON object {"pick": ..., "reason": ...}. The
# selection instructions below are unchanged.

_SELECTOR_B_SYSTEM = """You are a selection component for an AI coding assistant's memory system. Your job: given a user's message and a small set of candidate memories, pick AT MOST ONE memory that directly helps the user's CURRENT sub-task — or return NONE.

- `query` = the message the user just typed to the assistant (usually resuming work).
- `options` = candidate memories retrieved for this query.

Choose the single opt_id whose memory would directly help the user accomplish the SPECIFIC sub-task their query is about. You MUST distinguish:
  - actual current-sub-task continuation (PICK it),
  - same broad project/session but a different sub-task (do NOT pick),
  - broad topical similarity only (do NOT pick).

Return "NONE" whenever no candidate is specifically on-target for the current sub-task. Abstaining is correct and expected — a wrong pick is worse than no pick. Do NOT feel obligated to pick one. Only pick when a candidate clearly addresses the exact thing the query is asking about.

You have NO access to relevance labels or scores — judge purely from the query text and candidate texts.

Return exactly one JSON object: {"pick": "<opt_id>"|"NONE", "reason": "<=15 words"}."""

_SELECTOR_C_SYSTEM = """You are a selection component for an AI coding assistant's memory system. Your job: given a user's message and a small set of candidate memories (each with a little context about where it came from), pick AT MOST ONE memory that directly helps the user's CURRENT sub-task — or return NONE.

- `query` = the message the user just typed to the assistant (usually resuming work).
- `options` = candidate memories retrieved for this query. `source_task` gives the working directory and/or the originating task turn where that memory was created — use it to judge whether the memory is about the SAME sub-task the user is now on.

Choose the single opt_id whose memory would directly help the user accomplish the SPECIFIC sub-task their query is about. You MUST distinguish:
  - actual current-sub-task continuation (PICK it),
  - same broad project/session but a different sub-task (do NOT pick),
  - broad topical similarity only (do NOT pick).

Return "NONE" whenever no candidate is specifically on-target for the current sub-task. Abstaining is correct and expected — a wrong pick is worse than no pick. Do NOT feel obligated to pick one. Only pick when a candidate clearly addresses the exact thing the query is asking about.

You have NO access to relevance labels or scores — judge purely from the query text, candidate texts, and source_task context.

Return exactly one JSON object: {"pick": "<opt_id>"|"NONE", "reason": "<=15 words"}."""

_SCHEMA_DESCRIPTION = '{"pick": "<opt_id>|NONE", "reason": "string"}'

# Text field priority — matches the REPORT5 corpus builder (mem_text).
_TEXT_FIELDS = (
    "decision", "statement", "summary", "investigation_outcome", "rationale",
    "constraint", "text", "interest_text", "outcome", "next_step", "blocker",
)

# Rough public per-1M-token USD prices for cost ESTIMATION only (not billing).
# Keyed by substring of the model name; unknown model -> cost left None.
_PRICE_PER_MTOK: tuple[tuple[str, float, float], ...] = (
    ("haiku", 0.80, 4.00),
    ("sonnet", 3.00, 15.00),
    ("opus", 15.00, 75.00),
)

_MAX_OPTIONS = 5          # selectors see up to 5 cross-session candidates (REPORT5)
_MAX_CAND_SCAN = 6        # scan up to 6 ranked candidates before cross-session filter
_TEXT_TRUNCATE = 600
_TURN_TRUNCATE = 200
_CWD_TRUNCATE = 120


def _extract_text(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in _TEXT_FIELDS:
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:_TEXT_TRUNCATE]
    try:
        return json.dumps(payload)[:400]
    except (TypeError, ValueError):
        return ""


def _dominant_thread(evidence: list[Any] | None) -> tuple[str | None, str | None]:
    """Return (dominant thread_ref, first source_item_id) from an item's evidence."""
    if not evidence:
        return None, None
    counts: dict[str, int] = {}
    first_sid: str | None = None
    for ev in evidence:
        sid = getattr(ev, "source_item_id", None)
        if first_sid is None and sid:
            first_sid = sid
        tref = getattr(ev, "thread_ref", None)
        if tref:
            counts[tref] = counts.get(tref, 0) + 1
    if not counts:
        return None, first_sid
    dominant = max(counts.items(), key=lambda kv: kv[1])[0]
    return dominant, first_sid


def _estimate_tokens(text: str) -> int:
    return max(0, math.ceil(len(text) / 4))


def _estimate_cost_usd(model: str | None, prompt_tokens: int, completion_tokens: int) -> float | None:
    if not model:
        return None
    m = model.lower()
    for needle, in_price, out_price in _PRICE_PER_MTOK:
        if needle in m:
            return round(in_price * prompt_tokens / 1_000_000 + out_price * completion_tokens / 1_000_000, 8)
    return None


class SubtaskSelectorShadowRunner:
    """Observes qualifying queries and records frozen B/C selector picks.

    See module docstring. Construction is cheap; the LLM work is deferred to
    a background executor unless ``synchronous=True`` (used by tests).
    """

    def __init__(
        self,
        *,
        storage: Any,
        provider: Any,
        model: str | None,
        timeout_ms: int = 2000,
        prompt_version: str = PROMPT_VERSION,
        synchronous: bool = False,
        max_workers: int = 2,
    ) -> None:
        self._storage = storage
        self._provider = provider
        self._model = model
        self._timeout_ms = timeout_ms
        self._prompt_version = prompt_version
        self._synchronous = synchronous
        self._executor: ThreadPoolExecutor | None = (
            None if synchronous else ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="subtask-shadow")
        )
        self._pending: list[Any] = []
        self._lock = threading.Lock()

    # ── hot-path entry point ───────────────────────────────────────────────
    def observe(
        self,
        *,
        result: Any,
        query_text: str,
        container_ref: str | None,
        thread_ref: str | None,
        actor_ref: str | None,
        visibility: str | None,
        trigger_origin: str | None,
    ) -> bool:
        """Gate + dispatch. Returns True if a shadow job was dispatched.

        Cheap and in-memory: reads the finalized trace and candidate items.
        Never mutates ``result``. Never raises (caller also guards).
        """
        try:
            gate = self._build_gate(result=result, thread_ref=thread_ref)
        except Exception:
            logger.warning("subtask-shadow gate failed", exc_info=True)
            return False
        if gate is None:
            return False
        wr_state, options, total_candidates, cross_count = gate

        job = {
            "query_text": query_text,
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "actor_ref": actor_ref,
            "visibility": visibility,
            "trigger_origin": trigger_origin,
            "work_resumption_state": wr_state,
            "options": options,
            "candidate_count": total_candidates,
            "cross_session_candidate_count": cross_count,
        }
        if self._synchronous or self._executor is None:
            self._run_job(job)
            return True
        future = self._executor.submit(self._safe_run_job, job)
        with self._lock:
            self._pending = [f for f in self._pending if not f.done()]
            self._pending.append(future)
        return True

    def drain(self, timeout: float | None = None) -> None:
        """Block until pending shadow jobs complete (tests / shutdown)."""
        with self._lock:
            pending = list(self._pending)
        for future in pending:
            try:
                future.result(timeout=timeout)
            except Exception:
                pass

    # ── gate: build the cross-session candidate option set (in-memory) ──────
    def _build_gate(self, *, result: Any, thread_ref: str | None):
        trace = getattr(result, "trace", None)
        routing = getattr(trace, "routing", None) if trace is not None else None
        if not isinstance(routing, dict):
            return None
        if not _work_resumption_strongly_eligible(routing):
            return None

        # Ordered, deduped memory candidates from the three routing keys
        # (this is exactly the candidate set REPORT5/6 evaluated).
        entries: dict[str, dict[str, Any]] = {}
        for key in ("selected_results", "excluded_high_scoring_candidates", "demoted_higher_level_hits"):
            for entry in routing.get(key) or []:
                if entry.get("result_origin") != "memory":
                    continue
                rid = entry.get("result_id")
                if not rid:
                    continue
                rank = entry.get("routing_rank")
                prev = entries.get(rid)
                if prev is None or (rank is not None and (prev.get("routing_rank") is None or rank < prev["routing_rank"])):
                    entries[rid] = entry
        ordered = sorted(
            entries.values(),
            key=lambda e: (e.get("routing_rank") if e.get("routing_rank") is not None else 1_000_000),
        )[:_MAX_CAND_SCAN]
        if not ordered:
            return None

        item_map = self._build_item_map(result)
        wr_state = _work_resumption_state(routing)
        candidates: list[dict[str, Any]] = []
        for entry in ordered:
            rid = entry.get("result_id")
            item = item_map.get(str(rid))
            mid, text, dom_thread, first_sid = self._hydrate(rid, item)
            if not mid:
                continue
            cross_session = bool(dom_thread and dom_thread != thread_ref)
            candidates.append({
                "opt_id": mid,
                "type": entry.get("memory_type") or (getattr(item, "type", None)),
                "support_grade": entry.get("support_grade"),
                "routing_rank": entry.get("routing_rank"),
                "routing_score": entry.get("routing_score"),
                "retrieval_score": entry.get("retrieval_score"),
                "text": text,
                "thread_ref": dom_thread,
                "cross_session": cross_session,
                "source_item_id": first_sid,
            })

        cross = [c for c in candidates if c["cross_session"]]
        if len(cross) < 2:
            return None
        return wr_state, cross[:_MAX_OPTIONS], len(candidates), len(cross)

    def _build_item_map(self, result: Any) -> dict[str, Any]:
        ranked = getattr(result, "_ranked_candidates", None)
        item_map: dict[str, Any] = {}
        if not ranked:
            return item_map
        for cand in ranked:
            item = cand.get("item") if isinstance(cand, dict) else None
            rid = getattr(item, "result_id", None)
            if item is not None and rid is not None:
                item_map[str(rid)] = item
        return item_map

    def _hydrate(self, rid: Any, item: Any):
        """Return (mid, text, dominant_thread, first_source_item_id)."""
        if item is not None:
            mid = getattr(item, "memory_object_id", None) or _strip_prefix(str(rid))
            text = _extract_text(getattr(item, "payload", None))
            dom_thread, first_sid = _dominant_thread(getattr(item, "evidence", None))
            if dom_thread is None:
                dom_thread, first_sid = self._thread_from_storage(mid, first_sid)
            return mid, text, dom_thread, first_sid
        # Fallback: item not in ranked map — read from storage.
        mid = _strip_prefix(str(rid))
        text = ""
        try:
            mem = self._storage.get_memory_object(mid)
            text = _extract_text(getattr(mem, "payload", None))
        except Exception:
            pass
        dom_thread, first_sid = self._thread_from_storage(mid, None)
        return mid, text, dom_thread, first_sid

    def _thread_from_storage(self, mid: str, first_sid: str | None):
        try:
            evidence = self._storage.get_evidence_for_memory_object(mid)
        except Exception:
            return None, first_sid
        return _dominant_thread(evidence)

    # ── background job: source_task + two selector calls + write ────────────
    def _safe_run_job(self, job: dict[str, Any]) -> None:
        try:
            self._run_job(job)
        except Exception:
            logger.warning("subtask-shadow job failed", exc_info=True)

    def _run_job(self, job: dict[str, Any]) -> None:
        options = job["options"]
        # Fill per-candidate source_task (working dir + originating task turn).
        for opt in options:
            opt["source_task"] = self._source_task(opt.get("source_item_id"))

        b = self._call_selector(_SELECTOR_B_SYSTEM, _build_user_prompt(job["query_text"], options, with_ctx=False))
        c = self._call_selector(_SELECTOR_C_SYSTEM, _build_user_prompt(job["query_text"], options, with_ctx=True))

        valid_ids = {o["opt_id"] for o in options}
        b = _finalize_pick(b, valid_ids)
        c = _finalize_pick(c, valid_ids)

        total_cost = _sum_optional(b.get("est_cost_usd"), c.get("est_cost_usd"))
        total_latency = (b.get("latency_ms") or 0.0) + (c.get("latency_ms") or 0.0)

        row = {
            "id": new_id(),
            "created_at": utc_now(),
            "prompt_version": self._prompt_version,
            "provider_name": b.get("provider_name") or c.get("provider_name"),
            "model": self._model,
            "trigger_origin": job["trigger_origin"],
            "query_text": job["query_text"],
            "container_ref": job["container_ref"],
            "thread_ref": job["thread_ref"],
            "actor_ref": job["actor_ref"],
            "visibility": job["visibility"],
            "work_resumption_state": job["work_resumption_state"],
            "candidate_count": job["candidate_count"],
            "cross_session_candidate_count": job["cross_session_candidate_count"],
            "candidate_set_json": json.dumps(options, default=str),
            "selector_b_pick": b.get("pick_or_none"),
            "selector_c_pick": c.get("pick_or_none"),
            "selectors_json": json.dumps({"B": b, "C": c}, default=str),
            "total_est_cost_usd": total_cost,
            "total_latency_ms": total_latency,
        }
        self._storage.write_subtask_selector_shadow_row(row)

    def _source_task(self, source_item_id: str | None) -> str:
        if not source_item_id:
            return "(none)"
        try:
            src = self._storage.get_source_item(source_item_id)
        except Exception:
            return "(none)"
        metadata = getattr(src, "metadata", None) or {}
        parts: list[str] = []
        cwd = metadata.get("cwd") if isinstance(metadata, dict) else None
        if cwd:
            parts.append("working dir: " + str(cwd)[:_CWD_TRUNCATE])
        turn = metadata.get("agent_work_trace_turn") if isinstance(metadata, dict) else None
        if isinstance(turn, str) and turn.strip():
            parts.append("origin task: " + turn.strip()[:_TURN_TRUNCATE])
        return " | ".join(parts) if parts else "(none)"

    def _call_selector(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        from providers.llm.base import LLMProvider

        prompt_chars = len(system_prompt) + len(user_prompt)
        result: dict[str, Any] = {
            "pick": None, "reason": None, "parse_status": "llm_error", "error": None,
            "latency_ms": 0.0, "model": self._model, "provider_name": None,
            "est_prompt_tokens": _estimate_tokens(system_prompt + user_prompt),
            "est_completion_tokens": 0, "est_cost_usd": None,
        }
        if self._provider is None or not isinstance(self._provider, LLMProvider):
            result["error"] = "no_provider"
            return result

        start = time.monotonic()
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(
                self._provider.generate_json,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_description=_SCHEMA_DESCRIPTION,
            )
            response = future.result(timeout=self._timeout_ms / 1000.0)
            result["latency_ms"] = (time.monotonic() - start) * 1000
            parsed = getattr(response, "parsed_json", None) or {}
            metadata = getattr(response, "metadata", None)
            if metadata is not None:
                result["provider_name"] = getattr(metadata, "provider_name", None)
                if getattr(metadata, "model", None):
                    result["model"] = metadata.model
            raw_text = getattr(response, "raw_text", "") or ""
            result["est_completion_tokens"] = _estimate_tokens(raw_text)
            result["est_cost_usd"] = _estimate_cost_usd(
                result["model"], result["est_prompt_tokens"], result["est_completion_tokens"],
            )
            pick = parsed.get("pick")
            result["pick"] = str(pick) if pick is not None else None
            reason = parsed.get("reason")
            result["reason"] = str(reason)[:300] if reason is not None else None
            result["parse_status"] = "ok" if result["pick"] is not None else "schema_failure"
        except FuturesTimeoutError:
            result["latency_ms"] = (time.monotonic() - start) * 1000
            result["parse_status"] = "timeout"
            result["error"] = "timeout"
        except Exception as exc:  # provider / parse failure — shadow must not raise
            result["latency_ms"] = (time.monotonic() - start) * 1000
            result["parse_status"] = "llm_error"
            result["error"] = type(exc).__name__
        finally:
            pool.shutdown(wait=False)
        return result


def _work_resumption_state(routing: dict[str, Any]) -> str | None:
    lane_narrowing = routing.get("lane_narrowing")
    if not isinstance(lane_narrowing, dict):
        return None
    for detail in lane_narrowing.get("lane_details") or []:
        if isinstance(detail, dict) and detail.get("lane") == "work_resumption":
            return detail.get("state")
    return None


def _work_resumption_strongly_eligible(routing: dict[str, Any]) -> bool:
    return _work_resumption_state(routing) == "strongly_eligible"


def _strip_prefix(rid: str) -> str:
    return rid.replace("memory_object:", "").replace("source_item:", "")


def _build_user_prompt(query_text: str, options: list[dict[str, Any]], *, with_ctx: bool) -> str:
    lines = [f"query: {query_text}", "", "options:"]
    for opt in options:
        lines.append(f"- opt_id: {opt['opt_id']}")
        lines.append(f"  text: {opt.get('text', '')}")
        if with_ctx:
            lines.append(f"  source_task: {opt.get('source_task', '(none)')}")
    lines.append("")
    lines.append('Return one JSON object: {"pick": "<opt_id>"|"NONE", "reason": "<=15 words"}.')
    return "\n".join(lines)


def _finalize_pick(sel: dict[str, Any], valid_ids: set[str]) -> dict[str, Any]:
    """Normalize pick to a valid opt_id, "NONE", or None (error)."""
    pick = sel.get("pick")
    if sel.get("parse_status") in {"llm_error", "timeout"}:
        sel["pick_or_none"] = None
        return sel
    if pick is None:
        sel["pick_or_none"] = None
        sel["parse_status"] = "schema_failure"
        return sel
    if pick == "NONE":
        sel["pick_or_none"] = "NONE"
        return sel
    if pick in valid_ids:
        sel["pick_or_none"] = pick
        return sel
    # A pick that isn't one of the offered options is treated as an abstention
    # but flagged so it is distinguishable in analysis.
    sel["pick_or_none"] = "NONE"
    sel["parse_status"] = "invalid_pick"
    return sel


def _sum_optional(a: float | None, b: float | None) -> float | None:
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)
