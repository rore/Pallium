---
id: decouple-session-history-from-derived-packages
title: Make raw Session History independent of derived packages
status: done
priority: high
commitment: committed
milestone: pallium-vnext-session-history
lane: architecture
---

## Product outcome

Pallium starts, records, governs, searches, and expands raw agent session history
without an LLM or enabled semantic package. Generated memories become optional
consumers of the raw history substrate and are disabled by default.

## Coupling removed

- Service startup no longer requires an active default semantic package.
- Raw ingestion and lexical indexing happen before optional package processing.
- Raw-source vector text and indexing are package-independent.
- Source-only search enforces visibility without consulting a semantic package.
- Disabling a package cancels its unfinished source and rebuild work.
- Explicit notes and memory-write operations remain core capabilities.

## Required package-free behavior

With all semantic packages disabled, Pallium must:

- start successfully;
- accept hook events and store redacted raw SourceItems;
- retain structural work references;
- create the raw lexical index synchronously;
- run raw vector indexing when a vector provider is explicitly enabled, using a
  package-independent raw-source text view;
- support broad and exact work-scoped history search plus bounded expansion;
- enforce visibility, redaction, forgetting, deletion, and retention;
- make no extraction, summary, thread-rebuild, consolidation, routing-prompt, or
  other derived-memory LLM call.

Package-level `enabled` remains the control. Do not add a second
`generation_enabled` flag. Derived packages are disabled by default, but their
implementations and stored outputs are not deleted and may be re-enabled.

## Decisions made

1. Session History keeps the existing governed SourceItem selection made by each
   integration; this feature adds no package-specific event allowlist.
2. Disabling a package cancels its unfinished source and rebuild work. Completed
   package output is preserved.
3. Stored, completed derived memories are preserved when their package is disabled.
   Direct expansion and governed mutations remain available; semantic querying
   resumes when an active default package is enabled.
4. Explicit note and memory-write operations remain governed core capabilities;
   package-free note ingestion stores only the faithful raw record.
5. Raw ingestion, lexical and optional vector indexing, search, expansion,
   forgetting, deletion, visibility, and retention are package-independent.

There is no migration requirement for changing defaults because Pallium currently
has one operator.

## Done when

1. A configuration with zero enabled semantic packages passes a full
   start -> ingest -> index -> broad search -> work search -> expand -> forget/delete
   lifecycle through the public hook, HTTP, and MCP surfaces.
2. A provider spy proves zero derived-memory model requests, including extraction,
   rebuilding, consolidation, and query-time semantic routing.
3. Lexical history works with no model or embedding configuration. Vector-disabled,
   vector-enabled, missing-provider, provider-failure, and Unicode paths have
   observable deterministic behavior without losing lexical availability.
4. Enabling one or several packages resumes only their owned processing and does not
   change raw-history correctness. Disabling and re-enabling packages preserves raw
   and derived stored data according to the recorded decisions.
5. Empty/invalid default-package settings, queued-work transitions, retries,
   idempotent ingest, duplicate source identity, visibility isolation, forgotten
   items, and retention/deletion interactions have E2E coverage.

## Dependencies

Follows the two search-surface items so the package-independent core is verified
against the intended public Session History contract.
