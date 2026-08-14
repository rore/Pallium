"""Self-test for scripts/live_funnel_smoke.py against a SYNTHETIC DB.

Marked slow: seeds a realistic (production-shaped) sqlite DB via the
agent_conversation_memory (visibility-enforcing) package + a stub LLM
provider, then points the live-funnel smoke's snapshot + scratch-server +
search->expand->persist logic at THAT file as the "live" DB. Confirms the
chain runs and the unscoped events_recorded count increments ON THE COPY —
without ever touching the real :19836 service or the real production DB
(``--skip-real-status`` equivalent: skip_real_status=True).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.config_helpers import build_llm_test_config
from tests.stub_providers import TieredMemorySemanticProvider

pytestmark = pytest.mark.slow

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "live_funnel_smoke.py"

_CONTAINER = "chat:smoke-selftest"
_THREAD = "chat:smoke-selftest:t1"
_USER = "Decision: use item event time for reservation ordering to avoid duplicate holds."
_WORK = "We discussed reservation ordering and duplicate holds at length in this thread."


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("live_funnel_smoke", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # let dataclasses resolve module namespace
    spec.loader.exec_module(module)
    return module


def _seed_synthetic_db(monkeypatch, sqlite_url: str) -> None:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: TieredMemorySemanticProvider(),
    )
    with TestClient(
        create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=sqlite_url))
    ) as client:
        for source_id, content, role, kind in (
            ("u1", _USER, "user", "message"),
            ("a1", _WORK, "assistant", "assistant_output"),
        ):
            source_type = "chat_message" if role == "user" else "assistant_artifact"
            resp = client.post("/items", json=[{
                "source_type": source_type,
                "source_id": source_id,
                "content_type": "text/plain",
                "content": content,
                "artifact_kind": kind,
                "role": role,
                "container_ref": _CONTAINER,
                "thread_ref": _THREAD,
                "visibility": "private",
            }])
            assert resp.status_code == 200, resp.text
            client.app.state.pallium_service.drain_processing_queue(worker_id="selftest")


def test_smoke_against_synthetic_db(monkeypatch, tmp_path: Path) -> None:
    live_db = tmp_path / "synthetic-live.db"
    _seed_synthetic_db(monkeypatch, f"sqlite:///{live_db}")
    assert live_db.exists()

    smoke = _load_smoke_module()
    result = smoke.run_smoke(
        live_db=live_db,
        scratch_port=19941,
        real_url="http://127.0.0.1:19836",
        container_ref=_CONTAINER,
        thread_ref=_THREAD,
        visibility="private",
        query_text="reservation ordering duplicate holds",
        skip_real_status=True,  # never touch the real service in the self-test
    )

    names = {name: (ok, detail) for name, ok, detail in result.checks}
    assert names["search-lookup-persisted"][0], names["search-lookup-persisted"][1]
    assert names["expand-source-context"][0], names["expand-source-context"][1]
    assert names["events-recorded-incremented"][0], names["events-recorded-incremented"][1]
    assert names["copy-has-lookup-row"][0], names["copy-has-lookup-row"][1]
    assert names["copy-expansion-links-lookup"][0], names["copy-expansion-links-lookup"][1]
    assert names["scratch-cleanup"][0], names["scratch-cleanup"][1]
    assert result.passed, result.checks

    # The disposable copy must not linger next to the synthetic DB.
    leftovers = list(tmp_path.glob("pallium-smoke-*.db"))
    assert not leftovers, leftovers
