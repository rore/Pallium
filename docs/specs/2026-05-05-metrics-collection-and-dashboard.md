# Metrics Collection and Dashboard Updates

**Date:** 2026-05-05
**Status:** Draft
**Scope:** Persistent metrics table, dashboard integration for agent_work_trace, production enablement

---

## Problem

Pallium tracks operational metrics in three disconnected, ephemeral stores:

1. **QueryStats** — in-memory counters (injection rate, skip reasons). Lost on restart.
2. **Work trace metrics** — append-only JSONL file on disk. Not queryable via API, not backed up with DB, not visible in dashboard.
3. **Queue health** — live DB queries with no historical record. Can't answer "was the queue backed up yesterday?"

The dashboard shows only since-restart snapshots. There's no way to observe trends, compare time windows, or correlate events across restarts.

Additionally, the newly shipped `agent_work_trace` package is not enabled in production and has no dashboard visibility.

---

## Goals

1. **Unified metrics table** — single persistent store for all timestamped operational events
2. **Durable query stats** — injection rates, skip reasons survive restarts and support historical queries
3. **Work trace measurement** — replace JSONL file and state files with DB records, enabling the orientation-cost comparison directly from the dashboard
4. **Dashboard updates** — show work trace sessions, enable historical query stats views
5. **Production enablement** — enable `agent_work_trace` package in production config

---

## Design

### Metrics Table Schema

**ORM model** (follows existing pattern in `storage/sqlite_schema.py`):

```python
class MetricRecord(Base):
    __tablename__ = "metrics"

    id = Column(String, primary_key=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=False)
    category = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    container_ref = Column(String, nullable=True)
    thread_ref = Column(String, nullable=True)
    actor_ref = Column(String, nullable=True)
    value = Column(Float, nullable=True)
    payload = Column(String, nullable=True)  # JSON blob
```

**Indexes:**

```sql
CREATE INDEX ix_metrics_cat_ts ON metrics(category, timestamp);
CREATE INDEX ix_metrics_cat_evt_ts ON metrics(category, event_type, timestamp);
CREATE INDEX ix_metrics_container_ts ON metrics(container_ref, timestamp);
```

No standalone timestamp index — every real query filters by category first, making `ix_metrics_cat_ts` sufficient for time-range scans.

**Columns:**

| Column | Purpose |
|--------|---------|
| `id` | UUID, unique per event |
| `timestamp` | DateTime(timezone=True), event time in UTC |
| `category` | Top-level grouping: `query`, `work_trace`, `processing`, `system` |
| `event_type` | Specific event within category (see below) |
| `container_ref` | Optional scope dimension |
| `thread_ref` | Optional session/thread dimension |
| `actor_ref` | Optional user dimension |
| `value` | Optional numeric value for single-metric events (count, duration_ms, etc.) |
| `payload` | JSON blob for event-specific structured data |

**Why a single table:** All metrics share the same access pattern (filter by time + category + dimension, aggregate). A single table with compound indexes is simpler than N typed tables, and SQLite handles this scale easily (tens of thousands of rows per month for an active user).

**Why `value` as a dedicated column:** Enables `SUM(value)`, `AVG(value)` without JSON extraction for the most common aggregation pattern. Events that need richer data use `payload`.

---

### Event Types

#### Category: `query`

| event_type | value | payload |
|------------|-------|---------|
| `injection` | block_count | `{"decision_reason": "..."}` |
| `skip` | null | `{"decision_reason": "...", "skip_reason": "..."}` |
| `flag` | null | `{"memory_object_id": "...", "suppressed": bool}` |
| `feedback` | null | `{"memory_object_id": "...", "rating": "relevant\|not_relevant"}` |

#### Category: `work_trace`

| event_type | value | payload |
|------------|-------|---------|
| `thread_rebuild` | turn_count | `{"exploratory_file_count": N, "productive_file_count": N, "commands_succeeded": N, "commands_failed": N, "has_outcome": bool, "subject": "..."}` |

Note: "trace was injected in session X" is derived from `query/injection` events where the injected blocks include a task_trace — no separate `trace_injected` event needed.

#### Category: `processing`

| event_type | value | payload |
|------------|-------|---------|
| `item_processed` | duration_ms | `{"package": "...", "memory_types_created": [...]}` |
| `thread_rebuilt` | duration_ms | `{"package": "...", "item_count": N}` |
| `extraction_failed` | null | `{"package": "...", "error": "..."}` |

#### Category: `system`

| event_type | value | payload |
|------------|-------|---------|
| `service_start` | null | `{"version": "...", "packages_enabled": [...]}` |
| `retention_run` | null | `{"deleted_source_items": N, "deleted_memory_objects": N}` |

---

### Retention

Metrics rows are cleaned by the existing retention cleaner:
- Default retention: **disabled** (no automatic deletion)
- Configurable via `[observability] metrics_retention_days = 0` in config (0 = disabled, any positive integer = delete rows older than N days)
- When enabled, cleanup runs alongside existing source item retention

At ~100 events/day for an active user, even a year of data is ~36,000 rows. Negligible storage. Start with retention disabled and enable it only if storage becomes a concern.

---

### Storage Layer

New file: `storage/metrics.py`

```python
class MetricsStore:
    def record(self, category: str, event_type: str, *,
               container_ref: str | None = None,
               thread_ref: str | None = None,
               actor_ref: str | None = None,
               value: float | None = None,
               payload: dict | None = None) -> None: ...

    def query(self, *,
              category: str | None = None,
              event_type: str | None = None,
              container_ref: str | None = None,
              since: str | None = None,
              until: str | None = None,
              limit: int = 1000) -> list[MetricRow]: ...

    def aggregate(self, *,
                  category: str,
                  event_type: str | None = None,
                  container_ref: str | None = None,
                  since: str | None = None,
                  until: str | None = None,
                  group_by: Literal["hour", "day", "week"] = "day",
                  ) -> list[AggregateBucket]: ...

    def cleanup(self, retention_days: int) -> int: ...
```

**`aggregate()` return schema:**

```python
@dataclass
class AggregateBucket:
    bucket: str          # ISO date/hour string for the bucket start ("2026-05-05", "2026-05-05T14")
    event_type: str      # grouped event type
    count: int           # number of events in this bucket
    sum_value: float     # SUM(value) for events with value, 0 otherwise
    avg_value: float     # AVG(value) for events with value, 0 otherwise
```

Valid `group_by` values: `"hour"` (dashboard real-time view), `"day"` (default trend view), `"week"` (long-term comparison). The bucket string format matches the granularity: `"2026-05-05"` for day, `"2026-05-05T14"` for hour, `"2026-W19"` for week.

The `MetricsStore` is instantiated alongside the existing SQLite storage and exposed via the service container.

---

### Integration Points

#### 1. QueryStats → Metrics

`QueryStats.record_query()` continues to maintain in-memory counters for the `/status` endpoint (fast, no DB hit). Additionally, it calls `MetricsStore.record()` to persist each event. The dashboard can then show historical data by querying the metrics table instead of relying solely on in-memory snapshots.

The in-memory `QueryStats` remains for the fast `/status` path — the metrics table is the durable historical store queried by the dashboard for trends.

`QueryStats` receives a `MetricsStore` reference at construction time (injected by `app/dependencies.py`). When `MetricsStore` is `None` (e.g., in tests), recording is silently skipped.

#### 2. Work Trace → Metrics

**Recording happens in the infrastructure layer, not the plugin.** Plugins have no access to storage or infrastructure (they receive only their LLMProvider). The metric recording point is the processor orchestration layer (`core/processing.py` `ItemProcessor`), which already observes thread rebuild outcomes.

After `build_thread_summary()` returns a `ProcessResult`, the `ItemProcessor` extracts work-trace-specific fields from the produced `MemoryObject.payload` and records the metric:

```python
# In core/processing.py, after thread rebuild persistence
if memory_obj.schema_id == "task_trace":
    payload = json.loads(memory_obj.payload) if memory_obj.payload else {}
    metrics_store.record(
        category="work_trace",
        event_type="thread_rebuild",
        container_ref=memory_obj.container_ref,
        thread_ref=memory_obj.thread_ref,
        value=payload.get("turn_count"),
        payload={
            "exploratory_file_count": len(payload.get("exploratory_files", [])),
            "productive_file_count": len(payload.get("productive_files", [])),
            "commands_succeeded": len(payload.get("commands_succeeded", [])),
            "commands_failed": len(payload.get("commands_failed", [])),
            "has_outcome": "outcome" in payload,
            "subject": payload.get("subject", ""),
        },
    )
```

This keeps `AgentWorkTracePlugin` pure — no infrastructure coupling. The existing `_append_metric_event()` function and `METRICS_LOG_FILENAME` constant are removed.

**Replace state file:** The `trace_injected` signal is derived server-side from the query path. When `/query` returns `should_inject=True` and the injectable blocks include a `task_trace`, the query metrics recording (via QueryStats → MetricsStore, see Integration Point #1) captures this as a `query/injection` event with the relevant `thread_ref`. The query audit log retains the injected block details for deeper analysis.

No hook changes are needed. The `_write_work_trace_state()` function becomes dead code and is removed in the cleanup phase, but hooks themselves are not modified.

#### 3. Processing Pipeline → Metrics

The processor worker (`core/processing.py`) records `item_processed` and `extraction_failed` events after each item, using the `MetricsStore` it already holds. Thread rebuild records `thread_rebuilt` with duration. This is the same infrastructure layer that handles persistence — no plugin changes needed.

#### 4. Service Lifecycle → Metrics

On startup, record a `service_start` event. On retention run completion, record `retention_run`.

---

### Dashboard Updates

#### New: Historical Query Stats Panel

Replace the current since-restart snapshot with a time-series view:
- Injection rate over time (daily/hourly buckets)
- Skip reason distribution over time
- Query volume trend

Data source: `SELECT event_type, COUNT(*) FROM metrics WHERE category='query' AND timestamp > ? GROUP BY date(timestamp), event_type`

#### New: Work Trace Sessions Panel

A section showing recent agent sessions with work trace data:
- Session (thread_ref), subject, turn count, file counts
- Whether a trace was injected at session start
- Link to memory browser filtered by that thread

Data source: `SELECT * FROM metrics WHERE category='work_trace' ORDER BY timestamp DESC LIMIT 20`

#### New: Orientation Cost Comparison

The key measurement view:
- Sessions WITH trace injection vs. sessions WITHOUT
- Average turn count, average file discovery count
- Side-by-side comparison table

Data source: Join `trace_injected` events with `thread_rebuild` events on `thread_ref` to identify which sessions had trace available.

#### Existing panels: unchanged

The overview cards, system health, and memory browser remain as-is. The query activity panel gains a "Historical" toggle that switches from in-memory snapshot to metrics-table query.

---

### API Endpoints

All metric recording happens server-side via direct `MetricsStore.record()` calls — no external write API needed. The API surface is read-only, for the dashboard:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /metrics/query` | GET | Query metrics with filters (category, event_type, container, time range) |
| `GET /metrics/aggregate` | GET | Aggregated metrics for dashboard charts |
| `GET /dashboard/api/metrics/query-activity` | GET | Dashboard-specific: query stats over time |
| `GET /dashboard/api/metrics/work-trace` | GET | Dashboard-specific: work trace sessions |

---

### Hook Changes

No hook changes needed. All metrics are recorded server-side within Pallium. Hooks continue to call `/query` and `/items` as before — metrics recording is a self-contained concern of the Pallium service, not reported from the outside.

The `_write_work_trace_state()` function in session_start hooks becomes dead code and is removed in the cleanup phase.

---

### MCP Tool Updates

#### `pallium_status`

The `/status` endpoint should include a `metrics_summary` field showing:
- Total metric events (all time)
- Events in last 24h by category
- Work trace: sessions with/without injection (last 7 days)

This enriches what the MCP tool returns without requiring a separate query.

---

### Production Enablement

Add to the service config (`pallium.toml`):

```toml
[semantic_packages.agent_work_trace]
implementation = "agent_work_trace"
llm_provider = "anthropic"
model = "claude-haiku-latest"
```

Restart the service. The package will claim source items with `agent_work_trace_turn` metadata and begin producing `task_trace` memory objects.

---

### What Does NOT Change

- Existing `MemoryFeedbackRecord` and `MemoryFlagRecord` tables stay as-is — they store per-memory quality signals, not operational metrics
- The `/debug/queue/health` endpoint remains a live DB query (not metrics-based) — it shows current state, not history
- `QueryStats` in-memory class remains for the fast `/status` response
- No changes to the query/routing path
- No changes to semantic extraction or thread aggregation logic

---

### Evals and Invariants

#### Existing evals: no changes needed

The metrics table is purely operational infrastructure. It doesn't affect extraction quality, routing decisions, or injection behavior. Existing semantic evals, routing replay, and invariant runner continue to validate correctness.

#### New test coverage needed

**Unit tests — MetricsStore (`tests/test_metrics_store.py`):**

| Test | Purpose |
|------|---------|
| `test_record_and_query_basic` | Record a single event, query it back by category |
| `test_record_all_fields` | Record with all optional fields populated, verify round-trip |
| `test_query_filter_by_category` | Multiple categories, filter returns only matching |
| `test_query_filter_by_event_type` | Multiple event types, filter returns only matching |
| `test_query_filter_by_container_ref` | Filter by container_ref dimension |
| `test_query_filter_by_time_range_since` | Only returns events after `since` |
| `test_query_filter_by_time_range_until` | Only returns events before `until` |
| `test_query_filter_by_time_range_window` | Combined since + until window |
| `test_query_limit` | Returns at most `limit` rows, ordered by timestamp desc |
| `test_query_empty_table` | Empty table returns empty list, not error |
| `test_aggregate_by_day` | Groups events into daily buckets correctly |
| `test_aggregate_by_hour` | Groups events into hourly buckets correctly |
| `test_aggregate_by_week` | Groups events into weekly buckets correctly |
| `test_aggregate_returns_count_sum_avg` | Numeric value aggregation: count, sum, avg all correct |
| `test_aggregate_with_null_values` | Events without value don't break sum/avg (treated as 0) |
| `test_aggregate_filter_by_container` | Aggregate respects container_ref filter |
| `test_aggregate_empty_range` | No events in range returns empty list |
| `test_cleanup_deletes_old_rows` | Rows older than retention_days are deleted |
| `test_cleanup_preserves_recent_rows` | Rows within retention window are kept |
| `test_cleanup_disabled_when_zero` | retention_days=0 deletes nothing |
| `test_cleanup_returns_count` | Returns number of deleted rows |
| `test_record_with_none_payload` | Null payload stored correctly |
| `test_record_generates_unique_ids` | Multiple records get distinct IDs |
| `test_concurrent_writes` | Multiple threads writing simultaneously don't corrupt data |

**Unit tests — QueryStats integration (`tests/test_query_stats_metrics.py`):**

| Test | Purpose |
|------|---------|
| `test_record_query_injection_persists` | Injection event written to metrics table |
| `test_record_query_skip_persists` | Skip event with reason written to metrics table |
| `test_record_query_skip_reason_in_payload` | Skip reason stored in payload JSON |
| `test_record_flag_persists` | Flag event written with suppressed field |
| `test_record_feedback_persists` | Feedback rating written to metrics table |
| `test_metrics_store_none_graceful` | When MetricsStore is None, recording is silently skipped |
| `test_metrics_failure_does_not_block_query` | DB error in metrics doesn't affect query response |
| `test_in_memory_and_persistent_stay_consistent` | In-memory counter matches metrics table count |

**Unit tests — Processing pipeline metrics (`tests/test_processing_metrics.py`):**

| Test | Purpose |
|------|---------|
| `test_item_processed_records_duration` | item_processed event with duration_ms as value |
| `test_item_processed_records_package_name` | Payload contains correct package identifier |
| `test_item_processed_records_memory_types` | Payload lists memory types created |
| `test_thread_rebuilt_records_duration` | thread_rebuilt event with duration_ms |
| `test_thread_rebuilt_records_item_count` | Payload contains item count |
| `test_extraction_failed_records_error` | Error message captured in payload |
| `test_task_trace_rebuild_records_work_trace_metric` | task_trace MemoryObject triggers work_trace/thread_rebuild metric |
| `test_task_trace_metric_extracts_file_counts` | Metric payload has correct exploratory/productive counts |
| `test_non_task_trace_rebuild_no_work_trace_metric` | Non-task_trace memory objects don't emit work_trace events |

**API endpoint tests (`tests/test_metrics_api.py`):**

| Test | Purpose |
|------|---------|
| `test_get_query_filters` | GET /metrics/query respects all filter params |
| `test_get_query_default_limit` | Default limit is 1000 |
| `test_get_aggregate_day` | Aggregate endpoint returns daily buckets |
| `test_get_aggregate_hour` | Aggregate endpoint returns hourly buckets |
| `test_get_aggregate_invalid_group_by` | Invalid group_by value returns 422 |

**Dashboard API tests (`tests/test_dashboard_metrics.py`):**

| Test | Purpose |
|------|---------|
| `test_query_activity_historical_returns_buckets` | Returns time-bucketed injection/skip counts |
| `test_query_activity_historical_respects_time_range` | Only includes events in requested window |
| `test_query_activity_empty_range` | Empty time range returns empty buckets |
| `test_work_trace_sessions_list` | Returns recent work trace sessions with metadata |
| `test_work_trace_sessions_empty` | No work trace data returns empty list |
| `test_orientation_cost_comparison` | Sessions with injection vs without, shows averages |
| `test_orientation_cost_insufficient_data` | Fewer than 2 sessions returns insufficient_data flag |

**E2E tests (`tests/test_metrics_e2e.py`):**

| Test | Purpose |
|------|---------|
| `test_full_lifecycle_ingest_to_metric` | Ingest item → process → thread rebuild → metric appears in DB |
| `test_query_triggers_injection_metric` | POST /query with injection → query/injection metric recorded |
| `test_query_triggers_skip_metric` | POST /query with skip → query/skip metric recorded with reason |
| `test_flag_triggers_metric` | POST flag → query/flag metric recorded |
| `test_feedback_triggers_metric` | POST rate_memory → query/feedback metric recorded |
| `test_service_start_records_metric` | On startup, system/service_start event present |
| `test_retention_run_records_metric` | After retention cleaner runs, system/retention_run event present |
| `test_metrics_survive_restart` | Record metrics, simulate restart, metrics still queryable |
| `test_dashboard_reflects_recorded_metrics` | Metrics recorded via API appear in dashboard endpoints |
| `test_status_endpoint_includes_metrics_summary` | /status response has metrics_summary with counts |
| `test_aggregate_across_multiple_days` | Multiple days of data, aggregate returns correct per-day bucketing |
| `test_work_trace_orientation_cost_e2e` | Full flow: session with trace injection → rebuild → comparison view shows both sessions |

#### Edge cases to cover

- Metrics recording failure must not block the operation that triggered it (fire-and-forget)
- High-frequency recording (many queries/second) must not degrade query latency
- Empty metrics table returns empty results, not errors
- Concurrent writes from multiple threads (processor + API server)
- Timestamps are always server UTC
- Unicode in payload values (container_ref with non-ASCII characters)
- Very long thread_ref or container_ref values (bounded by column, not rejected)
- Duplicate record calls with same data produce separate rows (append-only, no dedup)
- Retention cleanup under concurrent reads (readers see consistent state)
- Aggregate with exactly one event in a bucket (avg = sum = value)
- Query with all filters set simultaneously (AND semantics)

#### Performance considerations

- `record()` is fire-and-forget with a single INSERT per call — minimal latency impact on the caller
- SQLite WAL mode (already configured) allows concurrent reads during writes
- The compound indexes (`category + timestamp`, `category + event_type + timestamp`) cover all dashboard query patterns without full-table scans
- At typical volumes (~100 events/day), even un-indexed queries would be fast; indexes are insurance for long-term accumulation
- `aggregate()` uses SQLite's `strftime` for bucketing — computed at query time, no pre-aggregation needed at this scale
- If write frequency becomes a concern (>1000 events/second), batch recording can be added later without changing the interface

---

### Migration

The metrics table is additive — no existing tables are modified. Schema creation happens at startup alongside existing table creation in `storage/sqlite_schema.py`.

For the work trace JSONL → DB migration:
- Existing JSONL files are **not** migrated (low volume, recent feature)
- Going forward, all metrics go to the DB
- The `_append_metric_event()` function and `METRICS_LOG_FILENAME` constant are removed from `semantic/agent_work_trace.py`
- The `_write_work_trace_state()` function is removed from session_start hooks

---

### Implementation Order

1. Schema + MetricsStore (storage layer)
2. Read-only API endpoints (query + aggregate)
3. Wire QueryStats → MetricsStore
4. Wire processing pipeline → MetricsStore (replace JSONL)
5. Dashboard: historical query stats + work trace panels
6. Retention integration
7. MCP /status metrics_summary + service lifecycle events
8. Cleanup: remove JSONL code, state file code
