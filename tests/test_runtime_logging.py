from __future__ import annotations

import re
import types

from app.cleaner import run_cleaner
from app.config import AppConfig
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
