from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from app.cleaner import run_cleaner
from app.processor import run_processor
from app.runtime_logging import build_uvicorn_log_config
from app.supervisor import run_supervisor

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Pallium locally")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("all", "serve", "mcp", "processor", "cleaner", "snapshot", "rebuild-vector-index", "download-embedding-model"),
        default="all",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--processors", type=int, default=1)
    parser.add_argument("--cleaners", type=int, default=1)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--processor-id", default=None)
    parser.add_argument("--cleaner-id", default=None)
    parser.add_argument("--poll-interval-seconds", type=float, default=0.2)
    parser.add_argument("--run-interval-seconds", type=float, default=None)
    parser.add_argument("--lease-seconds", type=int, default=None)
    parser.add_argument("--max-attempts", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--once", action="store_true")
    return parser


def run(args: list[str] | None = None) -> int:
    parsed = build_parser().parse_args(args)
    if parsed.mode == "serve":
        # Auto-set PALLIUM_BASE_URL if not already set — needed by the MCP endpoint
        # which is mounted on this server and calls back to the HTTP API
        import os
        if "PALLIUM_BASE_URL" not in os.environ:
            os.environ["PALLIUM_BASE_URL"] = f"http://{parsed.host}:{parsed.port}"
        uvicorn.run(
            "app.main:app",
            factory=True,
            host=parsed.host,
            port=parsed.port,
            reload=parsed.reload,
            log_config=build_uvicorn_log_config(component="api"),
        )
        return 0
    if parsed.mode == "mcp":
        try:
            from app.mcp.server import main as mcp_main
        except ImportError:
            logger.error("MCP dependencies not installed. Run: pip install -e '.[mcp]'")
            return 1
        mcp_main()
        return 0
    if parsed.mode == "processor":
        processor_args: list[str] = []
        if parsed.processor_id:
            processor_args.extend(["--processor-id", parsed.processor_id])
        processor_args.extend(["--poll-interval-seconds", str(parsed.poll_interval_seconds)])
        if parsed.lease_seconds is not None:
            processor_args.extend(["--lease-seconds", str(parsed.lease_seconds)])
        if parsed.max_attempts is not None:
            processor_args.extend(["--max-attempts", str(parsed.max_attempts)])
        if parsed.once:
            processor_args.append("--once")
        return run_processor(processor_args)
    if parsed.mode == "cleaner":
        cleaner_args: list[str] = []
        if parsed.cleaner_id:
            cleaner_args.extend(["--cleaner-id", parsed.cleaner_id])
        if parsed.run_interval_seconds is not None:
            cleaner_args.extend(["--run-interval-seconds", str(parsed.run_interval_seconds)])
        if parsed.lease_seconds is not None:
            cleaner_args.extend(["--lease-seconds", str(parsed.lease_seconds)])
        if parsed.batch_size is not None:
            cleaner_args.extend(["--batch-size", str(parsed.batch_size)])
        if parsed.once:
            cleaner_args.append("--once")
        return run_cleaner(cleaner_args)
    if parsed.mode == "snapshot":
        from app.snapshot import run_snapshot
        return run_snapshot()
    if parsed.mode == "rebuild-vector-index":
        return _run_rebuild_vector_index()
    if parsed.mode == "download-embedding-model":
        return _run_download_embedding_model()
    supervisor_args = [
        "--host",
        parsed.host,
        "--port",
        str(parsed.port),
        "--processors",
        str(parsed.processors),
        "--cleaners",
        str(parsed.cleaners),
    ]
    if parsed.reload:
        supervisor_args.append("--reload")
    return run_supervisor(supervisor_args)


def _run_rebuild_vector_index() -> int:
    """Rebuild the vector index from scratch using all vector index entries in SQLite."""
    from pathlib import Path

    from app.config import AppConfig
    from app.dependencies import build_embedding_provider, build_storage_provider

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    config = AppConfig.from_env()
    vector_config = config.vector_index

    if not vector_config.enabled:
        logger.error("Vector index is not enabled in configuration. Set [vector_index] enabled = true.")
        return 1

    if not vector_config.embedding_provider:
        logger.error("No embedding_provider configured under [vector_index].")
        return 1

    try:
        embedding_provider = build_embedding_provider(config, provider_name=vector_config.embedding_provider)
    except Exception as exc:
        logger.error("Failed to build embedding provider: %s", exc)
        return 1

    storage = build_storage_provider(config)
    entries = storage.list_index_entries_by_type("vector")
    logger.info("Found %d vector index entries in SQLite.", len(entries))

    from storage.vector_index import VectorIndex

    index_path = Path(vector_config.index_path)
    try:
        vector_index = VectorIndex.create_empty(
            index_path,
            dimensions=embedding_provider.dimensions(),
            model_name=embedding_provider.model_name(),
        )
    except ImportError:
        logger.error("usearch not installed. pip install usearch")
        return 1

    if entries:
        texts = [entry.text_view for entry in entries]
        logger.info("Embedding %d entries...", len(texts))
        vectors = embedding_provider.embed(texts, mode="passage")
        for entry, vector in zip(entries, vectors):
            vector_index.add(entry.id, vector)

    vector_index.save()
    logger.info("Vector index rebuilt successfully at %s with %d entries.", index_path, vector_index.entry_count())
    return 0


def _run_download_embedding_model() -> int:
    """Download the embedding model (eagerly initializes the provider)."""
    from app.config import AppConfig
    from app.dependencies import build_embedding_provider

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    config = AppConfig.from_env()
    vector_config = config.vector_index

    if not vector_config.embedding_provider:
        logger.error("No embedding_provider configured under [vector_index].")
        return 1

    try:
        provider = build_embedding_provider(config, provider_name=vector_config.embedding_provider)
    except Exception as exc:
        logger.error("Failed to build embedding provider: %s", exc)
        return 1

    logger.info(
        "Embedding model '%s' ready (dimensions=%d).",
        provider.model_name(),
        provider.dimensions(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
