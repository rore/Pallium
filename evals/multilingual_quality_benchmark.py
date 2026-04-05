"""Multilingual memory quality benchmark.

Validates that Hebrew (and other non-English) content produces correct
memory objects through the full pipeline: ingest → LLM extraction →
thread rebuild → consolidation → inspect payloads.

Checks that memory payloads preserve the source language and contain
the expected factual content. This is a quality validation benchmark,
not a unit test — run on demand when changing prompts or validating
multilingual claims.

Usage:
    python -m evals.multilingual_quality_benchmark
    python -m evals.multilingual_quality_benchmark --run-name my-run
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.config import AppConfig
from app.main import create_app
from core.models import MemoryObject

try:
    from starlette.testclient import TestClient
except ImportError:
    from fastapi.testclient import TestClient  # type: ignore[assignment]


DEFAULT_OUTPUT_DIR = Path("evals/multilingual_quality/output")

HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
CHINESE_RE = re.compile(r"[\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF]")


def _has_hebrew(text: str) -> bool:
    return bool(HEBREW_RE.search(text or ""))


def _has_chinese(text: str) -> bool:
    return bool(CHINESE_RE.search(text or ""))


# ---------------------------------------------------------------------------
# Scenarios — each is a self-contained ingest + inspect test
# ---------------------------------------------------------------------------

SCENARIOS: list[dict[str, Any]] = [
    {
        "scenario_id": "hebrew-thread-summary-quality",
        "description": "Hebrew conversation thread should produce a Hebrew thread_summary with correct facts",
        "events": [
            {
                "source_type": "chat_message",
                "source_id": "mqb-heb-ts-1",
                "content_type": "text/plain",
                "content": "אנחנו צריכים להחליט מתי לעשות סנכרון של הקטלוג. בשעות השיא יש עומס כבד על המערכת.",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "chat:library-ops",
                "thread_ref": "chat:library-ops:sync-schedule",
                "visibility": "private",
                "occurred_at": "2026-03-15T10:00:00Z",
            },
            {
                "source_type": "chat_message",
                "source_id": "mqb-heb-ts-2",
                "content_type": "text/plain",
                "content": "החלטה: סנכרון הקטלוג יתבצע בצורה יומית בשעה 03:00 בלילה כדי למנוע עומס על המערכת בשעות השיא. 95% מהפעולות מתרחשות בין 08:00 ל-20:00.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:library-ops",
                "thread_ref": "chat:library-ops:sync-schedule",
                "visibility": "private",
                "occurred_at": "2026-03-15T10:01:00Z",
            },
        ],
        "checks": [
            {
                "check_id": "thread-summary-exists",
                "memory_type": "thread_summary",
                "field": None,
                "assert": "exists",
            },
            {
                "check_id": "thread-summary-in-hebrew",
                "memory_type": "thread_summary",
                "field": "summary",
                "assert": "has_hebrew",
            },
            {
                "check_id": "thread-summary-mentions-03:00",
                "memory_type": "thread_summary",
                "field": "summary",
                "assert": "contains",
                "value": "03:00",
            },
            {
                "check_id": "decision-in-hebrew",
                "memory_type": "decision",
                "field": "decision",
                "assert": "has_hebrew",
            },
            {
                "check_id": "atomic-facts-exist",
                "memory_type": "atomic_fact",
                "field": None,
                "assert": "exists",
            },
            {
                "check_id": "atomic-facts-in-hebrew",
                "memory_type": "atomic_fact",
                "field": "statement",
                "assert": "all_have_hebrew",
            },
        ],
    },
    {
        "scenario_id": "hebrew-task-checkpoint-quality",
        "description": "Hebrew investigation thread with blocker should produce a Hebrew task_checkpoint",
        "events": [
            {
                "source_type": "chat_message",
                "source_id": "mqb-heb-cp-1",
                "content_type": "text/plain",
                "content": "צריך לבדוק למה סנכרון הקטלוג נכשל בשעות הלילה. הלקוחות מדווחים על פריטים חסרים.",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "chat:library-ops",
                "thread_ref": "chat:library-ops:sync-failure",
                "visibility": "private",
                "occurred_at": "2026-03-15T11:00:00Z",
            },
            {
                "source_type": "chat_message",
                "source_id": "mqb-heb-cp-2",
                "content_type": "text/plain",
                "content": "Investigation found: סנכרון הקטלוג נכשל כי גודל האצווה של 200 פריטים גורם ל-timeout כשהקטלוג גדול. פריטים מעבר ל-200 לא מסונכרנים.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:library-ops",
                "thread_ref": "chat:library-ops:sync-failure",
                "visibility": "private",
                "occurred_at": "2026-03-15T11:01:00Z",
            },
            {
                "source_type": "chat_message",
                "source_id": "mqb-heb-cp-3",
                "content_type": "text/plain",
                "content": "blocked: הגדלת גודל האצווה דורשת שינוי ב-API של ספק הקטלוג. next step: לפנות לספק ולבקש הגדלת מגבלת ה-API ל-1000 פריטים.",
                "artifact_kind": "tool_use_summary",
                "role": "assistant",
                "container_ref": "chat:library-ops",
                "thread_ref": "chat:library-ops:sync-failure",
                "visibility": "private",
                "occurred_at": "2026-03-15T11:02:00Z",
            },
        ],
        "checks": [
            {
                "check_id": "checkpoint-exists",
                "memory_type": "task_checkpoint",
                "field": None,
                "assert": "exists",
            },
            {
                "check_id": "checkpoint-summary-in-hebrew",
                "memory_type": "task_checkpoint",
                "field": "summary",
                "assert": "has_hebrew",
            },
            {
                "check_id": "checkpoint-mentions-200",
                "memory_type": "task_checkpoint",
                "field": "summary",
                "assert": "contains_any",
                "values": ["200", "timeout", "batch"],
            },
            {
                "check_id": "atomic-facts-exist",
                "memory_type": "atomic_fact",
                "field": None,
                "assert": "exists",
            },
            {
                "check_id": "atomic-facts-in-hebrew",
                "memory_type": "atomic_fact",
                "field": "statement",
                "assert": "all_have_hebrew",
            },
        ],
    },
    {
        "scenario_id": "mixed-language-thread-summary",
        "description": "Mixed Hebrew/English thread should produce a summary preserving both languages",
        "events": [
            {
                "source_type": "chat_message",
                "source_id": "mqb-mix-ts-1",
                "content_type": "text/plain",
                "content": "אני חושב שנשתמש ב-Redis לשכבת ה-caching של הקטלוג. יש לו ביצועים טובים ו-pub-sub לביטול מטמון.",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "chat:library-ops",
                "thread_ref": "chat:library-ops:caching-decision",
                "visibility": "private",
                "occurred_at": "2026-03-15T12:00:00Z",
            },
            {
                "source_type": "chat_message",
                "source_id": "mqb-mix-ts-2",
                "content_type": "text/plain",
                "content": "Decision: use Redis for the catalog caching layer. The key-value access patterns match our needs and pub-sub provides built-in cache invalidation.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:library-ops",
                "thread_ref": "chat:library-ops:caching-decision",
                "visibility": "private",
                "occurred_at": "2026-03-15T12:01:00Z",
            },
        ],
        "checks": [
            {
                "check_id": "thread-summary-exists",
                "memory_type": "thread_summary",
                "field": None,
                "assert": "exists",
            },
            {
                "check_id": "thread-summary-mentions-redis",
                "memory_type": "thread_summary",
                "field": "summary",
                "assert": "contains_any",
                "values": ["Redis", "redis", "caching", "cache"],
            },
            {
                "check_id": "decision-mentions-redis",
                "memory_type": "decision",
                "field": "decision",
                "assert": "contains_any",
                "values": ["Redis", "redis"],
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _run_scenario(scenario: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    with TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'multilingual-quality.db'}"
        vector_index_config = replace(config.vector_index, index_path=str(Path(temp_dir) / "vector.index"))
        scenario_config = replace(
            config,
            sqlite_url=database_url,
            default_use_case="agent_conversation_memory",
            vector_index=vector_index_config,
        )
        with TestClient(create_app(scenario_config)) as client:
            # Ingest events
            for event in scenario["events"]:
                event_with_vis = {**event}
                if "visibility" not in event_with_vis:
                    event_with_vis["visibility"] = "private"
                response = client.post("/items", json=[event_with_vis])
                response.raise_for_status()

            # Process everything
            client.app.state.pallium_service.drain_processing_queue(
                worker_id="multilingual-quality-runner"
            )

            # Collect all memory objects
            storage = client.app.state.pallium_service._storage
            all_memory = storage.list_memory_objects()
            active_memory = [m for m in all_memory if m.lifecycle == "active"]

            # Run checks
            check_results = []
            for check in scenario["checks"]:
                result = _run_check(check, active_memory)
                check_results.append(result)

            # Collect memory snapshot for output
            memory_snapshot = [
                {
                    "id": m.id,
                    "type": m.type,
                    "lifecycle": m.lifecycle,
                    "payload": m.payload,
                }
                for m in active_memory
            ]

            engine = getattr(storage, "_engine", None)
            if engine is not None:
                engine.dispose()

    all_passed = all(c["passed"] for c in check_results)
    return {
        "scenario_id": scenario["scenario_id"],
        "description": scenario["description"],
        "passed": all_passed,
        "checks": check_results,
        "memory_objects_created": len(active_memory),
        "memory_types": sorted({m.type for m in active_memory}),
        "memory_snapshot": memory_snapshot,
    }


def _run_check(check: dict[str, Any], memory: list[MemoryObject]) -> dict[str, Any]:
    check_id = check["check_id"]
    memory_type = check["memory_type"]
    field = check.get("field")
    assert_type = check["assert"]

    matching = [m for m in memory if m.type == memory_type]

    if assert_type == "exists":
        passed = len(matching) > 0
        return {"check_id": check_id, "passed": passed, "detail": f"found {len(matching)} {memory_type}"}

    if not matching:
        return {"check_id": check_id, "passed": False, "detail": f"no {memory_type} found"}

    # Get field value from first matching memory
    obj = matching[0]
    value = obj.payload.get(field, "") if field else ""
    if not isinstance(value, str):
        value = str(value)

    if assert_type == "has_hebrew":
        passed = _has_hebrew(value)
        return {"check_id": check_id, "passed": passed, "detail": f"hebrew={'yes' if passed else 'no'}", "value_preview": value[:100]}

    if assert_type == "has_chinese":
        passed = _has_chinese(value)
        return {"check_id": check_id, "passed": passed, "detail": f"chinese={'yes' if passed else 'no'}", "value_preview": value[:100]}

    if assert_type == "contains":
        target = check["value"]
        passed = target.lower() in value.lower()
        return {"check_id": check_id, "passed": passed, "detail": f"contains '{target}': {'yes' if passed else 'no'}", "value_preview": value[:100]}

    if assert_type == "contains_any":
        targets = check["values"]
        found = [t for t in targets if t.lower() in value.lower()]
        passed = len(found) > 0
        return {"check_id": check_id, "passed": passed, "detail": f"found: {found}", "value_preview": value[:100]}

    if assert_type == "all_have_hebrew":
        # Check that ALL matching memories have Hebrew in the specified field
        values = [m.payload.get(field, "") for m in matching if isinstance(m.payload.get(field, ""), str)]
        hebrew_count = sum(1 for v in values if _has_hebrew(v))
        passed = hebrew_count == len(values) and len(values) > 0
        previews = [v[:60] for v in values[:3]]
        return {"check_id": check_id, "passed": passed, "detail": f"hebrew in {hebrew_count}/{len(values)} {memory_type}", "value_preview": str(previews)}

    return {"check_id": check_id, "passed": False, "detail": f"unknown assert type: {assert_type}"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_multilingual_quality_benchmark(
    *,
    output_root: Path = DEFAULT_OUTPUT_DIR,
    config: AppConfig | None = None,
    run_name: str | None = None,
) -> Path:
    if config is None:
        config = AppConfig.from_env()

    run_id = run_name or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    results: list[dict[str, Any]] = []
    with results_path.open("w", encoding="utf-8") as f:
        for scenario in SCENARIOS:
            print(f"  Running: {scenario['scenario_id']}...")
            result = _run_scenario(scenario, config)
            results.append(result)
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
            status = "PASS" if result["passed"] else "FAIL"
            print(f"    {status} ({result['memory_objects_created']} memories, {len(result['checks'])} checks)")
            for c in result["checks"]:
                mark = "pass" if c["passed"] else "FAIL"
                print(f"      [{mark}] {c['check_id']}: {c['detail']}")

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    summary = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenarios_total": total,
        "scenarios_passed": passed,
        "scenarios_failed": failed,
        "results_file": results_path.name,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'='*50}")
    print(f"Multilingual quality: {passed}/{total} scenarios passed")
    if failed:
        print(f"FAILURES: {[r['scenario_id'] for r in results if not r['passed']]}")
    print(f"Output: {run_dir}")
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Run multilingual memory quality benchmark.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    args = parser.parse_args()

    run_dir = run_multilingual_quality_benchmark(
        output_root=args.output_dir,
        run_name=args.run_name,
    )
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
