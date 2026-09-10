"""Focused E2E coverage and deterministic subprocess pilot for the paired runner."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.slow

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.reliable_pair_runner import PackError, run, validate_pack


PYTHON = sys.executable
HERE = Path(__file__).resolve()


def _pack(
    *,
    case_count: int = 1,
    total_input: int = 1000,
    total_output: int = 200,
    retry_input: int = 200,
    retry_output: int = 40,
    max_attempts: int = 2,
) -> dict[str, Any]:
    cases = []
    sources = []
    gold = {}
    for index in range(case_count):
        case_id = f"case-{index + 1}"
        query = f"résumé marker {index + 1}"
        answer = "\u627e\u5230\u7b54\u6848" if index == 0 else f"\u7b54\u6848-{index + 1}"
        cases.append({"id": case_id, "query": query, "limit": 5})
        sources.append(
            {
                "source_id": f"source-{index + 1}",
                "source_type": "chat_message",
                "artifact_kind": "message",
                "role": "assistant",
                "thread_ref": f"history-{index + 1}",
                "content": f"{query} \u2014 authoritative result: {answer} \u2705",
            }
        )
        gold[case_id] = {"required_substring": answer, "allow_abstain": False}
    return {
        "schema_version": 1,
        "config": {
            "container_ref": "fixture:reliable-pair",
            "thread_ref": "pilot-active-thread",
            "visibility": "private",
            "max_attempts": max_attempts,
            "max_expansions": 2,
            "attempt_input_tokens": 100,
            "attempt_output_tokens": 20,
            "retry_input_tokens": retry_input,
            "retry_output_tokens": retry_output,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "expansion_before": 0,
            "expansion_after": 0,
            "expansion_max_chars": 2000,
            "max_driver_line_bytes": 16384,
            "driver_timeout_seconds": 4,
        },
        "variants": ["baseline", "candidate"],
        "cases": cases,
        "sources": sources,
        "gold": gold,
    }


def _write_pack(root: Path, value: dict[str, Any]) -> Path:
    path = root / "pack.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _driver(mode: str, control: Path) -> list[str]:
    return [PYTHON, str(HERE), "--driver", mode, str(control)]


def _append(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(value + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _mark_once(control: Path, name: str) -> bool:
    path = control / name
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("used\n", encoding="utf-8")
    return True


def _send(value: dict[str, Any]) -> None:
    sys.stdout.buffer.write(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
    )
    sys.stdout.buffer.flush()


def _driver_main(mode: str, control: Path) -> int:
    raw = sys.stdin.buffer.readline()
    if not raw:
        return 3
    search = json.loads(raw.decode("utf-8", errors="strict"))
    if search.get("type") != "search":
        return 4
    key = f"{search['case_id']}:{search['variant']}"
    _append(control / "dispatch.log", key)

    if mode == "indeterminate_once" and _mark_once(control, "indeterminate.used"):
        _append(control / "external_execution.log", key)
        (control / "blocked").write_text("ready\n", encoding="utf-8")
        while sys.stdin.buffer.readline():
            pass
        return 0
    if mode == "transient_once" and _mark_once(control, f"transient-{key}.used"):
        _send({"type": "transport_error", "code": "connection_lost"})
        return 0
    if mode == "invalid_utf8_once" and _mark_once(control, f"utf8-{key}.used"):
        sys.stdout.buffer.write(b"\xff\n")
        sys.stdout.buffer.flush()
        return 0
    if mode == "permanent":
        _send({"type": "transport_error", "code": "authentication_failed"})
        return 0
    if mode == "malformed":
        sys.stdout.buffer.write(b"not-json\n")
        sys.stdout.buffer.flush()
        return 0
    if mode == "missing":
        return 0

    _append(control / "external_execution.log", key)
    search_payload = json.loads(search["tool_text"])
    results = search_payload.get("results", [])
    source_id = next(
        item["source_item_id"]
        for item in results
        if "résumé marker" in item.get("excerpt", "")
    )
    _send({"type": "expand", "source_item_id": source_id})
    expansion_raw = sys.stdin.buffer.readline()
    if not expansion_raw:
        return 5
    expansion = json.loads(expansion_raw.decode("utf-8", errors="strict"))
    if expansion.get("type") != "expansion":
        return 6
    tool_payload = json.loads(expansion["tool_text"])
    assert tool_payload["parent_lookup_id"] == expansion["parent_lookup_id"]
    content = "\n".join(item.get("content", "") for item in tool_payload.get("items", []))
    if mode == "transient_after_expansion_once" and _mark_once(
        control, f"after-expansion-{key}.used"
    ):
        _send({"type": "transport_error", "code": "connection_lost"})
        return 0
    if mode == "abstain":
        _send(
            {
                "type": "result",
                "outcome": "abstain",
                "answer": "",
                "usage": {"input_tokens": 20, "output_tokens": 2, "cost_usd": 0.0},
            }
        )
        return 0
    answer_match = re.search(r"(\u627e\u5230\u7b54\u6848|\u7b54\u6848-\d+)", content)
    if not answer_match:
        _send(
            {
                "type": "result",
                "outcome": "abstain",
                "answer": "",
                "usage": {"input_tokens": 20, "output_tokens": 2, "cost_usd": 0.0},
            }
        )
        return 0
    output_tokens = 21 if mode == "usage_over" else 5
    _send(
        {
            "type": "result",
            "outcome": "answer",
            "answer": answer_match.group(1),
            "usage": {
                "input_tokens": 20,
                "output_tokens": output_tokens,
                "cost_usd": 0.0,
            },
        }
    )
    return 0


def _attempts(state: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((state / "attempts").glob("*/*/attempt-*.json"))
    ]


def _run(pack_path: Path, state: Path, mode: str, control: Path) -> dict[str, Any]:
    return asyncio.run(run(pack_path, state, _driver(mode, control)))


def test_pilot_real_surfaces_unicode_resume_and_pair_order(tmp_path: Path) -> None:
    pack_path = _write_pack(tmp_path, _pack(case_count=2))
    state, control = tmp_path / "state", tmp_path / "control"

    report = _run(pack_path, state, "normal", control)

    assert report["decision_status"] == "complete"
    assert report["usable_pairs"] == 2
    assert report["quality"] == {
        "usable_pairs": 2,
        "baseline_correct": 2,
        "candidate_correct": 2,
        "measurement": "scripted infrastructure pilot; not agent quality",
    }
    assert (state / "fixture.db").exists()
    assert (state / "report.json").exists()
    assert (control / "dispatch.log").read_text(encoding="utf-8").splitlines() == [
        "case-1:baseline",
        "case-1:candidate",
        "case-2:baseline",
        "case-2:candidate",
    ]
    expansion = json.loads(
        next((state / "steps" / "case-1" / "baseline").glob("expand-*.json")).read_text(
            encoding="utf-8"
        )
    )
    search = json.loads(
        (state / "steps" / "case-1" / "baseline" / "search.json").read_text(
            encoding="utf-8"
        )
    )
    assert "\u627e\u5230\u7b54\u6848" in expansion["tool_text"]
    assert expansion["parent_lookup_id"] == search["lookup_event_id"]
    rows = _attempts(state)
    assert report["attempt_count"] == len(rows)
    assert report["usage"]["charged_input_tokens"] == sum(
        row["charged_usage"]["input_tokens"] for row in rows
    )
    assert json.loads((state / "report.json").read_text(encoding="utf-8")) == report
    first_records_hash = report["records_hash"]

    resumed = _run(pack_path, state, "normal", control)
    assert resumed["records_hash"] == first_records_hash
    assert len((control / "dispatch.log").read_text(encoding="utf-8").splitlines()) == 4


@pytest.mark.parametrize("mode", ["transient_once", "invalid_utf8_once"])
def test_safe_transport_failure_retries_with_reserved_budget(
    tmp_path: Path, mode: str
) -> None:
    pack_path = _write_pack(tmp_path, _pack())
    state, control = tmp_path / "state", tmp_path / "control"

    report = _run(pack_path, state, mode, control)
    rows = _attempts(state)

    assert report["usable_pairs"] == 1
    assert [row["status"] for row in rows] == [
        "transport_invalid",
        "completed",
        "transport_invalid",
        "completed",
    ]
    assert report["attempt_count"] == 4
    assert report["usage"]["charged_input_tokens"] == 240


def test_completed_expansion_is_reused_after_transport_retry(tmp_path: Path) -> None:
    pack_path = _write_pack(tmp_path, _pack())
    state, control = tmp_path / "state", tmp_path / "control"

    report = _run(pack_path, state, "transient_after_expansion_once", control)
    rows = _attempts(state)

    assert report["usable_pairs"] == 1
    assert len(list((state / "steps" / "case-1" / "baseline").glob("expand-*.json"))) == 1
    assert len(list((state / "steps" / "case-1" / "candidate").glob("expand-*.json"))) == 1
    assert all(
        any(
            item["direction"] == "to_driver"
            and item["message"].get("type") == "expansion"
            for item in row["transcript"]
        )
        for row in rows
    )


def test_valid_abstention_is_a_product_result_not_transport_invalid(tmp_path: Path) -> None:
    pack_path = _write_pack(tmp_path, _pack())
    report = _run(pack_path, tmp_path / "state", "abstain", tmp_path / "control")

    assert report["invalid_pairs"] == 0
    assert report["usable_pairs"] == 1
    assert report["quality"]["baseline_correct"] == 0
    assert report["quality"]["candidate_correct"] == 0
    assert report["attempt_statuses"] == {"completed": 2}


@pytest.mark.parametrize(
    "mode,code",
    [
        ("permanent", "authentication_failed"),
        ("malformed", "malformed_output"),
        ("missing", "missing_output"),
    ],
)
def test_permanent_or_exhausted_transport_is_invalid_not_quality(
    tmp_path: Path, mode: str, code: str
) -> None:
    pack_value = _pack(retry_input=0, retry_output=0)
    pack_path = _write_pack(tmp_path, pack_value)
    state, control = tmp_path / "state", tmp_path / "control"

    report = _run(pack_path, state, mode, control)

    assert report["usable_pairs"] == 0
    assert report["invalid_pairs"] == 1
    assert report["quality"] is None
    assert report["decision_status"] == "complete"
    assert report["usage"]["cost_usd_total"] is None
    assert report["usage"]["cost_unknown_attempts"] == 2
    assert all(row["error"]["code"] == code for row in _attempts(state))


def test_exact_pair_budget_and_cannot_start_pair(tmp_path: Path) -> None:
    exact = _pack(total_input=400, total_output=80)
    pack_path = _write_pack(tmp_path / "exact", exact)
    report = _run(pack_path, tmp_path / "exact-state", "normal", tmp_path / "exact-control")
    assert report["usable_pairs"] == 1

    short = _pack(total_input=399, total_output=80)
    short_path = _write_pack(tmp_path / "short", short)
    short_state = tmp_path / "short-state"
    stopped = _run(short_path, short_state, "normal", tmp_path / "short-control")
    assert stopped["cannot_start_pairs"] == 1
    assert stopped["attempt_count"] == 0
    assert stopped["quality"] is None


def test_output_overrun_is_terminal_and_reported(tmp_path: Path) -> None:
    pack_path = _write_pack(tmp_path, _pack())
    state = tmp_path / "state"

    report = _run(pack_path, state, "usage_over", tmp_path / "control")

    assert report["quality"] is None
    assert all(row["status"] == "permanent_failure" for row in _attempts(state))
    assert all(row["error"]["code"] == "usage_exceeds_reservation" for row in _attempts(state))
    assert report["usage"]["charged_output_tokens"] == 42


def test_resume_rejects_changed_config_sources_cases_or_gold(tmp_path: Path) -> None:
    original = _pack()
    pack_path = _write_pack(tmp_path, original)
    state, control = tmp_path / "state", tmp_path / "control"
    _run(pack_path, state, "normal", control)

    changes = []
    changed = deepcopy(original)
    changed["config"]["max_expansions"] = 3
    changes.append(changed)
    changed = deepcopy(original)
    changed["sources"][0]["content"] += " changed"
    changes.append(changed)
    changed = deepcopy(original)
    changed["cases"][0]["query"] += " changed"
    changes.append(changed)
    changed = deepcopy(original)
    changed["gold"]["case-1"]["required_substring"] = "changed"
    changes.append(changed)

    for value in changes:
        _write_pack(tmp_path, value)
        with pytest.raises(PackError, match="incompatible resume"):
            _run(pack_path, state, "normal", control)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda value: value.__setitem__("schema_version", 2), "schema_version"),
        (lambda value: value["config"].__setitem__("max_attempts", 0), "max_attempts"),
        (lambda value: value["config"].__setitem__("max_attempts", True), "max_attempts"),
        (lambda value: value["config"].__setitem__("max_attempts", 11), "max_attempts"),
        (lambda value: value["config"].__setitem__("total_input_tokens", -1), "total_input_tokens"),
        (lambda value: value["config"].__setitem__("attempt_output_tokens", "20"), "attempt_output_tokens"),
        (lambda value: value["sources"][0].__setitem__("metadata", []), "metadata"),
        (lambda value: value["gold"].__setitem__("extra", {}), "gold keys"),
    ],
)
def test_pack_validation_rejects_invalid_types_and_bounds(mutate, match: str) -> None:
    value = _pack()
    mutate(value)
    with pytest.raises(PackError, match=match):
        validate_pack(value)


def test_real_process_interruption_records_indeterminate_and_restores_lineage(
    tmp_path: Path,
) -> None:
    pack_path = _write_pack(tmp_path, _pack())
    state, control = tmp_path / "state", tmp_path / "control"
    command = [
        PYTHON,
        "-m",
        "evals.reliable_pair_runner",
        "--pack",
        str(pack_path),
        "--run-dir",
        str(state),
        "--driver",
        *_driver("indeterminate_once", control),
    ]
    process = subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 15
    while not (control / "blocked").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert (control / "blocked").exists(), process.stderr.read().decode("utf-8", errors="replace")
    process.terminate()
    process.wait(timeout=10)

    first = json.loads(
        (state / "attempts" / "case-1" / "baseline" / "attempt-001.json").read_text(
            encoding="utf-8"
        )
    )
    assert first["status"] == "started"
    assert first["transcript"][0]["direction"] == "to_driver"
    assert first["transcript"][0]["message"]["type"] == "search"

    resumed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        check=True,
        timeout=30,
    )
    report = json.loads(resumed.stdout.decode("utf-8", errors="strict"))
    recovered = _attempts(state)

    assert report["usable_pairs"] == 1
    assert recovered[0]["status"] == "indeterminate"
    assert recovered[0]["error"]["code"] == "crash_after_dispatch_unknown"
    assert recovered[0]["charged_usage"] == {"input_tokens": 100, "output_tokens": 20}
    assert (control / "external_execution.log").read_text(encoding="utf-8").splitlines() == [
        "case-1:baseline",
        "case-1:baseline",
        "case-1:candidate",
    ]
    search = json.loads(
        (state / "steps" / "case-1" / "baseline" / "search.json").read_text(
            encoding="utf-8"
        )
    )
    expansion = json.loads(
        next((state / "steps" / "case-1" / "baseline").glob("expand-*.json")).read_text(
            encoding="utf-8"
        )
    )
    assert expansion["parent_lookup_id"] == search["lookup_event_id"]


def _pilot(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    pack_path = _write_pack(output, _pack())
    report = _run(pack_path, output / "state", "normal", output / "control")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["usable_pairs"] == 1 else 1


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", nargs=2, metavar=("MODE", "CONTROL"))
    parser.add_argument("--pilot", type=Path)
    args = parser.parse_args()
    if args.driver:
        return _driver_main(args.driver[0], Path(args.driver[1]))
    if args.pilot:
        return _pilot(args.pilot)
    parser.error("use --driver or --pilot")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
