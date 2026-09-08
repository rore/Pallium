---
id: add-context-conscious-upstream-field-feedback
title: Context-conscious upstream field feedback
status: done
priority: medium
commitment: committed
milestone: Later
lane: integration-feedback
---

## Summary

Give Pallium's Codex, Claude Code, and OpenCode skills a tiny always-loaded trigger that opens detailed, privacy-safe upstream defect reporting only when a repeatable Pallium-owned defect is observed.

This lane covers product, integration, contract, packaging, and documentation defects in `rore/Pallium`. Memory extraction, retrieval, ranking, relevance, and injection misses remain owned by [the existing feedback and replay loop](add-live-integration-improvement-loop-and-replay-pipeline.md).

## In Scope

- byte-identical lazy guidance across all three shipped skills
- explicit repeatability, actionability, upstream ownership, redaction, duplicate, approval, bounded issue, and fallback rules
- full-tree Codex and Claude installation plus OpenCode package verification

## Out of Scope

- telemetry, service APIs, feedback databases, or automatic issue submission
- memory-quality miss capture, scoring, or replay promotion

## Done When

All three normal-context pointers stay bounded and aligned, their detailed references ship through each supported install/package path, lifecycle and privacy contracts are tested, and the workflow is independently reviewed.
