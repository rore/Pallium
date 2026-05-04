# Memory Injection & Expand Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the injection text for every memory type so agents get the fields they need to orient, and replace the `/evidence` endpoint with `/expand` that returns both the structured payload and source items.

**Architecture:** Three independent areas: (1) injection text fixes in `_build_raw_injectable_block` and `_task_checkpoint_injection_text` — all package-owned presentation logic; (2) rename `source_expanded_available → expand_available` throughout and replace the length-based trigger with payload-field-presence checks per type; (3) rename `/memory/{id}/evidence → /memory/{id}/expand`, extend the service method and response schema to return filtered payload alongside source items, and rename the MCP tool to match.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic 2, pytest, httpx (MCP client)

> ⚠️ **Prerequisite check:** Tasks 1–5 modify `semantic/agent_conversation_memory_routing_selection.py`. An active constraint says "don't touch routing code until the routing simplification refactor is confirmed done." The injection and expand-availability functions in that file are presentation-layer (not routing logic), but confirm with the project owner before starting if there is any doubt.

---

## File Map

| File | Change |
|---|---|
| `semantic/agent_conversation_memory_routing_selection.py` | Injection text: task_checkpoint, continuity_memory, thread_summary, pattern_memory. Rename `_source_expanded_available` → `_expand_available`, replace trigger logic. Add `_get_conclusion_text` helper. |
| `core/models.py` | Rename `InjectableBlock.source_expanded_available` → `expand_available` |
| `api/schemas.py` | Rename `InjectableBlockResponse.source_expanded_available` → `expand_available`. Rename `MemoryEvidenceResponse` → `MemoryExpandResponse`, add `payload: dict \| None` field. |
| `api/routes.py` | Rename `_serialize_injectable_block` key. Rename endpoint `/evidence` → `/expand`, update handler to call `get_memory_expand`. Add `_EXPAND_PAYLOAD_EXCLUDED_KEYS` constant; filter payload in route handler. |
| `core/service.py` | Rename `get_memory_evidence` → `get_memory_expand`, return `tuple[dict \| None, list[SourceItem]]` (raw, unfiltered). |
| `app/mcp/client.py` | Rename `get_memory_evidence` → `get_memory_expand`, update URL. |
| `app/mcp/server.py` | Rename tool `pallium_get_evidence` → `pallium_expand`, update method call. |
| `tests/test_agent_conversation_memory_routing_injection.py` | Add injection text tests for new fields. |
| `tests/test_source_expanded_flag.py` | Rename field references. Rewrite parametrize cases for payload-presence logic. |
| `tests/test_evidence_drilldown.py` | Rename URL `/evidence` → `/expand`. Rename service method calls. Add `payload` assertions. |

---

## Task 1: task_checkpoint injection — task headline + key_findings

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_selection.py` (lines 849–858, 980–1001)
- Test: `tests/test_agent_conversation_memory_routing_injection.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_agent_conversation_memory_routing_injection.py`:

```python
from core.models import QueryResultItem
from semantic.agent_conversation_memory_routing_selection import (
    _build_injectable_block_from_candidate,
)


def _checkpoint_item(payload: dict) -> QueryResultItem:
    return QueryResultItem(
        result_kind="memory_hit",
        memory_object_id="mo-ck",
        type="task_checkpoint",
        payload=payload,
        score=100,
        evidence=[],
    )


def _block(item: QueryResultItem) -> object:
    return _build_injectable_block_from_candidate({"item": item}, intent="work_resumption")


def test_task_checkpoint_task_field_in_title() -> None:
    item = _checkpoint_item({"task": "Evaluate extraction alternatives", "current_state": "In progress"})
    block = _block(item)
    assert "Evaluate extraction alternatives" in block.title


def test_task_checkpoint_no_task_falls_back_to_plain_title() -> None:
    item = _checkpoint_item({"current_state": "In progress"})
    block = _block(item)
    assert block.title == "Task Checkpoint"


def test_task_checkpoint_key_findings_first_two_in_text() -> None:
    item = _checkpoint_item({
        "task": "T",
        "current_state": "running",
        "key_findings": ["Finding A", "Finding B", "Finding C", "Finding D"],
    })
    block = _block(item)
    assert "Finding A" in block.text
    assert "Finding B" in block.text
    assert "[+2 more]" in block.text
    assert "Finding C" not in block.text


def test_task_checkpoint_single_finding_no_count() -> None:
    item = _checkpoint_item({"task": "T", "key_findings": ["Only one"]})
    block = _block(item)
    assert "Only one" in block.text
    assert "more]" not in block.text


def test_task_checkpoint_no_findings_no_findings_line() -> None:
    item = _checkpoint_item({"task": "T", "current_state": "done"})
    block = _block(item)
    assert "Findings:" not in block.text
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/test_agent_conversation_memory_routing_injection.py::test_task_checkpoint_task_field_in_title tests/test_agent_conversation_memory_routing_injection.py::test_task_checkpoint_key_findings_first_two_in_text -v
```

Expected: FAIL — `AssertionError` (task not in title, findings not in text).

- [ ] **Step 3: Update `_build_raw_injectable_block` — task_checkpoint title**

In `semantic/agent_conversation_memory_routing_selection.py`, replace lines 849–858:

```python
    if item.type == "task_checkpoint":
        task = str(payload.get("task") or "").strip()
        title = f"Task Checkpoint — {task}" if task else "Task Checkpoint"
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title=title,
            text=_task_checkpoint_injection_text(payload),
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
        )
```

- [ ] **Step 4: Update `_task_checkpoint_injection_text` — add key_findings**

Replace lines 980–1001:

```python
def _task_checkpoint_injection_text(payload: dict[str, object]) -> str:
    summary = str(payload.get("summary") or "").strip()
    current_state = str(payload.get("current_state") or "").strip()
    blocker = str(payload.get("blocker_state") or "").strip()
    next_step = str(payload.get("next_step") or "").strip()
    key_findings = [str(f).strip() for f in (payload.get("key_findings") or []) if str(f).strip()]
    parts: list[str] = []
    if blocker:
        parts.append(f"Blocker: {blocker}")
    if current_state and normalize_for_index(current_state) not in normalize_for_index(blocker):
        parts.append(f"Current state: {current_state}")
    elif not blocker and summary:
        parts.append(summary)
    if next_step:
        parts.append(f"Next step: {next_step}")
    if summary and not current_state:
        parts.append(summary)
    if key_findings:
        joined = "; ".join(key_findings[:2])
        suffix = f" [+{len(key_findings) - 2} more]" if len(key_findings) > 2 else ""
        parts.append(f"Findings: {joined}{suffix}")
    return _join_unique_text_parts(parts)
```

- [ ] **Step 5: Run the new tests to confirm they pass**

```
python -m pytest tests/test_agent_conversation_memory_routing_injection.py -k "task_checkpoint" -v
```

Expected: all PASS.

- [ ] **Step 6: Run full test suite**

```
python -m pytest tests/ -x -q
```

Expected: all pass (or pre-existing failures only — no new failures).

- [ ] **Step 7: Commit**

```bash
git add semantic/agent_conversation_memory_routing_selection.py tests/test_agent_conversation_memory_routing_injection.py
git commit -m "feat: add task field to task_checkpoint title and key_findings to injection text"
```

---

## Task 2: continuity_memory injection — Q+A format

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_selection.py` (lines 875–884)
- Test: `tests/test_agent_conversation_memory_routing_injection.py`

- [ ] **Step 1: Write failing tests**

> Note: the `_block` and `_checkpoint_item` helpers from Task 1 are already defined in this test file — do not re-define them.

Add to `tests/test_agent_conversation_memory_routing_injection.py`:

```python
def _continuity_item(payload: dict) -> QueryResultItem:
    return QueryResultItem(
        result_kind="memory_hit",
        memory_object_id="mo-cm",
        type="continuity_memory",
        payload=payload,
        score=100,
        evidence=[],
    )


def test_continuity_memory_shows_question_and_answer() -> None:
    item = _continuity_item({
        "continuity_question": "Which deployment approach are we using?",
        "carry_forward_answer": "Kubernetes on AKS with ephemeral SQLite.",
    })
    block = _build_injectable_block_from_candidate({"item": item}, intent="recall")
    assert "Q: Which deployment approach are we using?" in block.text
    assert "A: Kubernetes on AKS with ephemeral SQLite." in block.text


def test_continuity_memory_answer_only_when_no_question() -> None:
    item = _continuity_item({"carry_forward_answer": "Use Redis for caching."})
    block = _build_injectable_block_from_candidate({"item": item}, intent="recall")
    assert "Use Redis for caching." in block.text
    assert "Q:" not in block.text


def test_continuity_memory_falls_back_to_summary() -> None:
    item = _continuity_item({"summary": "Summary fallback text."})
    block = _build_injectable_block_from_candidate({"item": item}, intent="recall")
    assert "Summary fallback text." in block.text
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/test_agent_conversation_memory_routing_injection.py::test_continuity_memory_shows_question_and_answer -v
```

Expected: FAIL — question not in text.

- [ ] **Step 3: Update `_build_raw_injectable_block` — continuity_memory case**

Replace lines 875–884:

```python
    if item.type == "continuity_memory":
        question = str(payload.get("continuity_question") or "").strip()
        answer = str(payload.get("carry_forward_answer") or payload.get("summary") or "").strip()
        if question and answer:
            text = f"Q: {question}\nA: {answer}"
        else:
            text = answer or question
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Carry Forward",
            text=text,
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
        )
```

- [ ] **Step 4: Run new tests**

```
python -m pytest tests/test_agent_conversation_memory_routing_injection.py -k "continuity" -v
```

Expected: all PASS.

- [ ] **Step 5: Run full suite**

```
python -m pytest tests/ -x -q
```

Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
git add semantic/agent_conversation_memory_routing_selection.py tests/test_agent_conversation_memory_routing_injection.py
git commit -m "feat: inject continuity_memory as Q+A pair instead of answer-only"
```

---

## Task 3: thread_summary and pattern_memory injection — conclusions

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_selection.py` (lines 885–935)
- Test: `tests/test_agent_conversation_memory_routing_injection.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_agent_conversation_memory_routing_injection.py`:

```python
def _thread_summary_item(payload: dict) -> QueryResultItem:
    return QueryResultItem(
        result_kind="memory_hit",
        memory_object_id="mo-ts",
        type="thread_summary",
        payload=payload,
        score=100,
        evidence=[],
    )


def _pattern_item(payload: dict) -> QueryResultItem:
    return QueryResultItem(
        result_kind="memory_hit",
        memory_object_id="mo-pm",
        type="pattern_memory",
        payload=payload,
        score=100,
        evidence=[],
    )


def test_thread_summary_conclusions_appear_in_text() -> None:
    item = _thread_summary_item({
        "summary": "Thread about catalog sync.",
        "conclusions": [
            {"type": "finding", "text": "Duplicate holds traced to stale ordering."},
            {"type": "finding", "text": "Fix deployed in v2.3."},
            {"type": "finding", "text": "Third conclusion here."},
        ],
    })
    block = _build_injectable_block_from_candidate({"item": item}, intent="recall")
    assert "Duplicate holds traced to stale ordering." in block.text
    assert "Fix deployed in v2.3." in block.text
    assert "[+1 more]" in block.text
    assert "Third conclusion here." not in block.text


def test_thread_summary_no_conclusions_text_is_summary_only() -> None:
    item = _thread_summary_item({"summary": "Just the summary."})
    block = _build_injectable_block_from_candidate({"item": item}, intent="recall")
    assert block.text == "Just the summary."
    assert "Conclusions:" not in block.text


def test_pattern_memory_first_conclusion_inline() -> None:
    item = _pattern_item({
        "summary": "Pattern: delayed sync.",
        "conclusions": [
            {"type": "finding", "text": "Stale ordering is root cause."},
            {"type": "finding", "text": "Seen in three incidents."},
        ],
    })
    block = _build_injectable_block_from_candidate({"item": item}, intent="recall")
    assert "Stale ordering is root cause." in block.text
    assert "[+1 more]" in block.text
    assert "Seen in three incidents." not in block.text


def test_pattern_memory_single_conclusion_no_count() -> None:
    item = _pattern_item({
        "summary": "Pattern: one thing.",
        "conclusions": [{"type": "finding", "text": "Only finding."}],
    })
    block = _build_injectable_block_from_candidate({"item": item}, intent="recall")
    assert "Only finding." in block.text
    assert "more]" not in block.text
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/test_agent_conversation_memory_routing_injection.py::test_thread_summary_conclusions_appear_in_text tests/test_agent_conversation_memory_routing_injection.py::test_pattern_memory_first_conclusion_inline -v
```

Expected: FAIL.

- [ ] **Step 3: Add `_get_conclusion_text` helper**

Add near `_join_unique_text_parts` in `semantic/agent_conversation_memory_routing_selection.py` (after line 1016):

```python
def _get_conclusion_text(conclusion: object) -> str:
    if isinstance(conclusion, dict):
        return str(conclusion.get("text") or "").strip()
    return str(conclusion).strip()
```

- [ ] **Step 4: Update `_build_raw_injectable_block` — thread_summary case**

Replace lines 926–936:

```python
    if item.type in {"thread_summary"}:
        summary_text = str(payload.get("summary") or "").strip()
        conclusions = [c for c in (payload.get("conclusions") or []) if c]
        parts: list[str] = [summary_text] if summary_text else []
        if conclusions:
            texts = [_get_conclusion_text(c) for c in conclusions[:2]]
            texts = [t for t in texts if t]
            if texts:
                joined = "; ".join(texts)
                suffix = f" [+{len(conclusions) - 2} more]" if len(conclusions) > 2 else ""
                parts.append(f"Conclusions: {joined}{suffix}")
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Thread Summary",
            text=_join_unique_text_parts(parts),
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
        )
```

- [ ] **Step 5: Update `_build_raw_injectable_block` — pattern_memory case**

Replace lines 885–894:

```python
    if item.type == "pattern_memory":
        summary_text = str(payload.get("summary") or "").strip()
        conclusions = [c for c in (payload.get("conclusions") or []) if c]
        parts: list[str] = [summary_text] if summary_text else []
        if conclusions:
            first_text = _get_conclusion_text(conclusions[0])
            if first_text:
                suffix = f" [+{len(conclusions) - 1} more]" if len(conclusions) > 1 else ""
                parts.append(f"{first_text}{suffix}")
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Pattern Memory",
            text=_join_unique_text_parts(parts),
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
        )
```

- [ ] **Step 6: Run new tests**

```
python -m pytest tests/test_agent_conversation_memory_routing_injection.py -k "thread_summary or pattern_memory" -v
```

Expected: all PASS.

- [ ] **Step 7: Run full suite**

```
python -m pytest tests/ -x -q
```

Expected: no new failures.

- [ ] **Step 8: Commit**

```bash
git add semantic/agent_conversation_memory_routing_selection.py tests/test_agent_conversation_memory_routing_injection.py
git commit -m "feat: inject conclusions into thread_summary and pattern_memory injection text"
```

---

## Verification: Work Resumption Benchmark (after Tasks 1–3)

After completing Tasks 1–3, verify that the injection text improvements are observable end-to-end using the agent simulation harness.

- [ ] **Step 1: Start the server**

```bash
python -m app.run serve --host 127.0.0.1 --port 8000
```

- [ ] **Step 2: Run the agent simulation**

```bash
python -m app.agent_simulation
```

- [ ] **Step 3: Spot-check injection output**

In the simulation trace, look for injected blocks with type `task_checkpoint`, `continuity_memory`, `thread_summary`, or `pattern_memory`. Confirm:
- `task_checkpoint` blocks include the `task` name in the title and `Findings:` line if `key_findings` present
- `continuity_memory` blocks show `Q: ... / A: ...` format
- `thread_summary` blocks show `Conclusions: ...` suffix when conclusions are present
- `pattern_memory` blocks show the first conclusion inline

If any of these are absent, the routing is not selecting these types — investigate routing policy before continuing to Task 4.

---

## Task 4: Rename source_expanded_available → expand_available throughout

**Files:**
- Modify: `core/models.py` (line 257)
- Modify: `api/schemas.py` (line 160)
- Modify: `api/routes.py` (serialization function)
- Modify: `semantic/agent_conversation_memory_routing_selection.py` (function name + all uses)
- Test: `tests/test_source_expanded_flag.py`

- [ ] **Step 1: Rename field in `core/models.py`**

In `core/models.py` line 257, change:

```python
    source_expanded_available: bool = False
```

to:

```python
    expand_available: bool = False
```

- [ ] **Step 2: Rename field in `api/schemas.py`**

In `api/schemas.py` line 160, change:

```python
    source_expanded_available: bool = False
```

to:

```python
    expand_available: bool = False
```

- [ ] **Step 3: Update serialization in `api/routes.py`**

In `api/routes.py`, in `_serialize_injectable_block`, change:

```python
        "source_expanded_available": block.source_expanded_available,
```

to:

```python
        "expand_available": block.expand_available,
```

- [ ] **Step 4: Rename function and usages in `routing_selection.py`**

In `semantic/agent_conversation_memory_routing_selection.py`:

**a)** Rename the function (around line 796):

```python
def _expand_available(item: QueryResultItem) -> bool:
    return (
        item.type in _SOURCE_EXPANDED_TYPES
        and item.envelope is not None
        and item.envelope.source_content_length > _SOURCE_EXPANDED_THRESHOLD
    )
```

**b)** Update the call site in `_build_injectable_block_from_candidate` (around line 975):

```python
        if _expand_available(item):
            block = replace(block, expand_available=True)
```

**c)** Update the note branch (around line 957) — change `source_expanded_available=truncated` to `expand_available=truncated`.

- [ ] **Step 5: Update field references in `tests/test_source_expanded_flag.py`**

Replace all occurrences of `source_expanded_available` with `expand_available` in that file. There are references at lines 101, 125, 158.

Run a targeted replace:

```
python -m pytest tests/test_source_expanded_flag.py -v
```

If tests fail with `AttributeError: 'InjectableBlock' object has no attribute 'source_expanded_available'`, confirm the replacement is complete.

- [ ] **Step 6: Run full suite**

```
python -m pytest tests/ -x -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add core/models.py api/schemas.py api/routes.py semantic/agent_conversation_memory_routing_selection.py tests/test_source_expanded_flag.py
git commit -m "refactor: rename source_expanded_available to expand_available throughout"
```

---

## Task 5: Fix expand availability — payload-presence-based per-type logic

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_selection.py` (the `_expand_available` function and `_SOURCE_EXPANDED_TYPES` / `_SOURCE_EXPANDED_THRESHOLD` constants)
- Test: `tests/test_source_expanded_flag.py`

- [ ] **Step 1: Write new test cases**

Replace the parametrize block in `tests/test_source_expanded_flag.py` (section B, starting around line 109). Keep sections A (codec roundtrip), D (source_evidence never flagged), E (null envelope) unchanged. Replace the B block with:

> Also remove the `_TYPE_PAYLOADS` dict in section B — it becomes dead code once the per-type parametrize cases below replace the old block. Delete the dict and any variables referencing it.

```python
@pytest.mark.parametrize(("mem_type", "payload", "expected"), [
    # decision: expand when evidence text present
    ("decision", {"decision": "x", "decision_evidence_text": "verbatim quote"}, True),
    ("decision", {"decision": "x"}, False),
    ("decision", {"decision": "x", "decision_evidence_text": ""}, False),
    # investigation_outcome: expand when evidence text present
    ("investigation_outcome", {"investigation_outcome": "x", "investigation_evidence_text": "verbatim"}, True),
    ("investigation_outcome", {"investigation_outcome": "x"}, False),
    # task_checkpoint: expand when key_findings or work_artifacts present
    ("task_checkpoint", {"summary": "x", "key_findings": ["f1", "f2"]}, True),
    ("task_checkpoint", {"summary": "x", "selected_work_artifacts": [{"text": "a"}]}, True),
    ("task_checkpoint", {"summary": "x"}, False),
    ("task_checkpoint", {"summary": "x", "key_findings": []}, False),
    # thread_summary: expand when conclusions or work_artifacts present
    ("thread_summary", {"summary": "x", "conclusions": [{"type": "t", "text": "c"}]}, True),
    ("thread_summary", {"summary": "x", "selected_work_artifacts": [{"text": "a"}]}, True),
    ("thread_summary", {"summary": "x"}, False),
    # pattern_memory: expand when >1 conclusion
    ("pattern_memory", {"summary": "x", "conclusions": [{"text": "a"}, {"text": "b"}]}, True),
    ("pattern_memory", {"summary": "x", "conclusions": [{"text": "only one"}]}, False),
    ("pattern_memory", {"summary": "x"}, False),
    # constraint_memory: expand when evidence_context present
    ("constraint_memory", {"constraint_text": "x", "evidence_context": "full ctx"}, True),
    ("constraint_memory", {"constraint_text": "x"}, False),
    # types with no expand
    ("fact_summary", {"summary": "x"}, False),
    ("interest", {"interest_text": "x"}, False),
    ("atomic_fact", {"statement": "x"}, False),
])
def test_expand_available_per_type(mem_type: str, payload: dict, expected: bool) -> None:
    item = _item(mem_type, payload, source_content_length=500)
    block = _block(item)
    assert block.expand_available is expected, f"type={mem_type}, payload={payload}"
```

- [ ] **Step 2: Run new tests to confirm they fail**

```
python -m pytest tests/test_source_expanded_flag.py::test_expand_available_per_type -v
```

Expected: most cases FAIL because logic still uses length threshold.

- [ ] **Step 3: Replace `_expand_available` logic in `routing_selection.py`**

Remove `_SOURCE_EXPANDED_TYPES` and `_SOURCE_EXPANDED_THRESHOLD` constants. Replace `_expand_available` with:

```python
def _expand_available(item: QueryResultItem) -> bool:
    if item.envelope is None:
        return False
    payload = item.payload or {}
    if item.type == "decision":
        return bool(str(payload.get("decision_evidence_text") or "").strip())
    if item.type == "investigation_outcome":
        return bool(str(payload.get("investigation_evidence_text") or "").strip())
    if item.type == "task_checkpoint":
        return bool(payload.get("key_findings")) or bool(payload.get("selected_work_artifacts"))
    if item.type == "thread_summary":
        return bool(payload.get("conclusions")) or bool(payload.get("selected_work_artifacts"))
    if item.type == "pattern_memory":
        conclusions = payload.get("conclusions") or []
        return len(conclusions) > 1
    if item.type == CONSTRAINT_MEMORY_TYPE:
        return bool(str(payload.get("evidence_context") or "").strip())
    return False
```

- [ ] **Step 4: Run new tests**

```
python -m pytest tests/test_source_expanded_flag.py -v
```

Expected: all PASS (codec roundtrip, new per-type cases, source_evidence never flagged, null envelope).

- [ ] **Step 5: Run full suite**

```
python -m pytest tests/ -x -q
```

Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
git add semantic/agent_conversation_memory_routing_selection.py tests/test_source_expanded_flag.py
git commit -m "feat: replace source-length expand trigger with payload-field-presence checks per type"
```

---

## Task 6: Rename /evidence → /expand and add payload to response

**Files:**
- Modify: `core/service.py` (rename method, add payload return)
- Modify: `api/schemas.py` (rename response class, add `payload` field)
- Modify: `api/routes.py` (rename route + handler)
- Test: `tests/test_evidence_drilldown.py`

- [ ] **Step 1: Rename service method in `core/service.py`**

Rename `get_memory_evidence` to `get_memory_expand` and change its return type to `tuple[dict | None, list[SourceItem]]`. The service returns the raw, unfiltered payload — payload key filtering is a presentation concern handled by the route handler in Step 3.

```python
def get_memory_expand(
    self, memory_object_id: str, *, container_ref: str | None = None, query_actor_ref: str | None = None,
) -> tuple[dict | None, list[SourceItem]]:
    """Return structured payload and source items for a memory object."""
    memory_object = self._storage.get_memory_object(memory_object_id)
    effective_container = container_ref or memory_object.container_ref
    if container_ref and memory_object.visibility != "global" and memory_object.container_ref != container_ref:
        raise KeyError(memory_object_id)
    refs = self._storage.get_evidence_for_memory_object(memory_object_id)
    items: list[SourceItem] = []
    for ref in refs:
        try:
            item = self._storage.get_source_item(ref.source_item_id)
        except KeyError:
            continue
        effective_actor_ref = query_actor_ref or memory_object.actor_ref
        if is_visible(item.visibility, item.container_ref, effective_container, item.actor_ref, query_actor_ref=effective_actor_ref):
            items.append(item)
    return memory_object.payload, items
```

- [ ] **Step 2: Update `api/schemas.py` — rename response class, add payload field**

Rename `MemoryEvidenceResponse` to `MemoryExpandResponse` and add the `payload` field:

```python
class MemoryExpandResponse(BaseModel):
    memory_object_id: str
    payload: dict | None = None
    items: list[MemoryEvidenceItemResponse]
```

Update the import used in routes.py accordingly (`MemoryEvidenceResponse` → `MemoryExpandResponse`).

- [ ] **Step 3: Update `api/routes.py` — rename route and handler, add payload filtering**

Change the import at the top to use `MemoryExpandResponse` instead of `MemoryEvidenceResponse`.

Add the constant near the top of `api/routes.py` (after imports, before route registration):

```python
_EXPAND_PAYLOAD_EXCLUDED_KEYS: frozenset[str] = frozenset({
    "semantic_provenance",
    "retrieval_enrichment",
    "canonical_key",
})
```

Replace the `/evidence` route:

```python
    @router.get("/memory/{memory_object_id}/expand", response_model=MemoryExpandResponse)
    def get_memory_expand(memory_object_id: str, container_ref: str | None = None) -> MemoryExpandResponse:
        try:
            raw_payload, items = service.get_memory_expand(memory_object_id, container_ref=container_ref)
        except KeyError:
            raise HTTPException(status_code=404, detail="memory object not found")
        filtered: dict | None = None
        if raw_payload:
            raw = raw_payload or {}
            filtered = {
                k: v for k, v in raw.items()
                if k not in _EXPAND_PAYLOAD_EXCLUDED_KEYS and not k.startswith("_")
            } or None
        return MemoryExpandResponse(
            memory_object_id=memory_object_id,
            payload=filtered,
            items=[
                MemoryEvidenceItemResponse(
                    source_item_id=item.id,
                    source_type=item.source_type,
                    source_id=item.source_id,
                    content=item.content,
                    role=item.role,
                    actor_ref=item.actor_ref,
                    occurred_at=item.occurred_at,
                    thread_ref=item.thread_ref,
                    artifact_kind=item.artifact_kind,  # type: ignore[arg-type]
                )
                for item in items
            ],
        )
```

- [ ] **Step 4: Write failing tests**

In `tests/test_evidence_drilldown.py`, apply these renames before adding new tests:
- Class `TestGetMemoryEvidence` → `TestGetMemoryExpand`
- Class `TestMemoryEvidenceEndpoint` → `TestMemoryExpandEndpoint`
- All `service.get_memory_evidence(...)` calls → `service.get_memory_expand(...)`
- All `/memory/{id}/evidence` URL strings → `/memory/{id}/expand`

After renaming, add these new test methods:

```python
# In TestGetMemoryExpand (renamed from TestGetMemoryEvidence):

    def test_returns_filtered_payload(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        mo = MemoryObject(
            type="decision",
            schema_id="test",
            schema_version="1",
            payload={
                "decision": "use RRF",
                "rationale_text": "better recall",
                "canonical_key": "should-be-excluded",
                "semantic_provenance": {"model": "should-be-excluded"},
            },
            container_ref="container-a",
            visibility="private",
        )
        storage.create_memory_object(mo)

        with TestClient(app) as client:
            response = client.get(f"/memory/{mo.id}/expand", params={"container_ref": "container-a"})

        assert response.status_code == 200
        body = response.json()
        assert body["payload"]["decision"] == "use RRF"
        assert body["payload"]["rationale_text"] == "better recall"
        assert "canonical_key" not in body["payload"]
        assert "semantic_provenance" not in body["payload"]

# In TestMemoryExpandEndpoint (renamed from TestMemoryEvidenceEndpoint):

    def test_happy_path(self, test_db_url: str) -> None:
        # ... same setup ...
        with TestClient(app) as client:
            response = client.get(f"/memory/{mo.id}/expand", params={"container_ref": "container-a"})
        assert response.status_code == 200
        body = response.json()
        assert body["memory_object_id"] == mo.id
        assert len(body["items"]) == 1
        assert body["items"][0]["content"] == "original text"

    def test_payload_included_in_expand_response(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        mo = MemoryObject(
            type="decision",
            schema_id="test",
            schema_version="1",
            payload={"decision": "use RRF", "rationale_text": "fast"},
            container_ref="container-a",
            visibility="private",
        )
        storage.create_memory_object(mo)

        with TestClient(app) as client:
            response = client.get(f"/memory/{mo.id}/expand", params={"container_ref": "container-a"})

        assert response.status_code == 200
        body = response.json()
        assert body["payload"]["decision"] == "use RRF"
        assert body["payload"]["rationale_text"] == "fast"

    def test_wrong_container_returns_404(self, test_db_url: str) -> None:
        # ... same setup, but call /expand ...
        with TestClient(app) as client:
            response = client.get(f"/memory/{mo.id}/expand", params={"container_ref": "container-b"})
        assert response.status_code == 404

    def test_expand_payload_is_null_when_memory_object_has_no_payload(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        mo = MemoryObject(
            type="decision",
            schema_id="test",
            schema_version="1",
            payload=None,
            container_ref="container-a",
            visibility="private",
        )
        storage.create_memory_object(mo)

        with TestClient(app) as client:
            response = client.get(f"/memory/{mo.id}/expand", params={"container_ref": "container-a"})

        assert response.status_code == 200
        body = response.json()
        assert body["payload"] is None
```

- [ ] **Step 5: Run new tests to confirm they fail**

```
python -m pytest tests/test_evidence_drilldown.py -v
```

Expected: failures due to old URL `/evidence` and old method name `get_memory_evidence`.

- [ ] **Step 6: Run tests after implementation**

```
python -m pytest tests/test_evidence_drilldown.py -v
```

Expected: all PASS.

- [ ] **Step 7: Run full suite**

```
python -m pytest tests/ -x -q
```

Expected: no new failures.

- [ ] **Step 8: Commit**

```bash
git add core/service.py api/schemas.py api/routes.py tests/test_evidence_drilldown.py
git commit -m "feat: rename /evidence to /expand and include filtered payload in response"
```

---

## Task 7: Rename MCP tool pallium_get_evidence → pallium_expand

**Files:**
- Modify: `app/mcp/client.py` (rename method, update URL)
- Modify: `app/mcp/server.py` (rename tool, update method call and docstring)

- [ ] **Step 1: Update `app/mcp/client.py`**

Rename method `get_memory_evidence` → `get_memory_expand` and update the URL from `/evidence` to `/expand`:

```python
    async def get_memory_expand(self, memory_object_id: str) -> dict[str, Any]:
        """Fetch structured payload and source items for a memory object (expanded view)."""
        params: dict[str, str] = {}
        if self._ctx.container_ref:
            params["container_ref"] = self._ctx.container_ref
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=30.0) as http:
                response = await http.get(f"/memory/{memory_object_id}/expand", params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            try:
                body = exc.response.json()
            except Exception:
                body = exc.response.text
            return {"error": str(exc), "detail": body}
        except Exception as exc:
            return {"error": str(exc)}
```

- [ ] **Step 2: Update `app/mcp/server.py`**

Rename the tool from `pallium_get_evidence` to `pallium_expand` and update the client call:

```python
    @server.tool()
    async def pallium_expand(
        memory_object_id: str,
        container_ref: str | None = None,
        actor_ref: str | None = None,
        visibility: str | None = None,
    ) -> str:
        """Get the full structured payload and source items for a memory object.

        Use when a memory card has [+expand] available and you need:
        - The complete structured fields (decision evidence, key findings, conclusions, etc.)
        - The original source conversation turns that backed the memory

        Returns a JSON object with 'payload' (structured fields) and 'items' (source turns).
        """
        # (keep the existing context setup logic unchanged)
        ...
        result = await client.get_memory_expand(memory_object_id)
        return json.dumps(result, indent=2, default=str)
```

- [ ] **Step 3: Run full suite**

```
python -m pytest tests/ -x -q
```

Expected: all pass (MCP tools have no direct unit tests in the test suite).

- [ ] **Step 4: Smoke-test the MCP tool manually (optional)**

Start the server and confirm the tool is listed:

```bash
python -m app.run serve --host 127.0.0.1 --port 8000
```

In a separate terminal, query the MCP tool list to verify `pallium_expand` appears and `pallium_get_evidence` does not.

- [ ] **Step 5: Commit**

```bash
git add app/mcp/client.py app/mcp/server.py
git commit -m "feat: rename pallium_get_evidence MCP tool to pallium_expand"
```

---

## Self-Review

**Spec coverage:**
- task_checkpoint `task` field in title: Task 1 ✓
- task_checkpoint `key_findings` in injection: Task 1 ✓
- continuity_memory Q+A format: Task 2 ✓
- thread_summary conclusions: Task 3 ✓
- pattern_memory first conclusion: Task 3 ✓
- Rename `source_expanded_available → expand_available`: Task 4 ✓
- Payload-presence-based expand availability per type: Task 5 ✓
- Rename `/evidence → /expand`: Task 6 ✓
- Add `payload` to expand response: Task 6 ✓
- Filter internal keys from payload: Task 6 ✓
- Rename MCP tool: Task 7 ✓

**Out of scope (per architect review):** evidence quote truncation in injection, atomic_fact dead code cleanup, fact_summary intent gating, new MCP tool (tool is renamed not added).

**Architect review fixes applied:**
- F1 (Critical): `_EXPAND_PAYLOAD_EXCLUDED_KEYS` moved to `api/routes.py`; service returns raw unfiltered payload
- F2: Task 5 Step 1 notes removal of dead `_TYPE_PAYLOADS` dict
- F3: Task 6 Step 4 lists all class/method renames explicitly
- F4: Fixed `len(list(conclusions)) > 1` → `len(conclusions) > 1`
- F5: Task 2 Step 1 notes `_block` helper is already available from Task 1
- F6: Added `test_expand_payload_is_null_when_memory_object_has_no_payload`
- Verification gap: Work resumption benchmark added after Task 3

**Placeholder scan:** No TBDs, no "similar to Task N" shortcuts, all code blocks complete.

**Type consistency:** `_expand_available` (Task 4 rename) used consistently in Task 5 replacement. `get_memory_expand` returns `tuple[dict | None, list[SourceItem]]` used consistently in Task 6 route handler. `MemoryExpandResponse` defined in Task 6 Step 2 used in route in Step 3.

**One gap found and added:** Task 6 Step 4 tests cover the payload-filtered case (excluded keys) but not the `no_container_ref` and `visibility_filtering` cases from the original test class — these are covered by keeping the renamed versions of existing tests, which Task 6 Step 4 instructs to do via "rename all `/evidence` references to `/expand` and all `get_memory_evidence` calls to `get_memory_expand`."
