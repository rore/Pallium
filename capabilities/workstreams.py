"""Workstream assignment cascade and registry (Phase 4A, design 014).

Strong-signal-only workstream resolution. Implements the §6.2 stage order
with §4 reliability ranking:

  1. work_refs match (exact normalized)
  2. file-path overlap (≥2 directory segments)
  3. symbol-name overlap
  4. explicit-title 3-gram match (non-stopword)
  5. workstream-kind subject-anchor match
  6. same-thread recency prior (≤30 min, no other strong signal disagrees)
  7. open-new (requires ≥1 strong signal AND that signal must not be wholly
     contained in the most-recent open workstream's signature — §6.2 stage 9
     self-referential protection)
  8. unknown — return the scoped pseudo-id

The watermark used by the cascade is the rebuild-watermark string (5-minute
bucket of ``created_at`` per ``(container_ref, thread_ref)``).

Workstream registry: a per-``(container_ref, visibility)`` dict of open
workstream records. Workstreams stay open while last-touched within the
configurable window (default 14 days; closed entries are kept for
explainability but filtered out of the join search).

The capability is purely deterministic structural logic — no LLM calls, no
network. Persistence uses the storage tables ``workstreams``,
``memory_workstreams``, ``source_item_workstreams`` introduced in
Phase 4A.

This module is the in-repo port of
``.local/research/_workstream_replay/cascade.py`` plus
``.local/research/_workstream_replay/pseudo_id.py``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Literal

from capabilities.workstream_signals import ItemSignals


# ---------------------------------------------------------------------------
# WorkstreamId — pseudo_id helpers
# ---------------------------------------------------------------------------


WorkstreamKind = Literal["resolved", "unknown"]


@dataclass(frozen=True)
class WorkstreamId:
    id: str
    kind: WorkstreamKind


def unknown_pseudo_id(container_ref: str, thread_ref: str | None, watermark: str) -> WorkstreamId:
    """Return ``unknown:{container_ref}:{thread_ref or 'NULL'}:{watermark}``.

    Two unknown items from different ``(container, thread, watermark)`` tuples
    NEVER collide. The rebuild watermark is part of the id so that two
    consecutive watermark windows in the same thread produce distinct
    pseudo-ids — even though they may later resolve into the same real
    workstream.
    """
    if not container_ref:
        raise ValueError("container_ref is required for unknown pseudo-ids")
    if not watermark:
        raise ValueError("watermark is required for unknown pseudo-ids")
    pseudo = f"unknown:{container_ref}:{thread_ref or 'NULL'}:{watermark}"
    return WorkstreamId(id=pseudo, kind="unknown")


def resolved_id_from_signals(signal_strings: Iterable[str]) -> WorkstreamId:
    """Stable hash of a sorted-deduplicated set of signal strings.

    The signal strings should be the *dominant* strong signals in the
    workstream's signature (typically: work_refs, distinctive file
    directories, distinctive symbols, explicit titles). Lexical noise must
    not be included or the id becomes unstable across rebuilds.
    """
    cleaned = sorted({s for s in signal_strings if s and isinstance(s, str)})
    if not cleaned:
        raise ValueError("resolved id requires at least one strong signal")
    digest = hashlib.sha1("\n".join(cleaned).encode("utf-8")).hexdigest()[:16]
    return WorkstreamId(id=f"ws:{digest}", kind="resolved")


# ---------------------------------------------------------------------------
# Workstream record stored in the registry
# ---------------------------------------------------------------------------


@dataclass
class WorkstreamRecord:
    workstream_id: str
    container_ref: str
    visibility: str
    work_refs: set[str] = field(default_factory=set)
    file_paths: set[str] = field(default_factory=set)
    file_dirs: set[str] = field(default_factory=set)
    symbols: set[str] = field(default_factory=set)
    commands: set[str] = field(default_factory=set)
    titles: set[str] = field(default_factory=set)
    title_ngrams: set[tuple[str, ...]] = field(default_factory=set)
    anchors: set[str] = field(default_factory=set)
    last_touched_thread: str | None = None
    last_touched_at: datetime | None = None
    opened_at: datetime | None = None
    closed: bool = False
    # The signal *seed* used at open() time. Used by the open-new guard
    # (stage 9: self-referential) to detect whether the new item carries any
    # signal change vs the workstream's seed.
    seed_signal_set: frozenset[str] = field(default_factory=frozenset)

    def merge_signals(self, item_signals: ItemSignals) -> None:
        self.work_refs |= item_signals.work_refs
        self.file_paths |= item_signals.file_paths
        self.file_dirs |= item_signals.file_dirs
        self.symbols |= item_signals.symbols
        self.commands |= item_signals.commands
        self.titles |= item_signals.titles
        self.title_ngrams |= item_signals.title_ngrams
        self.anchors |= item_signals.anchors

    def signal_signature(self) -> frozenset[str]:
        """Stable string set used to compute a deterministic workstream id."""
        seq: list[str] = []
        for r in self.work_refs:
            seq.append(f"wr:{r}")
        for d in self.file_dirs:
            seq.append(f"fd:{d}")
        for s in self.symbols:
            seq.append(f"sy:{s}")
        for t in sorted(self.titles)[:3]:
            seq.append(f"ti:{t}")
        for a in self.anchors:
            seq.append(f"an:{a}")
        return frozenset(seq)

    def signature_blob(self) -> dict:
        """JSON-serializable dominant-signal blob for ``workstreams.signature_blob``."""
        return {
            "work_refs": sorted(self.work_refs),
            "file_dirs": sorted(self.file_dirs),
            "symbols": sorted(self.symbols),
            "titles": sorted(self.titles)[:3],
            "anchors": sorted(self.anchors),
        }


# ---------------------------------------------------------------------------
# Cascade stage names — kept as constants so the runner can build histograms.
# ---------------------------------------------------------------------------

STAGE_WORK_REFS = "work_refs_match"
STAGE_FILE_PATH = "file_path_overlap"
STAGE_SYMBOL = "symbol_overlap"
STAGE_TITLE = "explicit_title_match"
STAGE_ANCHOR = "subject_anchor_match"
STAGE_RECENCY = "same_thread_recency"
STAGE_OPEN_NEW = "open_new"
STAGE_SELF_REF_ATTACH = "self_ref_attach"
STAGE_UNKNOWN = "unknown_pseudo_id"

ALL_STAGES = (
    STAGE_WORK_REFS,
    STAGE_FILE_PATH,
    STAGE_SYMBOL,
    STAGE_TITLE,
    STAGE_ANCHOR,
    STAGE_RECENCY,
    STAGE_OPEN_NEW,
    STAGE_SELF_REF_ATTACH,
    STAGE_UNKNOWN,
)


@dataclass
class AssignmentResult:
    workstream_id: WorkstreamId
    stage: str
    matched_workstream: str | None = None  # registry key if attached


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class WorkstreamRegistry:
    """Per-(container_ref, visibility) open-workstream registry.

    Closed workstreams are NOT removed; they remain in the dict so that
    explainability tools can replay the assignment. The cascade filters
    them out of the join search via ``open_records()``.
    """

    open_window_days: int = 14
    by_id: dict[str, WorkstreamRecord] = field(default_factory=dict)

    def open_records(self, *, container_ref: str, visibility: str, now: datetime) -> list[WorkstreamRecord]:
        cutoff = now - timedelta(days=self.open_window_days)
        records: list[WorkstreamRecord] = []
        for r in self.by_id.values():
            if r.closed:
                continue
            if r.container_ref != container_ref or r.visibility != visibility:
                continue
            if r.last_touched_at and r.last_touched_at < cutoff:
                # auto-close the record on access; idempotent.
                r.closed = True
                continue
            records.append(r)
        # Most-recent-first.
        records.sort(key=lambda x: x.last_touched_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return records

    def add(self, record: WorkstreamRecord) -> None:
        self.by_id[record.workstream_id] = record


# ---------------------------------------------------------------------------
# 5-minute rebuild watermark
# ---------------------------------------------------------------------------


def watermark_for(created_at: datetime, *, bucket_minutes: int = 5) -> str:
    """Bucket ``created_at`` into a fixed-width watermark string.

    The replay treats every (container, thread) batch of source items
    falling into the same 5-minute bucket as one rebuild watermark window.
    """
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    minute = (created_at.minute // bucket_minutes) * bucket_minutes
    bucketed = created_at.replace(minute=minute, second=0, microsecond=0)
    return bucketed.strftime("%Y%m%dT%H%M")


# ---------------------------------------------------------------------------
# Cascade itself
# ---------------------------------------------------------------------------


def _signals_subset_of(item: ItemSignals, ws: WorkstreamRecord) -> bool:
    """True iff every strong-signal value the item carries is already in ``ws``.

    Used by §6.2 stage 9: self-referential protection — open-new requires
    that at least one strong signal is *not* already contained in the most
    recently-touched open workstream's signature.
    """
    if item.work_refs and not item.work_refs.issubset(ws.work_refs):
        return False
    if item.file_dirs and not item.file_dirs.issubset(ws.file_dirs):
        return False
    if item.symbols and not item.symbols.issubset(ws.symbols):
        return False
    if item.title_ngrams and not item.title_ngrams.issubset(ws.title_ngrams):
        return False
    if item.anchors and not item.anchors.issubset(ws.anchors):
        return False
    return True


RECENCY_WINDOW = timedelta(minutes=30)


def assign_workstream_for_item(
    *,
    item_signals: ItemSignals,
    container_ref: str,
    thread_ref: str | None,
    visibility: str,
    created_at: datetime,
    watermark: str,
    registry: WorkstreamRegistry,
) -> AssignmentResult:
    """Single-item assignment cascade. Mutates ``registry`` on attach/open."""
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    open_ws = registry.open_records(container_ref=container_ref, visibility=visibility, now=created_at)

    # Stage 1: work_ref exact match.
    if item_signals.work_refs:
        for ws in open_ws:
            if item_signals.work_refs & ws.work_refs:
                _attach(ws, item_signals, thread_ref, created_at)
                return AssignmentResult(
                    workstream_id=WorkstreamId(id=ws.workstream_id, kind="resolved"),
                    stage=STAGE_WORK_REFS,
                    matched_workstream=ws.workstream_id,
                )

    # Stage 2: file-path / directory overlap (≥2 segments shared at depth 2).
    if item_signals.file_dirs:
        for ws in open_ws:
            if item_signals.file_dirs & ws.file_dirs:
                _attach(ws, item_signals, thread_ref, created_at)
                return AssignmentResult(
                    workstream_id=WorkstreamId(id=ws.workstream_id, kind="resolved"),
                    stage=STAGE_FILE_PATH,
                    matched_workstream=ws.workstream_id,
                )

    # Stage 3: distinctive symbol overlap (≥1 shared symbol).
    if item_signals.symbols:
        for ws in open_ws:
            if item_signals.symbols & ws.symbols:
                _attach(ws, item_signals, thread_ref, created_at)
                return AssignmentResult(
                    workstream_id=WorkstreamId(id=ws.workstream_id, kind="resolved"),
                    stage=STAGE_SYMBOL,
                    matched_workstream=ws.workstream_id,
                )

    # Stage 4: explicit-title 3-gram overlap.
    if item_signals.title_ngrams:
        for ws in open_ws:
            if item_signals.title_ngrams & ws.title_ngrams:
                _attach(ws, item_signals, thread_ref, created_at)
                return AssignmentResult(
                    workstream_id=WorkstreamId(id=ws.workstream_id, kind="resolved"),
                    stage=STAGE_TITLE,
                    matched_workstream=ws.workstream_id,
                )

    # Stage 5: workstream-kind subject anchor match.
    if item_signals.anchors:
        for ws in open_ws:
            if item_signals.anchors & ws.anchors:
                _attach(ws, item_signals, thread_ref, created_at)
                return AssignmentResult(
                    workstream_id=WorkstreamId(id=ws.workstream_id, kind="resolved"),
                    stage=STAGE_ANCHOR,
                    matched_workstream=ws.workstream_id,
                )

    # Stage 6: same-thread recency tiebreaker. Only fires when no strong
    # signal *disagrees*. We treat "disagrees" as: the item has a strong
    # signal whose value-set is wholly disjoint from the recent ws's
    # corresponding set. If the item has no strong signals at all, the
    # recency prior is allowed to attach (it's the "ack/short followup"
    # case).
    if thread_ref is not None:
        for ws in open_ws:
            if ws.last_touched_thread != thread_ref:
                continue
            if not ws.last_touched_at:
                continue
            if (created_at - ws.last_touched_at) > RECENCY_WINDOW:
                continue
            if _strongly_disagrees(item_signals, ws):
                continue
            _attach(ws, item_signals, thread_ref, created_at)
            return AssignmentResult(
                workstream_id=WorkstreamId(id=ws.workstream_id, kind="resolved"),
                stage=STAGE_RECENCY,
                matched_workstream=ws.workstream_id,
            )

    # Stage 7: open-new — requires at least one strong signal AND a signal
    # change vs the most-recent open workstream (self-ref protection).
    if item_signals.has_any_strong():
        most_recent = open_ws[0] if open_ws else None
        if most_recent is None or not _signals_subset_of(item_signals, most_recent):
            sig_strings = _signals_for_id(item_signals)
            new_id = resolved_id_from_signals(sig_strings)
            new_record = WorkstreamRecord(
                workstream_id=new_id.id,
                container_ref=container_ref,
                visibility=visibility,
                opened_at=created_at,
                seed_signal_set=frozenset(sig_strings),
            )
            new_record.merge_signals(item_signals)
            new_record.last_touched_thread = thread_ref
            new_record.last_touched_at = created_at
            registry.add(new_record)
            return AssignmentResult(
                workstream_id=new_id,
                stage=STAGE_OPEN_NEW,
                matched_workstream=new_id.id,
            )
        else:
            # All signals contained in most-recent ws. Attach instead of
            # split (§6.2 stage 9 self-ref protection). Tag the stage
            # explicitly so the histogram distinguishes "genuine new
            # workstream" from "self-referential attach" — the architect
            # review of T1.1+T1.2+T1.3 specifically requested this split.
            _attach(most_recent, item_signals, thread_ref, created_at)
            return AssignmentResult(
                workstream_id=WorkstreamId(id=most_recent.workstream_id, kind="resolved"),
                stage=STAGE_SELF_REF_ATTACH,
                matched_workstream=most_recent.workstream_id,
            )

    # Stage 8: unknown.
    pseudo = unknown_pseudo_id(container_ref, thread_ref, watermark)
    return AssignmentResult(
        workstream_id=pseudo,
        stage=STAGE_UNKNOWN,
        matched_workstream=None,
    )


def _attach(
    ws: WorkstreamRecord,
    item_signals: ItemSignals,
    thread_ref: str | None,
    created_at: datetime,
) -> None:
    ws.merge_signals(item_signals)
    ws.last_touched_thread = thread_ref
    ws.last_touched_at = created_at


def _strongly_disagrees(item: ItemSignals, ws: WorkstreamRecord) -> bool:
    """Item has a strong signal that the workstream does not also have at all.

    "Disagrees" is intentionally conservative: we only block recency
    attachment when the item brings a signal kind whose values are entirely
    disjoint from the workstream's set for that kind AND the workstream
    *has* a non-empty set there too. If the workstream doesn't have a
    work_ref and the item does, that's a disagreement (different ws). If
    neither has a work_ref, that's not a disagreement.
    """
    if item.work_refs and ws.work_refs and not (item.work_refs & ws.work_refs):
        return True
    if item.file_dirs and ws.file_dirs and not (item.file_dirs & ws.file_dirs):
        # file-set divergence is a strong disagreement (§6.2 stage 10
        # monorepo protection).
        return True
    if item.anchors and ws.anchors and not (item.anchors & ws.anchors):
        return True
    return False


def _signals_for_id(item: ItemSignals) -> list[str]:
    """Pick which signal values participate in the resolved-id hash.

    Use the strong-signal kinds that are present, in priority order. We do
    NOT include symbols-only ids (too volatile) unless no other signal is
    present — but the cascade guarantees at least one strong signal at this
    point, so include them all.
    """
    sig: list[str] = []
    sig.extend(f"wr:{w}" for w in sorted(item.work_refs))
    sig.extend(f"fd:{d}" for d in sorted(item.file_dirs))
    sig.extend(f"sy:{s}" for s in sorted(item.symbols))
    # Titles are bucketed via 3-gram signatures, which would produce a
    # different hash for two items with the same title surface but a
    # different word at the boundary. Use the raw normalized title instead.
    sig.extend(f"ti:{t.lower()}" for t in sorted(item.titles))
    sig.extend(f"an:{a}" for a in sorted(item.anchors))
    return sig


# ---------------------------------------------------------------------------
# WorkstreamCapability — public façade
# ---------------------------------------------------------------------------


class WorkstreamCapability:
    """Public capability for workstream assignment + lookups.

    Owns reads/writes against the ``workstreams``, ``memory_workstreams``,
    and ``source_item_workstreams`` tables. Purely deterministic; no LLM
    or network calls.

    Storage hand-off: the capability writes through a thin
    :class:`WorkstreamStore` instance that wraps a
    :class:`storage.base.StorageProvider`. The storage layer exposes the
    raw read/write helpers; the capability does the cascade and idempotency
    work above them.
    """

    def __init__(self, store: "WorkstreamStore") -> None:
        self._store = store

    # ---- registry persistence ----

    def load_registry(self, *, container_ref: str, visibility: str) -> WorkstreamRegistry:
        """Load the open registry rows for a (container, visibility) scope."""
        registry = WorkstreamRegistry()
        for row in self._store.list_open_workstreams(container_ref=container_ref, visibility=visibility):
            blob = _safe_load_signature_blob(row.get("signature_blob"))
            record = WorkstreamRecord(
                workstream_id=row["id"],
                container_ref=row["container_ref"],
                visibility=row["visibility"],
                work_refs=set(blob.get("work_refs", [])),
                file_dirs=set(blob.get("file_dirs", [])),
                symbols=set(blob.get("symbols", [])),
                titles=set(blob.get("titles", [])),
                anchors=set(blob.get("anchors", [])),
                opened_at=row.get("opened_at"),
                last_touched_at=row.get("last_touched_at"),
            )
            # Reconstruct title n-grams from titles for self-ref subset checks.
            from capabilities.workstream_signals import title_ngrams as _tng
            for t in record.titles:
                record.title_ngrams |= _tng(t, n=3)
            registry.add(record)
        return registry

    def persist_registry(self, registry: WorkstreamRegistry, *, now: datetime) -> None:
        """Upsert each record in the registry into the workstreams table."""
        for record in registry.by_id.values():
            self._store.upsert_workstream(
                workstream_id=record.workstream_id,
                container_ref=record.container_ref,
                visibility=record.visibility,
                kind="resolved",
                signature_blob=json.dumps(record.signature_blob(), sort_keys=True),
                opened_at=record.opened_at or now,
                last_touched_at=record.last_touched_at or now,
                created_by="thread_rebuild",
            )

    def record_unknown_workstream(
        self,
        *,
        ws_id: WorkstreamId,
        container_ref: str,
        visibility: str,
        opened_at: datetime,
    ) -> None:
        """Persist an unknown pseudo-id row so FKs in junction tables resolve."""
        self._store.upsert_workstream(
            workstream_id=ws_id.id,
            container_ref=container_ref,
            visibility=visibility,
            kind="unknown",
            signature_blob=json.dumps({}, sort_keys=True),
            opened_at=opened_at,
            last_touched_at=opened_at,
            created_by="thread_rebuild",
        )

    # ---- junction-table writes (idempotent) ----

    def link_source_item(
        self,
        *,
        source_item_id: str,
        workstream_id: str,
        watermark: str,
        assigned_at: datetime,
        stage: str | None = None,
    ) -> None:
        self._store.insert_source_item_workstream(
            source_item_id=source_item_id,
            workstream_id=workstream_id,
            watermark=watermark,
            assigned_at=assigned_at,
            stage=stage,
        )

    def link_memory(
        self,
        *,
        memory_object_id: str,
        workstream_id: str,
        assigned_at: datetime,
    ) -> None:
        self._store.insert_memory_workstream(
            memory_object_id=memory_object_id,
            workstream_id=workstream_id,
            assigned_at=assigned_at,
        )

    # ---- lookups ----

    def lookup_memory(self, memory_object_id: str) -> str | None:
        return self._store.get_memory_workstream_id(memory_object_id)

    def lookup_query_source_item(self, source_item_id: str) -> str | None:
        return self._store.get_latest_source_item_workstream_id(source_item_id)


def _safe_load_signature_blob(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        v = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


# ---------------------------------------------------------------------------
# WorkstreamStore — thin storage adapter contract
# ---------------------------------------------------------------------------


class WorkstreamStore:
    """Thin storage adapter for workstream tables.

    A subclass is provided by ``storage/sqlite_workstream.py`` — this module
    only declares the contract so the capability can stay storage-agnostic.
    """

    def list_open_workstreams(self, *, container_ref: str, visibility: str) -> list[dict]:
        raise NotImplementedError

    def upsert_workstream(
        self,
        *,
        workstream_id: str,
        container_ref: str,
        visibility: str,
        kind: str,
        signature_blob: str,
        opened_at: datetime,
        last_touched_at: datetime,
        created_by: str,
    ) -> None:
        raise NotImplementedError

    def insert_source_item_workstream(
        self,
        *,
        source_item_id: str,
        workstream_id: str,
        watermark: str,
        assigned_at: datetime,
        stage: str | None = None,
    ) -> None:
        raise NotImplementedError

    def insert_memory_workstream(
        self,
        *,
        memory_object_id: str,
        workstream_id: str,
        assigned_at: datetime,
    ) -> None:
        raise NotImplementedError

    def get_memory_workstream_id(self, memory_object_id: str) -> str | None:
        raise NotImplementedError

    def get_latest_source_item_workstream_id(self, source_item_id: str) -> str | None:
        raise NotImplementedError
