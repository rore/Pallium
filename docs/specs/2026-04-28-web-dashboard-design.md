# Web Dashboard Design

**Date:** 2026-04-28
**Status:** Proposed

## Problem

Pallium runs as a local sidecar for Claude Code, but there's no way to observe its behavior in real time. The only visibility is through the MCP `pallium_status` tool (text output in the agent conversation) or raw API calls. When tuning extraction, routing, or retrieval quality, you need to see what's actually happening — how many memories exist, what's being injected, what's being skipped, and what the queue looks like.

## Goals

1. See at a glance whether Pallium is healthy and active
2. Understand ingestion/injection flow — is it working, how often, what's being skipped
3. Browse memory objects to understand what was extracted and spot quality issues
4. Zero setup — just open a URL while Pallium is running

## Non-Goals

- Historical time-series (no persistent metrics store)
- Write actions from the dashboard (no flagging, deleting, or re-processing)
- Authentication (local-only service)
- Mobile responsiveness (dev tool, viewed on desktop)

## Approach

Single HTML page served at `GET /dashboard` by the existing FastAPI app. Vanilla HTML/CSS/JS, no build step, no external dependencies. Polls existing REST endpoints every 10 seconds. Static assets (logo) served via a `/static/` mount.

## Architecture

```
Browser                         Pallium FastAPI
  │                                   │
  │  GET /dashboard                   │
  │──────────────────────────────────>│  → returns single HTML page
  │                                   │
  │  GET /static/pallium_header.png   │
  │──────────────────────────────────>│  → serves logo
  │                                   │
  │  (every 10s)                      │
  │  GET /status                      │
  │──────────────────────────────────>│  → returns full status JSON
  │                                   │
  │  GET /debug/queue/health          │
  │──────────────────────────────────>│  → returns queue state
  │                                   │
  │  GET /dashboard/api/memories?...  │
  │──────────────────────────────────>│  → returns paginated memory list
  │                                   │
  │  GET /memory/{id}/evidence        │
  │──────────────────────────────────>│  → returns evidence for expansion
  │                                   │
```

## New Endpoints

### `GET /dashboard`

Returns the HTML page. Single inline `<style>` and `<script>` block. No external CSS/JS.

### `GET /dashboard/api/memories`

New endpoint for the memory browser. Builds on `storage.list_memory_objects()` but adds pagination (LIMIT/OFFSET at the SQL level) and a computed display text.

**Query params:**
- `type` (optional) — filter by memory type (e.g., `decision`, `atomic_fact`)
- `lifecycle` (optional) — filter by lifecycle (`active`, `suppressed`, `superseded`). Default: `active`
- `container_ref` (optional) — filter by container
- `limit` (optional) — max results, default 50, max 200
- `offset` (optional) — pagination offset

**Response:**
```json
{
  "memories": [
    {
      "id": "abc-123",
      "type": "decision",
      "lifecycle": "active",
      "container_ref": "git:github.com/rore/pallium",
      "thread_ref": "session-xyz",
      "display_text": "Auth middleware rewrite driven by compliance...",
      "confidence": 0.85,
      "created_at": "2026-04-28T10:30:00Z"
    }
  ],
  "total": 142,
  "offset": 0,
  "limit": 50
}
```

**Note:** `display_text` is computed from the payload dict:
`payload.get("summary") or payload.get("decision") or payload.get("investigation_outcome") or payload.get("interest_text") or payload.get("constraint_text") or ""`
```

### `GET /static/{path}`

FastAPI `StaticFiles` mount pointing to `assets/` directory for the logo.

## Dashboard Sections

### 1. Header Bar

- Pallium logo (`pallium_header.png`, constrained to 28px height)
- Health badge: green "HEALTHY" or red "UNHEALTHY" (based on `/health` response)
- Uptime display (from `/status.uptime_seconds`)
- Auto-refresh indicator ("refreshing in 8s...")

### 2. Key Metrics Row (4 cards)

| Card | Source | Color Logic |
|------|--------|-------------|
| Memory Objects | `status.total_memory_objects` | Neutral |
| Source Items | `status.total_source_items` | Neutral |
| Queries (injection rate) | `status.query.total_queries`, computed rate | Rate < 50%: yellow |
| Pending Queue | `status.pending_items` | 0: green, >0: yellow, >10: red |

### 3. Storage Panel

- SQLite DB size (`status.storage.sqlite_mb`) with visual bar
- Vector index size (`status.storage.vector_index_mb`) with visual bar
- Data directory path (informational)
- Vector index ready status

### 4. Query & Injection Panel

- Total queries / injections / skips with percentages
- Blocks injected (total)
- Flags / suppressions count
- Last query timestamp (relative: "3s ago")

### 5. Skip Reasons

Table of `status.query.skip_reasons` sorted by count descending. Helps identify why queries aren't injecting.

### 6. Processing Queue

- Status counts from `/debug/queue/health`: pending, processing, completed, failed, skipped
- Recent failures (if any) — shows error message and attempt count
- Retention status: last run time, items cleaned

### 7. Memory Browser

- Search input (client-side filter on loaded results)
- Type filter dropdown (all types from the data)
- Sortable table: type, container, summary (truncated), created_at (relative)
- Click row to expand: full summary, confidence, thread_ref, lifecycle
- Expanded row has "View Evidence" button → fetches `/memory/{id}/evidence` and shows source items inline
- Suppressed/flagged memories shown with strikethrough and flag icon
- Pagination (50 per page)

## Visual Design

- **Theme**: Dark navy (#1a1a2e background, #16213e cards) — matches Pallium logo palette
- **Typography**: System monospace stack (`'SF Mono', 'Consolas', 'Liberation Mono', monospace`)
- **Colors**:
  - Green (#0f3): healthy, zero pending, good states
  - Blue (#6af): informational metrics, links
  - Purple (#a6f): vector/embedding related
  - Yellow (#aa6): warnings, skips
  - Red (#f66): errors, failures, flags
  - Teal (#6a6): success rates, active counts
- **Status indicators**: Pill badges for health, colored dots for memory types
- **Cards**: Rounded corners (8px), subtle border (#2a2a4a), consistent padding
- **Responsive**: Not required (desktop dev tool), but fluid grid that works at 1200px+

## File Structure

```
app/
  dashboard.py          — route handler, memories endpoint, mount function
  dashboard.html        — the HTML page (CSS + JS inline, read and served by dashboard.py)
assets/
  logo/                 — existing logo files (served as static)
```

`app/dashboard.py` contains:
- `mount_dashboard(app)` function that registers all routes and static mount
- `/dashboard/api/memories` endpoint with pagination
- Reads and serves `app/dashboard.html` for the `/dashboard` route

`app/dashboard.html` contains:
- Complete HTML page with inline `<style>` and `<script>`
- All dashboard UI logic (polling, rendering, memory browser interactions)

## Integration with `app/main.py`

```python
from app.dashboard import mount_dashboard

def create_app(...):
    app = FastAPI(...)
    # ... existing setup ...
    mount_dashboard(app)
    return app
```

`mount_dashboard(app)` handles:
- `app.mount("/static", StaticFiles(directory="assets"), name="static")`
- `app.get("/dashboard")` route
- `app.get("/dashboard/api/memories")` route

## Polling Strategy

- `/status` and `/debug/queue/health`: every 10 seconds
- Memory browser: on initial load + when user changes filters/pagination
- Visual refresh countdown in header so user knows data freshness
- Fetch errors shown as a banner ("Connection lost — retrying...") without crashing the page

## Future Extensions (not in scope)

- Historical metrics with a time-series SQLite table
- Query audit log browser (replay individual query traces)
- WebSocket push instead of polling
- Dark/light theme toggle
- Export functionality
