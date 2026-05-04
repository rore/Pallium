# Note Memory Type Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `note` memory type that faithfully preserves content from explicit `pallium_ingest` calls, bypassing LLM type classification.

**Architecture:** When `artifact_kind="note"` is set on a source item, the semantic plugin uses a dedicated note extraction prompt (not the standard type-classification prompt) to derive retrieval metadata (at minimum a title; topics/context depending on eval results), then creates a `note` memory object with the full content preserved. The caller explicitly passes `artifact_kind="note"` when the user asks to remember something. Notes are durable, high-value, and indexed for both lexical and vector retrieval.

**Tech Stack:** Python 3.12, existing Pallium semantic pipeline, pytest

---

## File Structure

| File | Responsibility |
|------|----------------|
| `api/schemas.py` | Add `"note"` to `ArtifactKind` literal |
| `semantic/agent_conversation_memory.py` | Note bypass in `process_item`, type registration, retention |
| `semantic/agent_conversation_memory_note.py` (create) | Note LLM extraction + memory object builder |
| `semantic/agent_conversation_memory_embedding.py` | Embedding text builder for notes |
| `semantic/agent_conversation_memory_routing_constants.py` | Add note to routing layers and weights |
| `semantic/agent_conversation_memory_routing_selection.py` | Add note branch in injectable block builder (with truncation + source pointer) |
| `storage/sqlite.py` | Add `"content"` to `_DISPLAY_TEXT_KEYS` |
| `app/mcp/server.py` | Update docstring to document artifact_kind="note" |
| `integrations/claude-code/claude_md_block.py` | Add note usage instructions |
| `integrations/codex/AGENTS.md` | Add note usage instructions |
| `tests/test_note_memory.py` (create) | Unit tests for note extraction and routing |
| `evals/note_extraction_eval.py` (create) | Prompt iteration eval harness for note extraction |
| `evals/live_value_scenarios/scenarios.json` | Add note recall eval scenario |

---

### Task 1: Add "note" to ArtifactKind literal

**Files:**
- Modify: `api/schemas.py:11`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_note_memory.py
import pytest
from api.schemas import ArtifactKind
from typing import get_args
from core.models import SourceItem


def _make_source_item(
    content: str,
    *,
    artifact_kind: str = "note",
    container_ref: str = "git:test/repo",
    actor_ref: str = "user:test",
    visibility: str = "private",
    role: str = "user",
    source_id: str = "test-source-1",
    thread_ref: str = "test-thread-1",
) -> SourceItem:
    return SourceItem(
        source_type="agent_artifact",
        source_id=source_id,
        content_type="text/plain",
        content=content,
        artifact_kind=artifact_kind,
        role=role,
        container_ref=container_ref,
        actor_ref=actor_ref,
        thread_ref=thread_ref,
        visibility=visibility,
    )


def test_note_is_valid_artifact_kind():
    valid_kinds = get_args(ArtifactKind)
    assert "note" in valid_kinds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_note_memory.py::test_note_is_valid_artifact_kind -v`
Expected: FAIL with AssertionError

- [ ] **Step 3: Add "note" to the ArtifactKind literal**

In `api/schemas.py` line 11, change:
```python
ArtifactKind = Literal["message", "assistant_output", "tool_use_summary", "todo_snapshot", "notification"]
```
to:
```python
ArtifactKind = Literal["message", "assistant_output", "tool_use_summary", "todo_snapshot", "notification", "note"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_note_memory.py::test_note_is_valid_artifact_kind -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/schemas.py tests/test_note_memory.py
git commit -m "feat: add 'note' to ArtifactKind literal"
```

---

### Task 2: Build note extraction prompt eval harness and iterate to find the right prompt

**Files:**
- Create: `semantic/agent_conversation_memory_note.py`
- Create: `evals/note_extraction_eval.py`

The note prompt needs iteration — we don't know upfront whether topics help or hurt, what model works, or what structure is most useful for injection. Build the harness first, then iterate.

**Design questions to answer via eval:**
- Does topic extraction improve retrieval, or does it add noise? (full content is already indexed)
- What structure gives value in injection? (title alone? title + snippet? title + topics?)
- Which model works? (Haiku may suffice for title extraction — token conscious)
- Generalized prompt vs specific: "extract retrieval metadata" vs "produce a findable title"

- [ ] **Step 1: Build a test corpus of real explicit-ingest content**

Gather 10-15 representative items that would be explicitly ingested as notes. Include:
- SQL queries with operational context (the BM25 floor gate case)
- Technical procedures ("how to check X", "steps to deploy Y")
- Configuration recipes ("set X=Y when Z")
- Reference documents (architecture summaries, API patterns)
- Short contextual facts ("project X uses framework Y because Z")
- Multi-paragraph structured content (headings, code blocks, lists)

Save as `evals/note_extraction_corpus.json`:
```json
[
  {
    "id": "operational-sql-query",
    "content": "## Tracking BM25 Floor Gate Impact\n\nRun this SQL...",
    "expected_findable_by": ["bm25 floor gate", "how to check injection misses", "audit log query"],
    "expected_title_contains": ["BM25", "floor gate", "tracking"]
  },
  ...
]
```

- [ ] **Step 2: Build the eval runner**

Create `evals/note_extraction_eval.py` that:
1. Loads the corpus
2. Runs each prompt variant against each item (with configurable model)
3. Evaluates: Is the title concise and descriptive? Do extracted topics add terms not already in content? Would the title work as an injection block heading?
4. Reports per-variant scores

```python
# evals/note_extraction_eval.py
"""Eval harness for note extraction prompt variants.

Tests prompt variants against a corpus of real explicit-ingest content.
Measures: title quality, topic usefulness, injection readability.

Usage:
    python -m evals.note_extraction_eval --variant all --model haiku
    python -m evals.note_extraction_eval --variant title_only --model sonnet
"""
```

- [ ] **Step 3: Define prompt variants to test**

Start with these candidates:

**Variant A: title_only** (minimal, token-cheap)
```
Extract a concise title (1 sentence, max 15 words) describing what this note is about.
Return JSON: {"title": "..."}
```

**Variant B: title_and_topics** (the original plan)
```
Extract retrieval metadata from this note:
- "title": 1-sentence description (max 15 words)
- "topics": 3-7 keywords someone might search for
Return JSON: {"title": "...", "topics": [...]}
```

**Variant C: title_and_context** (injection-focused)
```
Extract a title and a 1-2 sentence context summary for this note.
The context should help someone decide whether to read the full content.
Return JSON: {"title": "...", "context": "..."}
```

**Variant D: structured_note** (richest extraction)
```
Extract structured metadata from this note:
- "title": 1-sentence description (max 15 words)
- "context": 1-2 sentence summary of what this note helps with
- "topics": 3-5 keywords for search
Return JSON: {"title": "...", "context": "...", "topics": [...]}
```

- [ ] **Step 4: Run eval, compare variants**

Run: `python -m evals.note_extraction_eval --variant all --model haiku`
Run: `python -m evals.note_extraction_eval --variant all --model sonnet`

Evaluate each variant on:
- **Title quality**: Is it a good injection block heading? Better than first sentence?
- **Topic usefulness**: Do topics add retrieval vocabulary NOT already in the content? (If 90% overlap with content tokens → topics are noise, drop them)
- **Injection readability**: Given a 2000-char note, what should the injected block show? Full content wastes tokens. Title + context + "[+source]" pointer may be better.
- **Token cost**: How many input+output tokens per variant? Haiku vs Sonnet cost.

- [ ] **Step 5: Implement the winning variant in `agent_conversation_memory_note.py`**

Based on eval results, implement the chosen prompt. The builder signature is:

```python
def build_note_memory(source_item: SourceItem, *, provider: LLMProvider) -> ProcessResult:
```

The payload structure depends on which variant wins:
- If title_only: `{"content": ..., "title": ..., "source_type": ..., "source_id": ...}`
- If title_and_topics: add `"topics": [...]`
- If title_and_context: add `"context": "..."`
- If structured_note: add both

Key implementation details regardless of variant:
- Fallback title if LLM returns empty (first line of content, truncated)
- `normalize_for_index(title + topics + content)` for lexical index
- `build_embedding_text(memory_object)` for vector index
- `thread_rebuild_requested=False`

- [ ] **Step 6: Commit**

```bash
git add semantic/agent_conversation_memory_note.py evals/note_extraction_eval.py evals/note_extraction_corpus.json
git commit -m "feat: add note memory builder with eval-driven extraction prompt"
```

---

### Task 3: Wire note bypass into the semantic plugin

**Files:**
- Modify: `semantic/agent_conversation_memory.py:80-100`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_note_memory.py (append)
from unittest.mock import MagicMock
from semantic.agent_conversation_memory import AgentConversationMemoryPlugin


def test_plugin_process_item_note_uses_dedicated_prompt():
    """Note artifact_kind triggers the dedicated note prompt, not standard extraction."""
    mock_provider = MagicMock()
    # Mock LLM response — the exact structure depends on eval-chosen variant.
    # At minimum, the prompt returns {"title": ...}. Other fields are variant-dependent.
    mock_provider.generate_json.return_value = MagicMock(
        parsed_json={"title": "BM25 floor gate threshold info"},
        metadata={},
    )
    plugin = AgentConversationMemoryPlugin(
        provider=mock_provider,
        prompt_variant="strict_typed_memory_v8b_work_refs_separate",
    )
    source_item = _make_source_item(
        "Remember: the BM25 floor gate threshold is 12, precision went from 18% to 52.7%"
    )

    result = plugin.process_item(source_item)

    # LLM SHOULD be called — but with the note extraction prompt, not the standard one
    mock_provider.generate_json.assert_called_once()
    call_kwargs = mock_provider.generate_json.call_args
    system_prompt = call_kwargs[1].get("system_prompt") or call_kwargs[0][0]
    assert "title" in system_prompt.lower()
    assert "candidate_type" not in system_prompt  # NOT the standard extraction prompt

    # Should produce a note memory object with original content preserved
    assert len(result.memory_objects) == 1
    assert result.memory_objects[0].type == "note"
    assert "BM25 floor gate" in result.memory_objects[0].payload["content"]
    assert result.memory_objects[0].payload["title"] == "BM25 floor gate threshold info"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_note_memory.py::test_plugin_process_item_note_uses_dedicated_prompt -v`
Expected: FAIL (the plugin still calls the standard extraction for artifact_kind="note")

- [ ] **Step 3: Add the note bypass in process_item**

In `semantic/agent_conversation_memory.py`, add the import at the top:
```python
from semantic.agent_conversation_memory_note import build_note_memory
```

Then modify the `process_item` method to check for note first:

```python
def process_item(self, source_item: SourceItem) -> ProcessResult:
    if source_item.artifact_kind == "note":
        return build_note_memory(source_item, provider=self._provider_for_role("write_extraction"))

    direct_trace = self._delegate.analyze_item(source_item)
    direct_result = direct_trace.process_result
    direct_result = _append_typed_constraint_memory_objects(
        direct_result,
        source_item=source_item,
        extraction=direct_trace.extraction,
    )
    direct_result = _apply_direct_memory_envelopes(
        direct_result,
        source_item=source_item,
        extraction=direct_trace.extraction,
    )
    return ProcessResult(
        memory_objects=direct_result.memory_objects,
        relations=direct_result.relations,
        index_entries=direct_result.index_entries,
        source_item_metadata_updates=direct_result.source_item_metadata_updates,
        thread_rebuild_requested=direct_result.thread_rebuild_requested,
        supersession_hints=build_supersession_hints(source_item, direct_result),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_note_memory.py::test_plugin_process_item_note_uses_dedicated_prompt -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `python -m pytest tests/ -x -q`
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add semantic/agent_conversation_memory.py
git commit -m "feat: wire note extraction into AgentConversationMemoryPlugin.process_item"
```

---

### Task 4: Register note type and add embedding builder

**Files:**
- Modify: `semantic/agent_conversation_memory.py` (in `register_routing_types`)
- Modify: `semantic/agent_conversation_memory_embedding.py` (add to EMBEDDABLE_MEMORY_TYPES + builder)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_note_memory.py (append)
from core.type_registry import TypeRegistry


def test_note_type_registered_in_routing():
    mock_provider = MagicMock()
    plugin = AgentConversationMemoryPlugin(
        provider=mock_provider,
        prompt_variant="strict_typed_memory_v8b_work_refs_separate",
    )
    registry = TypeRegistry()
    plugin.register_routing_types(registry)

    assert "note" in registry
    reg = registry.get("note")
    assert reg is not None
    assert reg.high_value is True
    assert reg.block_title == "Note"
    assert reg.block_text_field == "content"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_note_memory.py::test_note_type_registered_in_routing -v`
Expected: FAIL (AssertionError: "note" not in registry)

- [ ] **Step 3: Add note TypeRegistration**

In `semantic/agent_conversation_memory.py`, in `register_routing_types`, add to the `_TYPES` list:

```python
TypeRegistration(
    type_name="note", layer_name="note",
    weight_by_intent={"recall": 145, "structured_recall": 130, "work_resumption": 130, "evidence_trace": 100},
    default_weight=140, block_title="Note", block_text_field="content", high_value=True,
),
```

- [ ] **Step 4: Add "note" to EMBEDDABLE_MEMORY_TYPES and builder**

In `semantic/agent_conversation_memory_embedding.py`, add `"note"` to the `EMBEDDABLE_MEMORY_TYPES` set:

```python
EMBEDDABLE_MEMORY_TYPES = {
    "decision",
    "investigation_outcome",
    "interest",
    "thread_summary",
    "task_checkpoint",
    "pattern_memory",
    "continuity_memory",
    "constraint_memory",
    "note",
}
```

Add `"note": _build_note_text` to the `builders` dict inside `build_embedding_text`.

Add the builder function:

```python
def _build_note_text(payload: dict) -> str:
    """Note: title + content (truncated for embedding model context)."""
    parts: list[str] = []
    title = payload.get("title")
    if title:
        parts.append(f"Note: {title}")
    content = payload.get("content")
    if content:
        parts.append(content[:1500])
    return " ".join(parts) if parts else ""
```

This is the single source of truth for note embedding text. The note builder (`build_note_memory`) calls `build_embedding_text(memory_object)` which delegates here. Re-indexing uses the same path.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_note_memory.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add semantic/agent_conversation_memory.py semantic/agent_conversation_memory_embedding.py
git commit -m "feat: register note type for routing and embedding"
```

---

### Task 4b: Add note to routing constants

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_constants.py`

The `TypeRegistry` weights are used by the block builder. The actual scoring path uses `ROUTING_LAYER_WEIGHTS[intent][layer]` where `layer` comes from `_result_layer()`. Without adding `"note"` to `STRUCTURED_LAYERS`, notes map to `"lower_level_memory"` and get generic weights.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_note_memory.py (append)
from semantic.agent_conversation_memory_routing_constants import (
    STRUCTURED_LAYERS,
    ROUTING_LAYER_WEIGHTS,
    ROUTING_PREFERRED_LAYERS,
    ROUTING_SAFE_FALLBACK_LAYERS,
)


def test_note_in_structured_layers():
    assert "note" in STRUCTURED_LAYERS


def test_note_in_routing_layer_weights():
    for intent in ("recall", "structured_recall", "work_resumption", "evidence_trace"):
        assert "note" in ROUTING_LAYER_WEIGHTS[intent], f"note missing from {intent} weights"


def test_note_in_routing_preferred_layers():
    for intent in ("recall", "structured_recall", "work_resumption", "evidence_trace"):
        assert "note" in ROUTING_PREFERRED_LAYERS[intent], f"note missing from {intent} preferred layers"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_note_memory.py -v -k "structured_layers or layer_weights or preferred_layers"`
Expected: FAIL

- [ ] **Step 3: Add note to routing constants**

In `semantic/agent_conversation_memory_routing_constants.py`:

Add `"note"` to `STRUCTURED_LAYERS`:
```python
STRUCTURED_LAYERS = frozenset({
    "decision", "investigation_outcome", "task_checkpoint",
    "pattern_memory", "continuity_memory", "interest", CONSTRAINT_MEMORY_TYPE,
    "thread_summary", "turn_summary", "atomic_fact", "note",
})
```

Add `"note"` entry to each intent in `ROUTING_LAYER_WEIGHTS`:
```python
ROUTING_LAYER_WEIGHTS = {
    "recall": {..., "note": 145},
    "structured_recall": {..., "note": 130},
    "work_resumption": {..., "note": 130},
    "evidence_trace": {..., "note": 100},
}
```

Add `"note"` to `ROUTING_PREFERRED_LAYERS` (position after `continuity_memory`, before `interest` — similar recall tier):
```python
"recall": (..., "continuity_memory", "note", "atomic_fact", ...),
"structured_recall": (..., "atomic_fact", "note", "interest", ...),
"work_resumption": (..., "continuity_memory", "note", "atomic_fact", ...),
"evidence_trace": (..., "atomic_fact", "note", "interest", ...),
```

Add `"note"` to `ROUTING_SAFE_FALLBACK_LAYERS` for recall and structured_recall:
```python
"recall": ("atomic_fact", "note", "task_checkpoint", "thread_summary", "lower_level_memory", "source_evidence"),
"structured_recall": ("atomic_fact", "note", "decision", "source_evidence", "thread_summary"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_note_memory.py -v -k "structured_layers or layer_weights or preferred_layers"`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add semantic/agent_conversation_memory_routing_constants.py
git commit -m "feat: add note to routing layer constants and weights"
```

---

### Task 4c: Add note branch in injectable block builder (with truncation)

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_selection.py`

Without this, notes fall through to the generic fallback which uses `payload.get("summary")` — notes don't have a `summary` field, so they'd render with empty text.

Big notes need truncation in injection — showing a 2000-char SQL procedure verbatim wastes context tokens. Strategy: if content exceeds a threshold, show title + snippet + `[+source]` pointer. The `source_expanded_available=True` flag tells the consuming agent it can call `pallium_get_evidence` for full content.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_note_memory.py (append)
from core.models import QueryResultItem, EvidenceReference
from semantic.agent_conversation_memory_routing_selection import _build_raw_injectable_block

_NOTE_TRUNCATION_THRESHOLD = 500  # chars — notes longer than this get truncated in injection


def test_note_injectable_block_short_content():
    """Short notes render full content, no source expansion needed."""
    item = QueryResultItem(
        result_kind="memory_hit",
        score=100.0,
        evidence=[],
        memory_object_id="test-note-id",
        type="note",
        payload={"content": "Full note content here", "title": "My Note Title"},
    )
    candidate = {"item": item, "layer": "note", "final_score": 100}
    block = _build_raw_injectable_block(candidate, intent="recall")

    assert block.title == "Note: My Note Title"
    assert block.text == "Full note content here"
    assert block.memory_object_id == "test-note-id"
    assert block.source_expanded_available is False  # short note — full content already shown


def test_note_injectable_block_big_content_truncated():
    """Big notes show title + snippet + source pointer instead of full content."""
    long_content = "A" * 1000  # well above threshold
    item = QueryResultItem(
        result_kind="memory_hit",
        score=100.0,
        evidence=[],
        memory_object_id="test-note-id",
        type="note",
        payload={"content": long_content, "title": "Long Procedure"},
    )
    candidate = {"item": item, "layer": "note", "final_score": 100}
    block = _build_raw_injectable_block(candidate, intent="recall")

    assert block.title == "Note: Long Procedure"
    # Should NOT contain the full 1000 chars
    assert len(block.text) < 700
    # Should contain a truncated snippet
    assert "AAA" in block.text
    # Should signal that full content is available via get_evidence
    assert block.source_expanded_available is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_note_memory.py -v -k "injectable_block"`
Expected: FAIL (generic fallback returns empty text)

- [ ] **Step 3: Add note branch with truncation logic**

In `semantic/agent_conversation_memory_routing_selection.py`, before the generic fallback `return InjectableBlock(...)` at the end of `_build_raw_injectable_block`, add:

```python
_NOTE_INJECTION_TRUNCATION = 500  # chars — notes longer than this get snippet + source pointer

if item.type == "note":
    content = str(payload.get("content") or "").strip()
    title = payload.get("title") or ""
    block_title = f"Note: {title}" if title else "Note"
    truncated = len(content) > _NOTE_INJECTION_TRUNCATION

    if truncated:
        snippet = content[:_NOTE_INJECTION_TRUNCATION].rsplit(" ", 1)[0] + "..."
        text = snippet
    else:
        text = content

    return InjectableBlock(
        result_id=str(item.result_id),
        block_type="memory",
        title=block_title,
        text=text,
        evidence=item.evidence,
        memory_type=item.type,
        memory_object_id=mo_id,
        source_expanded_available=truncated,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_note_memory.py -v -k "injectable_block"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add semantic/agent_conversation_memory_routing_selection.py
git commit -m "feat: add note branch in injectable block builder with truncation for big notes"
```

---

### Task 4d: Add note display key for dashboard

**Files:**
- Modify: `storage/sqlite.py:42`

- [ ] **Step 1: Add "content" and "title" to _DISPLAY_TEXT_KEYS**

In `storage/sqlite.py`, change line 42 from:
```python
_DISPLAY_TEXT_KEYS = ("summary", "statement", "decision", "investigation_outcome", "interest_text", "constraint_text", "carry_forward_answer")
```
to:
```python
_DISPLAY_TEXT_KEYS = ("summary", "statement", "decision", "investigation_outcome", "interest_text", "constraint_text", "carry_forward_answer", "content", "title")
```

`"content"` goes after the existing keys so it doesn't change display behavior for types that already have `"summary"`.

- [ ] **Step 2: Commit**

```bash
git add storage/sqlite.py
git commit -m "feat: add content/title to display text keys for note dashboard rendering"
```

---

### Task 5: Add note to retention policy

**Files:**
- Modify: `semantic/agent_conversation_memory.py` (in `memory_retention_policy`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_note_memory.py (append)

def test_note_in_durable_retention_types():
    mock_provider = MagicMock()
    plugin = AgentConversationMemoryPlugin(
        provider=mock_provider,
        prompt_variant="strict_typed_memory_v8b_work_refs_separate",
    )
    policy = plugin.memory_retention_policy
    assert "note" in policy.durable_types


def test_note_excluded_from_consolidation():
    """Notes are standalone — they must not participate in thread consolidation."""
    mock_provider = MagicMock()
    plugin = AgentConversationMemoryPlugin(
        provider=mock_provider,
        prompt_variant="strict_typed_memory_v8b_work_refs_separate",
    )
    from core.models import MemoryObject
    note_mo = MemoryObject(
        type="note",
        schema_id="agent_conversation_memory.note",
        payload={"content": "test", "title": "test"},
        container_ref="git:test/repo",
        visibility="private",
    )
    assert plugin.supports_consolidation(note_mo) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_note_memory.py::test_note_in_durable_retention_types -v`
Expected: FAIL

- [ ] **Step 3: Add "note" to durable_types**

In `semantic/agent_conversation_memory.py`, modify `memory_retention_policy`:

```python
@property
def memory_retention_policy(self) -> MemoryRetentionPolicy:
    return MemoryRetentionPolicy(
        durable_types=frozenset({"decision", "investigation_outcome", "note"}),
        working_types=frozenset({"thread_summary", "task_checkpoint", "continuity_memory", "pattern_memory"}),
        orphan_delete_types=frozenset({"turn_summary"}),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_note_memory.py::test_note_in_durable_retention_types -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add semantic/agent_conversation_memory.py
git commit -m "feat: add note to durable retention types"
```

---

### Task 6: Update MCP tool docstring

**Files:**
- Modify: `app/mcp/server.py:73-101`

The `artifact_kind` default stays `None` — the calling agent must explicitly pass `artifact_kind="note"` when the user asks to remember something. We just update the docstring to document this.

- [ ] **Step 1: Update the tool docstring**

In `app/mcp/server.py`, change the `pallium_ingest` docstring to:
```python
"""Store a conversation artifact in Pallium for semantic processing. Pass artifact_kind="note" when the user explicitly asks to remember something — this preserves content faithfully with a dedicated extraction prompt. Without artifact_kind, the standard type-classification extraction pipeline is used. Do not use for routine conversation — the integration layer already ingests outputs automatically."""
```

- [ ] **Step 2: Commit**

```bash
git add app/mcp/server.py
git commit -m "docs: update pallium_ingest docstring to document artifact_kind='note'"
```

---

### Task 7: Add eval scenario

**Files:**
- Modify: `evals/live_value_scenarios/scenarios.json`

- [ ] **Step 1: Add a note recall scenario**

Append to the scenarios array in `evals/live_value_scenarios/scenarios.json`:

```json
{
  "scenario_id": "note-recall-operational-procedure",
  "description": "User previously asked to remember a SQL query for tracking injection misses after deploying the BM25 floor gate. In a new thread, they ask about checking recall loss. The note should be surfaced with the full operational procedure.",
  "value_story": "Without this note, the user must re-derive the SQL query and remember which tables/columns to check. With the note, the exact query and its context are immediately available — the user asked to remember it and the system honored that request faithfully.",
  "category": "note_recall",
  "query": {
    "text": "how do I check if the BM25 floor gate is blocking relevant memories? what query should I run?",
    "container_ref": "git:github.com/rore/pallium",
    "visibility": "private"
  },
  "expected": {
    "should_inject": true,
    "memory_types": ["note"],
    "content_patterns": ["bm25", "floor", "audit_log"],
    "value_reason": "Surfaces the exact operational procedure the user explicitly asked to remember"
  },
  "anti_patterns": {
    "should_not_inject_types": [],
    "should_not_contain": ["reservation", "catalog"]
  },
  "original_event": null,
  "expected_status": "pass"
}
```

- [ ] **Step 2: Verify JSON is valid**

Run: `python -c "import json; json.load(open('evals/live_value_scenarios/scenarios.json'))"`
Expected: No error

- [ ] **Step 3: Commit**

```bash
git add evals/live_value_scenarios/scenarios.json
git commit -m "eval: add note recall scenario for live value eval"
```

---

### Task 8: Integration test — end-to-end note processing

**Files:**
- Modify: `tests/test_note_memory.py`

- [ ] **Step 1: Write an integration test that exercises the full processing path**

```python
# tests/test_note_memory.py (append)

def test_note_full_process_result_structure():
    """Integration: verify the full ProcessResult from the plugin has all expected pieces."""
    mock_provider = MagicMock()
    # The exact JSON keys depend on the eval-chosen variant.
    # title is always present; topics/context are variant-dependent.
    mock_provider.generate_json.return_value = MagicMock(
        parsed_json={
            "title": "Tracking BM25 floor gate impact with SQL query",
        },
        metadata={},
    )
    plugin = AgentConversationMemoryPlugin(
        provider=mock_provider,
        prompt_variant="strict_typed_memory_v8b_work_refs_separate",
    )
    content = (
        "## Tracking BM25 Floor Gate Impact\n\n"
        "Run this SQL to find blocked-but-relevant memories:\n"
        "```sql\n"
        "SELECT memory_object_id, excluded_reason_code\n"
        "FROM audit_log\n"
        "WHERE excluded_reason_code = 'bm25_floor_gate'\n"
        "```\n\n"
        "If same memory_object_id shows up repeatedly, the floor may be too aggressive.\n"
        "Related evals: evals/vector_only_penalty_sim.py, evals/lexical_scale_replay_eval.py"
    )
    source_item = _make_source_item(content)

    result = plugin.process_item(source_item)

    # Memory object
    assert len(result.memory_objects) == 1
    mo = result.memory_objects[0]
    assert mo.type == "note"
    assert mo.schema_id == "agent_conversation_memory.note"
    assert mo.payload["content"] == content
    assert mo.payload["title"] == "Tracking BM25 floor gate impact with SQL query"
    assert mo.visibility == "private"
    assert mo.container_ref == "git:test/repo"
    assert mo.actor_ref == "user:test"

    # Relation
    assert len(result.relations) == 1
    assert result.relations[0].from_id == mo.id

    # Index entries: lexical + vector
    assert len(result.index_entries) == 2
    lexical = [e for e in result.index_entries if e.index_type == "lexical"]
    vector = [e for e in result.index_entries if e.index_type == "vector"]
    assert len(lexical) == 1
    assert len(vector) == 1
    assert "bm25" in lexical[0].text_view.lower()
    assert "audit_log" in lexical[0].text_view

    # Thread rebuild NOT requested (notes are standalone)
    assert result.thread_rebuild_requested is False

    # LLM was called with note prompt (not standard extraction)
    mock_provider.generate_json.assert_called_once()


def test_non_note_artifact_kind_still_uses_standard_extraction():
    """Verify that artifact_kind != 'note' still goes through normal extraction path."""
    mock_provider = MagicMock()
    mock_provider.generate_json.return_value = MagicMock(
        parsed_json={
            "summary": "Test summary",
            "candidate_type": None,
            "is_low_value_meta": False,
            "decision_text": None,
            "decision_evidence_text": None,
            "investigation_text": None,
            "investigation_evidence_text": None,
            "rationale_text": None,
            "interest_text": None,
            "constraint_text": None,
            "next_step_text": None,
            "blocker_text": None,
            "progress_text": None,
            "key_finding_text": None,
            "subject_hints": [],
            "work_refs": [],
        },
        metadata={},
    )
    plugin = AgentConversationMemoryPlugin(
        provider=mock_provider,
        prompt_variant="strict_typed_memory_v8b_work_refs_separate",
    )
    source_item = _make_source_item(
        "Just a regular message about the project",
        artifact_kind="message",
    )

    plugin.process_item(source_item)

    # LLM SHOULD have been called with the standard extraction prompt
    mock_provider.generate_json.assert_called_once()
    call_kwargs = mock_provider.generate_json.call_args
    system_prompt = call_kwargs[1]["system_prompt"] if call_kwargs[1] else call_kwargs[0][0]
    assert "candidate_type" in system_prompt  # standard extraction prompt
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_note_memory.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run full test suite one final time**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass, no regressions

- [ ] **Step 4: Commit**

```bash
git add tests/test_note_memory.py
git commit -m "test: add integration tests for note memory end-to-end flow"
```

---

### Task 9: Update integration instructions (claude-code and codex)

**Files:**
- Modify: `integrations/claude-code/claude_md_block.py`
- Modify: `integrations/codex/AGENTS.md`
- Modify: `integrations/codex/skills/pallium-memory/SKILL.md`

Agents need to know they should pass `artifact_kind="note"` when the user asks to remember something. Without this instruction, agents will call `pallium_ingest` without it and the content will go through standard extraction (the problem this feature solves).

- [ ] **Step 1: Update claude-code integration**

In `integrations/claude-code/claude_md_block.py`, change line 24 from:
```
- `pallium_ingest` — user explicitly asks to remember something (hooks already ingest automatically)
```
to:
```
- `pallium_ingest` — user explicitly asks to remember something. **Pass `artifact_kind="note"`** to preserve content faithfully with retrieval metadata. Without it, standard extraction may lose content. Hooks already ingest routine conversation automatically — only call this for explicit "remember" requests.
```

- [ ] **Step 2: Update codex AGENTS.md**

In `integrations/codex/AGENTS.md`, change line 22 from:
```
- `pallium_ingest` — user explicitly asks to remember something (hooks already
  ingest automatically)
```
to:
```
- `pallium_ingest` — user explicitly asks to remember something. **Pass
  `artifact_kind="note"`** to preserve content faithfully with retrieval
  metadata. Without it, standard extraction may lose content. Hooks already
  ingest routine conversation automatically.
```

- [ ] **Step 3: Update codex skill**

In `integrations/codex/skills/pallium-memory/SKILL.md`, update the "For storing" section to add:
```
2. **For storing** (user says "remember this", "save this"):
   - Call `pallium_ingest` with the content
   - **Always pass `artifact_kind: "note"`** — this preserves the content faithfully
   - Pass `visibility: "private"` and `container_ref` for project-scoped memory
   - If user says "across all projects" or "globally": use `visibility: "global"` with `actor_ref`
   - Confirm to the user what was stored
```

- [ ] **Step 4: Commit**

```bash
git add integrations/claude-code/claude_md_block.py integrations/codex/AGENTS.md integrations/codex/skills/pallium-memory/SKILL.md
git commit -m "docs: add artifact_kind='note' instructions to integration layers"
```

---

## Design Decisions & Rationale

1. **`artifact_kind="note"` as the signal** — Uses the existing field on SourceItem. No new parameters, no new API fields. The calling agent explicitly passes it when the user asks to remember something — it's not a default.

2. **MCP default stays `None`** — The agent must consciously decide to use the note path. Hook-based ingests continue to set "message", "assistant_output", etc. Items ingested without `artifact_kind` go through standard extraction. This prevents accidental note creation.

3. **Dedicated LLM prompt (not the standard extraction prompt)** — The standard prompt tries to classify into decision/investigation/interest and loses content in the process. The note prompt only extracts retrieval metadata (title + topics) without classifying or compressing. Full content is always preserved in the payload.

4. **Payload: content + title (+ optional topics/context)** — `content` is the original verbatim. `title` is always present — a concise 1-sentence description for injection block display. Additional fields (topics, context) depend on which prompt variant wins the eval. This structure makes notes both preserving (content) and findable (title + content in the index).

5. **Durable retention** — Notes are explicitly stored by user request. They should never be garbage-collected by retention policies.

6. **Conservative routing weight (145 for recall)** — Same tier as decisions (150) and continuity_memory (145). Notes are user-intent-backed but unvalidated — BM25 content-overlap scoring will naturally boost notes that match well. Starting conservative avoids notes outranking grounded decisions.

7. **thread_rebuild_requested=False** — Notes are standalone artifacts, not part of conversation flow. They shouldn't trigger thread summary rebuilds.

8. **Full content in lexical index** — The lexical index text is: `title + topics + content`. Title and topics add retrieval vocabulary beyond what's literally in the content (e.g., "how to restart" when the content only says "scripts/restart-service.ps1"). The full content ensures any keyword from the note is findable.

9. **Single embedding text builder** — The note builder calls `build_embedding_text(memory_object)` from the embedding module (same as other types). The embedding text is `"[note] Note: {title} {content[:1500]}"` — truncated for the E5 model's context window.

10. **Full routing integration** — Notes are added to `STRUCTURED_LAYERS`, `ROUTING_LAYER_WEIGHTS`, `ROUTING_PREFERRED_LAYERS`, and `ROUTING_SAFE_FALLBACK_LAYERS`. Without this, they'd fall through to `lower_level_memory` and the registered TypeRegistry weights would be decorative.

11. **No envelope metadata** — Notes use a different prompt so they have no `MemoryEnvelope`. Acceptable for v1 since notes won't benefit from envelope-based routing optimizations (confidence, scope).

12. **No consolidation or supersession** — Notes don't participate in thread consolidation and have no deduplication logic. Duplicate ingests produce duplicate notes. Acceptable since notes are rare explicit actions.

13. **Injection truncation for big notes** — Notes above 500 chars are truncated to a snippet in the injectable block. Only truncated notes set `source_expanded_available=True`, signaling the agent can expand via `pallium_get_evidence`. Short notes show full content without the expansion signal — no point prompting the agent to expand what's already fully displayed.
