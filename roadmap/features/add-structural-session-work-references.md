---
id: add-structural-session-work-references
title: Attach structural work references to session history
status: done
priority: high
commitment: committed
milestone: pallium-vnext-session-history
lane: product-foundation
---

## Product outcome

Raw session turns carry reliable identifiers for the work they belong to whenever
the integrations already know them. Work-scoped history can then find prior work by
identity instead of hoping that free-text similarity reconstructs it.

## Current implementation

The shipped work-reference foundation accepts only list-valued explicit refs in
`metadata["pallium_work_refs"]`. The server redacts sensitive candidates, normalizes
and deduplicates them, and caps the stored result at five; invalid or redacted
candidates are dropped. Claude Code, Codex, and OpenCode attach branch and exact
Agent Workflow Work Record refs before ingestion, except that OpenCode on Windows
uses explicit refs only to avoid unsafe synchronous filesystem access through reparse
handlers. Elsewhere the structural resolver launches no process, reads only bounded
local metadata, and fails open to normal ingestion. Content-derived refs
remain semantic output and are not required for the raw Session History path.
## In scope

- In Python-based Claude Code and Codex hooks, and in OpenCode where the host can
  safely inspect local metadata, read the current Git branch from the hook working
  directory and attach a normalized, namespaced branch work reference. Windows
  OpenCode remains explicit-reference-only because Node cannot safely classify
  every reparse/cloud-placeholder path without risking developer work.
- When the branch follows Agent Workflow's branch-to-record convention, calculate
  the one expected `.agent-workflow/tasks/<slug>.md` path and attach a distinct Work
  Record reference only if that exact file exists.
- On `main`, another long-lived base branch, or detached HEAD, do not invent a
  current Work Record.
- Preserve structurally available Jira, pull-request, issue, incident, or similar
  identifiers from existing hook/event fields. Merge them with caller-provided
  references using the shipped normalization and deduplication path.
- Store the bounded result in the existing `pallium_work_refs` source metadata.
  Structural references must be available before and without semantic processing.
- Measure hook latency and failure behavior. No resolver subprocess or cache is in
  scope; unsafe platforms or paths preserve normal ingestion and explicit refs.

## Out of scope

- Asking an LLM whether a turn is still about a branch or Work Record.
- Scanning all Work Records on every hook call.
- Treating a branch as universal work identity or a session as one semantic task.
- A task graph, issue-tracker client, or inferred episode model.

## Done when

1. Python-based Claude Code and Codex plus non-Windows OpenCode emit the same
   canonical structural references. Every integration preserves explicit external
   identifiers; Windows OpenCode performs no structural filesystem access.
2. The expected Work Record is resolved by direct path calculation on Python
   integrations and non-Windows OpenCode; Windows OpenCode remains explicit-only.
   Missing, malformed, mismatched, base-branch, detached-HEAD, non-Git, and
   Unicode paths terminate safely without directory-wide scans.
3. Multiple references are normalized, deduplicated, bounded, redacted, and stored
   on the raw SourceItem even when every semantic package is disabled.
4. Hook E2E coverage drives real integration surfaces for empty/one/max/over-max
   references, branch changes, working-directory changes, missing records, explicit
   issue/PR/ticket data, and full ingest-to-history retrieval.
5. Added hook latency is measured for Git, non-Git, and missing paths. All reads
   are bounded, no resolver subprocess or cache ships, and every failure leaves
   normal ingestion working.

## Dependencies

Extends the shipped `add-work-ref-cross-surface-continuity` contract. It is the
first item in the ordered Session History slice and precedes exact work-scoped
history search.
