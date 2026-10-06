"""Caller-contract tests: synthetic native files -> CLI -> reopened export."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "evals" / "history_episode_export.py"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False) + "\r\n").encode("utf-8")


def fixture(tmp_path, source_format="codex"):
    """Two pages, repaired query, failed call, chained expansion and Unicode."""
    def message(role, text):
        if source_format == "codex":
            return {"type": "response_item", "payload": {"type": "message", "role": role,
                    "content": [{"type": "input_text", "text": text}]}}
        return {"type": role, "uuid": f"{role}-{text}",
                "message": {"role": role, "content": text}}

    records = [message("system", "system – שלום"), message("developer", "context 😀"),
               message("user", "Find earlier evidence"), message("assistant", "Looking")]
    choices, texts = [], []

    def call(identity, kind, arguments, output):
        text = json.dumps(output, ensure_ascii=False, indent=2)
        texts.append(text)
        choices.append({"call_id": identity, "kind": kind})
        if source_format == "codex":
            records.extend([
                {"type": "response_item", "payload": {"type": "function_call", "call_id": identity,
                 "name": "history_" + kind, "arguments": json.dumps(arguments)}},
                {"type": "response_item", "payload": {"type": "function_call_output", "call_id": identity,
                 "output": text}}])
        else:
            records.extend([
                {"type": "assistant", "uuid": identity + "-call", "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": identity, "name": "history_" + kind, "input": arguments}]}},
                {"type": "user", "uuid": identity + "-result", "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": identity, "content": [{"type": "text", "text": text}]}]}}])

    content = "  exact\nשלום 😀  "
    item = {"source_item_id": "source-α", "excerpt": content}
    revision = "a" * 64
    call("search-1", "search", {"query": "first", "result_offset": 0},
         {"lookup_event_id": "lookup-1", "results": [item], "next_offset": 1,
          "result_offset": 0, "result_revision": revision, "has_more": True, "total_count": 2})
    call("search-2", "search", {"query": "first", "result_offset": 1, "result_revision": revision},
         {"lookup_event_id": "lookup-2", "results": [item], "next_offset": None,
          "result_offset": 1, "result_revision": revision, "has_more": False, "total_count": 2})
    call("repair", "search", {"query": "repaired"},
         {"lookup_event_id": "lookup-3", "results": [item], "next_offset": None,
          "result_offset": 0, "result_revision": "b" * 64, "has_more": False, "total_count": 1})
    call("failed", "search", {"query": "retry"}, {"error": "bounded failure"})
    for index, offset in enumerate((0, 5, 10), start=1):
        end = min(offset + 5, len(content)) if index < 3 else len(content)
        arguments = {"source_item_id": "source-α", "parent_lookup_id": "lookup-3", "content_offset": offset}
        if offset:
            arguments["content_revision"] = "sha256:" + sha(content.encode())
        call(f"expand-{index}", "expansion", arguments,
             {"parent_lookup_id": "lookup-3", "items": [{"source_item_id": "source-α", "is_anchor": True,
              "content": content[offset:end]}], "next_offset": end if end < len(content) else None,
              "content_offset": offset, "content_revision": "sha256:" + sha(content.encode()),
              "has_more": end < len(content), "content_total_chars": len(content)})
    records.append(message("assistant", "Answer cites source-α"))
    records.append(message("user", "UNSELECTED must not be copied"))
    transcript, selection_path = tmp_path / "synthetic.jsonl", tmp_path / "selection.json"
    lines = list(map(json_bytes, records))
    transcript.write_bytes(b"".join(lines))
    def ref(index):
        return {"record_index": index, "sha256": sha(lines[index])}
    selection = {"version": 1, "source_format": source_format, "synthetic": True,
                 "designation": "development", "prior_inspection": "declared",
                 "request": ref(2), "answer": ref(len(records) - 2),
                 "context": [ref(0), ref(1), ref(3)], "calls": choices}
    selection_path.write_bytes(json_bytes(selection))
    return transcript, selection_path, tmp_path / "episode", records, selection, texts


def run(case, *extra, synthetic=True):
    transcript, selection_path, destination = case[:3]
    return subprocess.run([sys.executable, str(CLI), "--transcript", str(transcript),
                           "--selection", str(selection_path), "--destination", str(destination),
                           *(["--synthetic"] if synthetic else []), *map(str, extra)],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20)


def rewrite(case):
    transcript, selection_path, _, records, selection, _ = case
    lines = list(map(json_bytes, records))
    transcript.write_bytes(b"".join(lines))
    for ref in [selection["request"], selection["answer"], *selection["context"]]:
        index = ref["record_index"]
        if 0 <= index < len(lines):
            ref["sha256"] = sha(lines[index])
    selection_path.write_bytes(json_bytes(selection))


@pytest.mark.parametrize("source_format", ["codex", "claude"])
def test_native_cli_journey_and_restart(tmp_path, source_format):
    case = fixture(tmp_path, source_format)
    frozen = tmp_path / "pack.json"
    frozen.write_bytes(b'{"frozen":"exact"}\r\n')
    result = run(case, "--frozen-artifact", frozen)
    assert result.returncode == 0, result.stderr
    destination = case[2]
    raw = (destination / "records.jsonl").read_bytes()
    manifest = json.loads((destination / "manifest.json").read_bytes())
    original = case[0].read_bytes().splitlines(keepends=True)
    assert b"UNSELECTED" not in raw
    assert (destination / "frozen-000.bin").read_bytes() == frozen.read_bytes()
    indexed = {}
    for record in manifest["records"]:
        piece = raw[record["offset"]:record["offset"] + record["bytes"]]
        assert piece == original[record["record_index"]]
        assert sha(piece) == record["sha256"]
        indexed[record["record_index"]] = json.loads(piece)
    for call, expected in zip(manifest["calls"], case[5], strict=True):
        record = indexed[call["result_record_index"]]
        text = record["payload"]["output"] if source_format == "codex" else record["message"]["content"][call["result_block_index"]]["content"][0]["text"]
        assert text == expected
        assert sha(text.encode("utf-8")) == call["tool_text_sha256"]
    assert [call["call_id"] for call in manifest["calls"]] == [choice["call_id"] for choice in case[4]["calls"]]
    assert manifest["calls"][3]["observed_error"] is True
    assert manifest["calls"][-1]["lineage"] == "validated_recorded_links"
    assert manifest["readiness"]["caller_context"] == "incomplete"
    assert manifest["readiness"]["historical_replay"] is False
    assert manifest["readiness"]["downstream_task_effect"] is False
    second = run(case, "--frozen-artifact", frozen)
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == "verified existing export"
    assert (destination / "records.jsonl").read_bytes() == raw


@pytest.mark.parametrize("damage", ["missing_call", "duplicate_call", "duplicate_result", "missing_result",
                                   "call_order", "context_order", "missing_context", "parent", "revision",
                                   "source", "bad_arguments", "unsupported_output", "role", "flag",
                                   "duplicate_lookup", "duplicate_source", "format", "designation"])
def test_invalid_selection_or_native_links_fail_closed(tmp_path, damage):
    case = fixture(tmp_path)
    records, selection = case[3:5]
    if damage == "missing_call":
        selection["calls"][0]["call_id"] = "absent"
    elif damage == "duplicate_call":
        records[6]["payload"]["call_id"] = "search-1"
    elif damage == "duplicate_result":
        records[7]["payload"]["call_id"] = "search-1"
    elif damage == "missing_result":
        records[5]["payload"]["type"] = "unsupported"
    elif damage == "call_order":
        selection["calls"][:2] = reversed(selection["calls"][:2])
    elif damage == "context_order":
        selection["context"].reverse()
    elif damage == "missing_context":
        selection["context"][0]["record_index"] = 999
    elif damage in {"parent", "revision", "source", "duplicate_lookup", "duplicate_source"}:
        index = 15 if damage == "revision" else 13 if damage in {"parent", "source"} else 7
        payload = json.loads(records[index]["payload"]["output"])
        if damage == "parent":
            payload["parent_lookup_id"] = "absent"
        elif damage == "revision":
            payload["content_revision"] = "rev-stale"
        elif damage == "source":
            args = json.loads(records[12]["payload"]["arguments"])
            args["source_item_id"] = "absent"
            records[12]["payload"]["arguments"] = json.dumps(args)
        elif damage == "duplicate_lookup":
            payload["lookup_event_id"] = "lookup-1"
        else:
            payload["results"].append(payload["results"][0])
        records[index]["payload"]["output"] = json.dumps(payload)
    elif damage == "bad_arguments":
        records[4]["payload"]["arguments"] = "{"
    elif damage == "unsupported_output":
        records[5]["payload"]["output"] = {"text": "would be lossy"}
    elif damage == "role":
        records[2]["payload"]["role"] = "assistant"
    elif damage == "flag":
        selection["context_complete"] = True
    elif damage == "format":
        selection["source_format"] = "unknown"
    else:
        selection["designation"] = "held-out-proof"
    rewrite(case)
    result = run(case)
    assert result.returncode == 2, result.stdout
    assert not case[2].exists()


@pytest.mark.parametrize("damage", ["truncated", "malformed", "duplicate_key", "empty", "record_hash"])
def test_invalid_bytes_and_revision_rejected(tmp_path, damage):
    case = fixture(tmp_path)
    if damage == "truncated":
        case[0].write_bytes(case[0].read_bytes().rstrip())
    elif damage == "malformed":
        case[0].write_bytes(b"{broken}\n")
    elif damage == "duplicate_key":
        case[0].write_bytes(b'{"type":"one","type":"two"}\n')
    elif damage == "empty":
        case[0].write_bytes(b"")
    else:
        case[4]["request"]["sha256"] = "0" * 64
        case[1].write_bytes(json_bytes(case[4]))
    assert run(case).returncode == 2
    assert not case[2].exists()


@pytest.mark.parametrize("damage", ["input", "output", "manifest", "extra", "frozen"])
def test_repeat_checks_input_and_every_output(tmp_path, damage):
    case = fixture(tmp_path)
    frozen = tmp_path / "pack.bin"
    frozen.write_bytes(b"frozen")
    result = run(case, "--frozen-artifact", frozen)
    assert result.returncode == 0, result.stderr
    if damage == "input":
        case[0].write_bytes(case[0].read_bytes() + json_bytes({"unselected": "mutation"}))
    else:
        name = {"output": "records.jsonl", "manifest": "manifest.json", "extra": "extra", "frozen": "frozen-000.bin"}[damage]
        (case[2] / name).write_bytes(b"corrupt")
    before = {path.name: path.read_bytes() for path in case[2].iterdir()}
    assert run(case, "--frozen-artifact", frozen).returncode == 2
    assert {path.name: path.read_bytes() for path in case[2].iterdir()} == before


def test_size_boundaries(tmp_path):
    case = fixture(tmp_path)
    size = max(case[0].stat().st_size, case[1].stat().st_size)
    count = len(case[3])
    assert run(case, "--max-input-bytes", size - 1).returncode == 2
    assert run(case, "--max-records", count - 1).returncode == 2
    assert run(case, "--max-input-bytes", size, "--max-records", count).returncode == 0
    total = sum(path.stat().st_size for path in case[2].iterdir())
    assert run(case, "--max-output-bytes", total).returncode == 0
    assert run(case, "--max-output-bytes", total - 1).returncode == 2
    assert run(case, "--max-records", 0).returncode == 2


def test_synthetic_declarations_and_no_destination_fallback(tmp_path):
    case = fixture(tmp_path)
    assert run(case, synthetic=False).returncode == 2
    case[4]["synthetic"] = False
    rewrite(case)
    assert run(case).returncode == 2
    assert not case[2].exists()


@pytest.mark.parametrize("directory", ["data", ".pallium", ".codex/sessions", ".claude/projects"])
def test_live_directories_rejected(tmp_path, directory):
    parent = tmp_path / directory
    parent.mkdir(parents=True)
    case = fixture(parent)
    assert run(case).returncode == 2
    assert not case[2].exists()


def test_destination_input_overlap_and_existing_empty_directory(tmp_path):
    case = list(fixture(tmp_path))
    case[2] = case[0]
    assert run(case).returncode == 2
    case[2] = tmp_path / "empty"
    case[2].mkdir()
    assert run(case).returncode == 2
    assert list(case[2].iterdir()) == []


def test_plain_tool_text_preserved_without_invented_lineage(tmp_path):
    case = fixture(tmp_path)
    case[3][5]["payload"]["output"] = "  Unicode שלום\nexact  "
    # Its descendants cannot claim validated ancestry from an unparsed response.
    case[4]["calls"] = case[4]["calls"][:1]
    rewrite(case)
    assert run(case).returncode == 0
    manifest = json.loads((case[2] / "manifest.json").read_bytes())
    assert manifest["calls"][0]["lineage"] == "unavailable"
    assert manifest["calls"][0]["tool_text_sha256"] == sha("  Unicode שלום\nexact  ".encode())


@pytest.mark.parametrize("damage", ["search_revision", "search_offset", "expansion_offset", "page_boundary"])
def test_continuation_revision_and_offsets(tmp_path, damage):
    case = fixture(tmp_path)
    index = 6 if damage.startswith("search") else 14
    if damage == "page_boundary":
        payload = json.loads(case[3][7]["payload"]["output"])
        payload["total_count"] = 99
        case[3][7]["payload"]["output"] = json.dumps(payload)
    else:
        arguments = json.loads(case[3][index]["payload"]["arguments"])
        key = "result_revision" if damage == "search_revision" else "result_offset" if damage == "search_offset" else "content_offset"
        arguments[key] = "stale" if damage == "search_revision" else 99
        case[3][index]["payload"]["arguments"] = json.dumps(arguments)
    rewrite(case)
    assert run(case).returncode == 2


def test_native_mcp_text_envelope_hashes_outer_string(tmp_path):
    case = fixture(tmp_path)
    text = case[3][5]["payload"]["output"]
    outer = json.dumps({"content": [{"type": "text", "text": text}]}, ensure_ascii=False)
    case[3][5]["payload"]["output"] = outer
    rewrite(case)
    assert run(case).returncode == 0
    manifest = json.loads((case[2] / "manifest.json").read_bytes())
    assert manifest["calls"][0]["tool_text_sha256"] == sha(outer.encode())
    assert manifest["calls"][0]["lineage"] == "validated_recorded_links"


def test_failed_atomic_write_leaves_no_published_export(tmp_path):
    case = fixture(tmp_path)
    command = [sys.executable, "-c",
               "import os, runpy; os.fsync=lambda fd: (_ for _ in ()).throw(OSError('injected write failure')); "
               f"runpy.run_path({str(CLI)!r}, run_name='__main__')",
               "--transcript", str(case[0]), "--selection", str(case[1]),
               "--destination", str(case[2]), "--synthetic"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 2
    assert not case[2].exists()
    assert not list(tmp_path.glob(".history-episode-*"))
    assert run(case).returncode == 0


def test_reuse_rejects_symlink_output(tmp_path):
    case = fixture(tmp_path)
    assert run(case).returncode == 0
    outside = tmp_path / "outside.bin"
    original = (case[2] / "records.jsonl").read_bytes()
    outside.write_bytes(original)
    output = case[2] / "records.jsonl"
    output.unlink()
    try:
        output.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"host cannot create symlink: {exc}")
    assert run(case).returncode == 2
    assert outside.read_bytes() == original


@pytest.mark.parametrize("shape", ["missing_anchor", "empty_content"])
def test_expansion_requires_anchor_but_accepts_empty_content(tmp_path, shape):
    case = fixture(tmp_path)
    case[4]["calls"] = [*case[4]["calls"][:3], case[4]["calls"][4]]
    payload = json.loads(case[3][13]["payload"]["output"])
    if shape == "missing_anchor":
        payload = {"parent_lookup_id": "lookup-3", "items": []}
    else:
        payload["items"][0]["content"] = ""
        payload["content_total_chars"] = 0
        payload["has_more"] = False
        payload["next_offset"] = None
    case[3][13]["payload"]["output"] = json.dumps(payload)
    rewrite(case)
    result = run(case)
    assert result.returncode == (2 if shape == "missing_anchor" else 0), result.stderr


def test_public_formatter_outputs_through_cli(tmp_path):
    from app.mcp.server import _bounded_expansion
    from core.history_presentation import compact_history

    case = fixture(tmp_path)
    search = compact_history({"results": [{"source_item_id": "source-α", "excerpt": "שלום 😀"}],
                              "lookup_event_id": "lookup-1"}, "first")
    expansion = _bounded_expansion({"parent_lookup_id": "lookup-1", "items": [
        {"source_item_id": "source-α", "is_anchor": True, "content": "שלום 😀"}]})
    assert "lookup_event_id" not in expansion
    case[3][5]["payload"]["output"] = json.dumps(search, ensure_ascii=False)
    arguments = json.loads(case[3][12]["payload"]["arguments"])
    arguments["parent_lookup_id"] = "lookup-1"
    case[3][12]["payload"]["arguments"] = json.dumps(arguments)
    case[3][13]["payload"]["output"] = json.dumps(expansion, ensure_ascii=False)
    case[4]["calls"] = [case[4]["calls"][0], case[4]["calls"][4]]
    rewrite(case)
    result = run(case)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((case[2] / "manifest.json").read_bytes())
    assert all(call["lineage"] == "validated_recorded_links" for call in manifest["calls"])


@pytest.mark.parametrize("failure", ["manifest_write", "manifest_publish", "competing_directory", "unexpected_file"])
def test_publication_reservation_and_failure_cleanup(tmp_path, failure):
    case = fixture(tmp_path)
    destination = str(case[2])
    setup = "import os, runpy; from pathlib import Path\n"
    if failure == "competing_directory":
        setup += ("original=Path.mkdir\n"
                  "def competing(path,*a,**kw):\n"
                  f" if str(path)=={destination!r}: original(path); (path/'winner').write_bytes(b'winner')\n"
                  " return original(path,*a,**kw)\n"
                  "Path.mkdir=competing\n")
    elif failure == "manifest_publish":
        setup += "os.link=lambda *a,**kw: (_ for _ in ()).throw(OSError('commit failed'))\n"
    else:
        setup += "calls=0\noriginal=os.fsync\ndef failing(fd):\n global calls\n calls+=1\n"
        if failure == "unexpected_file":
            setup += f" (Path({destination!r})/'unexpected').write_bytes(b'other writer')\n raise OSError('write failed')\n"
        else:
            setup += " if calls==2: raise OSError('manifest write failed')\n return original(fd)\n"
        setup += "os.fsync=failing\n"
    setup += f"runpy.run_path({str(CLI)!r},run_name='__main__')\n"
    result = subprocess.run([sys.executable, "-c", setup, "--transcript", str(case[0]),
                             "--selection", str(case[1]), "--destination", destination, "--synthetic"],
                            cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 2, result.stderr
    if failure in {"manifest_write", "manifest_publish"}:
        assert not case[2].exists()
    elif failure == "competing_directory":
        assert {path.name for path in case[2].iterdir()} == {"winner"}
        assert (case[2] / "winner").read_bytes() == b"winner"
    else:
        assert {path.name for path in case[2].iterdir()} == {"unexpected"}
        assert (case[2] / "unexpected").read_bytes() == b"other writer"
    if case[2].exists():
        assert run(case).returncode == 2


def wrapper_fixture(tmp_path):
    case = fixture(tmp_path)
    case[3][4]["payload"] = {"type": "custom_tool_call", "call_id": "exec-wrapper",
                            "name": "exec", "input": "unparsed JavaScript שלום 😀 { invalid"}
    case[3][5]["payload"] = {"type": "custom_tool_call_output", "call_id": "exec-wrapper", "output": [
        {"type": "input_text", "text": "Script running with cell ID synthetic-cell\n"},
        {"type": "input_text", "text": '{"lookup_event_id":"opaque-α","results":[]}'}]}
    case[3][6]["payload"] = {"type": "function_call", "call_id": "wait-wrapper", "name": "wait",
                            "arguments": '{"cell_id":"synthetic-cell"}'}
    case[3][7]["payload"] = {"type": "function_call_output", "call_id": "wait-wrapper", "output": [
        {"type": "input_text", "text": "Script completed\nOutput:\nשלום 😀  "},
        {"type": "input_text", "text": '{"parent_lookup_id":"opaque-α","items":[]}'}]}
    case[4]["calls"] = [{"call_id": "exec-wrapper", "kind": "other"},
                        {"call_id": "wait-wrapper", "kind": "other"}]
    rewrite(case)
    return case


def test_native_exec_wait_wrappers_preserve_blocks_and_restart(tmp_path):
    case = wrapper_fixture(tmp_path)
    result = run(case)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((case[2] / "manifest.json").read_bytes())
    raw = (case[2] / "records.jsonl").read_bytes()
    for metadata in manifest["records"]:
        exact = raw[metadata["offset"]:metadata["offset"] + metadata["bytes"]]
        assert exact == case[0].read_bytes().splitlines(keepends=True)[metadata["record_index"]]
    for call in manifest["calls"]:
        original = case[3][call["result_record_index"]]["payload"]["output"]
        assert call["lineage"] == call["inner_history_lineage"] == "unavailable"
        assert "tool_text_sha256" not in call  # No invented flattened native string.
        for index, block in enumerate(call["tool_text_blocks"]):
            text = original[index]["text"].encode("utf-8")
            assert block == {"pointer": f"output/{index}/text", "sha256": sha(text), "bytes": len(text)}
    assert manifest["calls"][0]["input_encoding"] == "opaque_native_input"
    assert run(case).stdout.strip() == "verified existing export"


@pytest.mark.parametrize("damage", ["missing", "mismatch", "duplicate_call", "duplicate_result",
                                   "type_mismatch", "search_claim", "expansion_claim", "nonstring_input",
                                   "unsupported_block"])
def test_native_wrapper_invalid_identity_or_claim_rejected(tmp_path, damage):
    case = wrapper_fixture(tmp_path)
    if damage == "missing":
        case[3][5]["payload"].pop("call_id")
    elif damage == "mismatch":
        case[3][5]["payload"]["call_id"] = "different"
    elif damage == "duplicate_call":
        case[3][6]["payload"]["call_id"] = "exec-wrapper"
    elif damage == "duplicate_result":
        case[3][7]["payload"]["call_id"] = "exec-wrapper"
    elif damage == "type_mismatch":
        case[3][5]["payload"]["type"] = "function_call_output"
    elif damage in {"search_claim", "expansion_claim"}:
        case[4]["calls"][0 if damage == "search_claim" else 1]["kind"] = damage.split("_")[0]
    elif damage == "nonstring_input":
        case[3][4]["payload"]["input"] = {"cannot": "interpret"}
    else:
        case[3][7]["payload"]["output"][0]["type"] = "unknown"
    rewrite(case)
    result = run(case)
    assert result.returncode == 2, result.stderr
    assert not case[2].exists()


@pytest.mark.parametrize("output", [[], "", [{"type": "input_text", "text": ""}]])
def test_empty_native_wrapper_inputs_and_outputs(tmp_path, output):
    case = wrapper_fixture(tmp_path)
    case[3][4]["payload"]["input"] = ""
    case[3][5]["payload"]["output"] = output
    rewrite(case)
    result = run(case)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((case[2] / "manifest.json").read_bytes())
    blocks = manifest["calls"][0]["tool_text_blocks"]
    assert blocks == [] if output == [] else blocks[0]["bytes"] == 0


def test_native_wrapper_input_output_byte_boundaries(tmp_path):
    case = wrapper_fixture(tmp_path)
    maximum = max(case[0].stat().st_size, case[1].stat().st_size)
    assert run(case, "--max-input-bytes", maximum - 1).returncode == 2
    result = run(case, "--max-input-bytes", maximum)
    assert result.returncode == 0, result.stderr
    total = sum(path.stat().st_size for path in case[2].iterdir())
    assert run(case, "--max-output-bytes", total).returncode == 0
    assert run(case, "--max-output-bytes", total - 1).returncode == 2


@pytest.mark.parametrize("name", ["wait", "functions.wait"])
@pytest.mark.parametrize("kind", ["search", "expansion"])
def test_wait_string_cannot_claim_inner_history_lineage(tmp_path, name, kind):
    case = wrapper_fixture(tmp_path)
    case[3][6]["payload"]["name"] = name
    case[3][7]["payload"]["output"] = '{"lookup_event_id":"opaque","results":[]}'
    case[4]["calls"][1]["kind"] = kind
    rewrite(case)
    result = run(case)
    assert result.returncode == 2
    assert "require kind=other" in result.stderr
    assert not case[2].exists()
