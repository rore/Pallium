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
from core.type_registry import TypeRegistration, TypeRegistry
from providers.llm.base import LLMProvider, LLMJsonResponse
from semantic.base import ThreadAggregationSemanticPlugin
from semantic.operational_fact import (
    CommandRecord,
    OPERATIONAL_FACT_TYPE,
    OperationalFactCandidate,
    ScopeResolver,
    TurnRecord,
    build_default_scope_resolver,
    derive_operational_facts,
)

logger = logging.getLogger(__name__)

TASK_TRACE_TYPE = "task_trace"
TASK_TRACE_SCHEMA_ID = "agent_work_trace.task_trace"
TASK_TRACE_SCHEMA_VERSION = "v1"

LEXICAL_TEXT_VIEW_NAME = "memory_object.task_trace_lexical"

# W4 PR 3: operational_fact derivation constants
OPERATIONAL_FACT_SCHEMA_ID = "agent_work_trace.operational_fact"
OPERATIONAL_FACT_SCHEMA_VERSION = "v1"
OPERATIONAL_FACT_LEXICAL_TEXT_VIEW = "memory_object.operational_fact_lexical"

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

    def __init__(
        self,
        provider: LLMProvider,
        *,
        operational_fact_derivation_enabled: bool = False,
        scope_resolver: ScopeResolver | None = None,
    ) -> None:
        self._provider = provider
        self._operational_fact_derivation_enabled = operational_fact_derivation_enabled
        self._scope_resolver = scope_resolver or build_default_scope_resolver()

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
    def non_superseding_types(self) -> frozenset[str]:
        # operational_fact supersession is keyed on the conflict slot
        # (command_family, artifact_role, scope_kind, scope_ref) per the
        # design doc §Deduplication And Conflict — NOT on (type, schema_id).
        # Excluding it here prevents the blanket rebuild-supersedes-prior
        # sweep from wiping every prior derived fact in the rebuild window.
        # Slot-scoped supersession lands in a follow-up storage pass; the
        # design permits either "skip the derived candidate" or "write it
        # as superseded linked to the winner" and PR 3 chooses skip via
        # the `origin` boundary (see §5 of the PR-3 design doc).
        return frozenset({OPERATIONAL_FACT_TYPE})

    @property
    def memory_retention_policy(self) -> MemoryRetentionPolicy:
        return MemoryRetentionPolicy(
            working_types=frozenset({TASK_TRACE_TYPE}),
            durable_types=frozenset({OPERATIONAL_FACT_TYPE}),
        )

    def register_routing_types(self, registry: TypeRegistry) -> None:
        """Register operational_fact with the core type registry.

        task_trace is intentionally NOT registered here — it's a
        thread-level aggregate that is retrieved via internal paths, not
        the standard routing gate. operational_fact IS user-visible via
        Surface B (UserPromptSubmit + operational_intent signal) and
        must be routable.

        Weight-by-intent MUST match the hardcoded values in
        ``semantic/agent_conversation_memory_routing_constants.py``
        (``ROUTING_LAYER_WEIGHTS[intent][OPERATIONAL_FACT_TYPE]``).
        The routing layer reads the hardcoded constant, not this
        registration — this registration remains for renderer /
        block-title purposes and for a future refactor that unifies
        the two sources. Drift between them is caught by
        ``tests/test_operational_fact_routing_constants.py``.
        """
        registry.register(
            TypeRegistration(
                type_name=OPERATIONAL_FACT_TYPE,
                layer_name=OPERATIONAL_FACT_TYPE,
                weight_by_intent={
                    "recall": 145,
                    "structured_recall": 220,
                    "work_resumption": 145,
                    "evidence_trace": 180,
                },
                default_weight=145,
                block_title="Operational fact",
                block_text_field="subject",
                high_value=True,
            )
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

        # W4 PR 3: operational_fact derivation.
        # Runs only when the [features] operational_fact_derivation flag is
        # on (default: False). Zero cost when flag is off. When on, emits
        # additional operational_fact MemoryObjects + IndexEntries into
        # the same ProcessResult that carries task_trace.
        extra_memories: list[MemoryObject] = []
        extra_indexes: list[IndexEntry] = []
        if self._operational_fact_derivation_enabled and turns and trace_items:
            turn_stream = _build_turn_stream_from_aggregate(trace_items, turns)
            candidates = derive_operational_facts(
                turn_stream=turn_stream,
                container_ref=aggregate.container_ref,
                scope_resolver=self._scope_resolver,
            )
            for cand in candidates:
                mem = _candidate_to_memory_object(cand, aggregate)
                extra_memories.append(mem)
                extra_indexes.append(_candidate_to_index_entry(cand, mem))

        return ProcessResult(
            memory_objects=[memory_obj, *extra_memories],
            relations=[],
            index_entries=[index_entry, *extra_indexes],
            thread_rebuild_requested=False,
        )

    def reconcile_process_result(
        self,
        result: ProcessResult,
        *,
        storage: Any,
        container_ref: str,
        visibility: str,
    ) -> ProcessResult:
        """Cross-run dedup for operational_fact rows.

        The class-level ``non_superseding_types`` intentionally exempts
        ``operational_fact`` from the blanket rebuild-supersedes-prior
        sweep — because the correct dedup key is the conflict slot
        ``(command_family, artifact_role, scope_kind, scope_ref,
        artifact_normalized)``, not ``(type, schema_id)``.

        This hook implements the slot-scoped dedup the class-level
        docstring says the storage pass should handle: for each
        newly-derived operational_fact in ``result.memory_objects``,
        drop it if an active row with the same conflict slot already
        exists in the same container. The alternative — writing a
        superseded chain — was rejected in the PR-3 design (§5) in
        favor of "skip the derived candidate".

        Task_trace rows and index entries for kept memories pass
        through untouched.
        """
        op_facts = [m for m in result.memory_objects if m.type == OPERATIONAL_FACT_TYPE]
        if not op_facts:
            return result

        # Load active operational_fact rows for this container and
        # index by conflict slot. One query covers all candidates.
        try:
            existing = storage.list_memory_objects(
                memory_types=[OPERATIONAL_FACT_TYPE],
                lifecycle="active",
                container_ref=container_ref,
            )
        except Exception as exc:
            # Defensive: if the storage handle doesn't support the
            # signature we expect (e.g., a mock in a scenario harness),
            # skip dedup rather than break persistence.
            logger.warning(
                "operational_fact dedup skipped: storage.list_memory_objects failed (%s)",
                exc,
            )
            return result

        existing_slots: set[tuple[str, str, str, str, str]] = set()
        for row in existing:
            # `list_memory_objects` returns soft-deleted rows too — the
            # domain MemoryObject doesn't carry the flag. Treat every
            # matching slot as "already claimed" for dedup purposes:
            # if a row was soft-deleted (e.g. by the tightening cleanup
            # CLI), re-emitting the same slot would resurrect the
            # noise. Skip.
            p = row.payload or {}
            slot = (
                str(p.get("command_family") or ""),
                str(p.get("artifact_role") or ""),
                str(p.get("scope_kind") or ""),
                str(p.get("scope_ref") or ""),
                str(p.get("artifact_normalized") or ""),
            )
            existing_slots.add(slot)

        # Filter candidate op_facts against the existing slots.
        kept_ids: set[str] = set()
        dropped_ids: set[str] = set()
        for mem in op_facts:
            p = mem.payload or {}
            slot = (
                str(p.get("command_family") or ""),
                str(p.get("artifact_role") or ""),
                str(p.get("scope_kind") or ""),
                str(p.get("scope_ref") or ""),
                str(p.get("artifact_normalized") or ""),
            )
            if slot in existing_slots:
                dropped_ids.add(mem.id)
            else:
                kept_ids.add(mem.id)
                existing_slots.add(slot)  # so intra-batch dupes also collapse

        if not dropped_ids:
            return result

        logger.info(
            "operational_fact dedup: dropped %d candidate(s) already present in container %s",
            len(dropped_ids), container_ref,
        )

        # Strip dropped memories AND their index entries.
        filtered_memories = [
            m for m in result.memory_objects
            if m.type != OPERATIONAL_FACT_TYPE or m.id in kept_ids
        ]
        filtered_indexes = [
            idx for idx in result.index_entries
            if idx.target_id not in dropped_ids
        ]
        return ProcessResult(
            memory_objects=filtered_memories,
            relations=result.relations,
            index_entries=filtered_indexes,
            thread_rebuild_requested=result.thread_rebuild_requested,
        )


# --------------------------------------------------------------------------- #
# W4 PR 3 helpers — operational_fact derivation wiring                        #
# --------------------------------------------------------------------------- #


def _build_turn_stream_from_aggregate(
    trace_items: list[SourceItem],
    turns: list[dict],
) -> list[TurnRecord]:
    """Build the operational_fact predicate's TurnRecord stream.

    Pairs trace_items[i] with turns[i] by index — the same invariant
    build_thread_summary relies on when building task_trace.
    """
    assert len(trace_items) == len(turns), "trace_items/turns paired invariant violated"
    records: list[TurnRecord] = []
    for i, (item, turn) in enumerate(zip(trace_items, turns)):
        cmd_records = tuple(
            CommandRecord(
                cmd=str(c.get("cmd") or ""),
                exit_code=c.get("exit_code"),
                output_tail=str(c.get("output_tail") or ""),
                failure_class=str(c.get("failure_class") or ""),
            )
            for c in (turn.get("commands") or [])
            if isinstance(c, dict) and c.get("cmd")
        )
        ts = ""
        if item.occurred_at is not None:
            ts = item.occurred_at.isoformat()
        elif item.created_at is not None:
            ts = item.created_at.isoformat()
        records.append(
            TurnRecord(
                turn_index=i,
                source_item_id=item.id,
                timestamp=ts,
                commands=cmd_records,
                files_read=tuple(
                    str(p) for p in (turn.get("files_read") or []) if p
                ),
                files_modified=tuple(
                    str(p) for p in (turn.get("files_modified") or []) if p
                ),
                grep_patterns=tuple(
                    str(p) for p in (turn.get("grep_patterns") or []) if p
                ),
            )
        )
    return records


def _candidate_to_memory_object(
    cand: OperationalFactCandidate,
    aggregate: ThreadAggregate,
) -> MemoryObject:
    """Convert a derivation candidate into a persistable MemoryObject.

    Invariant 1 code-level guard: `use_counters` is a NESTED sub-blob
    under payload — never at top level. Any retrieval code trying to
    rank on `success_count` / `reuse_count` / `last_used_at` must
    reach through two levels of dict access, which is grep-visible in
    code review. See tests/test_operational_fact_invariant1.py.
    """
    now = utc_now()
    now_iso = now.isoformat()
    evidence_dicts = [
        {
            "kind": ev.kind,
            "source_item_id": ev.source_item_id,
            "tool": ev.tool,
            "turn_index": ev.turn_index,
            "timestamp": ev.timestamp,
            "fragment": ev.fragment,
        }
        for ev in cand.evidence
    ]
    payload: dict[str, Any] = {
        "command_family": cand.command_family,
        "artifact_role": cand.artifact_role,
        "scope_kind": cand.scope_kind,
        "scope_ref": cand.scope_ref,
        "subject": cand.subject,
        "artifact": cand.artifact,
        "artifact_normalized": cand.artifact_normalized,
        "evidence": evidence_dicts,
        # `origin` in payload identifies this memory as agent-derived
        # (structural extraction from tool trace). Explicit writes via
        # W3 pallium_remember carry origin='agent_explicit'. The
        # cross-origin rule (design doc §Conflict slot) states that
        # derivation never supersedes an existing agent_explicit fact
        # in the same conflict slot; that guard lands in a follow-up
        # storage-level pass. Meanwhile this field makes the intent
        # visible on every derived row.
        "origin": "agent_inferred",
        # Nested — Invariant 1 code-level guard. Ranking layer must not
        # read these fields on retrieval paths; only outcome-recording
        # writes them.
        "use_counters": {
            "reuse_count": 1,
            "success_count": 0,
            "failure_count": 0,
            "last_used_at": now_iso,
            "last_confirmed_at": None,
        },
    }
    return MemoryObject(
        type=OPERATIONAL_FACT_TYPE,
        schema_id=OPERATIONAL_FACT_SCHEMA_ID,
        schema_version=OPERATIONAL_FACT_SCHEMA_VERSION,
        lifecycle="active",
        visibility=aggregate.visibility,
        container_ref=aggregate.container_ref,
        freshness_at=now,
        payload=payload,
    )


def _candidate_to_index_entry(
    cand: OperationalFactCandidate,
    memory_obj: MemoryObject,
) -> IndexEntry:
    """Emit the lexical index entry for a derived operational_fact.

    Text view mirrors the W3 explicit-write shape: subject + family +
    role + artifact tokens — the terms a UserPromptSubmit query is
    likely to carry when the operational_intent signal fires.
    """
    parts = [
        cand.subject or "",
        cand.command_family or "",
        cand.artifact_role or "",
        cand.artifact_normalized or "",
        cand.artifact or "",
    ]
    text_view = " ".join(p for p in parts if p)
    return build_index_entry(
        target_kind="memory_object",
        target_id=memory_obj.id,
        index_type="lexical",
        text_view=text_view,
        text_view_name=OPERATIONAL_FACT_LEXICAL_TEXT_VIEW,
    )
