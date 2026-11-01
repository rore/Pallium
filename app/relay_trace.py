"""App-owned, bounded best-effort Relay trace writes."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class RelayTraceWriter:
    def __init__(self) -> None:
        self._slots = threading.BoundedSemaphore(64)
        self._lock = threading.Lock()
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="relay-trace")
        try:
            self._executor.submit(lambda: None).result()
        except BaseException:
            try:
                self._executor.shutdown(wait=True, cancel_futures=True)
            except BaseException:
                pass
            raise
        try:
            logger.info("relay_trace_lifecycle outcome=ready capacity=64")
        except Exception:
            pass

    def enqueue(self, writer: Callable[[dict[str, object]], object], event: dict[str, object]) -> bool:
        with self._lock:
            if self._closed or not self._slots.acquire(blocking=False):
                return False
            try:
                future = self._executor.submit(self._run, writer, dict(event))
            except Exception:
                self._slots.release()
                try:
                    logger.warning("relay trace enqueue failed")
                except Exception:
                    pass
                return False
            # Cancelled queued jobs never enter _run, but still return their slot.
            future.add_done_callback(lambda _future: self._slots.release())
            return True

    @staticmethod
    def _run(writer: Callable[[dict[str, object]], object], event: dict[str, object]) -> None:
        try:
            writer(event)
        except Exception:
            try:
                logger.warning("relay trace write failed")
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            first_close = not self._closed
            self._closed = True
        # Every caller waits, including one racing an earlier close.
        self._executor.shutdown(wait=True, cancel_futures=True)
        if first_close:
            try:
                logger.info("relay_trace_lifecycle outcome=closed")
            except Exception:
                pass
