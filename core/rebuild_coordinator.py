"""Background vector index rebuild with checkpoint/resume and hot-swap."""
from __future__ import annotations

import json
import logging
import shutil
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from core.vector_index_holder import VectorIndexHolder
from core.vector_rebuild import _recompute_embedding_text
from providers.embedding.base import EmbeddingProvider
from storage.base import StorageProvider
from storage.vector_index import VectorIndex, _atomic_write_json, _replace_with_retry

logger = logging.getLogger(__name__)


@dataclass
class RebuildCheckpoint:
    status: str  # "in_progress" | "completed" | "failed"
    reason: str
    model_name: str
    dimensions: int
    embedding_schema_version: int
    temp_index_dir: str
    last_processed_entry_id: str | None
    entry_count_total: int
    entry_count_processed: int
    batch_size: int
    started_at: str = ""
    updated_at: str = ""

    def save(self, path: Path) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
        _atomic_write_json(path, asdict(self))

    @classmethod
    def load(cls, path: Path) -> RebuildCheckpoint | None:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        # Only pass fields that exist in the dataclass
        valid_fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid_fields})


SHADOW_SAVE_INTERVAL = 1024


class RebuildCoordinator:
    """Background vector index rebuild with checkpoint/resume and hot-swap.

    Flow:
    1. Build shadow index at {index_path}.rebuild/ (sibling directory)
    2. Page through SQLite entries in batches (ID-ordered)
    3. After each batch: save checkpoint JSON. Save shadow binary every ~1024 entries.
    4. On completion: validate shadow, atomic file swap, holder.swap()
    5. On crash/restart: read checkpoint, resume from last_processed_entry_id
    """

    BATCH_SIZE_DEFAULT = 128

    def __init__(
        self,
        *,
        storage: StorageProvider,
        embedding_provider: EmbeddingProvider,
        index_holder: VectorIndexHolder,
        index_path: Path,
        target_model_name: str,
        target_dimensions: int,
        target_schema_version: int,
        reason: str,
        batch_size: int = BATCH_SIZE_DEFAULT,
        shadow_save_interval: int = SHADOW_SAVE_INTERVAL,
        on_swap_callback: Callable[[], None] | None = None,
    ) -> None:
        self._storage = storage
        self._embedding_provider = embedding_provider
        self._index_holder = index_holder
        self._index_path = Path(index_path)
        self._target_model_name = target_model_name
        self._target_dimensions = target_dimensions
        self._target_schema_version = target_schema_version
        self._reason = reason
        self._batch_size = batch_size
        self._shadow_save_interval = shadow_save_interval
        self._on_swap_callback = on_swap_callback
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._checkpoint: RebuildCheckpoint | None = None
        self._shadow_index: VectorIndex | None = None
        self._state_path = Path(f"{self._index_path}.rebuild_state.json")
        self._shadow_dir = Path(f"{self._index_path}.rebuild")

    # --- Public API ---

    def start(self) -> None:
        """Start rebuild in a background daemon thread."""
        self._thread = threading.Thread(
            target=self._run_safe, daemon=True, name="vector-rebuild",
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Signal stop and wait for thread to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def run_sync(self) -> None:
        """Run rebuild synchronously (for tests and CLI)."""
        self._run_safe()

    def status(self) -> dict | None:
        """Return current rebuild status for /status endpoint."""
        if self._checkpoint is None:
            return None
        return {
            "active": self._checkpoint.status == "in_progress",
            "status": self._checkpoint.status,
            "reason": self._reason,
            "progress_percent": round(
                self._checkpoint.entry_count_processed / max(self._checkpoint.entry_count_total, 1) * 100, 1
            ),
            "entries_processed": self._checkpoint.entry_count_processed,
            "entries_total": self._checkpoint.entry_count_total,
            "started_at": self._checkpoint.started_at,
        }

    @staticmethod
    def cleanup_orphaned_rebuild(index_path: Path) -> bool:
        """Remove orphaned rebuild artifacts (shadow dir without state file)."""
        shadow_dir = Path(f"{index_path}.rebuild")
        state_path = Path(f"{index_path}.rebuild_state.json")
        if shadow_dir.exists() and not state_path.exists():
            shutil.rmtree(shadow_dir, ignore_errors=True)
            logger.info("Cleaned orphaned rebuild dir: %s", shadow_dir)
            return True
        return False

    @staticmethod
    def has_pending_rebuild(index_path: Path) -> RebuildCheckpoint | None:
        """Check if there's a resumable rebuild from a prior crash."""
        state_path = Path(f"{index_path}.rebuild_state.json")
        return RebuildCheckpoint.load(state_path)

    # --- Internal ---

    def _run_safe(self) -> None:
        try:
            self._start_or_resume()
            self._rebuild_loop()
        except Exception:
            logger.error("Rebuild failed", exc_info=True)
            if self._checkpoint is not None:
                self._checkpoint.status = "failed"
                self._checkpoint.save(self._state_path)

    def _start_or_resume(self) -> None:
        """Initialize or resume from checkpoint."""
        existing = RebuildCheckpoint.load(self._state_path)
        if existing is not None and existing.status == "in_progress":
            logger.info(
                "Resuming rebuild from checkpoint: %d/%d entries processed",
                existing.entry_count_processed, existing.entry_count_total,
            )
            self._checkpoint = existing
            shadow_index_path = self._shadow_dir / "index.usearch"
            if shadow_index_path.exists() and Path(f"{shadow_index_path}.meta.json").exists():
                self._shadow_index = VectorIndex.load(shadow_index_path)
            else:
                self._checkpoint.last_processed_entry_id = None
                self._checkpoint.entry_count_processed = 0
                self._create_shadow_index()
        else:
            total = self._storage.count_index_entries_by_type("vector")
            self._checkpoint = RebuildCheckpoint(
                status="in_progress",
                reason=self._reason,
                model_name=self._target_model_name,
                dimensions=self._target_dimensions,
                embedding_schema_version=self._target_schema_version,
                temp_index_dir=str(self._shadow_dir),
                last_processed_entry_id=None,
                entry_count_total=total,
                entry_count_processed=0,
                batch_size=self._batch_size,
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            self._create_shadow_index()
            self._checkpoint.save(self._state_path)
            logger.info("Starting rebuild: %d entries, reason=%s", total, self._reason)

    def _create_shadow_index(self) -> None:
        """Create a fresh shadow VectorIndex in the rebuild directory."""
        self._shadow_dir.mkdir(parents=True, exist_ok=True)
        shadow_index_path = self._shadow_dir / "index.usearch"
        self._shadow_index = VectorIndex(
            shadow_index_path,
            dimensions=self._target_dimensions,
            model_name=self._target_model_name,
            embedding_schema_version=self._target_schema_version,
        )

    def _rebuild_loop(self) -> None:
        """Process batches until done or stopped."""
        while not self._stop_event.is_set():
            processed = self._process_one_batch()
            if processed == 0:
                self._finalize()
                return
            if self._stop_event.wait(0.01):
                logger.info("Rebuild stopped by signal at %d entries", self._checkpoint.entry_count_processed)
                return

    def _process_one_batch(self) -> int:
        """Process one batch of entries. Returns count processed (0 = done)."""
        batch = self._storage.list_index_entries_by_type_page(
            "vector",
            after_id=self._checkpoint.last_processed_entry_id,
            limit=self._batch_size,
        )
        if not batch:
            return 0

        texts = []
        valid_entries = []
        for entry in batch:
            text = _recompute_embedding_text(self._storage, entry)
            if text is None:
                text = entry.text_view
            elif text != entry.text_view:
                self._storage.update_index_entry_text_view(entry.id, text)
            if text:
                texts.append(text)
                valid_entries.append(entry)

        if texts:
            vectors = self._embedding_provider.embed(texts, mode="passage")
            for entry, vector in zip(valid_entries, vectors):
                self._shadow_index.add(entry.id, vector)

        self._checkpoint.last_processed_entry_id = batch[-1].id
        self._checkpoint.entry_count_processed += len(batch)
        self._checkpoint.save(self._state_path)

        if self._checkpoint.entry_count_processed % self._shadow_save_interval < self._batch_size:
            self._shadow_index.save()

        logger.info(
            "Rebuild progress: %d/%d entries (%.1f%%)",
            self._checkpoint.entry_count_processed,
            self._checkpoint.entry_count_total,
            self._checkpoint.entry_count_processed / max(self._checkpoint.entry_count_total, 1) * 100,
        )
        return len(batch)

    def _finalize(self) -> None:
        """Validate shadow index and perform atomic swap."""
        self._shadow_index.save()

        shadow_index_path = self._shadow_dir / "index.usearch"
        try:
            validated = VectorIndex.load(shadow_index_path)
        except Exception as exc:
            logger.error("Shadow index validation failed: %s. Rebuild marked failed.", exc)
            self._checkpoint.status = "failed"
            self._checkpoint.save(self._state_path)
            return

        if validated.entry_count() == 0 and self._checkpoint.entry_count_total > 0:
            logger.error(
                "Shadow index is empty but expected %d entries. Rebuild marked failed.",
                self._checkpoint.entry_count_total,
            )
            self._checkpoint.status = "failed"
            self._checkpoint.save(self._state_path)
            return

        self._atomic_swap_files(shadow_index_path)

        new_index = VectorIndex.load(self._index_path)
        old_index = self._index_holder.swap(new_index)

        if self._on_swap_callback is not None:
            self._on_swap_callback()

        shutil.rmtree(self._shadow_dir, ignore_errors=True)
        self._state_path.unlink(missing_ok=True)
        self._checkpoint.status = "completed"

        logger.info(
            "Rebuild complete: swapped live index (%d entries). Old had %d entries.",
            new_index.entry_count(),
            old_index.entry_count() if old_index else 0,
        )

    def _atomic_swap_files(self, shadow_index_path: Path) -> None:
        """Move shadow index files to the live path."""
        live = self._index_path
        shadow_dir = shadow_index_path.parent
        suffixes = ["", ".meta.json", ".idmap.json"]

        # Backup live files to .old
        for suffix in suffixes:
            src = Path(f"{live}{suffix}") if suffix else live
            dst = Path(f"{live}{suffix}.old")
            if src.exists():
                _replace_with_retry(str(src), str(dst))

        # Move shadow files to live
        for suffix in suffixes:
            src = shadow_dir / (f"index.usearch{suffix}" if suffix else "index.usearch")
            dst = Path(f"{live}{suffix}") if suffix else live
            if src.exists():
                _replace_with_retry(str(src), str(dst))

        # Remove .old backups
        for suffix in suffixes:
            old_path = Path(f"{live}{suffix}.old")
            old_path.unlink(missing_ok=True)
