# FTS5 Lexical Retrieval Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the O(N) full-table-scan lexical search with SQLite FTS5 inverted-index lookup + BM25 scoring.

**Architecture:** A standalone `lexical_fts` FTS5 virtual table is created alongside `index_entries`. Write and delete paths maintain both tables in the same transaction. The search path uses FTS5 `MATCH` + `bm25()` instead of loading all records into Python. BM25 scores (float) replace IDF integers. Downstream routing thresholds are recalibrated.

**Tech Stack:** SQLite FTS5 (bundled in Python's sqlite3), SQLAlchemy raw SQL for FTS5 operations.

**Spec:** `docs/specs/2026-04-07-fts5-lexical-retrieval-design.md`

---

## File Map

| File | Responsibility | Change |
|---|---|---|
| `storage/sqlite_schema.py` | Schema init | Create FTS5 table + availability check |
| `storage/sqlite.py` | Write path | FTS5 insert in `create_index_entry()`, container_ref resolution |
| `storage/sqlite_retention.py` | Delete path | Extract `_delete_index_entry_in_session()` helper with FTS5 cleanup |
| `storage/sqlite_search.py` | Search path | Full rewrite: FTS5 MATCH + BM25 + matched_tokens reconstruction |
| `storage/base.py` | Data contract | `IndexSearchHit.score: int` → `float` |
| `core/models.py` | Data contract | `QueryResultItem.lexical_score: int` → `float` |
| `api/schemas.py` | API contract | `RetrievalTraceHitResponse.score` → `float` |
| `retrieval/composite.py` | Fusion | Pass-through float `lexical_raw_score` |
| `semantic/agent_conversation_memory_routing_constants.py` | Scoring constants | Add `normalize_lexical_score()` utility; all lexical thresholds expressed in normalized 0–1 space |
| `semantic/agent_conversation_memory_routing_injection.py` | Routing | Call `normalize_lexical_score()`; thresholds in 0–1 space |
| `semantic/agent_conversation_memory_routing_floor.py` | Routing | Call `normalize_lexical_score()`; thresholds in 0–1 space |
| `semantic/agent_conversation_memory_routing_scoring.py` | Routing | Call `normalize_lexical_score()` in `_compute_quality_score()` |
| `semantic/agent_conversation_memory_routing_justification.py` | Routing | Call `normalize_lexical_score()` |
| `semantic/agent_conversation_memory_routing_selection.py` | Routing | Call `normalize_lexical_score()` |

---

### Task 1: FTS5 Schema Creation + Availability Check

**Files:**
- Modify: `storage/sqlite_schema.py`
- Test: `tests/test_storage_sqlite.py`

- [ ] **Step 1: Write failing test — FTS5 table exists after init**

Add to `tests/test_storage_sqlite.py`:

```python
def test_fts5_lexical_table_created(test_db_url: str) -> None:
    """Schema init must create the lexical_fts FTS5 virtual table."""
    from sqlalchemy import create_engine, text as sa_text
    storage = SQLiteStorageProvider(test_db_url)
    engine = create_engine(test_db_url)
    with engine.connect() as conn:
        tables = [
            row[0] for row in conn.execute(
                sa_text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        ]
    assert "lexical_fts" in tables
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_storage_sqlite.py::test_fts5_lexical_table_created -x -v`
Expected: FAIL — `lexical_fts` not in tables.

- [ ] **Step 3: Implement FTS5 table creation and availability check**

In `storage/sqlite_schema.py`, add to `_initialize_schema()` after the existing `_ensure_indexes()` call:

```python
self._ensure_fts5_table()
```

Add the methods to `SQLiteSchemaMixin`:

```python
def _ensure_fts5_available(self, connection) -> None:
    """Verify FTS5 extension is available. Fail fast with clear message."""
    try:
        connection.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_check USING fts5(x)"
        ))
        connection.execute(text("DROP TABLE IF EXISTS _fts5_check"))
    except Exception as exc:
        raise RuntimeError(
            "SQLite FTS5 extension is not available. "
            "Pallium requires FTS5 for lexical search. "
            "Python 3.9+ bundles SQLite with FTS5 enabled by default."
        ) from exc

def _ensure_fts5_table(self) -> None:
    with self._engine.begin() as connection:
        self._ensure_fts5_available(connection)
        connection.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS lexical_fts USING fts5("
            "text_view, "
            "index_entry_id UNINDEXED, "
            "target_kind UNINDEXED, "
            "target_id UNINDEXED, "
            "text_view_name UNINDEXED, "
            "container_ref UNINDEXED, "
            "tokenize='unicode61 remove_diacritics 2'"
            ")"
        ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_storage_sqlite.py::test_fts5_lexical_table_created -x -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add storage/sqlite_schema.py tests/test_storage_sqlite.py
git commit -m "feat: create FTS5 lexical_fts table on schema init"
```

---

### Task 2: Write Path — FTS5 Insert on Lexical Entry Creation

**Files:**
- Modify: `storage/sqlite.py`
- Test: `tests/test_storage_sqlite.py`

- [ ] **Step 1: Write failing test — lexical entry populates FTS5**

Add to `tests/test_storage_sqlite.py`:

```python
def test_create_lexical_index_entry_populates_fts5(test_db_url: str) -> None:
    """Creating a lexical index entry must also insert into lexical_fts."""
    from sqlalchemy import create_engine, text as sa_text
    storage = SQLiteStorageProvider(test_db_url)

    source_item = SourceItem(
        source_type="chat_message",
        source_id="fts5-write-test",
        content_type="text/plain",
        content="Test content for FTS5 write path",
        container_ref="test:container",
        visibility="container",
    )
    storage.create_source_item(source_item)

    index_entry = IndexEntry(
        target_kind="source_item",
        target_id=source_item.id,
        index_type="lexical",
        text_view="reservation ordering system updates",
    )
    storage.create_index_entry(index_entry)

    # Verify FTS5 row exists with correct metadata
    engine = create_engine(test_db_url)
    with engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT index_entry_id, target_kind, target_id, container_ref, text_view FROM lexical_fts")
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == index_entry.id
    assert rows[0][1] == "source_item"
    assert rows[0][2] == source_item.id
    assert rows[0][3] == "test:container"
    assert rows[0][4] == "reservation ordering system updates"


def test_create_vector_index_entry_does_not_populate_fts5(test_db_url: str) -> None:
    """Vector index entries must NOT be inserted into lexical_fts."""
    from sqlalchemy import create_engine, text as sa_text
    storage = SQLiteStorageProvider(test_db_url)

    index_entry = IndexEntry(
        target_kind="source_item",
        target_id="src-vec-1",
        index_type="vector",
        text_view="some vector content",
        provider_name="onnx",
    )
    storage.create_index_entry(index_entry)

    engine = create_engine(test_db_url)
    with engine.connect() as conn:
        count = conn.execute(
            sa_text("SELECT COUNT(*) FROM lexical_fts")
        ).scalar()
    assert count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_storage_sqlite.py::test_create_lexical_index_entry_populates_fts5 tests/test_storage_sqlite.py::test_create_vector_index_entry_does_not_populate_fts5 -x -v`
Expected: First test FAIL (FTS5 row count is 0).

- [ ] **Step 3: Implement FTS5 insert in create_index_entry**

In `storage/sqlite.py`, add the container_ref resolver and modify `create_index_entry()`:

```python
import json
from sqlalchemy import text as sa_text
```

Add method to `SQLiteStorageProvider`:

```python
def _resolve_container_ref_in_session(
    self, session, target_kind: str, target_id: str,
) -> str | None:
    """Resolve container_ref for an index target within an existing session."""
    if target_kind == "source_item":
        record = session.get(SourceItemRecord, target_id)
        return record.container_ref if record else None
    if target_kind == "memory_object":
        record = session.get(MemoryObjectRecord, target_id)
        if record is None:
            return None
        if record.container_ref is not None:
            return record.container_ref
        # Fallback: envelope_json → scope.container_ref
        if record.envelope_json:
            try:
                envelope = json.loads(record.envelope_json)
                return envelope.get("scope", {}).get("container_ref")
            except (json.JSONDecodeError, TypeError):
                return None
        return None
    return None
```

Replace `create_index_entry()`:

```python
def create_index_entry(self, index_entry: IndexEntry) -> None:
    record = IndexEntryRecord(
        id=index_entry.id,
        target_kind=index_entry.target_kind,
        target_id=index_entry.target_id,
        index_type=index_entry.index_type,
        text_view=index_entry.text_view,
        text_view_name=index_entry.text_view_name,
        provider_name=index_entry.provider_name,
        provider_version=index_entry.provider_version,
    )
    with self._session_factory.begin() as session:
        session.add(record)
        if index_entry.index_type == "lexical":
            container_ref = self._resolve_container_ref_in_session(
                session, index_entry.target_kind, index_entry.target_id,
            )
            session.execute(
                sa_text(
                    "INSERT INTO lexical_fts"
                    "(text_view, index_entry_id, target_kind, target_id, text_view_name, container_ref) "
                    "VALUES (:text_view, :index_entry_id, :target_kind, :target_id, :text_view_name, :container_ref)"
                ),
                {
                    "text_view": index_entry.text_view,
                    "index_entry_id": index_entry.id,
                    "target_kind": index_entry.target_kind,
                    "target_id": index_entry.target_id,
                    "text_view_name": index_entry.text_view_name,
                    "container_ref": container_ref,
                },
            )
```

Note: `sa_text` is the alias for `sqlalchemy.text` — use whatever import name the file already uses. Check the existing imports; `sqlite.py` uses `from sqlalchemy import ... text ...` already. Use that.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_storage_sqlite.py::test_create_lexical_index_entry_populates_fts5 tests/test_storage_sqlite.py::test_create_vector_index_entry_does_not_populate_fts5 -x -v`
Expected: PASS

- [ ] **Step 5: Run full existing tests to verify no breakage**

Run: `python -m pytest tests/test_storage_sqlite.py -x -q`
Expected: All existing tests pass (FTS5 insert is additive, search still uses old path).

- [ ] **Step 6: Write test — memory_object container_ref resolved from envelope fallback**

Add to `tests/test_storage_sqlite.py`:

```python
def test_fts5_resolves_container_ref_from_memory_object_envelope(test_db_url: str) -> None:
    """container_ref must be resolved from envelope_json when direct column is NULL."""
    from sqlalchemy import create_engine, text as sa_text
    storage = SQLiteStorageProvider(test_db_url)

    # Create memory_object with container_ref only in envelope
    mo = MemoryObject(
        type="decision",
        schema_id="test.decision",
        schema_version="v1",
        payload={"decision": "test"},
        visibility="container",
        container_ref=None,  # NULL on direct column
        envelope={"schema_id": "core.memory_envelope", "schema_version": "v1",
                  "kind": "finding", "scope": {"container_ref": "envelope:container"},
                  "subjects": [], "confidence": "high",
                  "derivation": {"producer_kind": "item_extraction",
                                 "producer_schema_id": "test", "producer_schema_version": "v1"}},
    )
    storage.create_memory_object(mo)

    storage.create_index_entry(IndexEntry(
        target_kind="memory_object",
        target_id=mo.id,
        index_type="lexical",
        text_view="envelope container ref test",
    ))

    engine = create_engine(test_db_url)
    with engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT container_ref FROM lexical_fts WHERE target_id = :tid"),
            {"tid": mo.id},
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "envelope:container"
```

- [ ] **Step 7: Run test and verify it passes**

Run: `python -m pytest tests/test_storage_sqlite.py::test_fts5_resolves_container_ref_from_memory_object_envelope -x -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add storage/sqlite.py tests/test_storage_sqlite.py
git commit -m "feat: insert lexical entries into FTS5 table on creation"
```

---

### Task 3: Delete Path — FTS5-Aware Deletion Helper

**Files:**
- Modify: `storage/sqlite_retention.py`
- Test: `tests/test_storage_sqlite.py`

- [ ] **Step 1: Write failing test — FTS5 row cleaned on retention delete**

Add to `tests/test_storage_sqlite.py`:

```python
def test_retention_deletes_fts5_rows(test_db_url: str) -> None:
    """Retention must delete FTS5 rows when deleting lexical index entries."""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import create_engine, text as sa_text
    from core.contracts import MemoryRetentionPolicy

    storage = SQLiteStorageProvider(test_db_url)

    source_item = SourceItem(
        source_type="chat_message",
        source_id="fts5-delete-test",
        content_type="text/plain",
        content="content to be deleted",
        container_ref="test:container",
        visibility="container",
    )
    storage.create_source_item(source_item)
    storage.create_index_entry(IndexEntry(
        target_kind="source_item",
        target_id=source_item.id,
        index_type="lexical",
        text_view="deletable content here",
    ))

    # Verify FTS5 row exists
    engine = create_engine(test_db_url)
    with engine.connect() as conn:
        count_before = conn.execute(sa_text("SELECT COUNT(*) FROM lexical_fts")).scalar()
    assert count_before == 1

    # Delete via retention: mark source as old enough, then run pass.
    # The retention pass calls _delete_source_item_cascade_in_session internally.
    now = datetime.now(timezone.utc)
    retention_policy = MemoryRetentionPolicy(
        source_max_age=timedelta(seconds=0),
        durable_types=frozenset(),
        working_types=frozenset(),
        orphan_delete_types=frozenset(),
    )
    storage.run_retention_pass(now=now, batch_size=10, retention_policy=retention_policy)

    # Verify FTS5 row is gone
    with engine.connect() as conn:
        count_after = conn.execute(sa_text("SELECT COUNT(*) FROM lexical_fts")).scalar()
    assert count_after == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_storage_sqlite.py::test_retention_deletes_fts5_rows -x -v`
Expected: FAIL — count_after is still 1 (FTS5 row not deleted).

- [ ] **Step 3: Extract `_delete_index_entry_in_session()` helper**

In `storage/sqlite_retention.py`, add the import and helper method. First, add to the imports at the top:

```python
from sqlalchemy import text as sa_text
```

Add the helper method to `SQLiteRetentionMixin`:

```python
def _delete_index_entry_in_session(
    self, session: Session, record: IndexEntryRecord,
) -> None:
    """Delete an index entry and its FTS5 shadow row (if lexical).

    ALL lexical index entry deletion MUST go through this helper.
    No code path should call session.delete() on an IndexEntryRecord directly.
    """
    if record.index_type == "lexical":
        session.execute(
            sa_text("DELETE FROM lexical_fts WHERE index_entry_id = :id"),
            {"id": record.id},
        )
    session.delete(record)
```

- [ ] **Step 4: Update both deletion sites to use the helper**

In `_delete_source_item_cascade_in_session()` (~line 614), replace:

```python
        for index_entry in source_index_records:
            session.delete(index_entry)
```

With:

```python
        for index_entry in source_index_records:
            self._delete_index_entry_in_session(session, index_entry)
```

In `_delete_memory_object_cascade_in_session()` (~line 676), replace:

```python
        for index_record in index_records:
            session.delete(index_record)
```

With:

```python
        for index_record in index_records:
            self._delete_index_entry_in_session(session, index_record)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_storage_sqlite.py::test_retention_deletes_fts5_rows -x -v`
Expected: PASS

- [ ] **Step 6: Run retention tests to verify no breakage**

Run: `python -m pytest tests/test_retention.py -x -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add storage/sqlite_retention.py tests/test_storage_sqlite.py
git commit -m "feat: extract FTS5-aware index entry deletion helper for retention"
```

---

### Task 4: Score Type Change — int to float

**Files:**
- Modify: `storage/base.py`
- Modify: `core/models.py`
- Modify: `api/schemas.py`
- Modify: `retrieval/composite.py`

This is a mechanical type annotation change. No behavioral change yet — the search path still returns IDF integers which are valid floats.

- [ ] **Step 1: Change `IndexSearchHit.score` to float**

In `storage/base.py:20`, change:

```python
    score: int
```

To:

```python
    score: float
```

- [ ] **Step 2: Change `QueryResultItem.lexical_score` to float**

In `core/models.py`, change line 198:

```python
    lexical_score: int | None = None
```

To:

```python
    lexical_score: float | None = None
```

Leave `score: int` on `QueryResultItem` (line 176) as-is — that's the RRF fused score which stays int.
Leave `vector_score: int | None` (line 199) as-is — vector retrieval is unchanged.

- [ ] **Step 3: Verify composite.py pass-through is compatible**

In `retrieval/composite.py:139`, the line:

```python
lexical_raw_score = lexical_items[result_id].score if result_id in lexical_items else None
```

This now passes through a float (BM25 score) to `QueryResultItem.lexical_score`. No code change needed — the `replace()` call at line 141 just copies the value. Verify the type annotation on `lexical_score` in the `replace()` target matches float.

- [ ] **Step 4: Change `RetrievalTraceHitResponse.score` to float**

In `api/schemas.py:182`, change:

```python
    score: int
```

To:

```python
    score: float
```

- [ ] **Step 4: Run tests to verify nothing breaks**

Run: `python -m pytest tests/ -x -q`
Expected: All pass — IDF integers are valid floats, so existing code works.

- [ ] **Step 5: Commit**

```bash
git add storage/base.py core/models.py api/schemas.py
git commit -m "refactor: change lexical score type from int to float for BM25"
```

---

### Task 5: Search Path — FTS5 MATCH + BM25

**Files:**
- Rewrite: `storage/sqlite_search.py`
- Test: `tests/test_storage_sqlite.py`

This is the core change. Replace the full-scan with FTS5 queries.

- [ ] **Step 1: Write failing test — FTS5 BM25 search returns results**

Add to `tests/test_storage_sqlite.py`:

```python
def test_fts5_search_returns_bm25_scores(test_db_url: str) -> None:
    """FTS5 search must return float BM25 scores with higher = better."""
    storage = SQLiteStorageProvider(test_db_url)

    texts = [
        "the quick brown fox jumps over the lazy dog",
        "the weather today is sunny and warm",
        "the reservation ordering system avoids missed hold updates",
    ]
    for i, content in enumerate(texts):
        si = SourceItem(
            source_type="chat_message",
            source_id=f"fts5-search-{i}",
            content_type="text/plain",
            content=content,
            visibility="public",
        )
        storage.create_source_item(si)
        storage.create_index_entry(IndexEntry(
            target_kind="source_item",
            target_id=si.id,
            index_type="lexical",
            text_view=content,
        ))

    hits = storage.search_index_entries(["reservation"], limit=10).hits
    assert hits
    assert isinstance(hits[0].score, float)
    assert hits[0].score > 0  # Negated BM25: positive means good match
    # Only the reservation entry should match
    assert len(hits) == 1
```

- [ ] **Step 2: Run test to verify it fails (or passes with old IDF path)**

Run: `python -m pytest tests/test_storage_sqlite.py::test_fts5_search_returns_bm25_scores -x -v`

Note: This may pass with the old path since "reservation" is a real token. The key behavior change is the score type (float vs int) and that BM25 scoring replaces IDF. We'll verify the rewrite doesn't break existing tests in step 6.

- [ ] **Step 3: Rewrite `search_index_entries()` in `storage/sqlite_search.py`**

Replace the entire file content:

```python
from __future__ import annotations

from sqlalchemy import text as sa_text

from core.filters import (
    matches_filters,
    target_visibility_and_container,
)
from core.models import QueryFilters
from core.text import tokenize_text
from core.visibility import VisibilityExclusion, is_visible
from storage.base import IndexSearchHit, IndexSearchResult
from storage.sqlite_schema import IndexEntryRecord

# Minimum BM25 relevance score (after negation, so higher = better).
# Candidates below this floor are treated as noise.
# Calibrate from eval corpus BM25 score distribution.
LEXICAL_BM25_FLOOR = 0.0  # permissive default; tighten after eval calibration


class SQLiteSearchMixin:
    def search_index_entries(
        self,
        tokens: list[str],
        limit: int,
        filters: QueryFilters | None = None,
        *,
        query_container_ref: str | None = None,
        include_visibility_trace: bool = False,
    ) -> IndexSearchResult:
        if not tokens:
            return IndexSearchResult(hits=[])

        # Build safe MATCH expression with OR semantics.
        # Quote each token to prevent FTS5 syntax injection (AND, OR, NOT, NEAR, *).
        # TOKEN_PATTERN only produces word characters and CJK ideographs, so tokens
        # cannot contain double quotes. The escape is defensive insurance.
        quoted = ['"' + token.replace('"', '""') + '"' for token in tokens]
        match_expr = " OR ".join(quoted)

        with self._session_factory() as session:
            rows = session.execute(
                sa_text(
                    "SELECT index_entry_id, target_kind, target_id, text_view_name, "
                    "text_view, bm25(lexical_fts) AS score "
                    "FROM lexical_fts "
                    "WHERE lexical_fts MATCH :match_expr "
                    "AND (:container_ref IS NULL OR container_ref = :container_ref) "
                    "ORDER BY score "
                    "LIMIT :limit"
                ),
                {
                    "match_expr": match_expr,
                    "container_ref": query_container_ref,
                    "limit": limit,
                },
            ).fetchall()

        hits: list[IndexSearchHit] = []
        exclusion_counts: dict[str, int] = {}
        unique_tokens = set(tokens)
        total_hits_before_visibility = 0
        total_hits_after_visibility = 0

        for row in rows:
            # Negate BM25 score: FTS5 returns negative (lower = better),
            # we want higher = better to match existing codebase convention.
            score = -row.score

            # Post-FTS5 score floor: skip weak matches.
            if score < LEXICAL_BM25_FLOOR:
                continue

            # Lifecycle and field filtering.
            if not matches_filters(
                self.get_memory_object,
                self.get_source_item,
                self.get_evidence_for_memory_object,
                row.target_kind,
                row.target_id,
                filters,
            ):
                continue

            # Reconstruct matched_tokens (approximate, trace/debug only).
            text_tokens = set(tokenize_text(row.text_view))
            matched_tokens = tuple(sorted(unique_tokens & text_tokens))

            total_hits_before_visibility += 1

            # Visibility filtering.
            candidate_visibility, candidate_container_ref, candidate_actor_ref = (
                target_visibility_and_container(
                    self.get_source_item,
                    self.get_memory_object,
                    row.target_kind,
                    row.target_id,
                )
            )
            if query_container_ref is not None and not is_visible(
                candidate_visibility,
                candidate_container_ref,
                query_container_ref,
                candidate_actor_ref,
            ):
                if include_visibility_trace:
                    reason = (
                        "candidate_visibility_missing"
                        if candidate_visibility is None
                        else "query_visibility_excludes_candidate"
                    )
                    exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
                continue

            total_hits_after_visibility += 1
            hits.append(
                IndexSearchHit(
                    target_kind=row.target_kind,
                    target_id=row.target_id,
                    index_entry_id=row.index_entry_id,
                    index_type="lexical",
                    text_view_name=row.text_view_name or "default",
                    score=score,
                    matched_tokens=matched_tokens,
                )
            )

        # Preserve memory_object tie-breaking at equal scores.
        hits.sort(
            key=lambda item: (
                item.score,
                1 if item.target_kind == "memory_object" else 0,
            ),
            reverse=True,
        )
        exclusions = tuple(
            VisibilityExclusion(reason=reason, count=count)
            for reason, count in sorted(exclusion_counts.items())
        )
        return IndexSearchResult(
            hits=hits,
            visibility_exclusions=exclusions,
            total_hits_before_visibility=total_hits_before_visibility,
            total_hits_after_visibility=total_hits_after_visibility,
        )
```

- [ ] **Step 4: Run the new test**

Run: `python -m pytest tests/test_storage_sqlite.py::test_fts5_search_returns_bm25_scores -x -v`
Expected: PASS

- [ ] **Step 5: Run all storage tests**

Run: `python -m pytest tests/test_storage_sqlite.py -x -v`

Some existing tests will need score value adjustments. The key behavioral assertions (which documents match, which are filtered, matched_tokens) should still pass. Score magnitude comparisons (e.g., `domain_top_score > common_top_score`) should still hold since BM25 also ranks rare terms higher.

If `test_idf_weighted_scoring_downweights_common_tokens` fails on score value assertions, that's expected — the score values change from IDF integers to BM25 floats. The ranking invariant (domain > common) should hold.

- [ ] **Step 6: Fix any assertion failures in existing storage tests**

Likely changes:
- `test_idf_weighted_scoring_downweights_common_tokens`: scores are now floats, but the relative ordering (`domain_top_score > common_top_score`) should still hold. If the test has exact score value checks, update them.
- `test_sqlite_storage_and_retrieval` line 129: `set(hits[0].matched_tokens) == {"delays", "missed"}` — should still work since matched_tokens reconstruction uses the same token intersection logic.

- [ ] **Step 7: Run lexical tokenize tests**

Run: `python -m pytest tests/test_lexical_tokenize.py -x -v`

These test via `LexicalRetrievalProvider` which calls `search_index_entries`. The matching behavior (plural expansion, container filtering) should still work. Score assertions may need float updates.

- [ ] **Step 8: Write additional regression and safety tests**

Add to `tests/test_storage_sqlite.py`:

```python
def test_fts5_container_scoped_filtering(test_db_url: str) -> None:
    """FTS5 search with query_container_ref must only return entries from that container."""
    storage = SQLiteStorageProvider(test_db_url)

    for container in ["container:a", "container:b"]:
        si = SourceItem(
            source_type="chat_message",
            source_id=f"fts5-container-{container}",
            content_type="text/plain",
            content=f"reservation in {container}",
            container_ref=container,
            visibility="container",
        )
        storage.create_source_item(si)
        storage.create_index_entry(IndexEntry(
            target_kind="source_item",
            target_id=si.id,
            index_type="lexical",
            text_view="reservation ordering discussion",
        ))

    hits_a = storage.search_index_entries(
        ["reservation"], limit=10, query_container_ref="container:a",
    ).hits
    hits_b = storage.search_index_entries(
        ["reservation"], limit=10, query_container_ref="container:b",
    ).hits
    hits_all = storage.search_index_entries(
        ["reservation"], limit=10,
    ).hits

    assert len(hits_a) == 1
    assert len(hits_b) == 1
    assert len(hits_all) == 2


def test_fts5_match_expression_safety(test_db_url: str) -> None:
    """Tokens that look like FTS5 operators must be quoted and not alter query semantics."""
    storage = SQLiteStorageProvider(test_db_url)

    si = SourceItem(
        source_type="chat_message",
        source_id="fts5-safety-test",
        content_type="text/plain",
        content="do not override the near settings",
        visibility="public",
    )
    storage.create_source_item(si)
    storage.create_index_entry(IndexEntry(
        target_kind="source_item",
        target_id=si.id,
        index_type="lexical",
        text_view="do not override the near settings",
    ))

    # These tokens overlap with FTS5 operators: NOT, NEAR, OR, AND
    # The quoting must prevent them from being interpreted as operators
    hits = storage.search_index_entries(["not", "near"], limit=10).hits
    assert hits  # Should match as literal words, not FTS5 operators


def test_fts5_bm25_rare_term_ranks_above_common(test_db_url: str) -> None:
    """BM25 must rank rare domain terms above ubiquitous common terms (regression)."""
    storage = SQLiteStorageProvider(test_db_url)

    common_texts = [
        "the quick brown fox jumps over the lazy dog",
        "the weather today is sunny and warm",
        "the latest release notes are available",
        "update the configuration file for deployment",
        "the team discussed project milestones",
        "review the pull request before merging",
    ]
    domain_text = "the reservation ordering system avoids missed hold updates"

    for i, txt in enumerate(common_texts + [domain_text]):
        si = SourceItem(
            source_type="chat_message",
            source_id=f"bm25-rank-{i}",
            content_type="text/plain",
            content=txt,
            visibility="public",
        )
        storage.create_source_item(si)
        storage.create_index_entry(IndexEntry(
            target_kind="source_item",
            target_id=si.id,
            index_type="lexical",
            text_view=txt,
        ))

    # Domain-specific token must score higher than common token
    domain_hits = storage.search_index_entries(["reservation"], limit=10).hits
    common_hits = storage.search_index_entries(["the"], limit=10).hits
    assert domain_hits
    assert common_hits
    assert domain_hits[0].score > common_hits[0].score, (
        f"Domain score ({domain_hits[0].score}) must exceed "
        f"common score ({common_hits[0].score})"
    )

    # Mixed query must rank domain doc first
    mixed_hits = storage.search_index_entries(["the", "reservation"], limit=10).hits
    assert mixed_hits[0].target_id == domain_hits[0].target_id
```

- [ ] **Step 9: Run the new tests**

Run: `python -m pytest tests/test_storage_sqlite.py::test_fts5_container_scoped_filtering tests/test_storage_sqlite.py::test_fts5_match_expression_safety tests/test_storage_sqlite.py::test_fts5_bm25_rare_term_ranks_above_common -x -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add storage/sqlite_search.py tests/test_storage_sqlite.py
git commit -m "feat: replace full-scan lexical search with FTS5 MATCH + BM25"
```

---

### Task 6: Routing Score Adaptation — Centralized Normalization

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_constants.py`
- Modify: `semantic/agent_conversation_memory_routing_injection.py`
- Modify: `semantic/agent_conversation_memory_routing_floor.py`
- Modify: `semantic/agent_conversation_memory_routing_scoring.py`
- Modify: `semantic/agent_conversation_memory_routing_justification.py`
- Modify: `semantic/agent_conversation_memory_routing_selection.py`
- Test: `tests/test_routing_quality_score.py`

**Design principle:** Raw BM25 scores must not leak past a single normalization boundary. All routing consumers work with normalized 0-1 scores. If the scoring engine changes again, only `LEXICAL_NORM_SCALE` and `normalize_lexical_score()` need updating — no threshold hunting across 6 files.

- [ ] **Step 1: Add `normalize_lexical_score()` utility and update `LEXICAL_NORM_SCALE`**

In `semantic/agent_conversation_memory_routing_constants.py`:

```python
LEXICAL_NORM_SCALE = 6.0  # BM25 normalization scale; recalibrate from eval score distributions


def normalize_lexical_score(raw_score: float | int | None) -> float:
    """Normalize raw lexical score (BM25 float) to 0.0-1.0 range.

    Single point of control for lexical score normalization.
    All routing consumers MUST call this instead of using raw scores.
    To recalibrate after scoring engine changes, adjust LEXICAL_NORM_SCALE only.
    """
    if raw_score is None:
        return 0.0
    return min(float(raw_score) / LEXICAL_NORM_SCALE, 1.0)
```

- [ ] **Step 2: Write test for normalize_lexical_score**

Add to `tests/test_routing_quality_score.py`:

```python
from semantic.agent_conversation_memory_routing_constants import normalize_lexical_score


def test_normalize_lexical_score_strong_match():
    # Score at LEXICAL_NORM_SCALE should normalize to 1.0
    assert normalize_lexical_score(6.0) == 1.0

def test_normalize_lexical_score_half():
    assert abs(normalize_lexical_score(3.0) - 0.5) < 0.01

def test_normalize_lexical_score_caps_at_one():
    assert normalize_lexical_score(12.0) == 1.0

def test_normalize_lexical_score_none():
    assert normalize_lexical_score(None) == 0.0

def test_normalize_lexical_score_zero():
    assert normalize_lexical_score(0) == 0.0

def test_normalize_lexical_score_accepts_int():
    # Backward compat: old integer scores still work
    assert abs(normalize_lexical_score(3) - 0.5) < 0.01
```

- [ ] **Step 3: Run new tests**

Run: `python -m pytest tests/test_routing_quality_score.py -x -v`
Expected: PASS

- [ ] **Step 4: Update `_compute_quality_score` to use the utility**

In `semantic/agent_conversation_memory_routing_scoring.py`, change:

```python
from semantic.agent_conversation_memory_routing_constants import (
    ...
    LEXICAL_NORM_SCALE,
    ...
)
```

To also import the new utility:

```python
from semantic.agent_conversation_memory_routing_constants import (
    ...
    normalize_lexical_score,
    ...
)
```

Change `_compute_quality_score`:

```python
def _compute_quality_score(lexical_score: float, vector_score: int) -> float:
    """Normalized quality from raw retrieval scores. Returns 0.0-1.0."""
    lex_norm = normalize_lexical_score(lexical_score)
    vec_norm = vector_score / 1000.0
    return max(lex_norm, vec_norm)
```

Remove `LEXICAL_NORM_SCALE` from the import list (no longer used directly).

At the call site (line 554), remove the `int()` cast:

```python
    quality_score = _compute_quality_score(
        float(item.lexical_score or 0),
        int(item.vector_score or 0),
    )
```

- [ ] **Step 5: Update injection gate to use normalized scores**

In `semantic/agent_conversation_memory_routing_injection.py`, add import:

```python
from semantic.agent_conversation_memory_routing_constants import normalize_lexical_score
```

Change `InjectionThresholds` to use normalized 0-1 thresholds:

```python
@dataclass(frozen=True)
class InjectionThresholds:
    """All injection check thresholds. Swappable for testing.
    Lexical thresholds are in normalized 0-1 space (via normalize_lexical_score).
    """
    set_lexical_threshold: float = 0.33   # ~2/6 in old IDF scale
    set_vector_high: int = 750
    set_lexical_low: float = 0.17         # ~1/6 in old IDF scale
    candidate_lexical_floor: float = 0.17
    candidate_vector_override: int = 800
    high_value_lexical_floor: float = 0.17
    high_value_vector_floor: int = 650
```

At line 84, replace the raw score comparison:

```python
        best_lexical = max(normalize_lexical_score(c.get("lexical_score")) for c in _lex_candidates)
```

All comparisons (`best_lexical >= thresholds.set_lexical_threshold`, etc.) now compare normalized 0-1 values against normalized thresholds. No other code changes needed in the comparison logic.

At the per-candidate level (~line 156):

```python
    raw_lex = candidate.get("lexical_score")
    lex = normalize_lexical_score(raw_lex)
```

- [ ] **Step 6: Update relevance floor to use normalized scores**

In `semantic/agent_conversation_memory_routing_floor.py`, add import:

```python
from semantic.agent_conversation_memory_routing_constants import normalize_lexical_score
```

Change threshold:

```python
@dataclass(frozen=True)
class FloorThresholds:
    """Relevance floor thresholds. Swappable for testing.
    Lexical threshold in normalized 0-1 space.
    """
    min_vector: int = 580
    min_lexical: float = 0.33  # ~2/6 in old IDF scale
```

Change the score extraction (line 46):

```python
        lex = normalize_lexical_score(raw_lex)
```

Update `filtered_score_ranges` type (line 22):

```python
    filtered_score_ranges: dict[str, tuple[float, float]]
```

- [ ] **Step 7: Update justification and selection**

In `semantic/agent_conversation_memory_routing_justification.py` line 142, change:

```python
        float(c["lexical_score"])
```

(Or use `normalize_lexical_score` if the values are compared against thresholds downstream — check the usage.)

In `semantic/agent_conversation_memory_routing_selection.py` line 286, change:

```python
            "best_lexical": max((normalize_lexical_score(c.get("lexical_score")) for c in final_candidates), default=0),
```

Add the import to both files.

- [ ] **Step 8: Run routing tests**

Run: `python -m pytest tests/test_routing_justification.py tests/test_routing_relevance_floor.py tests/test_retrieval_relevance_floor.py tests/test_routing_quality_score.py -x -v`

Fix any test failures. Tests that construct mock candidates with `lexical_score=N` (integer) will produce different normalized values — update threshold assertions accordingly.

- [ ] **Step 9: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 10: Commit**

```bash
git add semantic/agent_conversation_memory_routing_constants.py \
    semantic/agent_conversation_memory_routing_injection.py \
    semantic/agent_conversation_memory_routing_floor.py \
    semantic/agent_conversation_memory_routing_scoring.py \
    semantic/agent_conversation_memory_routing_justification.py \
    semantic/agent_conversation_memory_routing_selection.py \
    tests/test_routing_quality_score.py
git commit -m "refactor: centralize lexical score normalization, thresholds in 0-1 space"
```

---

### Task 7: Baseline Capture + Eval Calibration + Regression Gate

**Files:**
- Possibly modify: `LEXICAL_NORM_SCALE` in `routing_constants.py`, `LEXICAL_BM25_FLOOR` in `sqlite_search.py`, threshold defaults in injection/floor
- Test: evals + benchmarks

**Principle:** You can't quantify "no material regression" without a before/after comparison. This task captures baseline metrics BEFORE the FTS5 migration is exercised, then calibrates thresholds and verifies against that baseline.

- [ ] **Step 1: Capture pre-migration baseline (BEFORE clean-data.sh)**

If you still have a working database from before the FTS5 migration, capture baselines now. If not, skip to Step 2 (the pre-migration IDF test results from the last green commit serve as the baseline).

Run and save output:

```bash
python -m pytest tests/ -x -q 2>&1 | tee .local/baseline-tests.txt
python -m evals.generated_exploratory.invariant_runner --workers 4 --cache-dir .local/llm-cache 2>&1 | tee .local/baseline-exploratory.txt
python -m evals.fact_consolidation_eval 2>&1 | tee .local/baseline-fact-consolidation.txt
```

- [ ] **Step 2: Clean data and rebuild with FTS5**

```bash
bash scripts/clean-data.sh
```

- [ ] **Step 3: Run agent simulation to populate FTS5-indexed data**

```bash
python -m app.agent_simulation
```

Watch for:
- Any errors in the FTS5 write path during ingestion
- The simulation completing normally

- [ ] **Step 4: Run unit tests — first FTS5 regression check**

```bash
python -m pytest tests/ -x -q
```

All tests should pass. If any fail, fix before proceeding — this is the minimum bar.

- [ ] **Step 5: Extract BM25 score distributions**

Run a debug query to observe actual BM25 scores. Use the `/query/debug` endpoint or add a temporary log line in `search_index_entries()` to print raw BM25 scores for a sample query.

Record:
- **Strong match range:** BM25 score (after negation) for queries that should definitely inject (e.g., exact domain term match)
- **Weak match range:** BM25 score for queries that should NOT inject (e.g., single common word matching many docs)
- **Noise floor:** scores for the weakest single-token matches

These numbers drive all calibration below.

- [ ] **Step 6: Calibrate `LEXICAL_NORM_SCALE`**

Set `LEXICAL_NORM_SCALE` so that `normalize_lexical_score(strong_match_score) ≈ 1.0`.

Example: if strong matches score ~8.0 after negation, set `LEXICAL_NORM_SCALE = 8.0`.

Update in `semantic/agent_conversation_memory_routing_constants.py`.

- [ ] **Step 7: Calibrate `LEXICAL_BM25_FLOOR`**

Set `LEXICAL_BM25_FLOOR` above the noise floor observed in Step 5.

Update in `storage/sqlite_search.py`.

- [ ] **Step 8: Verify normalized thresholds are equivalent**

The injection and floor thresholds in Task 6 were set to `~old_value / old_LEXICAL_NORM_SCALE` (0.33 ≈ 2/6, 0.17 ≈ 1/6). With the new `LEXICAL_NORM_SCALE`, verify these normalized thresholds produce equivalent gating behavior:

- A query that previously had `best_lexical=2` (IDF) and passed the injection gate should still pass with the equivalent BM25 normalized score.
- A query that previously had `best_lexical=1` (IDF) and was blocked should still be blocked.

If the normalized values don't produce equivalent behavior, adjust the threshold defaults in `InjectionThresholds` and `FloorThresholds`.

- [ ] **Step 9: Run exploratory QA invariant runner**

```bash
python -m evals.generated_exploratory.invariant_runner --workers 4 --cache-dir .local/llm-cache
```

**Acceptance criteria:**
- Injection safety: off-topic queries are still blocked (no new false positives)
- Retrieval quality: relevant memories are still found (no new false negatives)
- Compare against baseline from Step 1: no material regression in aggregate pass rate

- [ ] **Step 10: Run fact consolidation eval**

```bash
python -m evals.fact_consolidation_eval
```

Compare against baseline.

- [ ] **Step 11: Run MABench benchmark**

```bash
python -m evals.mabench_benchmark
```

Compare against previous benchmark results for retrieval quality.

- [ ] **Step 12: Iterate if needed**

If any eval shows material regression:
1. Check which specific scenarios regressed
2. Examine the BM25 scores for those scenarios via debug endpoints
3. Adjust thresholds or `LEXICAL_NORM_SCALE`
4. Re-run the failing eval

Repeat until aggregate metrics are at or above baseline.

- [ ] **Step 13: Commit calibrated values**

```bash
git add storage/sqlite_search.py \
    semantic/agent_conversation_memory_routing_constants.py \
    semantic/agent_conversation_memory_routing_injection.py \
    semantic/agent_conversation_memory_routing_floor.py
git commit -m "calibrate: tune BM25 thresholds from eval score distributions"
```

---

### Task 8: Documentation + Roadmap Cleanup

**Files:**
- Modify: `docs/context/decisions.md`
- Modify: `docs/context/state.md`
- Modify: `roadmap/features/investigate-lexical-retrieval-scaling.md`
- Modify: `roadmap/board.md`

- [ ] **Step 1: Add decision entry**

Add to `docs/context/decisions.md`:

```markdown
### 2026-04-07 — FTS5 lexical retrieval

Replaced the O(N) full-table-scan lexical search with SQLite FTS5 inverted-index lookup + BM25 scoring. A standalone `lexical_fts` FTS5 virtual table lives alongside `index_entries`. Write and delete paths maintain both tables transactionally. BM25 scores (float) replace IDF integers; downstream routing thresholds recalibrated. See spec: `docs/specs/2026-04-07-fts5-lexical-retrieval-design.md`.
```

- [ ] **Step 2: Update state.md**

Update the "still weak or unstable" section in `docs/context/state.md` to remove the lexical retrieval scaling mention, or mark it as addressed.

- [ ] **Step 3: Update roadmap item to done**

In `roadmap/features/investigate-lexical-retrieval-scaling.md`, change:

```yaml
status: not-started
```

To:

```yaml
status: done
commitment: committed
```

- [ ] **Step 4: Update board.md**

Move `investigate-lexical-retrieval-scaling` from "Next" to "Done" in `roadmap/board.md`.

- [ ] **Step 5: Commit**

```bash
git add docs/context/decisions.md docs/context/state.md \
    roadmap/features/investigate-lexical-retrieval-scaling.md \
    roadmap/board.md
git commit -m "docs: record FTS5 lexical retrieval decision, close roadmap item"
```
