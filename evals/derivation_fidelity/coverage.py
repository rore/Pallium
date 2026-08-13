"""Pure coverage scoring for the source-episode derivation eval.

Survivorship-bias-free extraction/coverage measurement: we start from SOURCE
items (not from existing derived objects) and ask, per source item, whether the
derivation pipeline produced a derived memory object.

Coverage is deliberately SEGMENTED by linkage semantics and never blended into a
single rate, because producers link to their sources differently:

- ``item_extraction`` producers link a derived object to the specific source
  item(s) that produced it → coverage is measured at SOURCE-ITEM granularity.
- ``thread_aggregation`` / ``consolidation`` producers link the derived object to
  EVERY source item in the thread (verified: ``semantic/conversational_knowledge``
  and ``semantic/agent_conversation_memory_threads`` link supported_by to all
  thread source items). Measuring those per-item would inflate coverage, so they
  are measured at THREAD granularity.

Everything here is a pure function over small in-memory records — no DB, no LLM —
so it is trivially unit-testable. The runner (``runner.py``) maps live
``MemoryObject``/``SourceItem`` rows onto these records.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

# producer_kind → coverage granularity
ITEM_LEVEL_PRODUCER = "item_extraction"
THREAD_LEVEL_PRODUCERS = frozenset({"thread_aggregation", "consolidation"})

# Four coverage states (per lens).
NOT_PROCESSED = "not_processed"
PROCESSED_NOTHING = "processed_nothing"
EXTRACTED = "extracted"
EXTRACTED_THEN_DEMOTED = "extracted_then_demoted"


@dataclass(frozen=True)
class LinkedObject:
    """A derived object linked to a source item, reduced to what coverage needs."""

    memory_object_id: str
    memory_type: str
    producer_kind: str | None
    demoted: bool


@dataclass(frozen=True)
class ItemRecord:
    """One sampled source item + the derived objects linked to it."""

    source_item_id: str
    container_ref: str | None
    thread_ref: str | None
    processed: bool
    linked: tuple[LinkedObject, ...] = ()

    @property
    def thread_key(self) -> tuple[str | None, str | None]:
        return (self.container_ref, self.thread_ref)


def object_is_demoted(*, is_soft_deleted: bool, lifecycle: str | None) -> bool:
    """A linked object counts as demoted iff it is tombstoned or superseded.

    An item with ANY active (non-demoted) linked object is ``extracted``; an item
    whose linked objects are ALL demoted is ``extracted_then_demoted``.
    """
    return bool(is_soft_deleted) or (lifecycle == "superseded")


def _classify(processed: bool, relevant: list[LinkedObject]) -> str:
    if not processed:
        return NOT_PROCESSED
    if not relevant:
        return PROCESSED_NOTHING
    if any(not obj.demoted for obj in relevant):
        return EXTRACTED
    return EXTRACTED_THEN_DEMOTED


def _empty_state_counts() -> dict[str, int]:
    return {NOT_PROCESSED: 0, PROCESSED_NOTHING: 0, EXTRACTED: 0, EXTRACTED_THEN_DEMOTED: 0}


def _coverage_rate(counts: dict[str, int]) -> float | None:
    """Extracted / processed. None when there are no processed units."""
    processed = counts[PROCESSED_NOTHING] + counts[EXTRACTED] + counts[EXTRACTED_THEN_DEMOTED]
    if processed == 0:
        return None
    return counts[EXTRACTED] / processed


@dataclass
class _Lens:
    granularity: str
    counts: dict[str, int] = field(default_factory=_empty_state_counts)
    # NOTE: `counts` are per unit (per source item / per thread). `by_type` is
    # incremented per LINKED OBJECT, so a unit with multiple objects of one type
    # contributes multiple by_type increments — by_type[type][state] can exceed the
    # unit `counts`. Different unit; don't sum them together in a dashboard.
    by_type: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(_empty_state_counts))

    def to_dict(self) -> dict:
        processed = (
            self.counts[PROCESSED_NOTHING]
            + self.counts[EXTRACTED]
            + self.counts[EXTRACTED_THEN_DEMOTED]
        )
        return {
            "granularity": self.granularity,
            "counts": dict(self.counts),
            "processed_denominator": processed,
            "not_processed": self.counts[NOT_PROCESSED],
            "coverage_rate": _coverage_rate(self.counts),
            "by_type": {t: dict(c) for t, c in sorted(self.by_type.items())},
        }


def aggregate_coverage(records: list[ItemRecord]) -> dict:
    """Segmented coverage over sampled source items. Empty-data-safe.

    Returns two independent lenses (never a blended overall rate):
    ``item_extraction`` (source-item granularity) and ``thread_aggregation``
    (thread granularity, folding in ``consolidation`` producers).
    """
    item_lens = _Lens(granularity="source_item")

    # ---- item-extraction lens: per processed source item ----
    for rec in records:
        relevant = [o for o in rec.linked if o.producer_kind == ITEM_LEVEL_PRODUCER]
        state = _classify(rec.processed, relevant)
        item_lens.counts[state] += 1
        for o in relevant:
            item_lens.by_type[o.memory_type][state] += 1

    # ---- thread-aggregation lens: per thread with >=1 processed item ----
    thread_lens = _Lens(granularity="thread")
    threads: dict[tuple, list[ItemRecord]] = defaultdict(list)
    for rec in records:
        # Threadless items (thread_ref is None) cannot belong to a thread-aggregation
        # episode; grouping them by a null key would collapse unrelated items into one
        # synthetic thread. Exclude them from the thread lens entirely.
        if rec.thread_ref is None:
            continue
        threads[rec.thread_key].append(rec)
    for _key, recs in threads.items():
        if not any(r.processed for r in recs):
            continue  # excluded from the thread denominator entirely
        # gather thread-level producer objects across all items in the thread, deduped
        seen: dict[str, LinkedObject] = {}
        for r in recs:
            for o in r.linked:
                if o.producer_kind in THREAD_LEVEL_PRODUCERS:
                    seen[o.memory_object_id] = o
        relevant = list(seen.values())
        state = _classify(True, relevant)
        thread_lens.counts[state] += 1
        for o in relevant:
            thread_lens.by_type[o.memory_type][state] += 1

    pending = sum(1 for r in records if not r.processed)
    return {
        "sampled_items": len(records),
        "pending_items": pending,
        "item_extraction": item_lens.to_dict(),
        "thread_aggregation": thread_lens.to_dict(),
    }
