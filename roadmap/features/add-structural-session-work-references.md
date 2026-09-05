---
id: add-structural-session-work-references
title: Attach structural work references to session history
status: active
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

The shipped work-reference foundation accepts normalized `work_refs`, including
runtime hints in `metadata["pallium_work_refs"]`, but integrations do not
systematically attach the current branch or its exact Agent Workflow Work Record.
Content-derived references also require semantic processing, so they cannot be the
required raw Session History path.

## In scope

- In Claude Code, Codex, and OpenCode hooks, read the current Git branch from the
  hook working directory and attach a normalized, namespaced branch work reference.
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
- Measure hook latency. Add a cache only if measurement justifies it; if added, key
  and invalidate it on working-directory or branch changes.

## Out of scope

- Asking an LLM whether a turn is still about a branch or Work Record.
- Scanning all Work Records on every hook call.
- Treating a branch as universal work identity or a session as one semantic task.
- A task graph, issue-tracker client, or inferred episode model.

## Done when

1. Each supported integration emits the same canonical references for the same
   repository, branch, Work Record, and explicit external identifier.
2. The expected Work Record is resolved by direct path calculation; missing,
   malformed, mismatched, base-branch, detached-HEAD, non-Git, and Unicode paths
   terminate safely without directory-wide scans.
3. Multiple references are normalized, deduplicated, bounded, redacted, and stored
   on the raw SourceItem even when every semantic package is disabled.
4. Hook E2E coverage drives real integration surfaces for empty/one/max/over-max
   references, branch changes, working-directory changes, missing records, explicit
   issue/PR/ticket data, and full ingest-to-history retrieval.
5. Added hook latency is measured on warm and cold paths. No cache ships without a
   measured need and an invalidation test.

## Dependencies

Extends the shipped `add-work-ref-cross-surface-continuity` contract. It is the
first item in the ordered Session History slice and precedes exact work-scoped
history search.
