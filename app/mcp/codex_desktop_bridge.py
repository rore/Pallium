"""Inert lifecycle placeholder for the explicitly enabled Codex stdio child."""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager


def _diagnostic(category: str) -> None:
    try:
        print(f"Pallium Codex bridge inert: {category}", file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


async def _idle() -> None:
    await asyncio.Future()


def _task_finished(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        _diagnostic("task-failed")


@asynccontextmanager
async def lifespan(_server):
    task = asyncio.create_task(_idle())
    task.add_done_callback(_task_finished)
    try:
        yield {}
    finally:
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=1.0)
        if not done:
            _diagnostic("shutdown-timeout")
