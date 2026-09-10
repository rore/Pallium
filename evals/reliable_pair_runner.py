"""Durable paired evaluation runner for isolated Session History fixtures.

This is evaluation tooling, not a model adapter. A driver subprocess receives
real caller-formatted search text, may request expansions, and returns one
structured answer or abstention.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import httpx

from app.config import AppConfig, ObservabilityConfig, SemanticPackageConfig
from app.main import create_app
from app.mcp.client import PalliumMcpClient
from app.mcp.context import PalliumContext
from app.mcp.server import (
    _MCP_EXPANSION_MIN_CHARS,
    _bounded_expansion,
    _compact_history,
    _json_text,
)
from core.work_ref import work_refs_from_metadata
from storage.vector_index import VectorIndexConfig, _replace_with_retry


SCHEMA_VERSION = 1
VARIANTS = ("baseline", "candidate")
SAFE_RETRY_CODES = frozenset({"connection_lost", "invalid_utf8", "missing_output", "timeout"})
NONTERMINAL = frozenset({"reserved", "started"})


class PackError(ValueError):
    """The frozen input pack is invalid or incompatible with existing state."""


class PersistenceError(Exception):
    """A durable runner record could not be written."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError, OSError) as exc:
        raise PackError(f"cannot read UTF-8 JSON {path}: {exc}") from exc


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with tmp.open("w", encoding="utf-8", errors="strict", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(str(tmp), str(path))
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise PersistenceError(f"cannot persist {path}: {exc}") from exc


def _require_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise PackError(f"{name} must be an integer >= {minimum}")
    return value


def _require_text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise PackError(f"{name} must be a {'possibly empty ' if allow_empty else ''}string")
    value.encode("utf-8", errors="strict")
    return value


def _safe_name(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    return stem[:80] or hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def validate_pack(pack: Any) -> dict[str, Any]:
    if not isinstance(pack, dict):
        raise PackError("pack must be an object")
    if pack.get("schema_version") != SCHEMA_VERSION:
        raise PackError(f"schema_version must be {SCHEMA_VERSION}")

    config = pack.get("config")
    if not isinstance(config, dict):
        raise PackError("config must be an object")
    for key in ("container_ref", "thread_ref"):
        _require_text(config.get(key), f"config.{key}")
    if config.get("visibility") not in {"private", "public"}:
        raise PackError("config.visibility must be private or public")
    for key, minimum in (
        ("max_attempts", 1),
        ("max_expansions", 1),
        ("attempt_input_tokens", 1),
        ("attempt_output_tokens", 1),
        ("retry_input_tokens", 0),
        ("retry_output_tokens", 0),
        ("total_input_tokens", 0),
        ("total_output_tokens", 0),
        ("expansion_before", 0),
        ("expansion_after", 0),
        ("expansion_max_chars", _MCP_EXPANSION_MIN_CHARS),
        ("max_driver_line_bytes", 64),
    ):
        _require_int(config.get(key), f"config.{key}", minimum)
    if config["max_attempts"] > 10:
        raise PackError("config.max_attempts must be <= 10")
    if config["max_expansions"] > 10:
        raise PackError("config.max_expansions must be <= 10")
    timeout = config.get("driver_timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise PackError("config.driver_timeout_seconds must be a positive number")

    if pack.get("variants") != list(VARIANTS):
        raise PackError(f"variants must be {list(VARIANTS)!r}")

    sources = pack.get("sources")
    if not isinstance(sources, list) or not sources:
        raise PackError("sources must be a non-empty array")
    source_ids: set[str] = set()
    source_keys: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise PackError(f"sources[{index}] must be an object")
        source_id = _require_text(source.get("source_id"), f"sources[{index}].source_id")
        if source_id in source_ids:
            raise PackError(f"duplicate source_id: {source_id}")
        source_ids.add(source_id)
        source_key = _safe_name(source_id)
        if source_key in source_keys:
            raise PackError(f"source_id filename collision: {source_id}")
        source_keys.add(source_key)
        _require_text(source.get("content"), f"sources[{index}].content")
        for key in ("source_type", "artifact_kind", "role", "thread_ref"):
            if key in source:
                _require_text(source[key], f"sources[{index}].{key}")
        if "metadata" in source and not isinstance(source["metadata"], dict):
            raise PackError(f"sources[{index}].metadata must be an object")

    cases = pack.get("cases")
    if not isinstance(cases, list) or not cases:
        raise PackError("cases must be a non-empty array")
    case_ids: set[str] = set()
    case_keys: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise PackError(f"cases[{index}] must be an object")
        case_id = _require_text(case.get("id"), f"cases[{index}].id")
        if case_id in case_ids:
            raise PackError(f"duplicate case id: {case_id}")
        case_ids.add(case_id)
        case_key = _safe_name(case_id)
        if case_key in case_keys:
            raise PackError(f"case id filename collision: {case_id}")
        case_keys.add(case_key)
        query = _require_text(case.get("query"), f"cases[{index}].query", allow_empty=True)
        limit = _require_int(case.get("limit"), f"cases[{index}].limit", 1)
        if limit > 50:
            raise PackError(f"cases[{index}].limit must be <= 50")
        if "work_refs" in case:
            refs = case["work_refs"]
            normalized = work_refs_from_metadata({"pallium_work_refs": refs})
            if not isinstance(refs, list) or len(refs) != 1 or len(normalized) != 1:
                raise PackError(
                    f"cases[{index}].work_refs must contain one valid exact work reference"
                )
        elif not query.strip():
            raise PackError(f"cases[{index}].query must be non-blank for broad search")

    gold = pack.get("gold")
    if not isinstance(gold, dict) or set(gold) != case_ids:
        raise PackError("gold keys must exactly match case ids")
    for case_id, expected in gold.items():
        if not isinstance(expected, dict):
            raise PackError(f"gold.{case_id} must be an object")
        _require_text(expected.get("required_substring"), f"gold.{case_id}.required_substring")
        if type(expected.get("allow_abstain", False)) is not bool:
            raise PackError(f"gold.{case_id}.allow_abstain must be boolean")

    return pack


def load_pack(path: Path) -> dict[str, Any]:
    return validate_pack(_read_json(path))


def _component_hashes(pack: dict[str, Any], driver: Sequence[str]) -> dict[str, str]:
    return {
        "config": _digest({"config": pack["config"], "variants": pack["variants"], "driver": list(driver)}),
        "cases": _digest(pack["cases"]),
        "gold": _digest(pack["gold"]),
        "sources": _digest(pack["sources"]),
    }


def _prepare_manifest(pack: dict[str, Any], driver: Sequence[str], run_dir: Path) -> dict[str, Any]:
    hashes = _component_hashes(pack, driver)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "pack_hash": _digest(pack),
        "component_hashes": hashes,
        "driver_command": list(driver),
    }
    path = run_dir / "manifest.json"
    if path.exists():
        old = _read_json(path)
        if old != manifest:
            old_hashes = old.get("component_hashes", {}) if isinstance(old, dict) else {}
            mismatches = sorted(key for key, value in hashes.items() if old_hashes.get(key) != value)
            if old.get("pack_hash") != manifest["pack_hash"] and not mismatches:
                mismatches.append("pack")
            raise PackError(f"incompatible resume: changed {', '.join(mismatches) or 'manifest'}")
    else:
        _atomic_json(path, manifest)
    return manifest



def _attempt_paths(run_dir: Path, case_id: str, variant: str) -> list[Path]:
    folder = run_dir / "attempts" / _safe_name(case_id) / variant
    return sorted(folder.glob("attempt-*.json")) if folder.exists() else []


def _attempts(run_dir: Path) -> list[dict[str, Any]]:
    folder = run_dir / "attempts"
    return [_read_json(path) for path in sorted(folder.glob("*/*/attempt-*.json"))] if folder.exists() else []


def _charged(attempt: dict[str, Any], key: str) -> int:
    usage = attempt.get("charged_usage") or {}
    value = usage.get(key)
    return value if type(value) is int and value >= 0 else 0


def _budget_used(run_dir: Path) -> tuple[int, int]:
    rows = _attempts(run_dir)
    return sum(_charged(row, "input_tokens") for row in rows), sum(
        _charged(row, "output_tokens") for row in rows
    )


def _pair_required(config: dict[str, Any]) -> tuple[int, int]:
    return (
        2 * config["attempt_input_tokens"] + config["retry_input_tokens"],
        2 * config["attempt_output_tokens"] + config["retry_output_tokens"],
    )


def _pair_path(run_dir: Path, case_id: str) -> Path:
    return run_dir / "pairs" / f"{_safe_name(case_id)}.json"


def _start_step(path: Path, base: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if path.exists():
        row = _read_json(path)
        if row.get("status") == "completed":
            return row, row
        if row.get("status") != "started" or not row.get("attempts"):
            raise PackError(f"invalid durable step state: {path}")
        row["attempts"][-1]["status"] = "indeterminate"
    else:
        row = {**base, "attempts": []}
    row["attempts"].append({"attempt": len(row["attempts"]) + 1, "status": "started"})
    row["status"] = "started"
    _atomic_json(path, row)
    return None, row


def _finish_step(path: Path, row: dict[str, Any], **values: Any) -> dict[str, Any]:
    row.update(values)
    row["status"] = "completed"
    row["attempts"][-1]["status"] = "completed"
    _atomic_json(path, row)
    return row


def _recover_indeterminate(run_dir: Path, case_id: str, variant: str) -> None:
    for path in _attempt_paths(run_dir, case_id, variant):
        row = _read_json(path)
        if row.get("status") in NONTERMINAL:
            row["status"] = "indeterminate"
            row["error"] = {
                "code": "crash_after_dispatch_unknown",
                "message": "process ended before a terminal record; execution may have occurred",
                "retryable": True,
            }
            row["charged_usage"] = dict(row["reservation"])
            row["cost_usd"] = None
            row["cost_status"] = "unknown"
            _atomic_json(path, row)


def _retry_reserved(run_dir: Path, case_id: str) -> tuple[int, int]:
    rows = [
        row
        for row in _attempts(run_dir)
        if row.get("case_id") == case_id and row.get("attempt", 0) > 1
    ]
    return sum(row["reservation"]["input_tokens"] for row in rows), sum(
        row["reservation"]["output_tokens"] for row in rows
    )


def _score(result: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    outcome = result["outcome"]
    correct = (
        expected.get("allow_abstain", False)
        if outcome == "abstain"
        else expected["required_substring"].casefold() in result["answer"].casefold()
    )
    return {
        "correct": bool(correct),
        "scorer": "required_substring_v1",
        "gold_hash": _digest(expected),
    }


def _terminal_attempt(run_dir: Path, case_id: str, variant: str) -> dict[str, Any] | None:
    rows = [_read_json(path) for path in _attempt_paths(run_dir, case_id, variant)]
    completed = next((row for row in reversed(rows) if row.get("status") == "completed"), None)
    return completed or (rows[-1] if rows else None)


async def _fixture(pack: dict[str, Any], run_dir: Path) -> tuple[Any, PalliumMcpClient]:
    config = pack["config"]
    db_path = run_dir / "fixture.db"
    ready_path = run_dir / "fixture.ready.json"
    expected_ready = {"sources_hash": _digest(pack["sources"])}
    if ready_path.exists():
        if _read_json(ready_path) != expected_ready or not db_path.exists():
            raise PackError("fixture state does not match frozen sources")
    else:
        for candidate in (
            db_path,
            db_path.with_name("fixture-relay.db"),
            Path(str(db_path) + "-wal"),
            Path(str(db_path) + "-shm"),
        ):
            if candidate.exists():
                candidate.unlink()

    app = create_app(
        AppConfig(
            storage_backend="sqlite",
            sqlite_url=f"sqlite:///{db_path.as_posix()}",
            default_use_case="demo_agent_memory",
            semantic_packages={
                "demo_agent_memory": SemanticPackageConfig(
                    name="demo_agent_memory",
                    implementation="demo_agent_memory",
                    enabled=True,
                )
            },
            vector_index=VectorIndexConfig(enabled=False),
            observability=ObservabilityConfig(query_audit_log=True),
        )
    )
    app.state._lifespan_complete = True
    context = PalliumContext(
        base_url="http://runner",
        container_ref=config["container_ref"],
        thread_ref=config["thread_ref"],
        visibility=config["visibility"],
    )
    client = PalliumMcpClient(context)

    async def post(path: str, payload: Any) -> Any:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://runner", timeout=30
        ) as http:
            response = await http.post(path, json=payload)
            response.raise_for_status()
            return response.json()

    client._post = post

    async def get_source_context(source_item_id: str, **kwargs: Any) -> Any:
        params: dict[str, Any] = {
            "container_ref": config["container_ref"],
            "active_session_ref": config["thread_ref"],
            "query_visibility": config["visibility"],
        }
        for key in ("before", "after", "max_chars", "parent_lookup_id", "defer_delivery"):
            if kwargs.get(key) is not None:
                params[key] = kwargs[key]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://runner", timeout=30
        ) as http:
            response = await http.get(f"/source/{source_item_id}/context", params=params)
            response.raise_for_status()
            return response.json()

    client.get_source_context = get_source_context
    if not ready_path.exists():
        items = []
        for source in pack["sources"]:
            item = {
                "source_type": source.get("source_type", "chat_message"),
                "source_id": source["source_id"],
                "content_type": "text/plain",
                "content": source["content"],
                "artifact_kind": source.get("artifact_kind", "message"),
                "container_ref": config["container_ref"],
                "thread_ref": source.get("thread_ref", "fixture-history"),
                "visibility": config["visibility"],
                "metadata": source.get("metadata", {}),
            }
            if source.get("role") is not None:
                item["role"] = source["role"]
            items.append(item)
        await post("/items", items)
        app.state.pallium_service.drain_processing_queue(worker_id="reliable-pair-runner")
        _atomic_json(ready_path, expected_ready)
    return app, client


async def _search(
    pack: dict[str, Any],
    manifest: dict[str, Any],
    run_dir: Path,
    client: PalliumMcpClient,
    case: dict[str, Any],
    variant: str,
) -> dict[str, Any]:
    path = run_dir / "steps" / _safe_name(case["id"]) / variant / "search.json"
    work_refs = case.get("work_refs")
    requested_work_ref = (
        work_refs_from_metadata({"pallium_work_refs": work_refs})[0] if work_refs else None
    )
    request = {
        "query": case["query"],
        "limit": case["limit"],
        "mode": "exact_work_ref" if requested_work_ref else "broad",
        "work_ref": requested_work_ref,
        "defer_delivery": True,
    }
    completed, row = _start_step(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "pack_hash": manifest["pack_hash"],
            "case_id": case["id"],
            "variant": variant,
            "kind": "search",
            "request": request,
        },
    )
    if completed is not None:
        return completed
    if requested_work_ref:
        raw = await client.search_history_by_work_ref(
            requested_work_ref, case["query"], limit=case["limit"], defer_delivery=True
        )
        formatted = _compact_history(
            raw,
            case["query"],
            limit=case["limit"],
            container_ref=pack["config"]["container_ref"],
            thread_ref=pack["config"]["thread_ref"],
            search_mode="exact_work_ref",
            requested_work_ref=requested_work_ref,
        )
    else:
        raw = await client.search_history(case["query"], limit=case["limit"], defer_delivery=True)
        formatted = _compact_history(
            raw,
            case["query"],
            limit=case["limit"],
            container_ref=pack["config"]["container_ref"],
            thread_ref=pack["config"]["thread_ref"],
        )
    receipt = None
    if "error" not in formatted and raw.get("delivery_attempt_id"):
        receipt = await client.finalize_historical_delivery(
            raw["delivery_attempt_id"],
            items=[
                {"source_item_id": item["source_item_id"], "role": "search_match"}
                for item in formatted.get("results", [])
            ],
        )
        if receipt.get("error"):
            formatted = receipt
        else:
            formatted["lookup_event_id"] = receipt.get("lookup_event_id")
    text = _json_text(formatted)
    return _finish_step(
        path,
        row,
        raw_response=raw,
        delivery_receipt=receipt,
        tool_text=text,
        tool_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        lookup_event_id=formatted.get("lookup_event_id"),
    )


async def _expand(
    client: PalliumMcpClient,
    pack: dict[str, Any],
    manifest: dict[str, Any],
    run_dir: Path,
    case: dict[str, Any],
    variant: str,
    search: dict[str, Any],
    source_item_id: str,
) -> dict[str, Any]:
    path = (
        run_dir
        / "steps"
        / _safe_name(case["id"])
        / variant
        / f"expand-{_safe_name(source_item_id)}.json"
    )
    search_payload = json.loads(search["tool_text"])
    visible = {item["source_item_id"] for item in search_payload.get("results", [])}
    if source_item_id not in visible:
        raise PackError("driver requested a source not present in formatted search text")
    parent = search.get("lookup_event_id")
    if not isinstance(parent, str) or not parent:
        raise PackError("search produced no lookup_event_id for expansion lineage")
    config = pack["config"]
    request = {
        "before": config["expansion_before"],
        "after": config["expansion_after"],
        "max_chars": config["expansion_max_chars"],
        "parent_lookup_id": parent,
        "defer_delivery": True,
    }

    completed, row = _start_step(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "pack_hash": manifest["pack_hash"],
            "case_id": case["id"],
            "variant": variant,
            "kind": "expansion",
            "source_item_id": source_item_id,
            "parent_lookup_id": parent,
            "request": request,
        },
    )
    if completed is not None:
        if completed.get("parent_lookup_id") != parent:
            raise PackError("cached expansion lookup lineage mismatch")
        return completed
    raw = await client.get_source_context(
        source_item_id,
        before=config["expansion_before"],
        after=config["expansion_after"],
        max_chars=config["expansion_max_chars"],
        parent_lookup_id=parent,
        defer_delivery=True,
    )
    formatted = _bounded_expansion(raw, config["expansion_max_chars"])
    receipt = None
    if "error" not in formatted and raw.get("delivery_attempt_id"):
        receipt = await client.finalize_historical_delivery(
            raw["delivery_attempt_id"],
            items=[
                {
                    "source_item_id": item["source_item_id"],
                    "role": "anchor" if item.get("is_anchor") else "neighbor",
                }
                for item in formatted.get("items", [])
            ],
        )
        if receipt.get("error"):
            formatted = receipt
    text = _json_text(formatted)
    return _finish_step(
        path,
        row,
        raw_response=raw,
        delivery_receipt=receipt,
        tool_text=text,
        tool_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()


async def _driver_attempt(
    command: Sequence[str],
    client: PalliumMcpClient,
    pack: dict[str, Any],
    manifest: dict[str, Any],
    run_dir: Path,
    case: dict[str, Any],
    variant: str,
    search: dict[str, Any],
    attempt_path: Path,
    attempt_row: dict[str, Any],
) -> dict[str, Any]:
    config = pack["config"]
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=config["max_driver_line_bytes"] + 1,
        )
    except OSError as exc:
        return {
            "ok": False,
            "code": "driver_start_failed",
            "message": str(exc),
            "retryable": False,
            "transcript": [],
        }
    assert process.stdin is not None and process.stdout is not None
    transcript: list[dict[str, Any]] = []
    start = {
        "type": "search",
        "case_id": case["id"],
        "variant": variant,
        "query": case["query"],
        "tool_text": search["tool_text"],
        "max_input_tokens": config["attempt_input_tokens"],
        "max_output_tokens": config["attempt_output_tokens"],
    }

    def persist_transcript() -> None:
        attempt_row["transcript"] = list(transcript)
        _atomic_json(attempt_path, attempt_row)

    async def send(message: dict[str, Any]) -> None:
        process.stdin.write(_canonical(message) + b"\n")
        await process.stdin.drain()
        transcript.append({"direction": "to_driver", "message": message})
        persist_transcript()

    async def receive() -> dict[str, Any]:
        try:
            raw = await asyncio.wait_for(
                process.stdout.readline(), timeout=float(config["driver_timeout_seconds"])
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError("timeout") from exc
        except ValueError as exc:
            raise RuntimeError("line_too_large") from exc
        if not raw:
            stderr = await process.stderr.read() if process.stderr is not None else b""
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"missing_output\n{detail}" if detail else "missing_output")
        if len(raw) > config["max_driver_line_bytes"]:
            raise RuntimeError("line_too_large")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise RuntimeError("invalid_utf8") from exc
        try:
            message = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("malformed_output") from exc
        if not isinstance(message, dict):
            raise RuntimeError("malformed_output")
        transcript.append({"direction": "from_driver", "message": message})
        persist_transcript()
        return message

    expansions = 0
    try:
        await send(start)
        while True:
            message = await receive()
            kind = message.get("type")
            if kind == "expand":
                if expansions >= config["max_expansions"]:
                    raise RuntimeError("too_many_expansions")
                source_id = _require_text(message.get("source_item_id"), "driver.source_item_id")
                expanded = await _expand(
                    client, pack, manifest, run_dir, case, variant, search, source_id
                )
                expansions += 1
                await send(
                    {
                        "type": "expansion",
                        "source_item_id": source_id,
                        "parent_lookup_id": expanded["parent_lookup_id"],
                        "tool_text": expanded["tool_text"],
                    }
                )
                continue
            if kind == "transport_error":
                code = _require_text(message.get("code"), "driver.code")
                return {
                    "ok": False,
                    "code": code,
                    "message": str(message.get("message") or code),
                    "retryable": code in SAFE_RETRY_CODES,
                    "transcript": transcript,
                }
            if kind != "result":
                raise RuntimeError("unexpected_message")
            outcome = message.get("outcome")
            if outcome not in {"answer", "abstain"}:
                raise RuntimeError("invalid_outcome")
            answer = message.get("answer", "")
            if not isinstance(answer, str) or (outcome == "answer" and not answer):
                raise RuntimeError("invalid_answer")
            usage = message.get("usage")
            if not isinstance(usage, dict):
                raise RuntimeError("invalid_usage")
            input_tokens = _require_int(usage.get("input_tokens"), "usage.input_tokens", 0)
            output_tokens = _require_int(usage.get("output_tokens"), "usage.output_tokens", 0)
            cost = usage.get("cost_usd")
            if cost is not None and (
                isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0
            ):
                raise RuntimeError("invalid_cost")
            return {
                "ok": True,
                "result": {"outcome": outcome, "answer": answer},
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost,
                },
                "transcript": transcript,
            }
    except (BrokenPipeError, ConnectionError, OSError) as exc:
        return {
            "ok": False,
            "code": "connection_lost",
            "message": str(exc),
            "retryable": True,
            "transcript": transcript,
        }
    except PackError as exc:
        return {
            "ok": False,
            "code": "invalid_driver_request",
            "message": str(exc),
            "retryable": False,
            "transcript": transcript,
        }
    except RuntimeError as exc:
        message = str(exc)
        code = message.split("\n", 1)[0]
        return {
            "ok": False,
            "code": code,
            "message": message,
            "retryable": code in SAFE_RETRY_CODES,
            "transcript": transcript,
        }
    finally:
        await _stop_process(process)


def _can_retry(pack: dict[str, Any], run_dir: Path, case_id: str) -> bool:
    config = pack["config"]
    retry_in, retry_out = _retry_reserved(run_dir, case_id)
    return (
        retry_in + config["attempt_input_tokens"] <= config["retry_input_tokens"]
        and retry_out + config["attempt_output_tokens"] <= config["retry_output_tokens"]
    )


def _global_attempt_fits(pack: dict[str, Any], run_dir: Path) -> bool:
    config = pack["config"]
    used_in, used_out = _budget_used(run_dir)
    return (
        used_in + config["attempt_input_tokens"] <= config["total_input_tokens"]
        and used_out + config["attempt_output_tokens"] <= config["total_output_tokens"]
    )


async def _run_variant(
    command: Sequence[str],
    client: PalliumMcpClient,
    pack: dict[str, Any],
    manifest: dict[str, Any],
    run_dir: Path,
    case: dict[str, Any],
    variant: str,
) -> dict[str, Any]:
    _recover_indeterminate(run_dir, case["id"], variant)
    terminal = _terminal_attempt(run_dir, case["id"], variant)
    if terminal and terminal["status"] in {"completed", "permanent_failure", "budget_skipped"}:
        return terminal

    paths = _attempt_paths(run_dir, case["id"], variant)
    while len(paths) < pack["config"]["max_attempts"]:
        if paths and not _can_retry(pack, run_dir, case["id"]):
            break
        if not _global_attempt_fits(pack, run_dir):
            path = (
                run_dir
                / "attempts"
                / _safe_name(case["id"])
                / variant
                / f"attempt-{len(paths) + 1:03d}.json"
            )
            row = {
                "schema_version": SCHEMA_VERSION,
                "pack_hash": manifest["pack_hash"],
                "case_id": case["id"],
                "variant": variant,
                "attempt": len(paths) + 1,
                "status": "budget_skipped",
                "reservation": {"input_tokens": 0, "output_tokens": 0},
                "charged_usage": {"input_tokens": 0, "output_tokens": 0},
                "cost_usd": 0.0,
                "cost_status": "known",
                "reason": "insufficient remaining input/output or retry budget",
            }
            _atomic_json(path, row)
            return row
        number = len(paths) + 1
        path = (
            run_dir
            / "attempts"
            / _safe_name(case["id"])
            / variant
            / f"attempt-{number:03d}.json"
        )
        reservation = {
            "input_tokens": pack["config"]["attempt_input_tokens"],
            "output_tokens": pack["config"]["attempt_output_tokens"],
        }
        search = await _search(pack, manifest, run_dir, client, case, variant)
        row = {
            "schema_version": SCHEMA_VERSION,
            "pack_hash": manifest["pack_hash"],
            "case_id": case["id"],
            "variant": variant,
            "attempt": number,
            "status": "reserved",
            "reservation": reservation,
            "charged_usage": dict(reservation),
            "cost_usd": None,
            "cost_status": "unknown",
            "input": {
                "query": case["query"],
                "search_step": str(
                    run_dir / "steps" / _safe_name(case["id"]) / variant / "search.json"
                ),
                "search_tool_text_sha256": search["tool_text_sha256"],
            },
            "transcript": [],
        }
        _atomic_json(path, row)
        row["status"] = "started"
        _atomic_json(path, row)
        outcome = await _driver_attempt(
            command,
            client,
            pack,
            manifest,
            run_dir,
            case,
            variant,
            search,
            path,
            row,
        )
        row["transcript"] = outcome["transcript"]
        if outcome["ok"]:
            usage = outcome["usage"]
            exceeds = (
                usage["input_tokens"] > reservation["input_tokens"]
                or usage["output_tokens"] > reservation["output_tokens"]
            )
            row["charged_usage"] = {
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
            }
            row["cost_usd"] = usage["cost_usd"]
            row["cost_status"] = "known" if usage["cost_usd"] is not None else "unknown"
            if exceeds:
                row["status"] = "permanent_failure"
                row["error"] = {
                    "code": "usage_exceeds_reservation",
                    "message": "driver reported usage above the frozen input/output ceiling",
                    "retryable": False,
                }
            else:
                row["status"] = "completed"
                row["response"] = outcome["result"]
                row["score"] = _score(outcome["result"], pack["gold"][case["id"]])
        else:
            row["status"] = "transport_invalid" if outcome["retryable"] else "permanent_failure"
            row["error"] = {
                "code": outcome["code"],
                "message": outcome["message"],
                "retryable": bool(outcome["retryable"]),
            }
        _atomic_json(path, row)
        paths = _attempt_paths(run_dir, case["id"], variant)
        if row["status"] in {"completed", "permanent_failure"}:
            return row
    return _terminal_attempt(run_dir, case["id"], variant) or {
        "case_id": case["id"],
        "variant": variant,
        "status": "budget_skipped",
    }


def build_report(pack: dict[str, Any], manifest: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    statuses: Counter[str] = Counter()
    for case in pack["cases"]:
        pair_row = _read_json(_pair_path(run_dir, case["id"]))
        variants: dict[str, Any] = {}
        for variant in VARIANTS:
            attempt = _terminal_attempt(run_dir, case["id"], variant)
            if attempt is not None:
                variants[variant] = {
                    "status": attempt["status"],
                    "attempt": attempt["attempt"],
                    "score": attempt.get("score"),
                }
                statuses[attempt["status"]] += 1
        pair_row["variants"] = variants
        if pair_row["status"] != "cannot_start_pair":
            pair_row["status"] = (
                "completed"
                if all(variants.get(v, {}).get("status") == "completed" for v in VARIANTS)
                else "invalid"
            )
            _atomic_json(_pair_path(run_dir, case["id"]), pair_row)
        pairs.append(pair_row)

    usable = [pair for pair in pairs if pair["status"] == "completed"]
    quality = None
    if usable:
        quality = {
            "usable_pairs": len(usable),
            "baseline_correct": sum(
                bool(pair["variants"]["baseline"]["score"]["correct"]) for pair in usable
            ),
            "candidate_correct": sum(
                bool(pair["variants"]["candidate"]["score"]["correct"]) for pair in usable
            ),
            "measurement": "scripted infrastructure pilot; not agent quality",
        }
    attempts = _attempts(run_dir)
    known_costs = [row.get("cost_usd") for row in attempts if row.get("cost_usd") is not None]
    unknown_costs = sum(row.get("cost_usd") is None for row in attempts)
    attempt_statuses = Counter(row["status"] for row in attempts)
    report = {
        "schema_version": SCHEMA_VERSION,
        "pack_hash": manifest["pack_hash"],
        "decision_status": (
            "complete"
            if len(pairs) == len(pack["cases"])
            and all(pair["status"] in {"completed", "invalid", "cannot_start_pair"} for pair in pairs)
            else "incomplete"
        ),
        "pairs_total": len(pairs),
        "usable_pairs": len(usable),
        "invalid_pairs": sum(pair["status"] == "invalid" for pair in pairs),
        "cannot_start_pairs": sum(pair["status"] == "cannot_start_pair" for pair in pairs),
        "variant_statuses": dict(sorted(statuses.items())),
        "attempt_statuses": dict(sorted(attempt_statuses.items())),
        "quality": quality,
        "usage": {
            "charged_input_tokens": sum(_charged(row, "input_tokens") for row in attempts),
            "charged_output_tokens": sum(_charged(row, "output_tokens") for row in attempts),
            "cost_usd_total": sum(known_costs) if unknown_costs == 0 else None,
            "cost_usd_known_partial": sum(known_costs),
            "cost_unknown_attempts": unknown_costs,
        },
        "attempt_count": len(attempts),
        "pairs": pairs,
        "records_hash": _digest(attempts),
    }
    _atomic_json(run_dir / "report.json", report)
    return report


async def run(
    pack_path: Path,
    run_dir: Path,
    driver_command: Sequence[str],
) -> dict[str, Any]:
    if not driver_command or any(not isinstance(part, str) or not part for part in driver_command):
        raise PackError("driver command must contain non-empty strings")
    pack = load_pack(pack_path)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = _prepare_manifest(pack, driver_command, run_dir)
    _app, client = await _fixture(pack, run_dir)
    config = pack["config"]

    for case in pack["cases"]:
        pair_path = _pair_path(run_dir, case["id"])
        if not pair_path.exists():
            used_in, used_out = _budget_used(run_dir)
            required_in, required_out = _pair_required(config)
            if (
                used_in + required_in > config["total_input_tokens"]
                or used_out + required_out > config["total_output_tokens"]
            ):
                _atomic_json(
                    pair_path,
                    {
                        "case_id": case["id"],
                        "status": "cannot_start_pair",
                        "reason": "insufficient pair and retry reservation",
                        "required": {
                            "input_tokens": required_in,
                            "output_tokens": required_out,
                        },
                    },
                )
                continue
            _atomic_json(
                pair_path,
                {
                    "case_id": case["id"],
                    "status": "active",
                    "reservation": {
                        "input_tokens": required_in,
                        "output_tokens": required_out,
                    },
                },
            )
        pair = _read_json(pair_path)
        if pair["status"] in {"completed", "invalid", "cannot_start_pair"}:
            continue
        for variant in VARIANTS:
            await _run_variant(
                driver_command, client, pack, manifest, run_dir, case, variant
            )
        pair["status"] = "active"
        _atomic_json(pair_path, pair)

    return build_report(pack, manifest, run_dir)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--driver", nargs=argparse.REMAINDER, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = asyncio.run(run(args.pack, args.run_dir, args.driver))
    except PackError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["decision_status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
