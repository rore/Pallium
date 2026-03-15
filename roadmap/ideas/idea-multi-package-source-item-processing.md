---
id: idea-multi-package-source-item-processing
title: Multi-package source item processing
status: queued
priority: medium
commitment: uncommitted
milestone: Idea
---

## Summary

Preserve raw `SourceItem` ingest as package-neutral evidence and allow more than
one semantic package to process the same source item over time.

The intended future shape is:

- one ingested source item
- zero or more semantic packages attached to that source item
- each package producing its own annotations, memory objects, relations,
  indexes, and processing state

This would replace the current one-`use_case`-per-source-item model with a
package-processing model keyed by `(source_item_id, use_case)`.

## Why

Pallium's longer-term direction is not a single semantic package forever.
Different packages may want to interpret the same upstream evidence for
different jobs, for example:

- conversation continuity
- task/work-state carry-forward
- domain-specific investigation memory
- future shared/publication-oriented derivations

The current DB model stores one `use_case` directly on `SourceItem` and uses
that as the queue routing key. That is acceptable for the current narrow slice,
but it is intentionally narrower than the intended future architecture. If left
implicit, it could become an accidental blocker when Pallium grows into a real
multi-package memory engine.

## In Scope

- package-neutral raw `SourceItem` ingest as the durable evidence root
- a per-package processing record or queue model such as
  `(source_item_id, use_case)`
- separate processing state, retries, and leases per package
- allowing one source item to produce different memory artifacts under
  different semantic packages
- preserving explainability and visibility enforcement across packages

## Out of Scope

- implementing the multi-package model now
- broad workflow orchestration between packages
- automatic fanout to every installed package by default
- deciding the final package taxonomy before more than one real package exists

## Done When

1. The repo keeps an explicit record that the current single-`use_case` source
   item model is a temporary narrowing, not the final architecture.
2. There is a clear future design direction for moving queue ownership from
   `SourceItem` rows to per-package processing records when justified.
3. That future design is explicitly additive and non-destructive: existing
   `SourceItem` rows remain the durable evidence root, while current single-package
   rows can be backfilled into the new per-package processing table.
4. A later implementation can start from this idea instead of rediscovering the
   architectural constraint.

## Notes

Likely future shape:

1. keep `SourceItem` package-neutral
2. add a per-package processing table keyed by `(source_item_id, use_case)`
3. move async queue state and leases to that per-package record
4. backfill one per-package processing row for existing items that already have a
   current `use_case`
5. leave existing raw `SourceItem` rows and existing derived memory in place
   rather than invalidating them
6. switch workers to claim per-package processing rows instead of `SourceItem`
   rows
7. deprecate or eventually remove source-item-level queue fields only after the
   new path is proven
8. let retrieval and memory provenance remain package-aware while sharing the
   same source evidence root
