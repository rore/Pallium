from __future__ import annotations

import re

from core.contracts import ProcessResult
from core.models import Annotation, IndexEntry, MemoryObject, Relation, SourceItem
from semantic.base import SemanticPlugin


SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _summarize(content: str) -> str:
    text = content.strip()
    if not text:
        return ""
    sentences = [item.strip() for item in SENTENCE_PATTERN.split(text) if item.strip()]
    if sentences:
        return sentences[0]
    return text[:200].strip()


def _normalize_for_index(text: str) -> str:
    return " ".join(TOKEN_PATTERN.findall(text.lower()))


class DemoAgentMemoryPlugin(SemanticPlugin):
    name = "demo_agent_memory"

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        summary = _summarize(source_item.content)
        annotation = Annotation(
            source_item_id=source_item.id,
            type="summary",
            schema_id="core.summary",
            schema_version="v1",
            payload={"text": summary},
        )
        memory_object = MemoryObject(
            type="discussion_summary",
            schema_id="demo.discussion_summary",
            schema_version="v1",
            payload={
                "summary": summary,
                "source_type": source_item.source_type,
                "source_id": source_item.source_id,
            },
        )
        relation = Relation(
            from_kind="memory_object",
            from_id=memory_object.id,
            relation_type="supported_by",
            to_kind="source_item",
            to_id=source_item.id,
        )
        index_entry = IndexEntry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type="lexical",
            text_view=_normalize_for_index(summary),
        )
        return ProcessResult(
            annotations=[annotation],
            memory_objects=[memory_object],
            relations=[relation],
            index_entries=[index_entry],
        )
