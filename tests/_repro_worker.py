"""Subprocess worker helper for reproduction tests.

Usage: python -m tests._repro_worker --db-url <url> --worker-id <id> --duration <seconds>

Runs a processing loop (item processing + thread rebuilds) for the specified
duration, then exits. Uses the ThreadAwareStubProvider for LLM calls.
"""
from __future__ import annotations

import argparse
import sys
import time

# Patch the LLM provider before anything imports it
from tests.test_thread_aggregation import ThreadAwareStubProvider
import app.dependencies
app.dependencies._repro_provider = ThreadAwareStubProvider()
_original_build = app.dependencies.build_llm_provider
app.dependencies.build_llm_provider = lambda config, **_: app.dependencies._repro_provider

from tests.test_thread_aggregation import _thread_test_config
from app.dependencies import build_service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--duration", type=float, default=5.0)
    args = parser.parse_args()

    config = _thread_test_config(args.db_url)
    service = build_service(config, enable_vector=False)

    deadline = time.monotonic() + args.duration
    items_processed = 0
    rebuilds_done = 0

    while time.monotonic() < deadline:
        result = service.process_next_source_item(
            worker_id=args.worker_id, lease_seconds=60, max_attempts=3
        )
        if result is not None:
            items_processed += 1
            continue
        lease = service.process_next_thread_rebuild(
            worker_id=args.worker_id, lease_seconds=60
        )
        if lease is not None:
            rebuilds_done += 1
            continue
        time.sleep(0.05)

    print(f"worker={args.worker_id} items={items_processed} rebuilds={rebuilds_done}", file=sys.stderr)


if __name__ == "__main__":
    main()
