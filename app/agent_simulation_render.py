from __future__ import annotations

from typing import Any


MAX_PREVIEW = 120


def render_scope(defaults: dict[str, Any]) -> list[str]:
    visibility = defaults.get("visibility_context") or {}
    runtime = defaults.get("runtime_context") or {}
    return [
        f"container_ref: {defaults.get('container_ref') or '-'}",
        f"thread_ref: {defaults.get('thread_ref') or '-'}",
        f"session_ref: {defaults.get('session_ref') or '-'}",
        f"visibility_context: {visibility.get('kind', '-')} / {visibility.get('id')}",
        f"turn_kind: {runtime.get('turn_kind') or '-'}",
        f"session_has_sufficient_local_context: {runtime.get('session_has_sufficient_local_context')}",
    ]


def render_debug_summary(payload: dict[str, Any], *, verbose: bool) -> list[str]:
    lines = [
        f"should_inject: {payload.get('should_inject')}",
        f"decision_reason: {payload.get('decision_reason')}",
    ]
    injectable_blocks = payload.get("injectable_blocks") or []
    lines.append(f"injectable_blocks: {len(injectable_blocks)}")
    for index, block in enumerate(injectable_blocks[:3], start=1):
        lines.append(
            f"  [{index}] {block.get('block_type')} / {block.get('memory_type') or block.get('title')}: {preview_text(block.get('text'))}"
        )

    trace = payload.get("trace") or {}
    routing = trace.get("routing") or {}
    selected_layer = routing.get("selected_layer")
    query_family = routing.get("query_intent") or routing.get("query_family")
    if selected_layer or query_family:
        lines.append(f"routing: layer={selected_layer or '-'} family={query_family or '-'}")

    result_lines = _render_top_results(payload.get("results") or [])
    if result_lines:
        lines.extend(result_lines)

    exclusion_lines = _render_exclusions(trace)
    if exclusion_lines:
        lines.extend(exclusion_lines)

    visibility = trace.get("visibility") or {}
    fail_closed_reason = visibility.get("fail_closed_reason")
    if fail_closed_reason:
        lines.append(f"visibility_fail_closed: {fail_closed_reason}")

    if verbose:
        lines.extend(_render_trace_details(trace))
    return lines


def render_replay_diff(recorded: dict[str, Any], current: dict[str, Any]) -> list[str]:
    lines = [
        f"recorded should_inject={recorded.get('should_inject')} current={current.get('should_inject')}",
        f"recorded decision_reason={recorded.get('decision_reason')} current={current.get('decision_reason')}",
    ]
    recorded_blocks = [block.get("text") for block in (recorded.get("injectable_blocks") or [])]
    current_blocks = [block.get("text") for block in (current.get("injectable_blocks") or [])]
    lines.append(f"recorded blocks={len(recorded_blocks)} current blocks={len(current_blocks)}")
    if recorded_blocks != current_blocks:
        lines.append("injectable_blocks changed")

    recorded_signatures = _result_signatures(recorded.get("results") or [])
    current_signatures = _result_signatures(current.get("results") or [])
    if recorded_signatures != current_signatures:
        lines.append(f"top_results changed: recorded={recorded_signatures[:3]} current={current_signatures[:3]}")

    recorded_trace = recorded.get("trace") or {}
    current_trace = current.get("trace") or {}
    lines.append(
        "routing: "
        f"recorded={_routing_summary(recorded_trace)} current={_routing_summary(current_trace)}"
    )
    return lines


def preview_text(text: str | None, *, limit: int = MAX_PREVIEW) -> str:
    if not text:
        return ""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: limit - 3]}..."


def _render_top_results(results: list[dict[str, Any]]) -> list[str]:
    if not results:
        return []
    lines = ["top_results:"]
    for index, result in enumerate(results[:5], start=1):
        lines.append(
            f"  [{index}] {result.get('result_kind')} / {result.get('type') or result.get('artifact_kind') or '-'}"
            f" score={result.get('score')} id={result.get('result_id') or result.get('source_item_id') or '-'}"
            f" text={preview_text(result.get('excerpt') or _payload_summary(result.get('payload')))}"
        )
    return lines


def _render_exclusions(trace: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    routing = trace.get("routing") or {}
    excluded_candidates = routing.get("excluded_high_scoring_candidates") or []
    if excluded_candidates:
        reasons = sorted({item.get("excluded_reason_code") for item in excluded_candidates if item.get("excluded_reason_code")})
        if reasons:
            lines.append(f"suppression_reasons: {', '.join(reasons)}")
    visibility = trace.get("visibility") or {}
    excluded = visibility.get("excluded_candidates") or []
    if excluded:
        reasons = [f"{item.get('reason')} ({item.get('count')})" for item in excluded if item.get("reason")]
        if reasons:
            lines.append(f"visibility_exclusions: {', '.join(reasons)}")
    return lines


def _render_trace_details(trace: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    stages = trace.get("stages") or []
    for stage in stages:
        lines.append(
            f"stage {stage.get('stage_name')}: considered={stage.get('candidate_hits_considered')}"
            f" before_visibility={stage.get('candidate_hits_before_visibility')} after_visibility={stage.get('candidate_hits_after_visibility')}"
        )
    return lines


def _payload_summary(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    parts: list[str] = []
    for key in ("summary", "decision_text", "investigation_text", "task", "current_state"):
        value = payload.get(key)
        if value:
            parts.append(str(value))
    return " | ".join(parts)


def _result_signatures(results: list[dict[str, Any]]) -> list[tuple[str | None, str | None, str]]:
    signatures: list[tuple[str | None, str | None, str]] = []
    for item in results[:5]:
        signatures.append(
            (
                item.get("result_kind"),
                item.get("type") or item.get("artifact_kind"),
                preview_text(item.get("excerpt") or _payload_summary(item.get("payload"))),
            )
        )
    return signatures


def _routing_summary(trace: dict[str, Any]) -> str:
    routing = trace.get("routing") or {}
    return f"layer={routing.get('selected_layer')} family={routing.get('query_intent') or routing.get('query_family')}"
