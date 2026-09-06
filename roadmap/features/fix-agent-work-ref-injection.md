---
id: fix-agent-work-ref-injection
title: Give agents one copyable current-work reference
status: in-progress
priority: high
commitment: committed
milestone: pallium-vnext-session-history
lane: product-surface
---

## Product outcome

An agent can resume or search the current work item without knowing Pallium's
reference namespaces. The injected scope provides one ready-to-copy `work_ref`;
the agent either passes it unchanged to narrow search or uses broad search when
it is absent.

## Contract

- Reuse the first safe structural reference already discovered for ingestion;
  never promote an arbitrary caller-supplied reference into the injected field.
- Discover once per user-prompt hook and reuse the same result for scope and
  ingestion. Do not add Git processes or server-side prefix guessing.
- Include the optional field in normal and Relay-first context. Missing Git,
  base/detached branches, unsupported OpenCode-on-Windows discovery, unsafe
  paths, malformed Work Records, secrets, controls, and overlong values omit
  only `work_ref`; ordinary work must continue.
- Tell agents: copy the injected value unchanged; if absent, do not guess and
  use broad search. Omit a narrow-search query only for newest-state resumption.
- Keep the added prompt cost to one short JSON field and bounded guidance.

## Done when

1. Codex and Claude Code user-prompt hooks expose the same safe structural ref
   they attach to the ingested source, including Relay-first delivery.
2. Supported OpenCode environments behave the same; Windows retains its
   documented filesystem-discovery omission without affecting normal work.
3. A caller-level E2E captures the emitted value, ingests the turn through
   HTTP, copies the value into exact work search, and retrieves that source.
4. E2E and parity coverage proves explicit-only refs cannot become the scalar;
   missing/base/detached/malformed/secret/control/overlong/Unicode boundaries
   fail safely; discovery runs once; broad and exact empty hints stay distinct.
5. Guidance stays within existing character budgets, existing visibility and
   lifecycle contracts remain unchanged, CI/review is green, and the merged
   installed integrations pass a coordinated real lookup witness.

## Evidence

Dogfooding found that a bare branch name returned no exact results while the
stored `git-branch:<branch>` reference succeeded. Core normalization was already
symmetric; the usability gap was that agents could not see the namespaced value
the integrations had written.

## Dependencies

Follows `add-structural-session-work-references` and
`add-distinct-work-and-broad-history-search-tools`.