"""Token-bucket rate limiter for benchmark LLM calls."""
from __future__ import annotations

import threading
import time


class TokenBucketRateLimiter:
    """Thread-safe token bucket for LLM API rate limiting.

    Usage:
        limiter = TokenBucketRateLimiter(capacity=20, refill_interval=3.0)
        limiter.acquire()  # blocks until a token is available
        provider.generate_json(...)
    """

    def __init__(self, capacity: int = 20, refill_interval: float = 3.0):
        self._capacity = capacity
        self._refill_interval = refill_interval
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._condition = threading.Condition(threading.Lock())
        self._total_requests = 0
        self._total_waits = 0

    def acquire(self, timeout: float = 120.0) -> None:
        """Block until a token is available, then consume one."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._total_requests += 1
                    return
                # Calculate wait time until next token
                wait_time = self._refill_interval - (
                    time.monotonic() - self._last_refill
                )
                wait_time = max(0.01, min(wait_time, deadline - time.monotonic()))
                if time.monotonic() >= deadline:
                    raise TimeoutError("Rate limiter acquire timed out")
                self._total_waits += 1
                self._condition.wait(timeout=wait_time)

    def _refill(self) -> None:
        """Refill tokens based on elapsed time. Must hold lock.

        Advances _last_refill by consumed intervals (not to `now`) to avoid
        fractional-token drift from repeated small refills.
        """
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed / self._refill_interval
        if new_tokens >= 1.0:
            whole = int(new_tokens)
            self._tokens = min(self._capacity, self._tokens + whole)
            self._last_refill += whole * self._refill_interval
        elif self._tokens < self._capacity and new_tokens > 0:
            self._tokens = min(self._capacity, self._tokens + new_tokens)
            self._last_refill = now

    def pause(self, seconds: float) -> None:
        """Drain all tokens and pause refill. Call when a 429 leaks through.

        Sets _last_refill into the future so that _refill() sees negative
        elapsed time and produces no tokens until the pause expires. Threads
        already blocked in acquire() will chain-wait (re-check every
        refill_interval) until the pause expires.
        """
        with self._condition:
            self._tokens = 0.0
            self._last_refill = time.monotonic() + seconds - self._refill_interval

    @property
    def stats(self) -> dict[str, int]:
        with self._condition:
            return {
                "total_requests": self._total_requests,
                "total_waits": self._total_waits,
                "tokens_available": int(self._tokens),
            }
