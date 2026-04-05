---
id: add-multi-package-source-item-processing
title: Multi-package source item processing
status: done
priority: medium
commitment: committed
milestone: Done
---

## Summary

Allow more than one semantic package to process the same source item
independently, replacing the single-`use_case`-per-item model with per-package
processing records.

## Why

Pallium's direction is not a single semantic package forever. Different
packages need to interpret the same upstream evidence for different jobs
(conversation continuity, fact extraction, domain-specific memory). The
previous model stored one `use_case` on `SourceItem` and used it as the queue
routing key, blocking multi-package processing.

## In Scope

- Package-neutral `SourceItem` ingest as the durable evidence root
- `PackageProcessingRecord` keyed by `(source_item_id, use_case)` for
  per-package processing state, retries, and leases
- `parallel_processing = True` flag: packages with this flag process every
  incoming item regardless of `use_case` routing
- `TypeRegistry` for package-owned memory type metadata (display names,
  descriptions, categories)
- Preserving explainability and visibility enforcement across packages

## Out of Scope

- Broad workflow orchestration between packages
- Cross-package dependency or ordering
- Deciding the final package taxonomy

## Done When

1. Multiple packages can process the same source item independently.
2. Per-package processing state is tracked separately.
3. Parallel processing packages receive every item.
4. TypeRegistry provides runtime type metadata for routing.

## Notes

Shipped. First parallel package is `conversational_knowledge`. Resolves
`idea-multi-package-source-item-processing`.
