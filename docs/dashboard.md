# Dashboard

Pallium includes a browser-based dashboard for inspecting stored memories,
viewing evidence chains, checking system health, and debugging query behavior.

![Dashboard](../assets/dashboard_screenshot.png)

## Access

Open in your browser:

- **Service mode:** http://localhost:19836/dashboard
- **Dev mode:** http://localhost:8000/dashboard

No authentication required — the dashboard is localhost-only, same as the API.

## Features

### Overview

Four dual-time metric cards. Every important number shows the **last 24h**
(prominent, bright) alongside the **all-time** total (small, muted) so trends
are visible without needing to compare to memory.

- **Memory Objects** — `active / total` counts with a 24h creation sparkline
  and `+N created in 24h`
- **Source Items** — `processed 24h · total ingested` with a 24h sparkline
  and live pending / processing counters
- **Queries** — `24h · all-time` query count, hourly sparkline, and inject
  rate for both windows
- **Failed** — `24h · all-time` extraction failures, sparkline, plus
  current pending detail

The 24h sparkline anchors each card in the recent-window context so the
prominent number isn't read in isolation.

### System Health

Three cards aligned to the same row height:

- **Storage** — SQLite database and vector index sizes. Bars are normalized
  against absolute thresholds (200 MB / 50 MB) so the smaller index is no
  longer dwarfed by SQLite's larger footprint.
- **Ingestion Queue** — Pending · Done 24h+total · Failed 24h+total ·
  Skipped 24h+total. Every tile follows the dual-time pattern; retention
  state is the footer.
- **Extraction Health** — last three failures with category, error excerpt,
  attempts, and date — sourced from `/debug/queue/health.recent_failures`.
  When there are no recent failures the card simply reads `✓ no recent failures`.

### Query Activity

Two cards. The left card has four dual-time tiles plus an hourly stacked bar.

- **Injections** — 24h count with `blocks · avg blocks` plus all-time count
  and all-time average; revealing that recent quality differs from history.
- **Skips** — 24h · all-time, and `% of 24h queries` for context.
- **Flags / Suppressions** — 24h · all-time for flags; suppressions still
  fall back to the since-restart counter pending metrics-table wiring.
- **Feedback** — 24h count + all-time count, with a not-relevant rate for
  each window. Click `▸ review` to jump to the Memory Browser sorted by
  most negative.
- **Last 24h hourly** stacked bar — green = injections, yellow = skips —
  shows when query traffic actually happens.

The right card is the **Skip Reasons** trend table:

| Skip Reason | 24h | 7d | Δ vs prior 6d | 24h hourly |
|---|---|---|---|---|

Each row has a delta chip (`+47%`, `-12%`, `≈`, `new`) for today vs the
average of the prior 6 days, plus a per-row 24h hourly sparkline. The
footer totals 24h / 7d / all-time skips. This is how regressions like
`no_relevant_memory` jumping today first become visible.

### Memory Browser

The main view lists all stored memory objects with:

- **Search** — server-side text search across memory payloads
- **Filtering** by memory type, lifecycle state, and container
- **Sorting** by creation date or negative feedback count
- **Pagination** for large memory stores
- **Absolute timestamps** (e.g., `Apr 16 17:57`)

Each row shows the memory type, lifecycle, confidence level, container,
creation timestamp, and summary text.

### Memory Detail

Click any memory to see:

- **ID** with copy-to-clipboard button (for use with `pallium_flag_memory`)
- **Content fields** — decision, rationale, summary, interest_text, etc.
  displayed as structured key-value pairs
- **Technical metadata** — semantic provenance, source info (collapsed)
- **Feedback history** — relevant/not_relevant ratings with reasons
- **Evidence** — source conversation items grouped by thread, ordered
  chronologically

### Query Debug

Collapsible panel at the bottom for testing queries interactively:

- Enter query text and optionally select a container
- Calls `POST /query/debug` and shows:
  - Whether injection would occur (INJECT/SKIP)
  - Decision reason
  - Injectable memory blocks
  - Retrieval stage trace (candidates and selections per stage)

### Feedback

The dashboard shows aggregated feedback counts (relevant vs. not_relevant)
per memory. Feedback is submitted by agents via the `pallium_rate_memory`
MCP tool during normal operation — the dashboard surfaces it for inspection.

## When to Use

- **Monitoring health** — confirm the service is up, memories are being
  created, and processing is active
- **Debugging retrieval** — use Query Debug to test what memories would be
  injected for a given query
- **Verifying extraction** — inspect the content fields Pallium derived from
  conversation turns
- **Reviewing feedback** — sort by "Most negatively rated" to surface
  memories that agents consistently find irrelevant
- **Investigating skips** — check skip reasons to understand why queries
  aren't producing injections

## Dark Theme

The dashboard uses a dark theme by default with no toggle needed.
