"""Tests for the token bucket rate limiter."""
import threading
import time

from evals.eval_rate_limiter import TokenBucketRateLimiter


def test_immediate_burst():
    """First N requests up to capacity should not block."""
    limiter = TokenBucketRateLimiter(capacity=5, refill_interval=1.0)
    start = time.monotonic()
    for _ in range(5):
        limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.5, f"Burst of 5 should be immediate, took {elapsed:.2f}s"
    assert limiter.stats["total_requests"] == 5


def test_throttling_after_burst():
    """Requests beyond capacity should be delayed."""
    limiter = TokenBucketRateLimiter(capacity=2, refill_interval=0.2)
    start = time.monotonic()
    for _ in range(4):
        limiter.acquire()
    elapsed = time.monotonic() - start
    # 2 immediate, then 2 more at ~0.2s each
    assert elapsed >= 0.3, f"Should have waited, took {elapsed:.2f}s"
    assert limiter.stats["total_waits"] >= 1


def test_concurrent_access():
    """Multiple threads should share tokens safely."""
    limiter = TokenBucketRateLimiter(capacity=3, refill_interval=0.1)
    results = []

    def worker():
        limiter.acquire()
        results.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(6)]
    start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 6
    assert limiter.stats["total_requests"] == 6


def test_pause_drains_tokens():
    """pause() should drain tokens and delay refill."""
    limiter = TokenBucketRateLimiter(capacity=5, refill_interval=0.1)
    limiter.pause(0.5)
    start = time.monotonic()
    limiter.acquire(timeout=2.0)
    elapsed = time.monotonic() - start
    assert elapsed >= 0.3, f"Should have paused, took {elapsed:.2f}s"


def test_timeout():
    """acquire() should raise TimeoutError when tokens aren't available in time."""
    limiter = TokenBucketRateLimiter(capacity=1, refill_interval=10.0)
    limiter.acquire()  # consume the only token
    try:
        limiter.acquire(timeout=0.1)
        assert False, "Should have timed out"
    except TimeoutError:
        pass
