from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import AppConfig
from app.main import create_app
from core.models import MemoryObject
from storage.sqlite_schema import MemoryFlagRecord
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


def _test_config(tmp_path: Path) -> AppConfig:
    db_path = tmp_path / "test-dashboard.db"
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{db_path}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )


def _seed_memory(app, *, type: str = "decision", lifecycle: str = "active", container_ref: str = "test-container") -> MemoryObject:
    service = app.state.pallium_service
    mo = MemoryObject(
        type=type,
        schema_id="test",
        schema_version="1.0",
        payload={"summary": f"Test {type} memory"},
        lifecycle=lifecycle,
        container_ref=container_ref,
        created_at=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
    )
    service._storage.create_memory_object(mo)
    return mo


class TestDashboardMemoriesEndpoint:

    def test_returns_empty_list_when_no_memories(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/memories")
        assert resp.status_code == 200
        body = resp.json()
        assert body["memories"] == []
        assert body["total"] == 0
        assert body["offset"] == 0
        assert body["limit"] == 50

    def test_returns_seeded_memories(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_memory(app, type="decision")
            _seed_memory(app, type="atomic_fact")
            resp = client.get("/dashboard/api/memories")
        body = resp.json()
        assert body["total"] == 2
        assert len(body["memories"]) == 2
        mem = body["memories"][0]
        assert "id" in mem
        assert "type" in mem
        assert "display_text" in mem
        assert "created_at" in mem

    def test_filters_by_type(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_memory(app, type="decision")
            _seed_memory(app, type="atomic_fact")
            resp = client.get("/dashboard/api/memories?type=decision")
        body = resp.json()
        assert body["total"] == 1
        assert body["memories"][0]["type"] == "decision"

    def test_filters_by_lifecycle(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_memory(app, type="decision", lifecycle="active")
            _seed_memory(app, type="decision", lifecycle="suppressed")
            resp = client.get("/dashboard/api/memories?lifecycle=suppressed")
        body = resp.json()
        assert body["total"] == 1
        assert body["memories"][0]["lifecycle"] == "suppressed"

    def test_filters_by_flagged_lifecycle(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            mo_flagged = _seed_memory(app, type="decision", lifecycle="active")
            _seed_memory(app, type="decision", lifecycle="active")
            # Insert a flag record for the first memory
            storage = app.state.pallium_service._storage
            with storage._session_factory() as session:
                flag = MemoryFlagRecord(
                    id="test-flag-1",
                    memory_object_id=mo_flagged.id,
                    reason="test flag",
                    source_ref="test",
                    flagged_at=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
                )
                session.add(flag)
                session.commit()
            resp = client.get("/dashboard/api/memories?lifecycle=flagged")
        body = resp.json()
        assert body["total"] == 1
        assert body["memories"][0]["id"] == mo_flagged.id

    def test_pagination_limit_and_offset(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            for i in range(5):
                _seed_memory(app, type="decision")
            resp = client.get("/dashboard/api/memories?limit=2&offset=2")
        body = resp.json()
        assert body["total"] == 5
        assert len(body["memories"]) == 2
        assert body["offset"] == 2
        assert body["limit"] == 2

    def test_limit_capped_at_200(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/memories?limit=999")
        body = resp.json()
        assert body["limit"] == 200


class TestDashboardRelaySummary:

    def test_empty_relay_is_ready_and_names_all_supported_runtimes(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            response = client.get("/dashboard/api/relay/summary")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "idle"
        assert body["messages"] == {"last_24h": 0, "total": 0, "replies_last_24h": 0}
        assert set(body["sessions"]) == {"claude-code", "codex", "opencode"}

    def test_relay_summary_reports_pending_delivery_expiry_and_latency_without_content(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        scope = {"container_ref": "git:example.test/team/dashboard", "actor_ref": "operator"}
        with TestClient(app) as client:
            for runtime, session_ref in (("claude-code", "sender"), ("codex", "target")):
                response = client.post(
                    "/relay/turn",
                    json={"runtime": runtime, "session_ref": session_ref, **scope},
                )
                assert response.status_code == 200
            sent = client.post(
                "/relay/messages",
                json={
                    "sender_runtime": "claude-code",
                    "sender_session_ref": "sender",
                    "recipient": "codex:target",
                    "payload": "private-secret-payload",
                    **scope,
                },
            ).json()

            pending = client.get("/dashboard/api/relay/summary").json()
            assert pending["status"] == "active"
            assert pending["deliveries"]["pending_now"] == 1
            assert "private-secret-payload" not in str(pending)

            claimed = client.post(
                "/relay/turn",
                json={"runtime": "codex", "session_ref": "target", **scope},
            ).json()["deliveries"][0]
            ack = client.post(
                "/relay/deliveries/ack",
                json={
                    "delivery_id": claimed["delivery_id"],
                    "claim_token": claimed["claim_token"],
                    **scope,
                },
            )
            assert ack.status_code == 200
            delivered = client.get("/dashboard/api/relay/summary").json()
            assert delivered["deliveries"]["delivered_total"] == 1
            assert delivered["latency_seconds"]["sample_size"] == 1

            expiring = client.post(
                "/relay/messages",
                json={
                    "sender_runtime": "claude-code",
                    "sender_session_ref": "sender",
                    "recipient": "codex:target",
                    "payload": "expires",
                    "expires_in_seconds": 60,
                    **scope,
                },
            ).json()
            storage = app.state.pallium_service._storage
            with storage._session_factory() as session:
                session.execute(
                    text("UPDATE relay_messages SET expires_at=:past WHERE id=:id"),
                    {"past": datetime.now(timezone.utc) - timedelta(seconds=1), "id": expiring["message_id"]},
                )
                session.commit()

            expired = client.get("/dashboard/api/relay/summary").json()
            assert expired["status"] == "attention"
            assert expired["deliveries"]["pending_now"] == 0
            assert expired["deliveries"]["expired_total"] == 1
            assert sent["message_id"] != expiring["message_id"]


class TestDashboardPage:

    def test_dashboard_returns_html(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_static_logo_served(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/static/logo/pallium_header.png")
        assert resp.status_code == 200
        assert "image" in resp.headers["content-type"]


class TestDashboardIntegration:

    def test_dashboard_html_contains_key_elements(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard")
        html = resp.text
        assert "Pallium Dashboard" in html
        assert "Pallium" in html
        assert "fetchStatus" in html
        assert "/dashboard/api/memories" in html
        assert "/dashboard/api/relay/summary" in html
        assert '<details id="operational-summary"' in html
        assert "summary.hidden = !attention" in html
        assert "Agent Relay" in html
        assert 'class="table-scroll"' in html
        assert "@media (max-width: 600px)" in html

    def test_dashboard_html_has_dual_time_endpoints_wired(self, tmp_path: Path) -> None:
        """Regression guard: the dashboard must call the new /metrics/totals
        endpoint and render the dual-time tiles + hourly stacked bar that
        depend on it. If a refactor accidentally removes any of these, the
        UI silently falls back to since-restart counters and loses the
        24h vs all-time comparison the user explicitly asked for."""
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard")
        html = resp.text
        # New endpoint wiring
        assert "/dashboard/api/metrics/totals" in html
        assert "fetchMetricsTotals" in html
        # Dual-time atom + sparkline + stacked-bar renderers
        assert "renderQueryTiles" in html
        assert "renderSparkline" in html
        assert "renderStackedBars" in html
        # Skip-reason trend (24h + 7d + delta)
        assert "fetchSkipReasonStats" in html
        assert "renderSkipReasonsTable" in html
        # Extraction Health card backed by queue/health.recent_failures
        assert "fetchExtractionFailures" in html
        assert "extraction-fail-list" in html

    def test_memories_display_text_extraction(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            service = app.state.pallium_service
            mo = MemoryObject(
                type="investigation_outcome",
                schema_id="test",
                schema_version="1.0",
                payload={"investigation_outcome": "Found root cause in parser", "other": "data"},
                lifecycle="active",
                created_at=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
            )
            service._storage.create_memory_object(mo)
            resp = client.get("/dashboard/api/memories")
        body = resp.json()
        assert body["memories"][0]["display_text"] == "Found root cause in parser"

    def test_memories_operational_fact_renders_subject(self, tmp_path: Path) -> None:
        """Regression: operational_fact rows must NOT render as '<no summary>'.

        The type's payload uses ``subject`` (and ``artifact``) rather than
        ``summary``/``statement``. The dashboard endpoint must surface
        those via the shared ``subject_text_for_payload`` helper + the
        ``subject`` key in ``_DISPLAY_TEXT_KEYS``.
        """
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            service = app.state.pallium_service
            mo = MemoryObject(
                type="operational_fact",
                schema_id="agent_work_trace.operational_fact",
                schema_version="v1",
                payload={
                    "command_family": "python",
                    "artifact_role": "interpreter",
                    "scope_kind": "machine_repo",
                    "scope_ref": "test@machine:hash",
                    "subject": "python: .venv/Scripts/python.exe",
                    "artifact": ".venv/Scripts/python.exe",
                    "artifact_normalized": ".venv/scripts/python.exe",
                    "origin": "agent_inferred",
                    "use_counters": {
                        "reuse_count": 1,
                        "success_count": 0,
                        "failure_count": 0,
                        "last_used_at": None,
                        "last_confirmed_at": None,
                    },
                },
                lifecycle="active",
                created_at=datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc),
            )
            service._storage.create_memory_object(mo)
            resp = client.get("/dashboard/api/memories")
        body = resp.json()
        assert len(body["memories"]) == 1
        m = body["memories"][0]
        # display_text (SUMMARY column) must have content, not empty.
        assert m["display_text"], (
            f"operational_fact display_text was empty: {m!r}"
        )
        assert "python" in m["display_text"].lower()
        # subject field is also populated so tooltips / details work.
        assert m["subject"], "operational_fact subject was empty"

    def test_memories_subject_falls_back_when_column_null(self, tmp_path: Path) -> None:
        """The dashboard falls back to subject_text_for_payload when the
        DB column is NULL (older rows written before the subject writer
        landed). Applies to any type whose payload has 'subject'.
        """
        from sqlalchemy import text as _text

        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            service = app.state.pallium_service
            mo = MemoryObject(
                type="operational_fact",
                schema_id="agent_work_trace.operational_fact",
                schema_version="v1",
                payload={
                    "subject": "shell: uv sync",
                    "artifact": "uv sync",
                    "command_family": "uv",
                    "artifact_role": "runner",
                    "scope_kind": "repo",
                    "scope_ref": "test",
                    "origin": "agent_inferred",
                },
                lifecycle="active",
                created_at=datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc),
            )
            service._storage.create_memory_object(mo)
            # Simulate an older row: null the subject column directly.
            with service._storage._engine.begin() as conn:
                conn.execute(_text("UPDATE memory_objects SET subject=NULL"))
            resp = client.get("/dashboard/api/memories")
        body = resp.json()
        m = body["memories"][0]
        assert m["subject"] == "shell: uv sync"
        assert m["display_text"] == "shell: uv sync"

    def test_memories_default_lifecycle_shows_all(self, tmp_path: Path) -> None:
        """When no lifecycle filter is passed, all lifecycles are returned."""
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_memory(app, type="decision", lifecycle="active")
            _seed_memory(app, type="decision", lifecycle="suppressed")
            _seed_memory(app, type="decision", lifecycle="superseded")
            resp = client.get("/dashboard/api/memories")
        body = resp.json()
        assert body["total"] == 3

    def test_search_filters_by_payload(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            service = app.state.pallium_service
            from core.models import MemoryObject
            mo1 = MemoryObject(
                type="decision", schema_id="test", schema_version="1.0",
                payload={"summary": "Use PostgreSQL for the database"},
                lifecycle="active",
                created_at=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
            )
            mo2 = MemoryObject(
                type="decision", schema_id="test", schema_version="1.0",
                payload={"summary": "Deploy to Kubernetes"},
                lifecycle="active",
                created_at=datetime(2026, 4, 28, 11, 0, 0, tzinfo=timezone.utc),
            )
            service._storage.create_memory_object(mo1)
            service._storage.create_memory_object(mo2)
            resp = client.get("/dashboard/api/memories?search=PostgreSQL")
        body = resp.json()
        assert body["total"] == 1
        assert "PostgreSQL" in body["memories"][0]["display_text"]


class TestDashboardTwoViewShell:
    """The dashboard HTML must ship the two-view shell markers so the
    Operational / How-memory-helps switch is covered by the substring guard."""

    def test_html_contains_two_view_switch(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard")
        html = resp.text
        # Tab buttons + switch function
        assert 'id="tab-operational"' in html
        assert 'id="tab-how-it-helps"' in html
        assert "switchView(" in html
        # Both view containers present (CSS display toggle, both in DOM)
        assert 'id="view-operational"' in html
        assert 'id="view-how-it-helps"' in html
        # The "How memory helps" label + the funnel pill + report wiring
        assert "How memory helps" in html
        assert 'id="funnel-pill"' in html
        assert "fetchEffectivenessReports" in html
        assert "Did pulled-up memory help the next task?" in html
        assert "We do not know yet whether pulled-up memory helped." in html
        assert "does not show that Pallium improved real work." in html
        assert "hand-reviewed examples" in html
        # Derivation research leads with human conclusions; jargon stays secondary.
        assert "Are compact memories helping?" in html
        assert "Can it find the right past information?" in html
        assert "Are compact memories created faithfully?" in html
        assert "Original conversation history found the expected evidence" in html
        assert "Accuracy was not checked in this run." in html
        assert "This is not a success rate." in html
        assert "Technical details" in html
        assert ">Raw / Derived / Hybrid<" not in html
        assert "recovery ·" not in html

    def test_plain_language_renderers_execute(self) -> None:
        """Execute the shipped JS against present, missing, null, and judged reports."""
        import shutil
        import subprocess

        node = shutil.which("node")
        if node is None:
            pytest.skip("Node.js is required for the dashboard renderer contract test")
        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                node,
                str(Path(__file__).with_name("dashboard_plain_language_renderer.mjs")),
                str(repo_root / "app" / "dashboard.html"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "all cases passed" in result.stdout


class TestDashboardEffectivenessReports:
    """The read-only report endpoint: empty-safe 200 when absent, parsed
    JSON + last_modified when present, and traversal-proof (fixed keys only)."""

    def test_empty_state_when_dir_absent(self, tmp_path: Path, monkeypatch) -> None:
        # cwd where .local/research/ does not exist → present-but-empty 200
        monkeypatch.chdir(tmp_path)
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/effectiveness/reports")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body["reports"].keys()) == {"raw_derived_hybrid", "derivation_fidelity", "reuse_judge_calibration"}
        for entry in body["reports"].values():
            assert entry["available"] is False
            assert entry["last_modified"] is None

    def test_serves_parsed_report_and_mtime_when_present(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        research = tmp_path / ".local" / "research"
        research.mkdir(parents=True)
        payload = {"eval": "raw_derived_hybrid.v1", "query_count": 7}
        (research / "raw_derived_hybrid_report.json").write_text(
            __import__("json").dumps(payload), encoding="utf-8"
        )
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/effectiveness/reports")
        assert resp.status_code == 200
        body = resp.json()
        rdh = body["reports"]["raw_derived_hybrid"]
        assert rdh["available"] is True
        assert rdh["report"] == payload
        assert rdh["last_modified"] is not None
        # The other, unwritten report stays empty-safe
        assert body["reports"]["derivation_fidelity"]["available"] is False

    def test_non_finite_floats_are_sanitized(self, tmp_path: Path, monkeypatch) -> None:
        """A report with NaN/Infinity (json.loads accepts them) must be coerced
        to null so the HTTP response is strictly valid JSON — otherwise a
        browser fetch().json() would reject bare NaN and break the panel."""
        import json as _json
        monkeypatch.chdir(tmp_path)
        research = tmp_path / ".local" / "research"
        research.mkdir(parents=True)
        # allow_nan=True (default) writes literal NaN/Infinity into the file.
        payload = {"coverage": {"item_extraction": {"coverage_rate": float("nan")}},
                   "fidelity": {"misleading_rate": float("inf")}, "query_count": 3}
        (research / "derivation_fidelity_report.json").write_text(
            _json.dumps(payload), encoding="utf-8"
        )
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/effectiveness/reports")
        assert resp.status_code == 200
        # Response body must be strictly-parseable JSON (no bare NaN/Infinity).
        raw = resp.text
        assert "NaN" not in raw and "Infinity" not in raw
        rep = resp.json()["reports"]["derivation_fidelity"]["report"]
        assert rep["coverage"]["item_extraction"]["coverage_rate"] is None
        assert rep["fidelity"]["misleading_rate"] is None
        assert rep["query_count"] == 3

    def test_route_ignores_arbitrary_path_param(self, tmp_path: Path, monkeypatch) -> None:
        """Traversal-proof: there is no filename/path param — an arbitrary
        query string resolves the same fixed keys, never an outside file."""
        monkeypatch.chdir(tmp_path)
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get(
                "/dashboard/api/effectiveness/reports?report=../../../../etc/passwd"
            )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body["reports"].keys()) == {"raw_derived_hybrid", "derivation_fidelity", "reuse_judge_calibration"}

    def test_reports_endpoint_does_not_require_sqlite(self, tmp_path: Path, monkeypatch) -> None:
        """Unlike other /dashboard/api/* routes, the file-backed report
        endpoint returns 200 (not 501) even without a SQLite backend."""
        monkeypatch.chdir(tmp_path)
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/effectiveness/reports")
        assert resp.status_code == 200


class TestDashboardContainersEndpoint:

    def test_returns_distinct_containers(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_memory(app, container_ref="container-a")
            _seed_memory(app, container_ref="container-b")
            _seed_memory(app, container_ref="container-a")
            resp = client.get("/dashboard/api/containers")
        body = resp.json()
        assert set(body["containers"]) == {"container-a", "container-b"}

    def test_empty_when_no_containers(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/containers")
        body = resp.json()
        assert body["containers"] == []


class TestDashboardActivityEndpoint:

    def test_returns_recent_memories(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_memory(app, type="decision")
            _seed_memory(app, type="atomic_fact")
            resp = client.get("/dashboard/api/activity?limit=5")
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["items"][0]["event"] == "memory_created"
        assert "type" in body["items"][0]
        assert "display_text" in body["items"][0]


class TestDashboardFlagsEndpoint:

    def test_returns_flags_for_memory(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            mo = _seed_memory(app, type="decision")
            storage = app.state.pallium_service._storage
            with storage._session_factory() as session:
                session.add(MemoryFlagRecord(
                    id="flag-test-1",
                    memory_object_id=mo.id,
                    reason="incorrect decision",
                    source_ref="test-agent",
                    flagged_at=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
                ))
                session.commit()
            resp = client.get(f"/dashboard/api/memories/{mo.id}/flags")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["reason"] == "incorrect decision"
        assert body["items"][0]["source_ref"] == "test-agent"
        assert body["items"][0]["flagged_at"] is not None

    def test_returns_empty_when_no_flags(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            mo = _seed_memory(app, type="decision")
            resp = client.get(f"/dashboard/api/memories/{mo.id}/flags")
        assert resp.status_code == 200
        assert resp.json()["items"] == []
