# Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a built-in web dashboard at `GET /dashboard` that shows Pallium's current state — health, metrics, queue, and a browsable memory list.

**Architecture:** Single HTML page served by FastAPI, polls existing `/status` and `/debug/queue/health` endpoints every 10s. One new API endpoint (`/dashboard/api/memories`) wraps the storage layer with pagination. Static logo served via `/static/` mount. No build step, no external dependencies.

**Tech Stack:** Python 3.12+ / FastAPI / SQLAlchemy (existing), vanilla HTML/CSS/JS (new)

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `app/dashboard.py` | `mount_dashboard(app)` function, `/dashboard` HTML route, `/dashboard/api/memories` paginated endpoint |
| Create | `app/dashboard.html` | Complete dashboard page — inline CSS + JS, polls API, memory browser with expand/evidence drill-down |
| Modify | `app/main.py:58` | Call `mount_dashboard(app)` in `create_app()` |
| Create | `tests/test_dashboard.py` | Tests for `/dashboard` and `/dashboard/api/memories` |

---

### Task 1: Paginated memories endpoint — test first

**Files:**
- Create: `tests/test_dashboard.py`
- Create: `app/dashboard.py`

- [ ] **Step 1: Write the failing test for GET /dashboard/api/memories**

```python
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from core.models import MemoryObject
from storage.vector_index import VectorIndexConfig


def _test_config() -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url="sqlite:///:memory:",
        default_use_case="demo_agent_memory",
        vector_index=VectorIndexConfig(enabled=False),
    )


def _seed_memory(app, *, type: str = "decision", lifecycle: str = "active", container_ref: str = "test-container") -> MemoryObject:
    service = app.state.pallium_service
    mo = MemoryObject(
        type=type,
        schema_id="test",
        schema_version="1.0",
        payload={"summary": f"Test {type} memory"},
        lifecycle=lifecycle,
        container_ref=container_ref,
        created_at=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
    )
    service._storage.store_memory_object(mo)
    return mo


class TestDashboardMemoriesEndpoint:

    def test_returns_empty_list_when_no_memories(self) -> None:
        app = create_app(_test_config())
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/memories")
        assert resp.status_code == 200
        body = resp.json()
        assert body["memories"] == []
        assert body["total"] == 0
        assert body["offset"] == 0
        assert body["limit"] == 50

    def test_returns_seeded_memories(self) -> None:
        app = create_app(_test_config())
        with TestClient(app) as client:
            _seed_memory(app, type="decision")
            _seed_memory(app, type="atomic_fact")
            resp = client.get("/dashboard/api/memories")
        body = resp.json()
        assert body["total"] == 2
        assert len(body["memories"]) == 2
        mem = body["memories"][0]
        assert "id" in mem
        assert "type" in mem
        assert "display_text" in mem
        assert "created_at" in mem

    def test_filters_by_type(self) -> None:
        app = create_app(_test_config())
        with TestClient(app) as client:
            _seed_memory(app, type="decision")
            _seed_memory(app, type="atomic_fact")
            resp = client.get("/dashboard/api/memories?type=decision")
        body = resp.json()
        assert body["total"] == 1
        assert body["memories"][0]["type"] == "decision"

    def test_filters_by_lifecycle(self) -> None:
        app = create_app(_test_config())
        with TestClient(app) as client:
            _seed_memory(app, type="decision", lifecycle="active")
            _seed_memory(app, type="decision", lifecycle="suppressed")
            resp = client.get("/dashboard/api/memories?lifecycle=suppressed")
        body = resp.json()
        assert body["total"] == 1
        assert body["memories"][0]["lifecycle"] == "suppressed"

    def test_pagination_limit_and_offset(self) -> None:
        app = create_app(_test_config())
        with TestClient(app) as client:
            for i in range(5):
                _seed_memory(app, type="decision")
            resp = client.get("/dashboard/api/memories?limit=2&offset=2")
        body = resp.json()
        assert body["total"] == 5
        assert len(body["memories"]) == 2
        assert body["offset"] == 2
        assert body["limit"] == 2

    def test_limit_capped_at_200(self) -> None:
        app = create_app(_test_config())
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/memories?limit=999")
        body = resp.json()
        assert body["limit"] == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard.py -x -v`
Expected: ImportError or 404 (endpoint doesn't exist yet)

- [ ] **Step 3: Write `app/dashboard.py` with the memories endpoint and mount function**

```python
from __future__ import annotations

import json
import logging
from datetime import timezone
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import MemoryObjectRecord

logger = logging.getLogger(__name__)

_DASHBOARD_HTML_PATH = Path(__file__).parent / "dashboard.html"


def _extract_display_text(payload: dict) -> str:
    for key in ("summary", "decision", "investigation_outcome", "interest_text", "constraint_text", "carry_forward_answer"):
        val = payload.get(key)
        if val:
            return str(val)
    return ""


def mount_dashboard(app: FastAPI) -> None:
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    app.mount("/static", StaticFiles(directory=str(assets_dir)), name="static")

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_page() -> HTMLResponse:
        html = _DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
        return HTMLResponse(content=html)

    @app.get("/dashboard/api/memories")
    def dashboard_memories(
        type: str | None = Query(None),
        lifecycle: str | None = Query(None),
        container_ref: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        service = app.state.pallium_service
        storage = service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)

        with storage._session_factory() as session:
            stmt = select(MemoryObjectRecord)
            count_stmt = select(func.count()).select_from(MemoryObjectRecord)

            if type is not None:
                stmt = stmt.where(MemoryObjectRecord.type == type)
                count_stmt = count_stmt.where(MemoryObjectRecord.type == type)
            if lifecycle is not None:
                stmt = stmt.where(MemoryObjectRecord.lifecycle == lifecycle)
                count_stmt = count_stmt.where(MemoryObjectRecord.lifecycle == lifecycle)
            if container_ref is not None:
                stmt = stmt.where(MemoryObjectRecord.container_ref == container_ref)
                count_stmt = count_stmt.where(MemoryObjectRecord.container_ref == container_ref)

            total = session.scalar(count_stmt) or 0

            stmt = stmt.order_by(MemoryObjectRecord.created_at.desc())
            stmt = stmt.offset(offset).limit(limit)
            records = session.scalars(stmt).all()

        memories = []
        for rec in records:
            payload = json.loads(rec.payload_json) if rec.payload_json else {}
            envelope = json.loads(rec.envelope_json) if rec.envelope_json else {}
            confidence = envelope.get("confidence", "unknown")
            created_at = rec.created_at
            if created_at and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            memories.append({
                "id": rec.id,
                "type": rec.type,
                "lifecycle": rec.lifecycle,
                "container_ref": rec.container_ref,
                "display_text": _extract_display_text(payload),
                "confidence": confidence,
                "created_at": created_at.isoformat() if created_at else None,
            })

        return JSONResponse(content={
            "memories": memories,
            "total": total,
            "offset": offset,
            "limit": limit,
        })
```

- [ ] **Step 4: Create a minimal placeholder `app/dashboard.html`**

```html
<!DOCTYPE html>
<html><head><title>Pallium Dashboard</title></head>
<body><h1>Pallium Dashboard</h1><p>Loading...</p></body>
</html>
```

This placeholder allows the `/dashboard` route to work. The full HTML is built in Task 3.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_dashboard.py -x -v`
Expected: All 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/dashboard.py app/dashboard.html tests/test_dashboard.py
git commit -m "feat(dashboard): add /dashboard/api/memories endpoint with pagination"
```

---

### Task 2: Integrate mount into `app/main.py`

**Files:**
- Modify: `app/main.py:241` (before `app.include_router(...)`)
- Modify: `tests/test_dashboard.py` (add route test)

- [ ] **Step 1: Add test for dashboard page route**

Append to `tests/test_dashboard.py`:

```python
class TestDashboardPage:

    def test_dashboard_returns_html(self) -> None:
        app = create_app(_test_config())
        with TestClient(app) as client:
            resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_static_logo_served(self) -> None:
        app = create_app(_test_config())
        with TestClient(app) as client:
            resp = client.get("/static/logo/pallium_header.png")
        assert resp.status_code == 200
        assert "image" in resp.headers["content-type"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dashboard.py::TestDashboardPage -x -v`
Expected: FAIL — `mount_dashboard` is not called in `create_app`, so routes don't exist on the app created via `create_app()`.

Wait — actually `mount_dashboard` IS called in `create_app` if we already added it... Let me reconsider.

The `create_app()` in `app/main.py` doesn't call `mount_dashboard` yet. The tests in Task 1 that call `create_app` will also fail unless we integrate. So let me restructure: **integrate the mount call now as part of making Task 1 tests pass.**

- [ ] **Step 2 (revised): Add `mount_dashboard` call to `app/main.py`**

In `app/main.py`, add the import and call. Insert after line 19 (imports):

```python
from app.dashboard import mount_dashboard
```

Insert before `app.include_router(...)` (line 241):

```python
    mount_dashboard(app)
```

The final section of `create_app()` becomes:

```python
    mount_dashboard(app)

    app.include_router(build_router(
        service, audit_log_enabled=resolved_config.observability.query_audit_log,
    ))
    if mcp_available and mcp_app is not None:
        app.mount("", mcp_app)
        logger.info("MCP endpoint available at /mcp")
    return app
```

- [ ] **Step 3: Run all dashboard tests**

Run: `python -m pytest tests/test_dashboard.py -x -v`
Expected: All tests PASS (both memories endpoint and page/static tests)

- [ ] **Step 4: Commit**

```bash
git add app/main.py tests/test_dashboard.py
git commit -m "feat(dashboard): integrate mount_dashboard into create_app"
```

---

### Task 3: Build the full dashboard HTML page

**Files:**
- Modify: `app/dashboard.html` (replace placeholder with full implementation)

This is the largest task — the full single-page dashboard. No tests needed for HTML/CSS/JS (visual, tested in browser).

- [ ] **Step 1: Write the complete `app/dashboard.html`**

The file contains:
- Inline `<style>` with the dark theme, grid layout, card styles, table styles, animations
- Semantic HTML for all 7 sections (header, metrics, storage, query stats, skip reasons, queue, memory browser)
- Inline `<script>` with:
  - `fetchStatus()` — polls `/status` every 10s
  - `fetchQueueHealth()` — polls `/debug/queue/health` every 10s
  - `fetchMemories(params)` — fetches `/dashboard/api/memories` with filters
  - `fetchEvidence(id)` — fetches `/memory/{id}/evidence` on row expand
  - `renderMetrics(data)` — updates the 4 metric cards
  - `renderStorage(data)` — updates storage bars
  - `renderQueryStats(data)` — updates query/injection panel
  - `renderSkipReasons(data)` — updates skip reasons table
  - `renderQueue(data)` — updates queue status
  - `renderMemories(data)` — renders/updates memory table
  - `toggleRow(id)` — expand/collapse memory row
  - `timeAgo(iso)` — relative timestamp helper
  - `formatUptime(seconds)` — "2h 14m" helper
  - Countdown timer for refresh indicator

Full HTML (write to `app/dashboard.html`):

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pallium Dashboard</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }

:root {
  --bg: #1a1a2e;
  --card: #16213e;
  --border: #2a2a4a;
  --text: #e0e0e0;
  --text-dim: #888;
  --green: #0f3;
  --blue: #6af;
  --purple: #a6f;
  --yellow: #aa6;
  --red: #f66;
  --teal: #6a6;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Consolas', 'Liberation Mono', 'Menlo', monospace;
  font-size: 13px;
  line-height: 1.5;
}

/* Header */
.header {
  background: var(--card);
  padding: 12px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 100;
}
.header-left { display: flex; align-items: center; gap: 12px; }
.header-left img { height: 28px; }
.badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
}
.badge-ok { background: var(--green); color: #111; }
.badge-err { background: var(--red); color: #111; }
.header-right { font-size: 12px; color: var(--text-dim); }

/* Main content */
.main { padding: 20px 24px; max-width: 1400px; margin: 0 auto; }

/* Metric cards */
.metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
.metric-card {
  background: var(--card);
  border-radius: 8px;
  padding: 16px;
  border: 1px solid var(--border);
}
.metric-label { font-size: 11px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1px; }
.metric-value { font-size: 28px; font-weight: 700; margin-top: 4px; }
.metric-sub { font-size: 11px; margin-top: 2px; }

/* Two-column panels */
.panels { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
.panel {
  background: var(--card);
  border-radius: 8px;
  padding: 16px;
  border: 1px solid var(--border);
}
.panel-title { font-size: 13px; font-weight: 600; margin-bottom: 12px; color: #ccc; }

/* Rows inside panels */
.panel-row { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 12px; }
.panel-row-label { color: var(--text-dim); }

/* Storage bars */
.bar-bg { background: var(--border); border-radius: 4px; height: 6px; margin-bottom: 12px; margin-top: 4px; }
.bar-fill { border-radius: 4px; height: 6px; transition: width 0.3s; }

/* Skip reasons / queue table */
.table-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}
.table-row:last-child { border-bottom: none; }

/* Memory browser */
.browser {
  background: var(--card);
  border-radius: 8px;
  padding: 16px;
  border: 1px solid var(--border);
}
.browser-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.browser-controls { display: flex; gap: 8px; align-items: center; }
.browser-controls input, .browser-controls select {
  background: var(--border);
  border: 1px solid #3a3a5a;
  color: var(--text);
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-family: inherit;
}
.browser-controls input { width: 200px; }

/* Memory table */
.mem-table { width: 100%; font-size: 12px; }
.mem-table-header {
  display: grid;
  grid-template-columns: 100px 150px 1fr 100px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.mem-row {
  display: grid;
  grid-template-columns: 100px 150px 1fr 100px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.15s;
}
.mem-row:hover { background: rgba(255,255,255,0.02); }
.mem-row.suppressed { opacity: 0.5; text-decoration: line-through; }

.mem-type { font-weight: 500; }
.mem-type-decision { color: var(--blue); }
.mem-type-atomic_fact { color: var(--teal); }
.mem-type-fact_summary { color: var(--purple); }
.mem-type-interest { color: #f96; }
.mem-type-constraint_memory { color: var(--yellow); }
.mem-type-investigation_outcome { color: var(--blue); }
.mem-type-thread_summary { color: #8cf; }
.mem-type-discussion_summary { color: var(--text-dim); }
.mem-type-continuity_memory { color: #adf; }
.mem-type-pattern_memory { color: #daf; }

.mem-container { color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mem-text { color: #ccc; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mem-time { color: var(--text-dim); }

/* Expanded row */
.mem-expanded {
  padding: 12px 0 12px 16px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  display: none;
}
.mem-expanded.open { display: block; }
.mem-expanded-field { margin-bottom: 6px; }
.mem-expanded-label { color: var(--text-dim); display: inline-block; width: 100px; }
.evidence-btn {
  background: var(--border);
  border: 1px solid #3a3a5a;
  color: var(--blue);
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 11px;
  font-family: inherit;
  cursor: pointer;
  margin-top: 8px;
}
.evidence-btn:hover { background: #3a3a5a; }
.evidence-list { margin-top: 8px; padding-left: 12px; }
.evidence-item { margin-bottom: 8px; padding: 8px; background: var(--bg); border-radius: 4px; }
.evidence-item-meta { color: var(--text-dim); font-size: 11px; margin-bottom: 4px; }
.evidence-item-content { color: var(--text); white-space: pre-wrap; max-height: 150px; overflow-y: auto; }

/* Pagination */
.pagination { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; font-size: 12px; }
.pagination button {
  background: var(--border);
  border: 1px solid #3a3a5a;
  color: var(--text);
  padding: 4px 12px;
  border-radius: 4px;
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}
.pagination button:disabled { opacity: 0.4; cursor: default; }

/* Error banner */
.error-banner {
  background: #4a1a1a;
  color: var(--red);
  padding: 8px 24px;
  font-size: 12px;
  display: none;
}
.error-banner.visible { display: block; }

/* Hint text */
.hint { font-size: 11px; color: var(--text-dim); margin-top: 8px; }

/* Retention info */
.retention-info { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border); font-size: 11px; color: var(--text-dim); }
</style>
</head>
<body>

<div class="error-banner" id="error-banner">Connection lost — retrying...</div>

<div class="header">
  <div class="header-left">
    <img src="/static/logo/pallium_header.png" alt="Pallium">
    <span class="badge badge-ok" id="health-badge">HEALTHY</span>
  </div>
  <div class="header-right">
    <span id="uptime">—</span> &nbsp;|&nbsp; refreshing in <span id="countdown">10</span>s
  </div>
</div>

<div class="main">

  <!-- Metrics row -->
  <div class="metrics">
    <div class="metric-card">
      <div class="metric-label">Memory Objects</div>
      <div class="metric-value" id="m-memories">—</div>
      <div class="metric-sub" id="m-memories-sub">&nbsp;</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Source Items</div>
      <div class="metric-value" id="m-sources">—</div>
      <div class="metric-sub" id="m-sources-sub">&nbsp;</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Queries</div>
      <div class="metric-value" id="m-queries">—</div>
      <div class="metric-sub" id="m-queries-sub">&nbsp;</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Pending Queue</div>
      <div class="metric-value" id="m-pending">—</div>
      <div class="metric-sub" id="m-pending-sub">&nbsp;</div>
    </div>
  </div>

  <!-- Panels row 1: Storage + Query Stats -->
  <div class="panels">
    <div class="panel">
      <div class="panel-title">Storage</div>
      <div class="panel-row"><span class="panel-row-label">SQLite DB</span><span id="storage-sqlite">—</span></div>
      <div class="bar-bg"><div class="bar-fill" id="bar-sqlite" style="width:0%; background: var(--blue);"></div></div>
      <div class="panel-row"><span class="panel-row-label">Vector Index</span><span id="storage-vector">—</span></div>
      <div class="bar-bg"><div class="bar-fill" id="bar-vector" style="width:0%; background: var(--purple);"></div></div>
      <div class="panel-row"><span class="panel-row-label">Vector Ready</span><span id="storage-vready">—</span></div>
    </div>
    <div class="panel">
      <div class="panel-title">Query &amp; Injection</div>
      <div class="panel-row"><span class="panel-row-label">Total Queries</span><span id="q-total">—</span></div>
      <div class="panel-row"><span class="panel-row-label">Injections</span><span id="q-injections">—</span></div>
      <div class="panel-row"><span class="panel-row-label">Skipped</span><span id="q-skips">—</span></div>
      <div class="panel-row"><span class="panel-row-label">Blocks Injected</span><span id="q-blocks">—</span></div>
      <div class="panel-row"><span class="panel-row-label">Flags / Suppressions</span><span id="q-flags">—</span></div>
      <div class="panel-row"><span class="panel-row-label">Last Query</span><span id="q-last">—</span></div>
    </div>
  </div>

  <!-- Panels row 2: Skip Reasons + Processing Queue -->
  <div class="panels">
    <div class="panel">
      <div class="panel-title">Skip Reasons</div>
      <div id="skip-reasons"><div class="hint">No skips yet</div></div>
    </div>
    <div class="panel">
      <div class="panel-title">Processing Queue</div>
      <div id="queue-status">
        <div class="panel-row"><span class="panel-row-label">Pending</span><span id="pq-pending">—</span></div>
        <div class="panel-row"><span class="panel-row-label">Processing</span><span id="pq-processing">—</span></div>
        <div class="panel-row"><span class="panel-row-label">Completed</span><span id="pq-completed">—</span></div>
        <div class="panel-row"><span class="panel-row-label">Failed</span><span id="pq-failed">—</span></div>
        <div class="panel-row"><span class="panel-row-label">Skipped</span><span id="pq-skipped">—</span></div>
      </div>
      <div class="retention-info" id="retention-info">—</div>
    </div>
  </div>

  <!-- Memory Browser -->
  <div class="browser">
    <div class="browser-header">
      <div class="panel-title" style="margin-bottom:0">Memory Browser</div>
      <div class="browser-controls">
        <input type="text" id="mem-search" placeholder="Filter memories...">
        <select id="mem-type-filter">
          <option value="">all types</option>
        </select>
        <select id="mem-lifecycle-filter">
          <option value="">all states</option>
          <option value="active">active</option>
          <option value="suppressed">suppressed</option>
          <option value="superseded">superseded</option>
        </select>
      </div>
    </div>
    <div class="mem-table">
      <div class="mem-table-header">
        <span>Type</span><span>Container</span><span>Summary</span><span>Created</span>
      </div>
      <div id="mem-rows"></div>
    </div>
    <div class="pagination">
      <span id="mem-page-info">—</span>
      <div>
        <button id="mem-prev" disabled>&larr; Prev</button>
        <button id="mem-next" disabled>Next &rarr;</button>
      </div>
    </div>
  </div>

</div>

<script>
const REFRESH_INTERVAL = 10;
let countdown = REFRESH_INTERVAL;
let memoryOffset = 0;
const MEMORY_LIMIT = 50;
let currentMemories = [];
let knownTypes = new Set();

// --- Helpers ---
function timeAgo(iso) {
  if (!iso) return '—';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return Math.round(diff) + 's ago';
  if (diff < 3600) return Math.round(diff / 60) + 'm ago';
  if (diff < 86400) return Math.round(diff / 3600) + 'h ago';
  return Math.round(diff / 86400) + 'd ago';
}

function formatUptime(seconds) {
  if (!seconds) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return h + 'h ' + m + 'm';
  return m + 'm ' + Math.round(seconds % 60) + 's';
}

function pct(a, b) { return b > 0 ? Math.round(a / b * 100) : 0; }

function showError(show) {
  document.getElementById('error-banner').classList.toggle('visible', show);
}

// --- Fetch & Render ---
async function fetchStatus() {
  try {
    const resp = await fetch('/status');
    if (!resp.ok) throw new Error('status ' + resp.status);
    const data = await resp.json();
    showError(false);
    renderStatus(data);
  } catch (e) {
    showError(true);
  }
}

async function fetchQueueHealth() {
  try {
    const resp = await fetch('/debug/queue/health');
    if (!resp.ok) return;
    const data = await resp.json();
    renderQueue(data);
  } catch (e) { /* silent */ }
}

async function fetchMemories() {
  const type = document.getElementById('mem-type-filter').value;
  const lifecycle = document.getElementById('mem-lifecycle-filter').value;
  let url = '/dashboard/api/memories?limit=' + MEMORY_LIMIT + '&offset=' + memoryOffset;
  if (type) url += '&type=' + encodeURIComponent(type);
  if (lifecycle) url += '&lifecycle=' + encodeURIComponent(lifecycle);
  try {
    const resp = await fetch(url);
    if (!resp.ok) return;
    const data = await resp.json();
    currentMemories = data.memories;
    renderMemories(data);
  } catch (e) { /* silent */ }
}

async function fetchEvidence(memId, container) {
  const el = document.getElementById('evidence-' + memId);
  if (el.dataset.loaded === 'true') return;
  el.innerHTML = '<div class="hint">Loading evidence...</div>';
  try {
    let url = '/memory/' + memId + '/evidence';
    if (container) url += '?container_ref=' + encodeURIComponent(container);
    const resp = await fetch(url);
    if (!resp.ok) { el.innerHTML = '<div class="hint">Failed to load</div>'; return; }
    const data = await resp.json();
    if (!data.items || data.items.length === 0) {
      el.innerHTML = '<div class="hint">No evidence items</div>';
    } else {
      el.innerHTML = data.items.map(item =>
        '<div class="evidence-item">' +
          '<div class="evidence-item-meta">' + (item.role || '') + ' | ' + (item.source_type || '') + ' | ' + timeAgo(item.occurred_at) + '</div>' +
          '<div class="evidence-item-content">' + escapeHtml(item.content || '').slice(0, 500) + '</div>' +
        '</div>'
      ).join('');
    }
    el.dataset.loaded = 'true';
  } catch (e) { el.innerHTML = '<div class="hint">Error loading evidence</div>'; }
}

function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function renderStatus(data) {
  // Health badge
  const badge = document.getElementById('health-badge');
  const isOk = data.vector_index_ready !== false && data.pending_items !== null;
  badge.textContent = isOk ? 'HEALTHY' : 'UNHEALTHY';
  badge.className = 'badge ' + (isOk ? 'badge-ok' : 'badge-err');

  // Uptime
  document.getElementById('uptime').textContent = formatUptime(data.uptime_seconds);

  // Metrics
  document.getElementById('m-memories').textContent = data.total_memory_objects ?? '—';
  document.getElementById('m-sources').textContent = data.total_source_items ?? '—';
  document.getElementById('m-sources-sub').textContent = 'total ingested';

  const q = data.query || {};
  document.getElementById('m-queries').textContent = q.total_queries ?? '—';
  const injRate = pct(q.total_injections || 0, q.total_queries || 0);
  const rateColor = injRate < 50 ? 'var(--yellow)' : 'var(--blue)';
  document.getElementById('m-queries-sub').innerHTML = '<span style="color:' + rateColor + '">' + injRate + '% injection rate</span>';

  const pending = data.pending_items ?? 0;
  document.getElementById('m-pending').textContent = pending;
  const pendColor = pending === 0 ? 'var(--green)' : pending > 10 ? 'var(--red)' : 'var(--yellow)';
  document.getElementById('m-pending').style.color = pendColor;
  document.getElementById('m-pending-sub').textContent = pending === 0 ? 'all caught up' : (data.oldest_pending_age_seconds ? 'oldest: ' + Math.round(data.oldest_pending_age_seconds) + 's' : '');

  // Storage
  const sqlite = data.storage?.sqlite_mb;
  const vector = data.storage?.vector_index_mb;
  document.getElementById('storage-sqlite').textContent = sqlite != null ? sqlite + ' MB' : '—';
  document.getElementById('storage-vector').textContent = vector != null ? vector + ' MB' : '—';
  document.getElementById('bar-sqlite').style.width = sqlite ? Math.min(sqlite / 50 * 100, 100) + '%' : '0%';
  document.getElementById('bar-vector').style.width = vector ? Math.min(vector / 50 * 100, 100) + '%' : '0%';
  document.getElementById('storage-vready').innerHTML = data.vector_index_ready ? '<span style="color:var(--green)">yes</span>' : '<span style="color:var(--yellow)">no</span>';

  // Query stats
  document.getElementById('q-total').textContent = q.total_queries ?? '—';
  const injections = q.total_injections || 0;
  const skips = q.total_skips || 0;
  document.getElementById('q-injections').innerHTML = '<span style="color:var(--teal)">' + injections + ' (' + pct(injections, q.total_queries || 0) + '%)</span>';
  document.getElementById('q-skips').innerHTML = '<span style="color:var(--yellow)">' + skips + ' (' + pct(skips, q.total_queries || 0) + '%)</span>';
  document.getElementById('q-blocks').textContent = q.total_blocks_injected ?? '—';
  document.getElementById('q-flags').innerHTML = '<span style="color:var(--red)">' + (q.total_flags || 0) + ' / ' + (q.total_suppressions || 0) + '</span>';
  document.getElementById('q-last').textContent = q.last_query_at ? timeAgo(q.last_query_at) : 'never';

  // Skip reasons
  const skipReasons = q.skip_reasons || {};
  const skipEl = document.getElementById('skip-reasons');
  const entries = Object.entries(skipReasons).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) {
    skipEl.innerHTML = '<div class="hint">No skips yet</div>';
  } else {
    skipEl.innerHTML = entries.map(([reason, count]) =>
      '<div class="table-row"><span style="color:var(--yellow)">' + escapeHtml(reason) + '</span><span>' + count + '</span></div>'
    ).join('');
  }
}

function renderQueue(data) {
  const sc = data.status_counts || {};
  document.getElementById('pq-pending').innerHTML = '<span style="color:' + (sc.pending ? 'var(--yellow)' : 'var(--green)') + '">' + (sc.pending ?? 0) + '</span>';
  document.getElementById('pq-processing').innerHTML = '<span style="color:var(--blue)">' + (sc.processing ?? 0) + '</span>';
  document.getElementById('pq-completed').textContent = sc.completed ?? 0;
  document.getElementById('pq-failed').innerHTML = '<span style="color:' + (sc.failed ? 'var(--red)' : 'inherit') + '">' + (sc.failed ?? 0) + '</span>';
  document.getElementById('pq-skipped').innerHTML = '<span style="color:var(--yellow)">' + (sc.skipped ?? 0) + '</span>';

  const ret = data.retention || {};
  const retEl = document.getElementById('retention-info');
  if (ret.enabled) {
    const lastRun = ret.last_run_completed_at ? timeAgo(ret.last_run_completed_at) : 'never';
    const deleted = (ret.last_deleted_source_items || 0) + (ret.last_deleted_memory_objects || 0);
    retEl.textContent = 'Retention: last run ' + lastRun + (deleted ? ', cleaned ' + deleted + ' items' : '');
  } else {
    retEl.textContent = 'Retention: disabled';
  }
}

function renderMemories(data) {
  const container = document.getElementById('mem-rows');
  const search = document.getElementById('mem-search').value.toLowerCase();
  const memories = data.memories.filter(m => !search || m.display_text.toLowerCase().includes(search));

  // Update type filter options
  data.memories.forEach(m => {
    if (!knownTypes.has(m.type)) {
      knownTypes.add(m.type);
      const opt = document.createElement('option');
      opt.value = m.type;
      opt.textContent = m.type;
      document.getElementById('mem-type-filter').appendChild(opt);
    }
  });

  if (memories.length === 0) {
    container.innerHTML = '<div class="hint" style="padding:12px 0">No memories found</div>';
  } else {
    container.innerHTML = memories.map(m => {
      const rowClass = 'mem-row' + (m.lifecycle === 'suppressed' ? ' suppressed' : '');
      const typeClass = 'mem-type mem-type-' + m.type;
      return '<div class="' + rowClass + '" onclick="toggleRow(\'' + m.id + '\')">' +
        '<span class="' + typeClass + '">' + m.type + '</span>' +
        '<span class="mem-container" title="' + escapeHtml(m.container_ref || '') + '">' + (m.container_ref || '—').slice(0, 20) + '</span>' +
        '<span class="mem-text" title="' + escapeHtml(m.display_text || '') + '">' + escapeHtml(m.display_text || '—') + '</span>' +
        '<span class="mem-time">' + timeAgo(m.created_at) + '</span>' +
      '</div>' +
      '<div class="mem-expanded" id="expanded-' + m.id + '">' +
        '<div class="mem-expanded-field"><span class="mem-expanded-label">ID:</span>' + m.id + '</div>' +
        '<div class="mem-expanded-field"><span class="mem-expanded-label">Type:</span>' + m.type + '</div>' +
        '<div class="mem-expanded-field"><span class="mem-expanded-label">Lifecycle:</span>' + m.lifecycle + '</div>' +
        '<div class="mem-expanded-field"><span class="mem-expanded-label">Confidence:</span>' + (m.confidence || 'unknown') + '</div>' +
        '<div class="mem-expanded-field"><span class="mem-expanded-label">Full text:</span>' + escapeHtml(m.display_text || '') + '</div>' +
        '<button class="evidence-btn" onclick="event.stopPropagation(); fetchEvidence(\'' + m.id + '\', \'' + escapeHtml(m.container_ref || '') + '\')">View Evidence</button>' +
        '<div class="evidence-list" id="evidence-' + m.id + '"></div>' +
      '</div>';
    }).join('');
  }

  // Pagination
  document.getElementById('mem-page-info').textContent =
    'Showing ' + (data.offset + 1) + '–' + (data.offset + memories.length) + ' of ' + data.total;
  document.getElementById('mem-prev').disabled = data.offset === 0;
  document.getElementById('mem-next').disabled = data.offset + data.limit >= data.total;
}

function toggleRow(id) {
  const el = document.getElementById('expanded-' + id);
  if (el) el.classList.toggle('open');
}

// --- Pagination ---
document.getElementById('mem-prev').addEventListener('click', () => {
  memoryOffset = Math.max(0, memoryOffset - MEMORY_LIMIT);
  fetchMemories();
});
document.getElementById('mem-next').addEventListener('click', () => {
  memoryOffset += MEMORY_LIMIT;
  fetchMemories();
});

// --- Filters ---
document.getElementById('mem-type-filter').addEventListener('change', () => { memoryOffset = 0; fetchMemories(); });
document.getElementById('mem-lifecycle-filter').addEventListener('change', () => { memoryOffset = 0; fetchMemories(); });
document.getElementById('mem-search').addEventListener('input', () => {
  // Client-side filter on current data
  renderMemories({ memories: currentMemories, total: currentMemories.length, offset: memoryOffset, limit: MEMORY_LIMIT });
});

// --- Refresh loop ---
async function refresh() {
  await Promise.all([fetchStatus(), fetchQueueHealth(), fetchMemories()]);
}

setInterval(() => {
  countdown--;
  document.getElementById('countdown').textContent = countdown;
  if (countdown <= 0) {
    countdown = REFRESH_INTERVAL;
    refresh();
  }
}, 1000);

// Initial load
refresh();
</script>
</body>
</html>
```

- [ ] **Step 2: Verify in browser**

Run: `python -m app.run serve --host 127.0.0.1 --port 8000`

Open: http://localhost:8000/dashboard

Verify:
- Logo loads in header
- Health badge shows HEALTHY (green)
- Metrics cards populate with numbers
- Storage panel shows DB and vector sizes
- Query stats show counts
- Memory browser lists memories (if any exist)
- Clicking a row expands details
- "View Evidence" button loads evidence
- Filters and pagination work
- Error banner appears if you stop the server and reopen

- [ ] **Step 3: Commit**

```bash
git add app/dashboard.html
git commit -m "feat(dashboard): complete dashboard HTML with all sections and interactive memory browser"
```

---

### Task 4: Final integration test and cleanup

**Files:**
- Modify: `tests/test_dashboard.py` (add integration test)

- [ ] **Step 1: Add integration test verifying full flow**

Append to `tests/test_dashboard.py`:

```python
class TestDashboardIntegration:

    def test_dashboard_html_contains_key_elements(self) -> None:
        app = create_app(_test_config())
        with TestClient(app) as client:
            resp = client.get("/dashboard")
        html = resp.text
        assert "Pallium Dashboard" in html
        assert "/static/logo/pallium_header.png" in html
        assert "fetchStatus" in html
        assert "/dashboard/api/memories" in html

    def test_memories_display_text_extraction(self) -> None:
        app = create_app(_test_config())
        with TestClient(app) as client:
            service = app.state.pallium_service
            mo = MemoryObject(
                type="investigation_outcome",
                schema_id="test",
                schema_version="1.0",
                payload={"investigation_outcome": "Found root cause in parser", "other": "data"},
                lifecycle="active",
                created_at=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
            )
            service._storage.store_memory_object(mo)
            resp = client.get("/dashboard/api/memories")
        body = resp.json()
        assert body["memories"][0]["display_text"] == "Found root cause in parser"

    def test_memories_default_lifecycle_shows_all(self) -> None:
        """When no lifecycle filter is passed, all lifecycles are returned."""
        app = create_app(_test_config())
        with TestClient(app) as client:
            _seed_memory(app, type="decision", lifecycle="active")
            _seed_memory(app, type="decision", lifecycle="suppressed")
            _seed_memory(app, type="decision", lifecycle="superseded")
            resp = client.get("/dashboard/api/memories")
        body = resp.json()
        assert body["total"] == 3
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run existing tests to check for regressions**

Run: `python -m pytest tests/test_health.py -v`
Expected: All existing health tests still pass (the static mount and new routes don't conflict)

- [ ] **Step 4: Commit**

```bash
git add tests/test_dashboard.py
git commit -m "test(dashboard): add integration tests for HTML content and display_text extraction"
```

---

### Task 5: Add `.superpowers/` to `.gitignore`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Append `.superpowers/` to `.gitignore`**

```
.superpowers/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add .superpowers/ to gitignore"
```
