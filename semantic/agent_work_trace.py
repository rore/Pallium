"""Agent Work Trace — parallel semantic package for capturing agent discovery trails."""
from __future__ import annotations

import json
import logging
import posixpath
from collections import Counter
from datetime import datetime
from typing import Any

from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import MemoryRetentionPolicy, ProcessResult
from core.indexing import build_index_entry, BUILTIN_INDEX_PROVIDER_NAME, BUILTIN_INDEX_PROVIDER_VERSION
from core.models import IndexEntry, MemoryObject, Relation, SourceItem, new_id, utc_now
from providers.llm.base import LLMProvider, LLMJsonResponse
from semantic.base import ThreadAggregationSemanticPlugin

logger = logging.getLogger(__name__)

TASK_TRACE_TYPE = "task_trace"
TASK_TRACE_SCHEMA_ID = "agent_work_trace.task_trace"
TASK_TRACE_SCHEMA_VERSION = "v1"

LEXICAL_TEXT_VIEW_NAME = "memory_object.task_trace_lexical"

MAX_EXPLORATORY_FILES = 30
MAX_PRODUCTIVE_FILES = 20
MAX_COMMANDS_SUCCEEDED = 10
MAX_COMMANDS_FAILED = 10
MAX_FAILURE_FRAGMENTS = 5
MAX_FILES_MODIFIED = 20

OUTCOME_SYSTEM_PROMPT = (
    "Given these agent responses from a coding session, produce a 1-2 sentence "
    "summary of what was investigated and what if anything was found or resolved. "
    "If the responses contain only analysis, planning, or no clear conclusion, "
    "return null for the outcome field."
)


def normalize_path(p: str, cwd: str | None) -> str:
    """Normalize a file path relative to cwd.

    Uses posixpath for consistent behavior across platforms since agent paths
    are always forward-slash POSIX paths or Windows paths that we normalize.
    """

    try:
        normalized = p.replace("\\", "/")
        if cwd:
            cwd_normalized = cwd.replace("\\", "/")
            if normalized.startswith(cwd_normalized.rstrip("/") + "/"):
                rel = normalized[len(cwd_normalized.rstrip("/")) + 1:]
                return rel
            if posixpath.isabs(normalized):
                rel = posixpath.relpath(normalized, cwd_normalized)
                return rel
        cleaned = normalized.removeprefix("./") if normalized.startswith("./") else normalized
        return cleaned
    except (ValueError, TypeError):
        return p


def _compute_subject(all_files: list[str]) -> str:
    """Deterministic subject: most common directory prefix across all files."""
    if not all_files:
        return ""

    dirs: list[str] = []
    for f in all_files:
        parts = f.replace("\\", "/").split("/")
        if len(parts) > 1:
            dirs.append(parts[0] + "/")
        else:
            dirs.append(f)

    if not dirs:
        return all_files[0] if all_files else ""

    counter = Counter(dirs)
    most_common = counter.most_common(2)
    if len(most_common) == 1:
        return most_common[0][0]
    if most_common[0][1] > most_common[1][1]:
        return most_common[0][0]
    return ", ".join(all_files[:2])


class AgentWorkTracePlugin(ThreadAggregationSemanticPlugin):
    """Parallel semantic package that captures agent discovery trails."""

    name = "agent_work_trace"

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    @property
    def parallel_processing(self) -> bool:
        return True

    @property
    def thread_summary_schema_id(self) -> str:
        return TASK_TRACE_SCHEMA_ID

    @property
    def rebuild_supersedes_prior(self) -> bool:
        return True

    @property
    def memory_retention_policy(self) -> MemoryRetentionPolicy:
        return MemoryRetentionPolicy(
            working_types=frozenset({TASK_TRACE_TYPE}),
        )

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        """Check for work trace metadata. Request rebuild if present."""
        metadata = source_item.metadata or {}
        if "agent_work_trace_turn" not in metadata:
            return ProcessResult(
                memory_objects=[], relations=[], index_entries=[],
                thread_rebuild_requested=False,
            )
        return ProcessResult(
            memory_objects=[], relations=[], index_entries=[],
            thread_rebuild_requested=True,
        )

    def supports_thread_aggregation(self, source_item: SourceItem) -> bool:
        metadata = source_item.metadata or {}
        return "agent_work_trace_turn" in metadata

    def build_thread_summary(
        self,
        aggregate: ThreadAggregate,
        conclusions: list[MemoryObject],
    ) -> ProcessResult:
        """Aggregate per-turn work traces into a single task_trace MemoryObject."""
        turns: list[dict] = []
        trace_items: list[SourceItem] = []
        cwd: str | None = None

        for item in aggregate.source_items:
            meta = item.metadata or {}
            if "agent_work_trace_turn" in meta:
                turns.append(meta["agent_work_trace_turn"])
                trace_items.append(item)
                if cwd is None and "cwd" in meta:
                    cwd = meta["cwd"]

        if not turns:
            return ProcessResult(
                memory_objects=[], relations=[], index_entries=[],
                thread_rebuild_requested=False,
            )

        # Normalize all file paths
        for turn in turns:
            turn["files_read"] = [normalize_path(f, cwd) for f in turn.get("files_read", [])]

        # Exploratory vs. productive split
        first_write_action_turn = next(
            (i for i, t in enumerate(turns) if t.get("has_productive_action")), None
        )

        if first_write_action_turn is not None:
            exploratory_files = list(dict.fromkeys(
                f for t in turns[:first_write_action_turn] for f in t["files_read"]
            ))
            productive_files = list(dict.fromkeys(
                f for t in turns[first_write_action_turn:] for f in t["files_read"]
            ))
        else:
            exploratory_files = list(dict.fromkeys(
                f for t in turns for f in t["files_read"]
            ))
            productive_files = []

        # Aggregate commands
        commands_succeeded = [c for t in turns for c in t.get("commands", []) if c.get("exit_code") == 0]
        commands_failed = [c for t in turns for c in t.get("commands", []) if c.get("exit_code") != 0]

        # Aggregate modified files (direct signal — not inferred from read phase)
        files_modified = list(dict.fromkeys(
            f for t in turns for f in t.get("files_modified", [])
        ))
        files_modified = files_modified[:MAX_FILES_MODIFIED]

        # NOTE: per-turn `patch_bodies` (apply_patch raw body / structured
        # operation) is intentionally NOT aggregated into the task_trace
        # payload. The thread-level task_trace summary describes "what
        # happened" at file/command granularity; the raw patch body is
        # turn-level evidence for the operational-fact extractor (per
        # docs/specs/2026-05-31-operational-fact-memory-design.md
        # §Extraction Predicate, which reads source_items.metadata_json
        # directly, not memory_objects.payload). Adding patch_bodies here
        # would be a contract change. Pinned by
        # tests/test_agent_work_trace_e2e.py::test_patch_bodies_not_in_task_trace_payload.

        # Apply caps
        exploratory_files = exploratory_files[:MAX_EXPLORATORY_FILES]
        productive_files = productive_files[:MAX_PRODUCTIVE_FILES]
        commands_succeeded = commands_succeeded[:MAX_COMMANDS_SUCCEEDED]
        commands_failed = commands_failed[:MAX_COMMANDS_FAILED]

        # Deterministic subject
        all_files = exploratory_files + productive_files
        subject = _compute_subject(all_files)

        # Best-effort outcome extraction via LLM
        outcome: str | None = None
        outcome_source = "none"
        response_texts = [item.content for item in trace_items if item.content and item.content.strip()]
        if response_texts:
            try:
                combined = "\n---\n".join(response_texts[-5:])
                llm_response = self._provider.generate_json(
                    system_prompt=OUTCOME_SYSTEM_PROMPT,
                    user_prompt=combined,
                    schema_description='{"outcome": "string or null"}',
                )
                raw_outcome = llm_response.parsed_json.get("outcome")
                if raw_outcome and isinstance(raw_outcome, str) and raw_outcome.strip().lower() != "null":
                    outcome = raw_outcome.strip()
                    outcome_source = "llm_from_agent_responses"
            except Exception as exc:
                logger.debug("Outcome extraction failed (non-blocking): %s", exc)

        # Source item IDs for correlation
        turn_source_item_ids = [item.id for item in trace_items]

        # Build payload
        payload: dict[str, Any] = {
            "investigation_subject": subject,
            "outcome_source": outcome_source,
            "exploratory_files": exploratory_files,
            "productive_files": productive_files,
            "commands_succeeded": [c["cmd"] for c in commands_succeeded],
            "commands_failed": [c["cmd"] for c in commands_failed],
            "files_modified": files_modified,
            "bash_failure_fragments": [
                {"cmd": c["cmd"], "class": c.get("failure_class", ""), "tail": c.get("output_tail", "")}
                for c in commands_failed[:MAX_FAILURE_FRAGMENTS]
            ],
            "first_write_action_at_turn": first_write_action_turn,
            "turn_count": len(turns),
            "turn_source_item_ids": turn_source_item_ids,
        }
        if outcome:
            payload["outcome"] = outcome

        # Extract repo/branch/commit from metadata if available
        first_meta = trace_items[0].metadata or {} if trace_items else {}
        payload["repo_ref"] = aggregate.container_ref
        if "branch_ref" in first_meta:
            payload["branch_ref"] = first_meta["branch_ref"]
        if "commit_ref" in first_meta:
            payload["commit_ref"] = first_meta["commit_ref"]
        if cwd:
            payload["working_directory"] = cwd

        memory_obj = MemoryObject(
            type=TASK_TRACE_TYPE,
            schema_id=TASK_TRACE_SCHEMA_ID,
            schema_version=TASK_TRACE_SCHEMA_VERSION,
            lifecycle="active",
            visibility=aggregate.visibility,
            container_ref=aggregate.container_ref,
            freshness_at=utc_now(),
            payload=payload,
        )

        # Build lexical index text
        index_parts = [subject] + exploratory_files + files_modified + productive_files + [c["cmd"] for c in commands_succeeded]
        if outcome:
            index_parts.append(outcome)
        index_text = " ".join(index_parts)

        index_entry = build_index_entry(
            target_kind="memory_object",
            target_id=memory_obj.id,
            index_type="lexical",
            text_view=index_text,
            text_view_name=LEXICAL_TEXT_VIEW_NAME,
        )

        return ProcessResult(
            memory_objects=[memory_obj],
            relations=[],
            index_entries=[index_entry],
            thread_rebuild_requested=False,
        )
