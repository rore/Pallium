---
id: fix-budget-aware-historical-recall-hardening
title: Harden budget-aware historical recall surfaces
status: done
priority: high
commitment: committed
milestone: Current
---

## Summary

Make historical recall safe and useful at the public MCP boundary: compact
search results stay within a total serialized budget, and source expansion
keeps the anchor and its correlation link while honestly reporting clipping.

## Shipped Contract

- `pallium_search_history` defaults to three compact hits, includes
  `lookup_event_id`, centers excerpts on literal matches, and returns at most
  2000 serialized characters (300 for empty results).
- `pallium_expand_source` defaults to `before=1`, `after=1`, and a 4000-character
  serialized budget; it preserves the anchor, clips deterministically with
  `content_truncated`, preserves `parent_lookup_id`, and keeps chronological
  output.
- GitHub container references normalize supported case, slash, and `.git`
  forms without changing unknown references.
- Claude/Codex guidance names the available history, expansion, query, ingest,
  debug, flag, and explicit-write tools while retaining optional feedback and
  retrieval-is-not-use semantics.

## Invariant

Historical retrieval and expansion do not mutate accessibility state; verified
downstream use remains the only source of accessibility/ranking updates.