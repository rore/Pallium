# Dashboard

Pallium includes a browser-based dashboard for inspecting stored memories,
viewing evidence chains, and checking system health.

## Access

Open in your browser:

- **Service mode:** http://localhost:19836/dashboard
- **Dev mode:** http://localhost:8000/dashboard

No authentication required — the dashboard is localhost-only, same as the API.

## Features

### Memory Browser

The main view lists all stored memory objects with:

- **Filtering** by memory type (decision, investigation_outcome, atomic_fact,
  etc.), lifecycle state, and container
- **Sorting** by creation date or negative feedback count
- **Pagination** for large memory stores

Each row shows the memory type, display text, confidence level, container,
and creation timestamp.

### Memory Detail

Click any memory to see:

- Full payload (all extracted fields)
- Envelope metadata (confidence, schema, visibility, subject)
- Feedback history (relevant/not_relevant ratings with reasons)
- Source evidence links

### Feedback

The dashboard shows aggregated feedback counts (relevant vs. not_relevant)
per memory. Feedback is submitted by agents via the `pallium_rate_memory`
MCP tool during normal operation — the dashboard surfaces it for inspection.

### Evidence

Each memory links back to its source items — the original conversation turns
from which it was extracted. The detail view shows these evidence connections.

## When to Use

- **Debugging retrieval** — check what memories exist for a container and
  whether the expected content was extracted
- **Verifying extraction** — inspect the payload fields Pallium derived from
  a conversation turn
- **Reviewing feedback** — see which memories have been rated not_relevant
  by agents, indicating potential quality issues
- **Monitoring health** — confirm memories are being created and processing
  is active

## Dark Theme

The dashboard uses a dark theme by default with no toggle needed.
