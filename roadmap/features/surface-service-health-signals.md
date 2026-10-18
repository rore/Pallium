---
id: surface-service-health-signals
title: Surface service health signals
status: done
priority: high
commitment: committed
milestone: Done
---

## Outcome

Health and status now expose embedding-provider readiness and report degraded service state when configured vector search is unavailable; the dashboard surfaces the signal.

## Evidence

Shipped in commit `f1bf81c` ([Work Record](../../.agent-workflow/tasks/surface-service-health-signals.md)).

The October 9 service incident follow-up closes synchronous Relay callback and
registry I/O on the HTTP event loop and removes repeated diagnostic table scans.
Caller-surface regressions verify concurrent health responses, unchanged message
and reply persistence, callback failure handling and legacy NULL-status queue
semantics. Release and installed verification are tracked in the
[incident Work Record](../../.agent-workflow/tasks/relay-callback-offload.md).
The 120-second startup allowance remains a safeguard, not a performance fix;
the complete historical outage cause is not established by these regressions.

