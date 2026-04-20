# Injection Observability Design

**Date:** 2026-04-20
**Status:** Proposed

## Problem

Pallium's `/status` endpoint only reports ingestion metrics (pending queue, source items, memory objects, storage). There is no way to see whether retrieval/injection is working — whether queries return memories, how often injection is allowed vs skipped, what decision reasons dominate, or how often users flag bad memories.

The query audit log captures per-query data but requires explicit opt-in and has no aggregation endpoint.

## Approach

Add a `QueryStats` class with thread-safe in-memory counters, updated on every query and flag call, surfaced via a new `"query"` key on `/status`. Counters reset on restart — this is intentional for a sidecar that restarts with its host.

## QueryStats Class

**Location:** `core/observability.py` (alongside existing `IntegrationDebugLogger`)

### Counters

| Counter | Type | Updated by |
|---------|------|------------|
| `total_queries` | `int` | Every `QueryExecutor.query()` return |
| `total_injections` | `int` | `should_inject=True` and `len(injectable_blocks) > 0` |
| `total_skips` | `int` | `should_inject=False` |
| `total_blocks_injected` | `int` | Sum of `len(injectable_blocks)` across injecting queries |
| `total_flags` | `int` | Every `flag_memory_object()` call |
| `total_suppressions` | `int` | Flag calls where result is suppressed |
| `skip_reasons` | `dict[str, int]` | Keyed by `decision_reason` when `should_inject=False` |
| `last_query_at` | `str \| None` | ISO timestamp of most recent query |

### Bounds

- `skip_reasons` dict: max 50 distinct keys. The 51st+ distinct reason increments `"_other"`.
- `snapshot()` returns `skip_reasons` sorted by count descending, capped at top 20 entries.
- Python ints have no overflow. The skip_reasons cap prevents unbounded dict growth from buggy reason strings.

### API

```python
class QueryStats:
    def record_query(self, result: QueryResult) -> None: ...
    def record_flag(self, suppressed: bool) -> None: ...
    def snapshot(self) -> dict: ...
```

### Safety

Every public method wraps its body in `try/except Exception` — a stats bug can never break a query or flag call. The class is fully passive; it does not modify query results or flag outcomes.

## Integration Points

### Construction

Created in `app/main.py` during app startup, before `PalliumService` construction. Single instance.

### Query recording

`QueryExecutor` (in `core/query.py`) receives `QueryStats` at construction. Each of the three `return QueryResult(...)` code paths calls `stats.record_query(result)` before returning. This is the single chokepoint — every query flows through `QueryExecutor.query()`.

### Flag recording

`PalliumService.flag_memory_object()` (in `core/service.py`) calls `stats.record_flag(suppressed=result.suppressed)` before returning the `FlagResult`.

### Status endpoint

The `/status` handler in `app/main.py` adds a `"query"` key with `stats.snapshot()`. Wrapped in try/except like other status sections — failure returns `"query": null`.

## Status Response Shape

```json
{
  "pending_items": 3,
  "total_source_items": 150,
  "total_memory_objects": 80,
  "snapshot": { "..." : "..." },
  "storage": { "..." : "..." },
  "vector_index_ready": true,
  "uptime_seconds": 3600,
  "query": {
    "total_queries": 420,
    "total_injections": 180,
    "total_skips": 240,
    "total_blocks_injected": 512,
    "total_flags": 7,
    "total_suppressions": 2,
    "skip_reasons": {"gate_blocked": 95, "no_relevant_memory": 80},
    "last_query_at": "2026-04-20T14:30:00Z"
  }
}
```

## No Changes To

- `/health` endpoint
- Query response schemas (`QueryResponse`, `QueryResultResponse`, etc.)
- Query audit log
- Routing logic or semantic packages

## Testing

All tests in `tests/test_query_stats.py` (new file), plus one integration assertion.

### Unit tests

1. Basic counting — inject vs skip increments correct counters
2. Skip reason tracking — various `decision_reason` values accumulate correctly
3. Skip reason cap — 51 distinct reasons, 51st goes to `"_other"`
4. Flag counting — `suppressed=True` vs `False` increment correct fields
5. Blocks sum — multiple queries with varying block counts, verify sum
6. Snapshot isolation — mutating returned dict doesn't affect internal state
7. Thread safety — concurrent `record_query` from multiple threads, total equals expected
8. Exception safety — garbage input doesn't raise
9. `last_query_at` — populated after a query, `None` before
10. Snapshot skip_reasons cap — 30 stored, top 20 returned sorted by count

### Integration test

11. `/status` after queries and flags via test client — `"query"` key present with expected shape; graceful `null` if stats unavailable
