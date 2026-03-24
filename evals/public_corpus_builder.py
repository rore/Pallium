from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_REVIEW_MANIFEST = Path("evals/public_corpus/wildchat_review_manifest.json")
DEFAULT_WILDBENCH_REVIEW_MANIFEST = Path("evals/public_corpus/wildbench_review_manifest.json")
DEFAULT_OUTPUT_DIR = Path("evals/public_corpus/output")
DEFAULT_QUERY_LIMIT = 6
PARQUET_BATCH_SIZE = 256
ENGLISH_MARKERS = {"en", "en-us", "english"}
SAFE_FALSE_MARKERS = {"toxic", "unsafe", "flagged", "blocked", "fail", "failed", "no", "inappropriate", "false"}
SAFE_TRUE_MARKERS = {"safe", "clean", "approved", "allow", "allowed", "non-toxic", "non_toxic", "yes", "appropriate", "true"}
USER_ROLE_MARKERS = {"user", "human"}
ASSISTANT_ROLE_MARKERS = {"assistant", "gpt", "model", "bot"}
WILDCHAT_CORPUS_NAME = "wildchat"
WILDBENCH_CORPUS_NAME = "wildbench"
WORK_PROGRESS_PREFIXES = ("partial progress:", "progress update:", "review progress:", "progress:")
WORK_BLOCKER_PREFIXES = ("blocked:", "blocker:", "failed attempt:", "failure:")
WORK_NEXT_STEP_PREFIXES = ("next step:",)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build reviewed public-corpus episodes from a local public benchmark export.")
    parser.add_argument("--corpus-file", type=Path, required=True)
    parser.add_argument("--reviewed-manifest", type=Path, default=DEFAULT_REVIEW_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default="public-corpus-reviewed-build")
    parser.add_argument("--emit-candidates", action="store_true")
    args = parser.parse_args()

    output_dir = args.output_dir / args.run_name
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_review_manifest(args.reviewed_manifest)
    corpus_name = str(manifest.get("corpus_name", WILDCHAT_CORPUS_NAME))
    conversations = load_public_corpus_conversations(args.corpus_file, corpus_name=corpus_name)
    reviewed_episodes = build_reviewed_episodes(conversations=conversations, manifest=manifest)
    reviewed_path = output_dir / "reviewed_episodes.json"
    reviewed_path.write_text(json.dumps(reviewed_episodes, indent=2), encoding="utf-8")

    candidate_path = None
    candidate_count = None
    if args.emit_candidates:
        candidates = build_candidate_episodes(conversations)
        candidate_count = len(candidates)
        candidate_path = output_dir / "candidate_episodes.jsonl"
        with candidate_path.open("w", encoding="utf-8") as handle:
            for item in candidates:
                handle.write(json.dumps(item) + "\n")

    summary = {
        "corpus_name": corpus_name,
        "corpus_file": str(args.corpus_file),
        "reviewed_manifest": str(args.reviewed_manifest),
        "conversations_kept": len(conversations),
        "reviewed_episodes": len(reviewed_episodes),
        "candidate_episode_count": candidate_count,
        "reviewed_output": str(reviewed_path),
        "candidate_output": str(candidate_path) if candidate_path is not None else None,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(output_dir)
    return 0


def load_review_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_review_conversation_ids(manifest: dict[str, Any]) -> set[str]:
    conversation_ids: set[str] = set()
    for spec in manifest.get("episodes", []):
        for key in ("conversation_id", "target_conversation_id"):
            value = spec.get(key)
            if value not in (None, ""):
                conversation_ids.add(str(value))
        for value in spec.get("source_conversation_ids", []):
            if value not in (None, ""):
                conversation_ids.add(str(value))
    return conversation_ids


def load_public_corpus_conversations(
    path: Path,
    *,
    corpus_name: str,
    conversation_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    if corpus_name == WILDCHAT_CORPUS_NAME:
        return load_wildchat_conversations(path, conversation_ids=conversation_ids)
    if corpus_name == WILDBENCH_CORPUS_NAME:
        return load_wildbench_conversations(path, conversation_ids=conversation_ids)
    raise ValueError(f"Unsupported public corpus: {corpus_name}")


def load_wildchat_conversations(path: Path, *, conversation_ids: set[str] | None = None) -> list[dict[str, Any]]:
    return list(iter_wildchat_conversations(path, conversation_ids=conversation_ids))


def load_wildbench_conversations(path: Path, *, conversation_ids: set[str] | None = None) -> list[dict[str, Any]]:
    return list(iter_wildbench_conversations(path, conversation_ids=conversation_ids))


def iter_wildchat_conversations(path: Path, *, conversation_ids: set[str] | None = None) -> Iterator[dict[str, Any]]:
    for index, row in enumerate(_iter_rows(path)):
        if conversation_ids is not None:
            conversation_id = _extract_row_conversation_id(row=row, ordinal=index)
            if conversation_id is None or conversation_id not in conversation_ids:
                continue
        conversation = _normalize_wildchat_row(row=row, ordinal=index)
        if conversation is not None:
            yield conversation


def iter_wildbench_conversations(path: Path, *, conversation_ids: set[str] | None = None) -> Iterator[dict[str, Any]]:
    for index, row in enumerate(_iter_rows(path)):
        conversation_id = _extract_wildbench_conversation_id(row=row, ordinal=index)
        if conversation_ids is not None and (conversation_id is None or conversation_id not in conversation_ids):
            continue
        conversation = _normalize_wildbench_row(row=row, ordinal=index)
        if conversation is not None:
            yield conversation


def build_candidate_episodes(conversations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not conversations:
        return []
    corpus_name = str(conversations[0].get("corpus_name", WILDCHAT_CORPUS_NAME))
    if corpus_name == WILDBENCH_CORPUS_NAME:
        return _build_wildbench_candidate_episodes(conversations)
    return _build_wildchat_candidate_episodes(conversations)


def _build_wildchat_candidate_episodes(conversations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for conversation in conversations:
        query_turn_index = _last_user_turn_index(conversation["turns"])
        if query_turn_index is not None and query_turn_index >= 2:
            target_turn = conversation["turns"][query_turn_index]
            candidates.append(
                {
                    "episode_id": f"{conversation['conversation_id']}::within::{query_turn_index}",
                    "episode_type": "within_conversation_later_turn_recall",
                    "conversation_id": conversation["conversation_id"],
                    "query_turn_index": query_turn_index,
                    "current_context_turn_indices": [query_turn_index],
                    "query_text": target_turn["content"],
                    "user_key": conversation.get("user_key"),
                    "turn_count": len(conversation["turns"]),
                    "language": conversation["language"],
                }
            )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for conversation in conversations:
        user_key = conversation.get("user_key")
        if user_key:
            grouped[user_key].append(conversation)

    for user_key, rows in grouped.items():
        ordered = sorted(rows, key=lambda item: (item.get("sort_key"), item["conversation_id"]))
        for earlier, later in zip(ordered, ordered[1:]):
            query_turn_index = _first_user_turn_index(later["turns"])
            if query_turn_index is None:
                continue
            candidates.append(
                {
                    "episode_id": f"{earlier['conversation_id']}::{later['conversation_id']}::carry-forward",
                    "episode_type": "later_session_carry_forward",
                    "source_conversation_ids": [earlier["conversation_id"]],
                    "target_conversation_id": later["conversation_id"],
                    "target_query_turn_index": query_turn_index,
                    "current_context_turn_indices": [query_turn_index],
                    "query_text": later["turns"][query_turn_index]["content"],
                    "user_key": user_key,
                }
            )
    return candidates


def _build_wildbench_candidate_episodes(conversations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for conversation in conversations:
        query_turn_index = _last_user_turn_index(conversation["turns"])
        if query_turn_index is None or query_turn_index < 2:
            continue
        target_turn = conversation["turns"][query_turn_index]
        candidates.append(
            {
                "episode_id": f"{conversation['conversation_id']}::within::{query_turn_index}",
                "episode_type": "within_conversation_later_turn_recall",
                "conversation_id": conversation["conversation_id"],
                "query_turn_index": query_turn_index,
                "current_context_turn_indices": [query_turn_index],
                "query_text": target_turn["content"],
                "turn_count": len(conversation["turns"]),
                "language": conversation["language"],
                "primary_tag": conversation.get("primary_tag"),
                "intent": conversation.get("intent"),
                "checklist_count": len(conversation.get("checklist", [])),
            }
        )
    return candidates


def build_reviewed_episodes(*, conversations: list[dict[str, Any]], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    indexed = {item["conversation_id"]: item for item in conversations}
    episodes: list[dict[str, Any]] = []
    for spec in manifest.get("episodes", []):
        episode_type = spec["episode_type"]
        if episode_type == "within_conversation_later_turn_recall":
            episodes.append(_build_within_conversation_episode(indexed=indexed, spec=spec, manifest=manifest))
            continue
        if episode_type == "later_session_carry_forward":
            episodes.append(_build_later_session_episode(indexed=indexed, spec=spec, manifest=manifest))
            continue
        raise ValueError(f"Unsupported reviewed episode type: {episode_type}")
    return episodes


def _build_within_conversation_episode(*, indexed: dict[str, dict[str, Any]], spec: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    conversation = indexed[spec["conversation_id"]]
    query_turn_index = int(spec["query_turn_index"])
    context_turn_indices = _normalize_context_turn_indices(spec, default_query_turn_index=query_turn_index)
    prior_events = _build_prior_events(
        conversations=[conversation],
        include_turn_filter=lambda conversation_id, turn_index: turn_index < query_turn_index and turn_index not in context_turn_indices,
    )
    current_thread_context = _build_thread_context(conversation=conversation, context_turn_indices=context_turn_indices)
    query_text = conversation["turns"][query_turn_index]["content"]
    return _assemble_episode(
        manifest=manifest,
        spec=spec,
        query_text=query_text,
        current_thread_context=current_thread_context,
        prior_events=prior_events,
        target_conversation=conversation,
        source_conversation_ids=[conversation["conversation_id"]],
    )


def _build_later_session_episode(*, indexed: dict[str, dict[str, Any]], spec: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    source_conversations = [indexed[item] for item in spec["source_conversation_ids"]]
    target_conversation = indexed[spec["target_conversation_id"]]
    query_turn_index = int(spec.get("target_query_turn_index", _first_user_turn_index(target_conversation["turns"])))
    context_turn_indices = _normalize_context_turn_indices(spec, default_query_turn_index=query_turn_index)
    prior_events = _build_prior_events(
        conversations=source_conversations,
        include_turn_filter=lambda conversation_id, turn_index: turn_index <= int(spec.get("source_turn_end_index", 10_000)),
    )
    current_thread_context = _build_thread_context(conversation=target_conversation, context_turn_indices=context_turn_indices)
    query_text = target_conversation["turns"][query_turn_index]["content"]
    return _assemble_episode(
        manifest=manifest,
        spec=spec,
        query_text=query_text,
        current_thread_context=current_thread_context,
        prior_events=prior_events,
        target_conversation=target_conversation,
        source_conversation_ids=[item["conversation_id"] for item in source_conversations],
    )


def _assemble_episode(
    *,
    manifest: dict[str, Any],
    spec: dict[str, Any],
    query_text: str,
    current_thread_context: list[dict[str, Any]],
    prior_events: list[dict[str, Any]],
    target_conversation: dict[str, Any],
    source_conversation_ids: list[str],
) -> dict[str, Any]:
    effective_query_text = str(spec.get("query_text", query_text))
    expected_primary_layer = spec.get("expected_primary_layer", spec.get("expected_winning_layer"))
    acceptable_fallback_layers = list(spec.get("acceptable_fallback_layers") or [])
    if not acceptable_fallback_layers and spec.get("acceptable_winning_layers"):
        acceptable_fallback_layers = [
            item
            for item in spec.get("acceptable_winning_layers", [])
            if item != expected_primary_layer
        ]
    acceptable_layers: list[str] = []
    if expected_primary_layer:
        acceptable_layers.append(expected_primary_layer)
    for layer in acceptable_fallback_layers:
        if layer not in acceptable_layers:
            acceptable_layers.append(layer)
    current_query = {
        "text": effective_query_text,
        "limit": int(spec.get("query_limit", manifest.get("default_query_limit", DEFAULT_QUERY_LIMIT))),
        "container_ref": target_conversation["container_ref"],
        "visibility": "public",
    }
    if spec["episode_type"] == "within_conversation_later_turn_recall":
        current_query["thread_ref"] = target_conversation["thread_ref"]
    return {
        "episode_id": spec["episode_id"],
        "episode_type": spec["episode_type"],
        "corpus_name": manifest.get("corpus_name", WILDCHAT_CORPUS_NAME),
        "description": spec["description"],
        "source_conversation_ids": source_conversation_ids,
        "target_conversation_id": target_conversation["conversation_id"],
        "source_user_key": target_conversation.get("user_key"),
        "source_primary_tag": target_conversation.get("primary_tag"),
        "source_secondary_tags": target_conversation.get("secondary_tags", []),
        "source_intent": target_conversation.get("intent"),
        "source_checklist": target_conversation.get("checklist", []),
        "reference_answer": target_conversation.get("reference_answer"),
        "prior_events": prior_events,
        "current_thread_context": current_thread_context,
        "current_query": current_query,
        "target_question": spec.get("target_question", query_text),
        "should_memory_help": bool(spec.get("should_memory_help")),
        "scenario_family": spec.get("scenario_family", spec["episode_type"]),
        "expected_intent": spec.get("expected_intent"),
        "expected_primary_layer": expected_primary_layer,
        "acceptable_fallback_layers": acceptable_fallback_layers,
        "acceptable_layers": acceptable_layers,
        "forbidden_layers": list(spec.get("forbidden_layers", [])),
        "must_preserve": list(spec.get("must_preserve", [])),
        "must_not_introduce": list(spec.get("must_not_introduce", [])),
        "guard_terms": {
            key: [str(item).strip() for item in values if str(item).strip()]
            for key, values in (spec.get("guard_terms", {}) or {}).items()
        },
        "expected_gap_target": spec.get("expected_gap_target"),
        "expected_winning_layer": spec.get("expected_winning_layer"),
        "acceptable_winning_layers": spec.get("acceptable_winning_layers", acceptable_layers),
        "expected_memory_types": spec.get("expected_memory_types", []),
        "expected_higher_level_memory_types": spec.get("expected_higher_level_memory_types", []),
        "expected_answer_signals": spec.get("expected_answer_signals", []),
        "forbidden_terms": spec.get("forbidden_terms", []),
        "overreach_guard": bool(spec.get("overreach_guard")),
        "consolidation_strategy": spec.get("consolidation_strategy"),
        "review_notes": spec.get("review_notes"),
        "dataset_tier": spec.get("dataset_tier", manifest.get("dataset_tier", "confidence")),
    }


def _build_prior_events(
    *,
    conversations: list[dict[str, Any]],
    include_turn_filter,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for conversation in sorted(conversations, key=lambda item: (item.get("sort_key"), item["conversation_id"])):
        for turn in conversation["turns"]:
            if not include_turn_filter(conversation["conversation_id"], int(turn["turn_index"])):
                continue
            events.append(_build_source_event(conversation=conversation, turn=turn))
    return events


def _build_thread_context(*, conversation: dict[str, Any], context_turn_indices: list[int]) -> list[dict[str, Any]]:
    turns_by_index = {int(turn["turn_index"]): turn for turn in conversation["turns"]}
    context_items: list[dict[str, Any]] = []
    for turn_index in sorted(context_turn_indices):
        turn = turns_by_index[turn_index]
        artifact_kind = _infer_artifact_kind(role=turn["role"], content=turn["content"])
        context_items.append(
            {
                "role": turn["role"],
                "artifact_kind": artifact_kind,
                "content": turn["content"],
            }
        )
    return context_items


def _build_source_event(*, conversation: dict[str, Any], turn: dict[str, Any]) -> dict[str, Any]:
    occurred_at = conversation["base_timestamp"] + timedelta(minutes=int(turn["turn_index"]))
    role = str(turn["role"])
    artifact_kind = _infer_artifact_kind(role=role, content=str(turn["content"]))
    return {
        "source_type": "public_corpus_turn",
        "source_id": f"{conversation['conversation_id']}:{turn['turn_index']}",
        "content_type": "text/plain",
        "content": turn["content"],
        "artifact_kind": artifact_kind,
        "visibility": "public",
        "role": role,
        "container_ref": conversation["container_ref"],
        "thread_ref": conversation["thread_ref"],
        "actor_ref": f"public-corpus:{conversation['corpus_name']}:{role}",
        "source_ref": f"{conversation['corpus_name']}://{conversation['conversation_id']}/{turn['turn_index']}",
        "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
        "metadata": {
            "corpus_name": conversation["corpus_name"],
            "source_conversation_id": conversation["conversation_id"],
            "source_turn_index": int(turn["turn_index"]),
            "source_user_key": conversation.get("user_key"),
            "language": conversation["language"],
            "safe": conversation.get("safe"),
            "model": conversation.get("model"),
            "primary_tag": conversation.get("primary_tag"),
            "secondary_tags": conversation.get("secondary_tags", []),
            "intent": conversation.get("intent"),
            "checklist": conversation.get("checklist", []),
        },
    }


def _infer_artifact_kind(*, role: str, content: str) -> str:
    if role == "user":
        return "message"
    lowered = content.strip().lower()
    if lowered.startswith(WORK_NEXT_STEP_PREFIXES):
        return "todo_snapshot"
    if lowered.startswith(WORK_PROGRESS_PREFIXES) or lowered.startswith(WORK_BLOCKER_PREFIXES):
        return "tool_use_summary"
    return "assistant_output"


def _normalize_wildchat_row(*, row: dict[str, Any], ordinal: int) -> dict[str, Any] | None:
    turns = _normalize_turns(row.get("conversation") or row.get("messages") or row.get("turns") or [])
    if len(turns) < 4:
        return None
    if sum(1 for turn in turns if turn["role"] == "user") < 2:
        return None
    if sum(1 for turn in turns if turn["role"] == "assistant") < 2:
        return None

    language = _normalize_language(_find_first_value(row, {"language", "language_code", "lang", "detected_language"}))
    if language != "english":
        return None

    safe_value = _extract_safe_value(row)
    if safe_value is False:
        return None

    conversation_id = _extract_row_conversation_id(row=row, ordinal=ordinal) or f"wildchat-{ordinal:05d}"
    user_key_value = _find_first_value(row, {"hashed_ip", "user_hash", "user_id", "user_key"})
    user_key = str(user_key_value) if user_key_value not in (None, "") else None
    timestamp_value = _find_first_value(row, {"timestamp", "created_at", "createdAt", "conversation_created_at", "base_timestamp"})
    base_timestamp = _normalize_timestamp(timestamp_value, fallback_minutes=ordinal)
    model_value = _find_first_value(row, {"model", "model_name", "assistant_model"})
    model = str(model_value) if model_value not in (None, "") else None

    container_ref = _build_wildchat_container_ref(user_key=user_key, conversation_id=conversation_id)
    thread_ref = f"public-corpus:wildchat:thread:{conversation_id}"

    return {
        "corpus_name": WILDCHAT_CORPUS_NAME,
        "conversation_id": conversation_id,
        "language": language,
        "safe": safe_value,
        "user_key": user_key,
        "model": model,
        "turns": turns,
        "container_ref": container_ref,
        "thread_ref": thread_ref,
        "base_timestamp": base_timestamp,
        "sort_key": base_timestamp.isoformat(),
    }


def _normalize_wildbench_row(*, row: dict[str, Any], ordinal: int) -> dict[str, Any] | None:
    raw_turns = row.get("conversation_input") or row.get("conversation") or row.get("messages") or row.get("turns") or []
    turns = _normalize_turns(raw_turns)
    if len(turns) < 3:
        return None
    if turns[-1]["role"] != "user":
        return None
    if sum(1 for turn in turns if turn["role"] == "user") < 2:
        return None
    if sum(1 for turn in turns if turn["role"] == "assistant") < 1:
        return None

    provided_languages = [str(turn.get("language", "")).strip() for turn in raw_turns if isinstance(turn, dict) and str(turn.get("language", "")).strip()]
    if provided_languages and any(_normalize_language(language) != "english" for language in provided_languages):
        return None
    language = "english"

    safe_value = _extract_safe_value(row)
    if safe_value is False:
        return None

    conversation_id = _extract_wildbench_conversation_id(row=row, ordinal=ordinal) or f"wildbench-{ordinal:05d}"
    timestamp_value = _find_first_value(row, {"timestamp", "created_at", "createdAt", "session_created_at", "base_timestamp"})
    base_timestamp = _normalize_timestamp(timestamp_value, fallback_minutes=ordinal)
    primary_tag = _normalize_optional_text(row.get("primary_tag"))
    secondary_tags = _normalize_text_list(row.get("secondary_tags"))
    intent = _normalize_optional_text(row.get("intent"))
    reference_answer = _extract_reference_answer(row.get("references")) or _normalize_optional_text(row.get("reference_answer"))
    model = _normalize_optional_text(_find_first_value(row, {"model", "model_name", "assistant_model"}))

    container_ref = f"public-corpus:wildbench:session:{conversation_id}"
    thread_ref = f"public-corpus:wildbench:thread:{conversation_id}"

    return {
        "corpus_name": WILDBENCH_CORPUS_NAME,
        "conversation_id": conversation_id,
        "language": language,
        "safe": safe_value,
        "user_key": None,
        "model": model,
        "turns": turns,
        "container_ref": container_ref,
        "thread_ref": thread_ref,
        "base_timestamp": base_timestamp,
        "sort_key": base_timestamp.isoformat(),
        "primary_tag": primary_tag,
        "secondary_tags": secondary_tags,
        "intent": intent,
        "checklist": _normalize_text_list(row.get("checklist")),
        "reference_answer": reference_answer,
    }


def _normalize_turns(raw_turns: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_turns, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, raw_turn in enumerate(raw_turns):
        if not isinstance(raw_turn, dict):
            continue
        role = _normalize_role(raw_turn.get("role") or raw_turn.get("from") or raw_turn.get("speaker"))
        content = _normalize_turn_text(raw_turn.get("content") or raw_turn.get("text") or raw_turn.get("value"))
        if role is None or not content:
            continue
        normalized.append({"turn_index": index, "role": role, "content": content})
    return normalized


def _normalize_role(value: Any) -> str | None:
    if value is None:
        return None
    lowered = str(value).strip().lower()
    if lowered in USER_ROLE_MARKERS:
        return "user"
    if lowered in ASSISTANT_ROLE_MARKERS:
        return "assistant"
    return None


def _normalize_turn_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "content", "value"):
            if key in value:
                return _normalize_turn_text(value[key])
        return ""
    if isinstance(value, list):
        parts = [_normalize_turn_text(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    return ""


def _normalize_language(value: Any) -> str | None:
    if value is None:
        return None
    lowered = str(value).strip().lower()
    return "english" if lowered in ENGLISH_MARKERS else None


def _extract_safe_value(payload: Any) -> bool | None:
    for semantic, keys in (("safe", {"safe", "is_safe", "appropriate"}), ("toxic", {"toxic", "is_toxic", "toxicity"})):
        found = _find_first_keyed_value(payload, keys)
        if found is not None:
            _, value = found
            normalized = _normalize_safe_value(value, semantic=semantic)
            if normalized is not None:
                return normalized

    moderation = _find_first_keyed_value(payload, {"moderation"})
    if moderation is not None:
        _, value = moderation
        return _extract_safe_value(value)
    return None


def _normalize_safe_value(value: Any, *, semantic: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value if semantic == "safe" else not value
    if isinstance(value, (int, float)):
        if semantic == "safe":
            return value != 0
        return value == 0
    if isinstance(value, dict):
        return _extract_safe_value(value)
    lowered = str(value).strip().lower()
    if lowered in SAFE_TRUE_MARKERS:
        return True
    if lowered in SAFE_FALSE_MARKERS:
        return False
    if semantic == "safe":
        if lowered in {"1", "1.0", "true"}:
            return True
        if lowered in {"0", "0.0", "false"}:
            return False
    else:
        if lowered in {"1", "1.0", "true"}:
            return False
        if lowered in {"0", "0.0", "false"}:
            return True
    return None


def _build_wildchat_container_ref(*, user_key: str | None, conversation_id: str) -> str:
    if user_key:
        return f"public-corpus:wildchat:user:{user_key}"
    return f"public-corpus:wildchat:conversation:{conversation_id}"


def _normalize_context_turn_indices(spec: dict[str, Any], *, default_query_turn_index: int) -> list[int]:
    raw = spec.get("current_context_turn_indices")
    if not raw:
        return [default_query_turn_index]
    return sorted({int(item) for item in raw})


def _first_user_turn_index(turns: list[dict[str, Any]]) -> int | None:
    for turn in turns:
        if turn["role"] == "user":
            return int(turn["turn_index"])
    return None


def _last_user_turn_index(turns: list[dict[str, Any]]) -> int | None:
    for turn in reversed(turns):
        if turn["role"] == "user":
            return int(turn["turn_index"])
    return None


def _find_first_keyed_value(payload: Any, keys: set[str]) -> tuple[str, Any] | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys and value not in (None, ""):
                return key, value
        for value in payload.values():
            found = _find_first_keyed_value(value, keys)
            if found is not None and found[1] not in (None, ""):
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_first_keyed_value(item, keys)
            if found is not None and found[1] not in (None, ""):
                return found
    return None


def _find_first_value(payload: Any, keys: set[str]) -> Any:
    found = _find_first_keyed_value(payload, keys)
    return None if found is None else found[1]


def _normalize_timestamp(value: Any, *, fallback_minutes: int) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, str) and value.strip():
        normalized = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=fallback_minutes * 10)


def _extract_row_conversation_id(*, row: dict[str, Any], ordinal: int) -> str | None:
    value = _find_first_value(row, {"conversation_id", "id", "conversation_hash", "conversation_uuid"})
    if value in (None, ""):
        return None
    return str(value)


def _extract_wildbench_conversation_id(*, row: dict[str, Any], ordinal: int) -> str | None:
    value = _find_first_value(row, {"session_id", "conversation_id", "id"})
    if value in (None, ""):
        return None
    return str(value)


def _extract_reference_answer(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("gpt-4", "gpt4", "reference", "answer"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        for item in value.values():
            normalized = _extract_reference_answer(item)
            if normalized:
                return normalized
    if isinstance(value, list):
        for item in value:
            normalized = _extract_reference_answer(item)
            if normalized:
                return normalized
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _iter_rows(path: Path) -> Iterator[dict[str, Any]]:
    for corpus_file in _resolve_corpus_files(path):
        yield from _iter_rows_from_file(corpus_file)


def _resolve_corpus_files(path: Path) -> list[Path]:
    if not path.exists():
        raise FileNotFoundError(f"Corpus path does not exist: {path}")
    if path.is_file():
        return [path]

    files = sorted(item for item in path.rglob("*") if item.is_file())
    parquet_files = [item for item in files if item.suffix.lower() == ".parquet"]
    if parquet_files:
        return parquet_files

    jsonl_files = [item for item in files if item.suffix.lower() in {".jsonl", ".ndjson"}]
    if jsonl_files:
        return jsonl_files

    json_files = [item for item in files if item.suffix.lower() == ".json"]
    if len(json_files) == 1:
        return json_files

    raise ValueError(f"Unsupported corpus directory layout: {path}")


def _iter_rows_from_file(path: Path) -> Iterator[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)
        return
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    yield item
            return
        raise ValueError(f"Unsupported corpus JSON payload: {path}")
    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError("Reading public corpus parquet snapshots requires the optional 'pyarrow' package.") from exc
        parquet_file = pq.ParquetFile(path)
        for batch in parquet_file.iter_batches(batch_size=PARQUET_BATCH_SIZE):
            for row in batch.to_pylist():
                if isinstance(row, dict):
                    yield row
        return
    raise ValueError(f"Unsupported corpus file format: {path}")


if __name__ == "__main__":
    raise SystemExit(main())




