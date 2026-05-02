# Constraint Memory Extraction Quality Fix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate vague/anaphoric constraints (5→0) and collapse semantic duplicates (23→4) while preserving the 27 good unique constraints.

**Architecture:** Two-layer fix: (1) improve extraction prompt + add post-extraction quality gate to reject decontextualized fragments, (2) add container-scoped dedup via canonical_key on content tokens + existing supersession mechanism. The canonical_key is generated from sorted content_tokens (stopwords removed), which already collapses minor paraphrases. The 23 duplicates in the live DB are verbatim repeats — canonical_key handles them. Jaccard overlap for arbitrary paraphrases is deferred as disproportionate (would cross storage→semantic boundary).

**Tech Stack:** Python, existing `content_tokens()` from `semantic/common.py`, existing supersession mechanism in `storage/sqlite_queue.py`.

---

### Task 1: Quality Gate — Reject Vague Constraint Text

Reject constraints that are too short or anaphoric (pronouns without a named subject). This gate runs before creating the MemoryObject, so rejected constraints produce no storage artifacts.

**Files:**
- Modify: `semantic/agent_conversation_memory_memory.py:125-189`
- Test: `tests/test_constraint_quality.py` (create)

- [ ] **Step 1: Write failing tests for the quality gate**

```python
"""Tests for constraint_memory quality gate — rejects vague/anaphoric/short constraints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.config_helpers import build_agent_conversation_client

CONTAINER = "chat:quality-gate-test"
THREAD = "chat:quality-gate-test:thread-1"


def _build_client(monkeypatch, sqlite_url: str) -> TestClient:
    return build_agent_conversation_client(monkeypatch, sqlite_url)


class TestConstraintQualityGateRejectsVague:
    """Vague/anaphoric constraints should be rejected by the quality gate."""

    def test_rejects_too_short_constraint(self) -> None:
        """Constraint text shorter than 15 chars after normalization is rejected."""
        from semantic.agent_conversation_memory_memory import _should_reject_constraint_text
        assert _should_reject_constraint_text("on windows") is True

    def test_rejects_pronoun_only_fragment(self) -> None:
        """Anaphoric fragments with only pronouns + verb are rejected."""
        from semantic.agent_conversation_memory_memory import _should_reject_constraint_text
        assert _should_reject_constraint_text("never do that") is True
        assert _should_reject_constraint_text("don't do it") is True
        assert _should_reject_constraint_text("its' not allowed") is True
        assert _should_reject_constraint_text("i don't want to do it yet") is True

    def test_accepts_good_constraint(self) -> None:
        """Well-formed self-contained constraints pass the gate."""
        from semantic.agent_conversation_memory_memory import _should_reject_constraint_text
        assert _should_reject_constraint_text("do not use the name muxi in pallium documentation") is False
        assert _should_reject_constraint_text("never add new llm calls to the extraction pipeline") is False
        assert _should_reject_constraint_text("always do an architect review before merging") is False


class TestConstraintQualityGateIntegration:
    """Unit tests: vague LLM extractions don't produce constraint_memories."""

    def test_short_constraint_not_stored(self) -> None:
        """If LLM extracts a short constraint, no constraint_memory is created."""
        from semantic.common import SemanticExtraction
        from semantic.agent_conversation_memory_memory import _append_typed_constraint_memory_objects
        from core.contracts import ProcessResult
        from core.models import SourceItem

        source_item = SourceItem(
            source_type="chat_message",
            source_id="gate-short-1",
            content_type="text/plain",
            content="on windows, god dummit",
            artifact_kind="message",
            role="user",
            container_ref=CONTAINER,
            thread_ref=THREAD,
            visibility="private",
        )
        extraction = SemanticExtraction(
            summary="platform clarification",
            constraint_text="on windows",
        )
        result = ProcessResult(memory_objects=[], relations=[], index_entries=[])
        result = _append_typed_constraint_memory_objects(result, source_item=source_item, extraction=extraction)
        assert not result.memory_objects

    def test_anaphoric_constraint_not_stored(self) -> None:
        """If LLM extracts an anaphoric fragment, no constraint_memory is created."""
        from semantic.common import SemanticExtraction
        from semantic.agent_conversation_memory_memory import _append_typed_constraint_memory_objects
        from core.contracts import ProcessResult
        from core.models import SourceItem

        source_item = SourceItem(
            source_type="chat_message",
            source_id="gate-anaphoric-1",
            content_type="text/plain",
            content="are you doing removing changes without asking? never do that!",
            artifact_kind="message",
            role="user",
            container_ref=CONTAINER,
            thread_ref=THREAD,
            visibility="private",
        )
        extraction = SemanticExtraction(
            summary="user correction about removing changes",
            constraint_text="never do that",
        )
        result = ProcessResult(memory_objects=[], relations=[], index_entries=[])
        result = _append_typed_constraint_memory_objects(result, source_item=source_item, extraction=extraction)
        assert not result.memory_objects

    def test_good_constraint_passes_gate(self) -> None:
        """Well-formed constraints still produce constraint_memory."""
        from semantic.common import SemanticExtraction
        from semantic.agent_conversation_memory_memory import _append_typed_constraint_memory_objects
        from core.contracts import ProcessResult
        from core.models import SourceItem

        source_item = SourceItem(
            source_type="chat_message",
            source_id="gate-good-1",
            content_type="text/plain",
            content="first, i don't want us to add any new llm request to the pipeline",
            artifact_kind="message",
            role="user",
            container_ref=CONTAINER,
            thread_ref=THREAD,
            visibility="private",
        )
        extraction = SemanticExtraction(
            summary="constraint about LLM requests",
            constraint_text="do not add any new llm request to the pipeline",
        )
        result = ProcessResult(memory_objects=[], relations=[], index_entries=[])
        result = _append_typed_constraint_memory_objects(result, source_item=source_item, extraction=extraction)
        assert len(result.memory_objects) == 1
        assert result.memory_objects[0].type == "constraint_memory"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_constraint_quality.py -x -v`
Expected: FAIL — `_should_reject_constraint_text` does not exist yet.

- [ ] **Step 3: Implement the quality gate**

In `semantic/agent_conversation_memory_memory.py`, add `_should_reject_constraint_text()` and call it early in `_append_typed_constraint_memory_objects`.

Add this function before `_append_typed_constraint_memory_objects`:

```python
_ANAPHORIC_PRONOUNS = frozenset({"that", "it", "this", "those", "these", "them"})
_GENERIC_VERBS = frozenset({"do", "done", "allow", "allowed", "want", "wanted"})

def _should_reject_constraint_text(constraint_text: str) -> bool:
    """Reject constraint text that is too short or anaphoric (unresolvable without context)."""
    normalized = normalize_for_index(constraint_text)
    if len(normalized) < 15:
        return True
    tokens = content_tokens(constraint_text)
    if not tokens:
        return True
    meaningful_tokens = tokens - _ANAPHORIC_PRONOUNS - _GENERIC_VERBS
    if not meaningful_tokens:
        return True
    return False
```

Add the `content_tokens` import at the top (it's already available from `semantic.common`):
```python
from semantic.common import SemanticExtraction, normalize_for_index, _resolve_actor_ref, content_tokens
```

Then in `_append_typed_constraint_memory_objects`, add after `if not constraint_text: return result`:

```python
    if _should_reject_constraint_text(constraint_text):
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_constraint_quality.py -x -v`
Expected: PASS

- [ ] **Step 5: Run full test suite for regressions**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add semantic/agent_conversation_memory_memory.py tests/test_constraint_quality.py
git commit -m "$(cat <<'EOF'
feat: add quality gate for constraint_memory extraction

Reject vague/anaphoric constraint text that would be unretrievable:
- Too short after normalization (< 15 chars)
- Only pronouns + generic verbs with no named subject
EOF
)"
```

---

### Task 2: Improve Extraction Prompt — Self-Contained Constraint Text

Update the active prompt variant to guide the LLM toward producing self-contained constraint text and rejecting fragments.

**Files:**
- Modify: `semantic/llm_agent_memory.py:319` (the constraint_text line in `strict_typed_memory_v8b_work_refs_separate`)
- Test: `tests/test_semantic_llm_plugin.py` (verify prompt guidance exists)

- [ ] **Step 1: Write a test verifying the prompt guidance exists**

Add to `tests/test_semantic_llm_plugin.py`:

```python
def test_constraint_text_prompt_requires_self_contained():
    """The active prompt variant must instruct self-contained constraint_text."""
    from semantic.llm_agent_memory import PROMPT_VARIANTS, DEFAULT_PROMPT_VARIANT
    prompt = PROMPT_VARIANTS[DEFAULT_PROMPT_VARIANT]
    assert "understandable in isolation" in prompt or "self-contained" in prompt
    assert "pronoun" in prompt.lower() or "anaphoric" in prompt.lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_semantic_llm_plugin.py::test_constraint_text_prompt_requires_self_contained -x -v`
Expected: FAIL — prompt doesn't contain these phrases yet.

- [ ] **Step 3: Update the prompt text**

In `semantic/llm_agent_memory.py`, in the `strict_typed_memory_v8b_work_refs_separate` variant at line 319, replace:

```
- constraint_text: a definitive operational constraint — the speaker commits to a requirement, prohibition, or hard rule. Hedged or tentative language ("I think", "maybe", "probably", "leaning towards", "not sure") is not a constraint.
```

with:

```
- constraint_text: a definitive operational constraint — the speaker commits to a requirement, prohibition, or hard rule. The text must be understandable in isolation: if the source uses pronouns ("that", "it", "this") without naming the subject, resolve them from surrounding context into constraint_text. REJECT (leave null): anaphoric fragments where the referent cannot be named ("never do that", "it's not allowed"), temporal hesitations that aren't durable rules ("i don't want to do it yet", "let's hold off for now"), and platform/environment statements that are not constraints ("on windows"). Hedged or tentative language ("I think", "maybe", "probably", "leaning towards", "not sure") is not a constraint.
```

- [ ] **Step 4: Run to verify test passes**

Run: `python -m pytest tests/test_semantic_llm_plugin.py::test_constraint_text_prompt_requires_self_contained -x -v`
Expected: PASS

- [ ] **Step 5: Run full test suite for regressions**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add semantic/llm_agent_memory.py tests/test_semantic_llm_plugin.py
git commit -m "$(cat <<'EOF'
feat: extraction prompt requires self-contained constraint_text

Guide the LLM to resolve pronouns and reject anaphoric fragments,
temporal hesitations, and non-constraint statements.
EOF
)"
```

---

### Task 3: Add Canonical Key to Constraint Memory

Add a `canonical_key` to constraint_memory payloads derived from sorted content tokens. This enables the existing supersession mechanism to deduplicate constraints.

**Files:**
- Modify: `semantic/agent_conversation_memory_memory.py:125-189` (add canonical_key to payload)
- Test: `tests/test_constraint_quality.py` (add canonical_key tests)

- [ ] **Step 1: Write failing tests for canonical_key generation**

Add to `tests/test_constraint_quality.py`:

```python
class TestConstraintCanonicalKey:
    """canonical_key is generated from content tokens for dedup."""

    def test_canonical_key_generated(self) -> None:
        """Constraint memory objects have a canonical_key in payload."""
        from semantic.common import SemanticExtraction
        from semantic.agent_conversation_memory_memory import _append_typed_constraint_memory_objects
        from core.contracts import ProcessResult
        from core.models import SourceItem

        source_item = SourceItem(
            source_type="chat_message",
            source_id="key-gen-1",
            content_type="text/plain",
            content="do not add any new llm calls to the extraction pipeline",
            artifact_kind="message",
            role="user",
            container_ref=CONTAINER,
            thread_ref=THREAD,
            visibility="private",
        )
        extraction = SemanticExtraction(
            summary="constraint about LLM calls",
            constraint_text="do not add any new llm calls to the extraction pipeline",
        )
        result = ProcessResult(memory_objects=[], relations=[], index_entries=[])
        result = _append_typed_constraint_memory_objects(result, source_item=source_item, extraction=extraction)
        assert result.memory_objects
        payload = result.memory_objects[0].payload
        assert "canonical_key" in payload
        assert payload["canonical_key"]

    def test_canonical_key_stable_across_stopword_variations(self) -> None:
        """Same content words with different stopwords produce the same canonical_key."""
        from semantic.common import SemanticExtraction
        from semantic.agent_conversation_memory_memory import _append_typed_constraint_memory_objects, _constraint_canonical_key
        from core.contracts import ProcessResult
        from core.models import SourceItem

        # "do not add any new llm calls" vs "don't add new llm calls"
        # content_tokens strips stopwords: both -> {"add", "calls", "llm", "new"}
        key1 = _constraint_canonical_key("do not add any new llm calls")
        key2 = _constraint_canonical_key("don't add new llm calls")
        assert key1 == key2

    def test_different_constraints_get_different_keys(self) -> None:
        """Semantically different constraints get different canonical_keys."""
        from semantic.agent_conversation_memory_memory import _constraint_canonical_key

        key_llm = _constraint_canonical_key("do not add any new llm calls to the pipeline")
        key_muxi = _constraint_canonical_key("do not use the name muxi in documentation")
        assert key_llm != key_muxi
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_constraint_quality.py::TestConstraintCanonicalKey -x -v`
Expected: FAIL — `_constraint_canonical_key` does not exist.

- [ ] **Step 3: Add canonical_key generation**

In `semantic/agent_conversation_memory_memory.py`, add the helper:

```python
def _constraint_canonical_key(constraint_text: str) -> str:
    """Generate a dedup key from sorted content tokens (stopwords removed)."""
    tokens = sorted(content_tokens(constraint_text))
    return " ".join(tokens)
```

In `_append_typed_constraint_memory_objects`, add `canonical_key` to the payload dict (after the quality gate check, before creating the MemoryObject):

```python
    canonical_key = _constraint_canonical_key(constraint_text)
    payload = {
        "summary": constraint_text,
        "constraint_text": constraint_text,
        "canonical_key": canonical_key,
        "evidence_context": source_item.content,
        "container_ref": source_item.container_ref,
        "thread_ref": source_item.thread_ref,
        "semantic_provenance": dict(semantic_provenance),
    }
```

- [ ] **Step 4: Run to verify canonical_key tests pass**

Run: `python -m pytest tests/test_constraint_quality.py::TestConstraintCanonicalKey -x -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add semantic/agent_conversation_memory_memory.py tests/test_constraint_quality.py
git commit -m "$(cat <<'EOF'
feat: add canonical_key to constraint_memory for dedup

Key is generated from sorted content tokens (stopwords removed),
enabling supersession-based deduplication across threads.
EOF
)"
```

---

### Task 4: Container-Scoped Supersession for Constraints

The existing supersession mechanism is thread-scoped. Constraint dedup needs to work across threads within the same container. Modify `build_supersession_hints` to emit container-scoped hints for constraints, and modify `_resolve_supersession_pairs_in_session` to handle them via direct memory_object query.

**Files:**
- Modify: `semantic/agent_conversation_memory_memory.py:279-299` (`build_supersession_hints`)
- Modify: `storage/sqlite_queue.py:608-644` (`_resolve_supersession_pairs_in_session`)
- Test: `tests/test_constraint_quality.py` (add cross-thread dedup test)

- [ ] **Step 1: Write failing test for cross-thread constraint supersession**

Add to `tests/test_constraint_quality.py`:

```python
class TestConstraintCrossThreadDedup:
    """Repeated constraints across threads should be deduplicated via supersession."""

    def test_same_constraint_in_two_threads_supersedes(self, monkeypatch, test_db_url: str) -> None:
        """Second statement of same constraint supersedes the first across threads."""
        with _build_client(monkeypatch, test_db_url) as client:
            # First constraint in thread-1
            events_1 = [
                {
                    "source_type": "chat_message",
                    "source_id": "dedup-thread1-1",
                    "content_type": "text/plain",
                    "content": "do not add any new llm calls to the extraction pipeline",
                    "artifact_kind": "message",
                    "role": "user",
                    "container_ref": CONTAINER,
                    "thread_ref": f"{CONTAINER}:thread-dedup-1",
                    "visibility": "private",
                    "occurred_at": "2026-03-23T10:00:00Z",
                },
            ]
            response = client.post("/items", json=events_1)
            assert response.status_code == 200
            client.app.state.pallium_service.drain_processing_queue(worker_id="test")

            # Same constraint in thread-2
            events_2 = [
                {
                    "source_type": "chat_message",
                    "source_id": "dedup-thread2-1",
                    "content_type": "text/plain",
                    "content": "don't add new llm calls to the pipeline",
                    "artifact_kind": "message",
                    "role": "user",
                    "container_ref": CONTAINER,
                    "thread_ref": f"{CONTAINER}:thread-dedup-2",
                    "visibility": "private",
                    "occurred_at": "2026-03-23T11:00:00Z",
                },
            ]
            response = client.post("/items", json=events_2)
            assert response.status_code == 200
            client.app.state.pallium_service.drain_processing_queue(worker_id="test")

            # Only one active constraint_memory should remain
            storage = client.app.state.pallium_service._storage
            active_constraints = [
                m for m in storage.list_memory_objects(lifecycle="active")
                if m.type == "constraint_memory"
            ]
            assert len(active_constraints) == 1, (
                f"Expected 1 active constraint after dedup, got {len(active_constraints)}: "
                f"{[m.payload.get('constraint_text') for m in active_constraints]}"
            )

    def test_different_constraints_coexist(self, monkeypatch, test_db_url: str) -> None:
        """Different constraints in the same container are NOT deduplicated."""
        with _build_client(monkeypatch, test_db_url) as client:
            events = [
                {
                    "source_type": "chat_message",
                    "source_id": "coexist-1",
                    "content_type": "text/plain",
                    "content": "do not add any new llm calls to the extraction pipeline",
                    "artifact_kind": "message",
                    "role": "user",
                    "container_ref": CONTAINER,
                    "thread_ref": f"{CONTAINER}:thread-coexist-1",
                    "visibility": "private",
                    "occurred_at": "2026-03-23T10:00:00Z",
                },
                {
                    "source_type": "chat_message",
                    "source_id": "coexist-2",
                    "content_type": "text/plain",
                    "content": "do not use the name muxi in documentation or code",
                    "artifact_kind": "message",
                    "role": "user",
                    "container_ref": CONTAINER,
                    "thread_ref": f"{CONTAINER}:thread-coexist-2",
                    "visibility": "private",
                    "occurred_at": "2026-03-23T11:00:00Z",
                },
            ]
            response = client.post("/items", json=events)
            assert response.status_code == 200
            client.app.state.pallium_service.drain_processing_queue(worker_id="test")

            storage = client.app.state.pallium_service._storage
            active_constraints = [
                m for m in storage.list_memory_objects(lifecycle="active")
                if m.type == "constraint_memory"
            ]
            assert len(active_constraints) == 2, (
                f"Expected 2 different constraints to coexist, got {len(active_constraints)}"
            )
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_constraint_quality.py::TestConstraintCrossThreadDedup -x -v`
Expected: FAIL — supersession doesn't work cross-thread for constraints.

- [ ] **Step 3: Modify `build_supersession_hints` for container-scoped constraint hints**

In `semantic/agent_conversation_memory_memory.py`, modify `build_supersession_hints`. For constraint_memory, emit hints with `thread_ref=None` to signal container-wide scope:

Replace the existing function:

```python
def build_supersession_hints(source_item: SourceItem, result: ProcessResult) -> list[SupersessionHint]:
    if not source_item.container_ref or not source_item.thread_ref:
        return []
    hints: list[SupersessionHint] = []
    for memory_object in result.memory_objects:
        if memory_object.type not in {'decision', 'investigation_outcome'} and memory_object.type != CONSTRAINT_MEMORY_TYPE:
            continue
        canonical_key = str(memory_object.payload.get('canonical_key') or '').strip()
        if not canonical_key:
            continue
        # Constraints are container-scoped: same constraint stated in different
        # threads should supersede. Decisions/investigations remain thread-scoped.
        hint_thread_ref = None if memory_object.type == CONSTRAINT_MEMORY_TYPE else source_item.thread_ref
        hints.append(
            SupersessionHint(
                replacement_memory_id=memory_object.id,
                memory_type=memory_object.type,
                canonical_key=canonical_key,
                container_ref=source_item.container_ref,
                thread_ref=hint_thread_ref,
                visibility=source_item.visibility,
            )
        )
    return hints
```

- [ ] **Step 4: Modify `_resolve_supersession_pairs_in_session` to handle container-scoped hints**

In `storage/sqlite_queue.py`, modify `_resolve_supersession_pairs_in_session` to handle `thread_ref=None` by querying memory_objects directly (instead of going through source_items→relations).

Add a constant near the top of the file:
```python
_CONTAINER_SCOPED_SUPERSESSION_TYPES = frozenset({"constraint_memory"})
```

In the method, change the early-exit condition and add a branch for container-scoped resolution:

```python
    def _resolve_supersession_pairs_in_session(
        self,
        session: Session,
        result: ProcessResult,
    ) -> list[tuple[str, str]]:
        if not result.supersession_hints:
            return []
        replacements = {memory_object.id: memory_object for memory_object in result.memory_objects}
        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for hint in result.supersession_hints:
            replacement = replacements.get(hint.replacement_memory_id)
            if replacement is None:
                continue
            if not hint.container_ref or not hint.canonical_key:
                continue

            if hint.thread_ref is None and hint.memory_type in _CONTAINER_SCOPED_SUPERSESSION_TYPES:
                # Container-scoped: query memory_objects directly by type + container + canonical_key
                existing_records = session.scalars(
                    select(MemoryObjectRecord).where(
                        MemoryObjectRecord.container_ref == hint.container_ref,
                        MemoryObjectRecord.type == hint.memory_type,
                        MemoryObjectRecord.lifecycle == "active",
                        MemoryObjectRecord.id != hint.replacement_memory_id,
                    )
                ).all()
                for existing_record in existing_records:
                    existing_payload = self._loads(existing_record.payload_json)
                    existing_key = str(existing_payload.get("canonical_key") or "").strip()
                    if existing_key == hint.canonical_key:
                        pair = (existing_record.id, hint.replacement_memory_id)
                        if pair not in seen:
                            seen.add(pair)
                            pairs.append(pair)
                continue

            # Thread-scoped (existing behavior for decisions/investigations)
            if not hint.thread_ref:
                continue
            thread_item_records = session.scalars(
                select(SourceItemRecord).where(
                    SourceItemRecord.container_ref == hint.container_ref,
                    SourceItemRecord.thread_ref == hint.thread_ref,
                )
            ).all()
            # ... rest of existing thread-scoped logic unchanged ...
```

- [ ] **Step 5: Run the cross-thread dedup test**

Run: `python -m pytest tests/test_constraint_quality.py::TestConstraintCrossThreadDedup -x -v`
Expected: PASS

- [ ] **Step 6: Run full test suite for regressions**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass. Existing supersession tests for decisions/investigations are unaffected (they still use thread_ref).

- [ ] **Step 7: Commit**

```bash
git add semantic/agent_conversation_memory_memory.py storage/sqlite_queue.py tests/test_constraint_quality.py
git commit -m "$(cat <<'EOF'
feat: container-scoped supersession for constraint_memory dedup

Constraints emit supersession hints with thread_ref=None, telling the
storage layer to search across all threads in the container. Repeated
constraints across threads now collapse via canonical_key matching.
Different constraints coexist normally.
EOF
)"
```

---

### Task 5: Final Verification

Ensure all existing tests pass with the combined changes.

**Files:**
- None (verification only)

- [ ] **Step 1: Run complete test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 2: Run the constraint-specific existing tests**

Run: `python -m pytest tests/test_actor_scoped_memory.py -x -v`
Expected: PASS — role guard, visibility suppression, actor_ref tests all unaffected.

- [ ] **Step 3: Verify supersession mechanism for non-constraint types**

Run: `python -m pytest tests/ -x -q -k "supersession or supersede"`
Expected: PASS — decision/investigation supersession unchanged.

---

## Architect Review Notes

**Current fit:** Directly addresses data quality in `constraint_memory`, part of the `agent_conversation_memory` package within the current product slice.

**Boundary compliance:**
- Quality gate → semantic package ✓
- Prompt change → semantic package ✓
- Canonical key generation → semantic package ✓
- Container-scoped supersession resolution → storage layer ✓ (extends existing mechanism without new dependencies)

**Deferred:** Jaccard overlap for arbitrary paraphrases. Would require `storage/` to import from `semantic.common` (boundary violation). The canonical_key approach handles the actual duplicates in the live DB (verbatim repeats). If paraphrases become a problem post-prompt-fix, a `core/text.py` utility migration would enable it cleanly.

**Risk:** The integration tests in Task 4 depend on the LLM stub extracting `constraint_text` from the test messages. If the stub doesn't produce constraint_text for these inputs, the test needs a monkeypatch. Check the stub behavior when implementing.
