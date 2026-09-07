---
id: fix-disabled-derived-memory-injection-observability
title: Make disabled derived-memory injection truly quiet
status: done
priority: high
commitment: committed
milestone: pallium-vnext-session-history
lane: architecture
---

## Product outcome

When the active default derived-memory package is unavailable, Pallium still
records and searches raw Session History but does not search derived memory and
does not report the no-op as a skipped injection. The dashboard states whether
automatic injection can actually run.

## Contract

- Raw hook ingest continues through the shared server endpoint.
- A disabled automatic query exits before retrieval, routing, or model work.
- Disabled automatic queries create no injection counters, skip metrics, or
  generic query-audit rows.
- Explicit raw Session History searches remain available and retain their
  dedicated historical-lookup event, but never count as injection activity.
- `/status` distinguishes any active derived processing from availability of the
  configured default package used for automatic injection.
- Existing historical metrics are preserved; the change applies only to new
  events.

## Evidence

Covered by the Work Record
[`codex-disable-derived-injection-when-off`](../../.agent-workflow/tasks/codex-disable-derived-injection-when-off.md)
and caller-facing disabled/enabled lifecycle tests.