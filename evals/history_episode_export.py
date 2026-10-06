"""Export explicitly selected synthetic native transcript records, without replay.

CLI: python -m evals.history_episode_export --transcript FILE --selection FILE
     --destination NEW_DIRECTORY --synthetic [--frozen-artifact FILE ...]

Selection v1 contains source_format (codex/claude), synthetic=true, designation
(development/confirmation), prior_inspection (declared/not_declared), request,
answer, context (ordered list), and calls (ordered {call_id, kind} objects).
Record references are {record_index: zero-based JSONL line, sha256: raw-line hash}.
Call kinds are search/expansion/other; JSON history responses are validated when
available. Strings and arguments remain in records.jsonl, never duplicated in
the index. Declarations are audit information, not proof of data provenance.
Codex exec/wait wrappers are other-only: custom inputs are opaque and native
input_text output blocks are hashed individually, with inner lineage unavailable.
Selection copies whole raw records, including every block in a selected record.
Private transcripts, live source directories and full-context claims are outside
this slice. An export is not supported input to reliable_pair_runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

VERSION = 1
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_RECORDS = 10000


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def fail(message: str) -> None:
    raise ValueError(message)


def safe_path(value: str | Path) -> Path:
    path = Path(os.path.abspath(value))
    for component in (path, *path.parents):
        if component.is_symlink() or component.is_junction():
            fail("symlink/junction paths are unsupported")
    parts = [part.lower() for part in path.parts]
    if any(part in {"data", ".pallium"} for part in parts):
        fail("service data directories are outside synthetic scope")
    if any(a == ".codex" and b in {"sessions", "archived_sessions"}
           or a == ".claude" and b == "projects"
           for a, b in zip(parts, parts[1:])):
        fail("native live transcript directories are outside synthetic scope")
    return path


def read_bounded(path: Path, limit: int) -> bytes:
    path = safe_path(path)
    if not path.is_file():
        fail("input must be an explicitly named regular file")
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        fail("input exceeds byte limit")
    return value


def unique_object(pairs: list) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            fail("duplicate JSON key")
        value[key] = item
    return value


def decode(raw: bytes | str):
    return json.loads(raw, object_pairs_hook=unique_object,
                      parse_constant=lambda _: fail("non-finite JSON value"))


def require_keys(value: object, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        fail(f"invalid {label} fields")
    return value


def native_parts(record: dict, source_format: str) -> list[tuple[int | None, dict]]:
    if source_format == "codex":
        payload = record.get("payload")
        return [(None, payload)] if record.get("type") == "response_item" and isinstance(payload, dict) else []
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    return [(index, block) for index, block in enumerate(content)
            if isinstance(block, dict)] if isinstance(content, list) else []


def message_role(record: dict, source_format: str) -> str | None:
    key = "payload" if source_format == "codex" else "message"
    message = record.get(key)
    return message.get("role") if isinstance(message, dict) else None


def validate_page(payload: dict, arguments: dict, kind: str, pages: dict,
                  expansions: dict, lookup_ids: dict) -> None:
    if kind == "search":
        lookup = payload.get("lookup_event_id")
        if not isinstance(lookup, str) or not lookup or lookup in lookup_ids:
            fail("missing/duplicate lookup identity")
        items = payload.get("results")
    else:
        parent, source = arguments.get("parent_lookup_id"), arguments.get("source_item_id")
        if not isinstance(parent, str) or parent not in lookup_ids or payload.get("parent_lookup_id") != parent:
            fail("expansion parent mismatch")
        if source not in lookup_ids[parent]:
            fail("expanded source absent from parent search page")
        items = payload.get("items")
    if not isinstance(items, list):
        fail("missing history source list")
    sources = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("source_item_id"), str) or not item["source_item_id"] or item["source_item_id"] in sources:
            fail("missing/duplicate source identity")
        sources.add(item["source_item_id"])
    if kind == "search":
        lookup_ids[lookup] = sources
        offset_key, revision_key = "result_offset", "result_revision"
        key = encoded({name: value for name, value in arguments.items()
                       if name not in {offset_key, revision_key}})
        prior = pages.get(key)
    else:
        offset_key, revision_key = "content_offset", "content_revision"
        key = (parent, source)
        prior = expansions.get(key)
    offset = arguments.get(offset_key, 0)
    if type(offset) is not int or offset < 0:
        fail("invalid page offset")
    if kind == "search" and not items and offset == 0 and revision_key not in payload:
        return  # Native empty-page shape has no revision metadata.
    revision = payload.get(revision_key)
    if not isinstance(revision, str) or not revision or payload.get(offset_key) != offset:
        fail("missing page revision or offset mismatch")
    requested_revision = arguments.get(revision_key)
    if requested_revision is not None and requested_revision != revision:
        fail("stale requested page revision")
    if offset and (not prior or prior != (revision, offset) or requested_revision != revision):
        fail("missing or stale continuation page")
    next_offset = payload.get("next_offset")
    if (next_offset is not None and (type(next_offset) is not int or next_offset <= offset)) or payload.get("has_more") is not (next_offset is not None):
        fail("invalid page continuation metadata")
    if kind == "search":
        total = payload.get("total_count")
        end = offset + len(items)
        if type(total) is not int or total < end or next_offset != (end if end < total else None):
            fail("search page boundary mismatch")
        pages[key] = (revision, next_offset)
    else:
        anchors = [item for item in items if item.get("is_anchor") is True]
        if len(anchors) != 1 or anchors[0]["source_item_id"] != source or not isinstance(anchors[0].get("content"), str):
            fail("missing/ambiguous expansion anchor")
        total = payload.get("content_total_chars")
        end = offset + len(anchors[0]["content"])
        if type(total) is not int or total < end or next_offset != (end if end < total else None):
            fail("expansion page boundary mismatch")
        expansions[key] = (revision, next_offset)


def export(args: argparse.Namespace) -> str:
    if not args.synthetic:
        fail("explicit --synthetic declaration required; private export unsupported")
    for limit, ceiling in ((args.max_input_bytes, MAX_INPUT_BYTES),
                           (args.max_output_bytes, MAX_OUTPUT_BYTES),
                           (args.max_records, MAX_RECORDS)):
        if not 1 <= limit <= ceiling:
            fail("limits must be positive and at most the fixed ceiling")
    transcript, selection_path, destination = map(safe_path, (
        args.transcript, args.selection, args.destination))
    input_paths = [transcript, selection_path, *map(safe_path, args.frozen_artifact)]
    if len(set(input_paths)) != len(input_paths):
        fail("duplicate input paths")
    if not destination.parent.is_dir() or any(
            destination == path or destination in path.parents for path in input_paths):
        fail("destination must have an existing parent and contain no inputs")
    blobs = [read_bounded(path, args.max_input_bytes) for path in input_paths]
    if sum(map(len, blobs)) > args.max_output_bytes:
        fail("total inputs exceed output budget")
    selection = require_keys(decode(blobs[1]), {
        "version", "source_format", "synthetic", "designation", "prior_inspection",
        "request", "answer", "context", "calls"}, "selection")
    if selection["version"] != VERSION or selection["synthetic"] is not True:
        fail("only version 1 synthetic selections are supported")
    source_format = selection["source_format"]
    if source_format not in {"codex", "claude"}:
        fail("unsupported source_format")
    if selection["designation"] not in {"development", "confirmation"} or selection["prior_inspection"] not in {"declared", "not_declared"}:
        fail("invalid inspection/designation declaration")
    if not isinstance(selection["context"], list) or not isinstance(selection["calls"], list):
        fail("context and calls must be lists")
    raw_lines = blobs[0].splitlines(keepends=True)
    if not raw_lines or len(raw_lines) > args.max_records:
        fail("empty transcript or record limit exceeded")
    records = []
    for raw in raw_lines:
        if not raw.endswith(b"\n"):
            fail("truncated JSONL: every record must end with a newline")
        record = decode(raw)
        if not isinstance(record, dict):
            fail("native record must be an object")
        records.append(record)
    selected = set()

    def reference(ref: object) -> int:
        ref = require_keys(ref, {"record_index", "sha256"}, "record reference")
        index = ref["record_index"]
        if type(index) is not int or not 0 <= index < len(records):
            fail("missing record identity")
        if digest(raw_lines[index]) != ref["sha256"]:
            fail("record revision/hash mismatch")
        selected.add(index)
        return index

    request, answer = reference(selection["request"]), reference(selection["answer"])
    context = [reference(ref) for ref in selection["context"]]
    if request >= answer or message_role(records[request], source_format) != "user" or message_role(records[answer], source_format) != "assistant":
        fail("request/answer role or order mismatch")
    if context != sorted(set(context)) or request in context or answer in context or any(index >= answer for index in context):
        fail("duplicate or unordered context identity")
    calls, results = {}, {}
    for index, record in enumerate(records):
        for block_index, block in native_parts(record, source_format):
            kind = block.get("type")
            if kind in {"function_call", "custom_tool_call", "tool_use"}:
                identity = block.get("call_id") if source_format == "codex" else block.get("id")
                target = calls
            elif kind in {"function_call_output", "custom_tool_call_output", "tool_result"}:
                identity = block.get("call_id") if source_format == "codex" else block.get("tool_use_id")
                target = results
            else:
                continue
            if not isinstance(identity, str) or not identity or identity in target:
                fail("missing or duplicate native call identity")
            target[identity] = (index, block_index, block)
    call_index, lookup_ids, pages, expansions = [], {}, {}, {}
    last_position = (request, -1)
    for choice in selection["calls"]:
        choice = require_keys(choice, {"call_id", "kind"}, "call selection")
        identity, kind = choice["call_id"], choice["kind"]
        if not isinstance(identity, str) or identity not in calls or identity not in results:
            fail("missing selected call/result")
        if kind not in {"search", "expansion", "other"}:
            fail("invalid call kind")
        ci, cb, call = calls[identity]
        ri, rb, result = results[identity]
        position = (ci, cb if cb is not None else -1)
        if position <= last_position or not request < ci <= ri < answer or (ci == ri and (cb is None or rb is None or cb >= rb)):
            fail("call/result order mismatch")
        last_position = position
        selected.update((ci, ri))
        custom = source_format == "codex" and call.get("type") == "custom_tool_call"
        if source_format == "codex" and (result.get("type") == "custom_tool_call_output") != custom:
            fail("native call/result type mismatch")
        native_output = result.get("output") if source_format == "codex" else None
        wrapper = source_format == "codex" and (
            custom or call.get("name") in {"exec", "wait", "functions.exec", "functions.wait"}
            or isinstance(native_output, list) and (not native_output or any(
                isinstance(block, dict) and block.get("type") == "input_text"
                for block in native_output)))
        if wrapper:
            if kind != "other":
                fail("native wrappers require kind=other; inner History lineage unavailable")
            if custom:
                if not isinstance(call.get("input"), str):
                    fail("custom tool input must be an opaque string")
            else:
                arguments = call.get("arguments")
                if not isinstance(decode(arguments) if isinstance(arguments, str) else arguments, dict):
                    fail("unsupported/malformed tool arguments")
            blocks = []
            if isinstance(native_output, str):
                blocks.append({"pointer": "output", "sha256": digest(native_output.encode("utf-8")),
                               "bytes": len(native_output.encode("utf-8"))})
            elif isinstance(native_output, list):
                for index, block in enumerate(native_output):
                    if not isinstance(block, dict) or block.get("type") != "input_text" or not isinstance(block.get("text"), str):
                        fail("unsupported native wrapper output block")
                    raw_text = block["text"].encode("utf-8")
                    blocks.append({"pointer": f"output/{index}/text", "sha256": digest(raw_text),
                                   "bytes": len(raw_text)})
            else:
                fail("unsupported native wrapper output shape")
            call_index.append({"call_id": identity, "kind": kind,
                               "call_record_index": ci, "call_block_index": cb,
                               "result_record_index": ri, "result_block_index": rb,
                               "tool_text_blocks": blocks, "observed_error": result.get("is_error") is True,
                               "lineage": "unavailable", "inner_history_lineage": "unavailable",
                               "input_encoding": "opaque_native_input" if custom else "json_arguments"})
            continue
        arguments = call.get("arguments") if source_format == "codex" else call.get("input")
        parsed_args = decode(arguments) if isinstance(arguments, str) else arguments
        if not isinstance(parsed_args, dict):
            fail("unsupported/malformed tool arguments")
        text = result.get("output") if source_format == "codex" else result.get("content")
        text_pointer = "output" if source_format == "codex" else "content"
        if isinstance(text, list) and len(text) == 1 and isinstance(text[0], dict) and text[0].get("type") == "text":
            text = text[0].get("text")
            text_pointer += "/0/text"
        if not isinstance(text, str):
            fail("unsupported tool text shape; no lossy flattening")
        try:
            payload = decode(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and "content" in payload:
            blocks = payload["content"]
            if isinstance(blocks, list) and len(blocks) == 1 and isinstance(blocks[0], dict) and blocks[0].get("type") == "text" and isinstance(blocks[0].get("text"), str):
                try:
                    payload = decode(blocks[0]["text"])
                except json.JSONDecodeError:
                    payload = None
            else:
                payload = None
        lineage_status = "unavailable"
        is_error = result.get("is_error") is True or isinstance(payload, dict) and "error" in payload
        if kind in {"search", "expansion"} and isinstance(payload, dict) and not is_error:
            validate_page(payload, parsed_args, kind, pages, expansions, lookup_ids)
            lineage_status = "validated_recorded_links"
        call_index.append({"call_id": identity, "kind": kind,
                           "call_record_index": ci, "call_block_index": cb,
                           "result_record_index": ri, "result_block_index": rb,
                           "tool_text_pointer": text_pointer,
                           "tool_text_sha256": digest(text.encode("utf-8")),
                           "tool_text_bytes": len(text.encode("utf-8")),
                           "observed_error": is_error, "lineage": lineage_status})
    raw_output, record_index = bytearray(), []
    for index in sorted(selected):
        raw = raw_lines[index]
        record_index.append({"record_index": index, "offset": len(raw_output),
                             "bytes": len(raw), "sha256": digest(raw),
                             "native_id": records[index].get("uuid") if source_format == "claude" else (records[index]["payload"].get("id") if isinstance(records[index].get("payload"), dict) else None)})
        raw_output.extend(raw)
    files = {"records.jsonl": bytes(raw_output)}
    for index, blob in enumerate(blobs[2:]):
        files[f"frozen-{index:03d}.bin"] = blob
    manifest = {
        "version": VERSION, "parser_version": "native-lossless-v1",
        "source_format": source_format, "selection": selection,
        "inputs": [{"path": str(path), "sha256": digest(blob), "bytes": len(blob)}
                   for path, blob in zip(input_paths, blobs)],
        "records": record_index, "calls": call_index,
        "artifacts": {name: {"sha256": digest(blob), "bytes": len(blob)}
                      for name, blob in files.items()},
        "readiness": {"synthetic_declaration_is_proof": False,
                      "recorded_output_is_model_consumption": False,
                      "caller_context": "incomplete",
                      "context_gaps": ["full available system/developer/compaction context unverified"],
                      "historical_replay": False, "candidate_recovery": False,
                      "ranking": False, "downstream_task_effect": False,
                      "frozen_artifacts": "unvalidated" if blobs[2:] else "unavailable",
                      "runner_input": "unsupported"}}
    files["manifest.json"] = encoded(manifest)
    if sum(map(len, files.values())) > args.max_output_bytes:
        fail("export exceeds output byte limit")
    # Recheck named inputs before both publish and reuse; no source mutation is hidden.
    if any(read_bounded(path, args.max_input_bytes) != blob for path, blob in zip(input_paths, blobs)):
        fail("input changed during export")
    if destination.exists():
        if not destination.is_dir() or {path.name for path in destination.iterdir()} != set(files):
            fail("existing destination incompatible or corrupt")
        if any(read_bounded(destination / name, args.max_output_bytes) != blob for name, blob in files.items()):
            fail("existing destination input mismatch or output corruption")
        return "verified existing export"
    # Reserve without clobbering a competing directory on Windows or POSIX.
    # Directory visibility is not atomic: manifest.json is the commit marker.
    destination.mkdir()
    created = []
    published = False
    try:
        for name, blob in files.items():
            path = destination / (".manifest.tmp" if name == "manifest.json" else name)
            with path.open("xb") as stream:
                created.append(path)
                stream.write(blob)
                stream.flush()
                os.fsync(stream.fileno())
        # A hard link publishes a complete, fsynced manifest without overwriting
        # any existing entry. Unsupported filesystems fail closed.
        os.link(destination / ".manifest.tmp", destination / "manifest.json")
        created.append(destination / "manifest.json")
        (destination / ".manifest.tmp").unlink()
        published = True
    finally:
        if not published:
            for path in reversed(created):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                destination.rmdir()
            except OSError:
                pass  # Never recursively remove unexpected/concurrent files.
    return "published synthetic export"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("transcript", "selection", "destination"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--frozen-artifact", action="append", default=[])
    parser.add_argument("--max-input-bytes", type=int, default=MAX_INPUT_BYTES)
    parser.add_argument("--max-output-bytes", type=int, default=MAX_OUTPUT_BYTES)
    parser.add_argument("--max-records", type=int, default=MAX_RECORDS)
    args = parser.parse_args()
    try:
        print(export(args))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        print(f"export rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
