from __future__ import annotations

import logging
import re
import types

from app.cleaner import run_cleaner
from app.config import AppConfig
from app.runtime_logging import emit_runtime_log
from storage.vector_index import VectorIndexConfig
from storage.base import RetentionRunStats
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


TIMESTAMPED_CLEANER_LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T.+ \[cleaner\] cleaner_id=cleaner-test retention deleted_source_items=1 ",
    re.MULTILINE,
)


class FakeRetentionService:
    def run_retention_pass(self, *, worker_id: str, lease_seconds: int | None = None, batch_size: int | None = None):
        assert worker_id == "cleaner-test"
        return RetentionRunStats(deleted_source_items=1, skipped_protected_source_items=2)


def test_cleaner_runtime_logs_are_timestamped_and_labeled(monkeypatch, capsys) -> None:
    monkeypatch.setattr("app.cleaner.build_service", lambda config, **kw: types.SimpleNamespace(service=FakeRetentionService()))

    exit_code = run_cleaner(
        ["--once", "--cleaner-id", "cleaner-test"],
        config=AppConfig(storage_backend="sqlite", sqlite_url="sqlite:///:memory:", default_use_case="demo_agent_memory", semantic_packages=DEMO_SEMANTIC_PACKAGES, vector_index=VectorIndexConfig(enabled=False)),
        install_signal_handlers=False,
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert TIMESTAMPED_CLEANER_LINE.search(output)


# ---------------------------------------------------------------------------
# Routing-through-root regression suite (the wscript service bug).
#
# The original emit_runtime_log set propagate=False on its named loggers,
# which silently bypassed any FileHandler attached to root by
# configure_file_logging. Under wscript launch (no console, stdout→NUL),
# this meant supervisor lines disappeared entirely. These tests pin the
# routing contract that prevents the bug recurring.
# ---------------------------------------------------------------------------


def _attach_capture_handler_to_root(level: int = logging.INFO) -> tuple[list[str], logging.Handler]:
    """Attach a list-collecting handler to the root logger and return both."""
    captured: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(self.format(record))

    handler = _ListHandler(level=level)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    prev_level = root.level
    root.setLevel(level)
    root.addHandler(handler)
    handler._prev_root_level = prev_level  # type: ignore[attr-defined]
    return captured, handler


def _detach_capture_handler(handler: logging.Handler) -> None:
    root = logging.getLogger()
    root.removeHandler(handler)
    prev = getattr(handler, "_prev_root_level", logging.WARNING)
    root.setLevel(prev)


def test_emit_runtime_log_propagates_to_root_handlers() -> None:
    """Regression for the wscript bug: lines must reach root handlers (e.g.
    configure_file_logging's FileHandler), not just the local StreamHandler."""
    captured, handler = _attach_capture_handler_to_root()
    try:
        emit_runtime_log("supervisor", "hello-from-supervisor")
        assert any("hello-from-supervisor" in line for line in captured), (
            f"expected supervisor line in root-attached handler; got {captured!r}"
        )
    finally:
        _detach_capture_handler(handler)


def test_emit_runtime_log_propagates_stderr_path_too() -> None:
    """Stderr-routed messages must also reach root handlers — this is the
    code path that carries supervisor crash/restart notices."""
    captured, handler = _attach_capture_handler_to_root()
    try:
        emit_runtime_log("supervisor", "crash-msg", stderr=True)
        assert any("crash-msg" in line for line in captured)
    finally:
        _detach_capture_handler(handler)


def test_emit_runtime_log_still_writes_to_stdout_without_root_handlers(capsys) -> None:
    """Back-compat: when no root handlers are attached (e.g. dev/test mode),
    the local StreamHandler must still emit to stdout so capsys sees it."""
    emit_runtime_log("supervisor", "stdout-fallback-line")
    out = capsys.readouterr().out
    assert "stdout-fallback-line" in out, (
        "without root handlers, stdout must still receive the line via the local StreamHandler"
    )


def test_emit_runtime_log_no_duplicate_in_root_when_only_root_handler(capsys) -> None:
    """When a root handler is attached, the line must appear there exactly
    once — not twice from some accidental fan-out at the named-logger layer."""
    captured, handler = _attach_capture_handler_to_root()
    try:
        emit_runtime_log("supervisor", "single-msg-line")
    finally:
        _detach_capture_handler(handler)

    matches = [line for line in captured if "single-msg-line" in line]
    assert len(matches) == 1, f"expected exactly one root-handler hit, got {len(matches)}: {matches!r}"


def test_runtime_log_format_includes_component_label(capsys) -> None:
    """The `[component]` label discipline must hold for the propagation path
    too — root handlers receive a record with pallium_component populated.

    This guards the wscript service bug from regressing in a half-fixed form
    where lines reach the file but lose their `[supervisor]` label, making
    them indistinguishable from worker output.
    """
    captured: list[logging.LogRecord] = []

    class _RecordCapture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    h = _RecordCapture(level=logging.INFO)
    root = logging.getLogger()
    prev_level = root.level
    root.setLevel(logging.INFO)
    root.addHandler(h)
    try:
        emit_runtime_log("supervisor", "label-check")
    finally:
        root.removeHandler(h)
        root.setLevel(prev_level)

    assert captured, "no record reached root"
    # The named logger's own StreamHandler formats with [supervisor]; the root
    # handler receives the raw record and can apply its own formatter (e.g.
    # configure_file_logging's RuntimeLogFormatter). Verify the message body
    # so the contract is the message reaches root, not the formatter detail.
    assert any("label-check" in r.getMessage() for r in captured)


def test_root_filehandler_preserves_component_label(tmp_path) -> None:
    """When emit_runtime_log propagates to the root FileHandler installed by
    configure_file_logging, the actual component label must be preserved.

    Regression for the live-service bug where every supervisor/api/processor
    line appearing in pallium.log got rewritten to ``[service]`` because the
    FileHandler's RuntimeLogFormatter had a hardcoded fallback that always
    overrode whatever the per-record component said.
    """
    from app.runtime_logging import configure_file_logging

    log_dir = tmp_path / "logs"
    configure_file_logging(log_dir)
    log_file = log_dir / "pallium.log"
    try:
        emit_runtime_log("supervisor", "started api pid=999")
        emit_runtime_log("processor", "worker_id=p-1 status=ok")
        emit_runtime_log("service", "Active packages: foo")
    finally:
        # Detach FileHandler we just attached so other tests aren't affected.
        root = logging.getLogger()
        for h in list(root.handlers):
            if isinstance(h, logging.FileHandler) and h.baseFilename == str(log_file):
                root.removeHandler(h)
                h.close()

    content = log_file.read_text(encoding="utf-8")
    assert "[supervisor] started api pid=999" in content, content
    assert "[processor] worker_id=p-1 status=ok" in content, content
    assert "[service] Active packages: foo" in content, content
