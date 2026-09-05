---
id: decouple-session-history-from-derived-packages
title: Make raw Session History independent of derived packages
status: queued
priority: high
commitment: committed
milestone: pallium-vnext-session-history
lane: architecture
---

## Product outcome

Pallium starts, records, governs, searches, and expands raw agent session history
without an LLM or enabled semantic package. Generated memories become optional
consumers of the raw history substrate and are disabled by default.

## Current coupling to remove

- `build_service()` rejects a `default_use_case` that is not an active plugin.
- `ingest_item()` indexes the selected semantic plugin before storing a raw item.
- Source vector text is selected through the semantic plugin and queued processing.
- Source-only search reads visibility behavior from the default plugin.
- Already queued work for a package that becomes unavailable currently fails as an
  unknown use case.
- Explicit notes/remember operations currently use the agent-conversation package;
  their final ownership remains an explicit design decision for this feature.

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

## Decisions required during planning

1. Which event kinds are searchable Session History: user, assistant, tool,
   command, and hook-generated records.
2. Whether queued package work is cancelled, retained, or drained when a package is
   disabled.
3. Whether stored derived memories remain queryable while their package is disabled.
4. Whether explicit notes/remember operations belong to the raw core or an optional
   package.
5. Confirm that every raw governance operation is package-independent.

These decisions block code editing, not creation of this roadmap item. There is no
migration requirement for changing defaults because Pallium currently has one
operator.

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
