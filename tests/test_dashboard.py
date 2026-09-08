from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import AppConfig
from app.main import create_app
from core.models import MemoryObject, SourceItem
from storage.sqlite_schema import HistoricalLookupReuseEventRecord, HistoricalLookupReuseLabelRecord, MemoryFlagRecord, RelayDeliveryRecord, RelaySessionRecord
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
        scope = {"container_ref": "git:example.test/team/dashboard"}
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

            assert sent["expires_at"] is None
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
            assert expiring["expires_at"] is not None
            storage = app.state.pallium_service._storage
            with storage._relay_session_factory() as session:
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
        assert '<section id="operational-summary"' in html
        assert "summary.hidden = false" in html
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
        assert "qa-derived-mode" in html
        assert "automatic injection: " in html
        assert "Pallium does not search derived memory automatically" in html
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
            from core.models import MemoryObject, SourceItem
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
    Operations / Relay switch is covered by the substring guard."""

    def test_html_contains_two_view_switch(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard")
        html = resp.text
        # Tab buttons + switch function
        assert 'id="tab-operational"' in html
        assert 'id="tab-relay"' in html
        assert "switchView(" in html
        # Both view containers present (CSS display toggle, both in DOM)
        assert 'id="view-operational"' in html
        assert 'id="view-how-it-helps"' in html
        # The "How memory helps" label + the funnel pill + report wiring
        assert "How memory helps" in html
        assert 'id="funnel-pill"' in html
        assert "fetchEffectivenessReports" in html
        assert "Functional outcome evidence" in html
        assert "We do not know yet whether pulled-up history helped." in html
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
        assert set(body["reports"].keys()) == {"raw_derived_hybrid", "derivation_fidelity", "reuse_judge_calibration", "historical_lookup_measurement", "historical_lookup_judge"}
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
        assert set(body["reports"].keys()) == {"raw_derived_hybrid", "derivation_fidelity", "reuse_judge_calibration", "historical_lookup_measurement", "historical_lookup_judge"}

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

class TestDashboardSourceAndRelayProjections:
    def test_sources_require_scope_and_apply_optional_exact_actor_filter_forget_and_redaction(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
        visible = SourceItem(source_type="turn", source_id="visible", content_type="text/plain",
            content="api_key=AKIA1234567890ABCDEF", metadata={"secret": "AKIA1234567890ABCDEF"},
            container_ref="c1", actor_ref="a1", agent_ref="α-agent", visibility="private", created_at=now)
        other_actor = SourceItem(source_type="turn", source_id="other", content_type="text/plain", content="nope",
            container_ref="c1", actor_ref="a2", visibility="private", created_at=now + timedelta(seconds=1))
        actorless = SourceItem(source_type="turn", source_id="actorless", content_type="text/plain", content="shared",
            container_ref="c1", agent_ref="α-agent", visibility="private", created_at=now + timedelta(seconds=4))
        forgotten = SourceItem(source_type="turn", source_id="forgotten", content_type="text/plain", content="gone",
            container_ref="c1", actor_ref="a1", visibility="private", forgotten_at=now, created_at=now + timedelta(seconds=2))
        note = SourceItem(source_type="turn", source_id="note", content_type="text/plain", content="AKIA1234567890ABCDEF",
            artifact_kind="note", container_ref="c1", actor_ref="a1", agent_ref="α-agent", visibility="private", created_at=now + timedelta(seconds=3))
        app.state.pallium_service._storage.create_source_item(visible)
        app.state.pallium_service._storage.create_source_item(other_actor)
        app.state.pallium_service._storage.create_source_item(actorless)
        app.state.pallium_service._storage.create_source_item(forgotten)
        app.state.pallium_service._storage.create_source_item(note)
        with app.state.pallium_service._storage._session_factory() as session:
            session.execute(text("UPDATE source_items SET forgotten_at=:now WHERE id=:id"), {"now": now, "id": forgotten.id})
            session.commit()
        with TestClient(app) as client:
            assert client.get("/dashboard/api/sources").status_code == 422
            assert client.get("/dashboard/api/sources?container_ref=c1&actor_ref=a1&query_visibility=nope").status_code == 422
            assert client.get("/dashboard/api/sources?container_ref=c1&actor_ref=&query_visibility=private").status_code == 422
            unfiltered = client.get("/dashboard/api/sources?container_ref=c1&query_visibility=private").json()
            assert unfiltered["total"] == 4
            assert [item["id"] for item in unfiltered["sources"]] == [actorless.id, note.id, other_actor.id, visible.id]
            response = client.get("/dashboard/api/sources?container_ref=c1&actor_ref=a1&query_visibility=private&agent_ref=%CE%B1-agent")
            assert response.status_code == 200
            body = response.json()
            assert [item["id"] for item in body["sources"]] == [note.id, visible.id]
            assert "AKIA1234567890ABCDEF" not in body["sources"][1]["content"]
            assert "AKIA1234567890ABCDEF" not in str(body["sources"][1]["metadata"])
            assert body["sources"][0]["content"] == "AKIA1234567890ABCDEF"  # intentional note carve-out
            assert client.get(f"/dashboard/api/sources/{other_actor.id}?container_ref=c1&actor_ref=a1&query_visibility=private").status_code == 404
            assert client.get(f"/dashboard/api/sources/{actorless.id}?container_ref=c1&actor_ref=a1&query_visibility=private").status_code == 404
            assert client.get(f"/dashboard/api/sources/{other_actor.id}?container_ref=c1&query_visibility=private").status_code == 200
            assert client.get(f"/dashboard/api/sources/{forgotten.id}?container_ref=c1&actor_ref=a1&query_visibility=private").status_code == 404
            assert "AKIA1234567890ABCDEF" not in str(client.get("/dashboard/api/activity").json())

    def test_reuse_events_apply_optional_exact_actor_metadata_filter(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        storage = app.state.pallium_service._storage
        now = datetime.now(timezone.utc)
        with storage._session_factory() as session:
            for event_id, actor_ref, visibility in (
                ("event-a", "操作员甲", "private"),
                ("event-b", "操作员乙", "private"),
                ("event-none", None, "private"),
                ("event-global", "操作员甲", "global"),
            ):
                session.add(HistoricalLookupReuseEventRecord(
                    id=event_id, created_at=now, event_type="lookup",
                    container_ref="c1", actor_ref=actor_ref, visibility=visibility,
                ))
            session.commit()

        with TestClient(app) as client:
            base = "/dashboard/api/history/reuse-events?container_ref=c1&query_visibility=private"
            unfiltered = client.get(base).json()
            actor_a = client.get(base + "&actor_ref=%E6%93%8D%E4%BD%9C%E5%91%98%E7%94%B2").json()
            actor_b = client.get(base + "&actor_ref=%E6%93%8D%E4%BD%9C%E5%91%98%E4%B9%99").json()
            assert client.get(base + "&actor_ref=").status_code == 422

        assert unfiltered["total"] == 3
        assert {event["id"] for event in unfiltered["events"]} == {
            "event-a", "event-b", "event-none",
        }
        assert actor_a["total"] == 2
        assert {event["id"] for event in actor_a["events"]} == {"event-a", "event-global"}
        assert actor_b["total"] == 1
        assert actor_b["events"][0]["id"] == "event-b"


    def test_history_projection_never_returns_cached_source_text(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        storage = app.state.pallium_service._storage
        source = SourceItem(source_type="turn", source_id="s", content_type="text/plain", content="private body",
            container_ref="c1", actor_ref="a1", visibility="private")
        storage.create_source_item(source)
        with storage._session_factory() as session:
            session.add(HistoricalLookupReuseEventRecord(id="event", created_at=datetime.now(timezone.utc), event_type="lookup",
                container_ref="c1", actor_ref="a1", visibility="private", query_text="AKIA1234567890ABCDEF",
                request_source_item_id=source.id, exposed_json='[{"source_item_id":"%s","role":"anchor","raw_rank":1,"score":0.9}]' % source.id))
            session.add(HistoricalLookupReuseLabelRecord(id="label", lookup_event_id="event", rater_seed="r", rung="influence",
                rationale="AKIA1234567890ABCDEF", created_at=datetime.now(timezone.utc)))
            session.commit()
        with TestClient(app) as client:
            response = client.get("/dashboard/api/history/reuse-events?container_ref=c1&actor_ref=a1&query_visibility=private")
        assert response.status_code == 200
        item = response.json()["events"][0]
        assert item["request_source_item"] == {"id": source.id, "available": True}
        assert item["exposed"][0]["source_item_id"] == source.id
        assert item["exposed"][0]["role"] == "anchor"
        assert "private body" not in str(item)
        assert "AKIA1234567890ABCDEF" not in str(item)

    def test_relay_global_projection_is_paginated_read_only_and_secret_free(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        scope = {"container_ref": "c1"}
        with TestClient(app) as client:
            for runtime, session_ref in (("codex", "one"), ("claude-code", "two")):
                assert client.post("/relay/turn", json={"runtime": runtime, "session_ref": session_ref, **scope}).status_code == 200
            sent = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "one",
                "recipient": "claude-code:two", "payload": "AKIA1234567890ABCDEF", **scope}).json()
            sessions = client.get("/dashboard/api/relay/sessions?").json()["sessions"]
            assert {session["session_ref"] for session in sessions} == {"one", "two"}
            page = client.get("/dashboard/api/relay/messages?limit=1").json()
            assert page["total"] == 1 and page["messages"][0]["id"] == sent["message_id"]
            assert "claim_token" not in str(page) and "receipt" not in str(page)
            assert "AKIA1234567890ABCDEF" not in str(page)
            assert page["messages"][0]["expires_at"] is None
            assert len(client.get("/dashboard/api/relay/messages?").json()["messages"]) == 1

    def test_relay_session_filters_and_message_window_filters(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            for runtime, session_ref, container_ref in (("codex", "sender", "c1"), ("claude-code", "peer", "c2"), ("codex", "dormant", "c2")):
                assert client.post("/relay/turn", json={"runtime": runtime, "session_ref": session_ref,
                    "container_ref": container_ref}).status_code == 200
            sessions = client.get("/dashboard/api/relay/sessions?").json()
            assert sessions["total"] == 3
            endpoints = {item["session_ref"]: item["id"] for item in sessions["sessions"]}
            storage = app.state.pallium_service._storage
            with storage._relay_session_factory() as session:
                session.execute(text("UPDATE relay_sessions SET state='unreachable', last_seen_at=:old WHERE session_ref='dormant'"),
                    {"old": datetime.now(timezone.utc) - timedelta(days=2)})
                session.commit()
            filtered = client.get("/dashboard/api/relay/sessions?container_ref=c2&runtime=codex&lifecycle=dormant&destination_health=unreachable").json()
            assert filtered["total"] == 1
            assert filtered["sessions"][0]["lifecycle"] == "dormant"
            assert filtered["sessions"][0]["destination_health"] == "unreachable"
            assert client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender",
                "recipient": "claude-code:peer", "container_ref": "c1", "payload": "one"}).status_code == 200
            assert client.post("/relay/messages", json={"sender_runtime": "claude-code", "sender_session_ref": "peer",
                "recipient": "codex:sender", "container_ref": "c2", "payload": "two"}).status_code == 200
            query = f"/dashboard/api/relay/messages?endpoint_id={endpoints['sender']}&peer_endpoint_id={endpoints['peer']}&delivery_state=pending&limit=1"
            first = client.get(query).json()
            assert first["total"] == 2 and first["has_more"] is True and first["as_of"] == first["until"]
            assert all("claim_token" not in str(item) and "receipt" not in str(item) for item in first["messages"])
            assert all(endpoints["sender"] in {item["sender_endpoint_id"], *[d["recipient_endpoint_id"] for d in item["deliveries"]]} for item in first["messages"])
            second = client.get(query + f"&until={first['until'].replace('+', '%2B')}&before_created_at={first['next_before_created_at'].replace('+', '%2B')}&before_id={first['next_before_id']}").json()
            assert second["has_more"] is False and len(second["messages"]) == 1
            assert client.get("/dashboard/api/relay/messages?peer_endpoint_id=x").status_code == 422
            assert client.get("/dashboard/api/relay/messages?runtime=codex&container_ref=c1").json()["total"] == 1

    def test_source_scope_pagination_unicode_filters_and_reads_are_telemetry_free(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        storage = app.state.pallium_service._storage
        at = datetime(2026, 9, 7, 13, tzinfo=timezone.utc)
        rows = [
            SourceItem(id="page-a", source_type="chat", source_id="a", content_type="text", content="東京", role="user", artifact_kind="message", thread_ref="t", agent_ref="agent", container_ref="c1", actor_ref="a1", visibility="private", occurred_at=at, created_at=at),
            SourceItem(id="page-b", source_type="chat", source_id="b", content_type="text", content="東京", role="user", artifact_kind="message", thread_ref="t", agent_ref="agent", container_ref="c1", actor_ref="a1", visibility="private", occurred_at=at, created_at=at),
            SourceItem(id="container", source_type="chat", source_id="c", content_type="text", content="container", container_ref="c1", actor_ref="a1", visibility="container", created_at=at),
            SourceItem(id="public", source_type="chat", source_id="p", content_type="text", content="public", container_ref="c2", visibility="public", created_at=at),
            SourceItem(id="global", source_type="chat", source_id="g", content_type="text", content="global", container_ref="c2", actor_ref="a1", visibility="global", created_at=at),
        ]
        for row in rows:
            storage.create_source_item(row)
        with storage._session_factory() as session:
            before = session.query(HistoricalLookupReuseEventRecord).count()
        params = {"container_ref": "c1", "actor_ref": "a1", "query_visibility": "private", "source_type": "chat", "role": "user", "artifact_kind": "message", "thread_ref": "t", "agent_ref": "agent", "search": "東京", "limit": 1}
        with TestClient(app) as client:
            first = client.get("/dashboard/api/sources", params=params).json()
            second = client.get("/dashboard/api/sources", params={**params, "offset": 1}).json()
            assert first["total"] == 2 and [item["id"] for item in first["sources"]] == ["page-b"]
            assert [item["id"] for item in second["sources"]] == ["page-a"]
            assert client.get("/dashboard/api/sources/public", params={"container_ref": "c1", "actor_ref": "a1", "query_visibility": "public"}).status_code == 404
            assert client.get("/dashboard/api/sources/public", params={"container_ref": "c1", "query_visibility": "public"}).status_code == 200
            assert client.get("/dashboard/api/sources/global", params={"container_ref": "c1", "actor_ref": "a1", "query_visibility": "public"}).status_code == 200
            unfiltered_public = client.get("/dashboard/api/sources", params={"container_ref": "c1", "query_visibility": "public"}).json()
            assert unfiltered_public["total"] == 1
            assert [item["id"] for item in unfiltered_public["sources"]] == ["public"]
            assert client.get("/dashboard/api/sources/page-a", params={"container_ref": "c1", "actor_ref": "a1", "query_visibility": "public"}).status_code == 404
            container = client.get("/dashboard/api/sources", params={"container_ref": "c1", "actor_ref": "a1", "query_visibility": "container"}).json()
            assert "container" in {item["id"] for item in container["sources"]} and "page-a" not in {item["id"] for item in container["sources"]}
        with storage._session_factory() as session:
            assert session.query(HistoricalLookupReuseEventRecord).count() == before

    def test_reuse_events_hide_forgotten_and_missing_ids_and_tolerate_bad_json(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        storage = app.state.pallium_service._storage
        source = SourceItem(id="forgotten", source_type="chat", source_id="f", content_type="text", content="gone", container_ref="c", actor_ref="a", visibility="private")
        storage.create_source_item(source)
        with storage._session_factory() as session:
            session.execute(text("UPDATE source_items SET forgotten_at=:now WHERE id='forgotten'"), {"now": datetime.now(timezone.utc)})
            session.add(HistoricalLookupReuseEventRecord(id="bad", created_at=datetime.now(timezone.utc), event_type="lookup", container_ref="c", actor_ref="a", visibility="private", request_source_item_id="missing", exposed_json="not-json"))
            session.add(HistoricalLookupReuseEventRecord(id="hidden", created_at=datetime.now(timezone.utc), event_type="lookup", container_ref="c", actor_ref="a", visibility="private", request_source_item_id="forgotten", exposed_json='[{"source_item_id":"forgotten"},{"source_item_id":"missing"}]'))
            session.commit()
        with TestClient(app) as client:
            items = client.get("/dashboard/api/history/reuse-events?container_ref=c&actor_ref=a&query_visibility=private").json()["events"]
        hidden = next(item for item in items if item["id"] == "hidden")
        assert hidden["request_source_item"] == {"id": None, "available": False}
        assert all(entry["source_item_id"] is None and entry["available"] is False for entry in hidden["exposed"])
        assert next(item for item in items if item["id"] == "bad")["exposed"] == []

    def test_relay_split_store_and_multi_delivery_projection_boundaries(self, tmp_path: Path) -> None:
        config = replace(_test_config(tmp_path), relay_sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}")
        app = create_app(config)
        with TestClient(app) as client:
            for runtime, session_ref, container in (("codex", "sender", "c1"), ("claude-code", "first", "c2"), ("codex", "second", "c2"), ("codex", "other", "c3")):
                assert client.post("/relay/turn", json={"runtime": runtime, "session_ref": session_ref, "container_ref": container}).status_code == 200
            sessions = client.get("/dashboard/api/relay/sessions?").json()
            assert {item["container_ref"] for item in sessions["sessions"]} == {"c1", "c2", "c3"}
            assert client.get("/dashboard/api/relay/sessions?").json()["total"] == 4
            assert client.get("/dashboard/api/relay/messages").json()["messages"] == []
            sent = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender", "recipient": "claude-code:first", "container_ref": "c1", "payload": "fanout"}).json()
            ids = {item["session_ref"]: item["id"] for item in sessions["sessions"]}
            storage = app.state.pallium_service._storage
            with storage._relay_session_factory() as session:
                session.add(RelayDeliveryRecord(id="second-delivery", message_id=sent["message_id"], recipient_runtime="codex", recipient_session_ref="second", recipient_endpoint_id=ids["second"], recipient_container_ref="c2", state="pending", attempts=0))
                session.execute(text("UPDATE relay_sessions SET state='closed' WHERE id=:id"), {"id": ids["second"]})
                session.commit()
            page = client.get("/dashboard/api/relay/messages", params={"endpoint_id": ids["sender"], "peer_endpoint_id": ids["second"], "delivery_state": "pending"}).json()
            assert page["total"] == 1 and len(page["messages"][0]["deliveries"]) == 2
            assert client.get("/dashboard/api/relay/messages?limit=201").status_code == 422
            assert client.get("/dashboard/api/relay/messages?delivery_state=nope").status_code == 422
            assert client.get("/dashboard/api/relay/sessions?destination_health=nope").status_code == 422
            assert client.get("/dashboard/api/relay/messages?before_id=only").status_code == 422
            closed = client.get("/dashboard/api/relay/sessions?lifecycle=closed").json()["sessions"]
            assert closed[0]["session_ref"] == "second" and closed[0]["destination_health"] is None

    def test_reuse_event_free_text_is_suppressed_when_source_is_forgotten(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        storage = app.state.pallium_service._storage
        source = SourceItem(id="forgotten-text", source_type="chat", source_id="f", content_type="text", content="private source content", container_ref="c", actor_ref="a", visibility="private")
        storage.create_source_item(source)
        with storage._session_factory() as session:
            session.execute(text("UPDATE source_items SET forgotten_at=:now WHERE id=:id"), {"now": datetime.now(timezone.utc), "id": source.id})
            session.add(HistoricalLookupReuseEventRecord(id="hidden-text", created_at=datetime.now(timezone.utc), event_type="lookup", container_ref="c", actor_ref="a", visibility="private", query_text="private source content", request_source_item_id=source.id, exposed_json='[{"source_item_id":"forgotten-text"}]'))
            session.add(HistoricalLookupReuseLabelRecord(id="hidden-text-label", lookup_event_id="hidden-text", rater_seed="r", rung="influence", rationale="private source content", created_at=datetime.now(timezone.utc)))
            session.commit()
        with TestClient(app) as client:
            event = next(item for item in client.get("/dashboard/api/history/reuse-events?container_ref=c&actor_ref=a&query_visibility=private").json()["events"] if item["id"] == "hidden-text")
        assert event["text_available"] is False and event["query_text"] is None and event["labels"][0]["rationale"] is None

    def test_relay_effective_delivery_state_and_naive_times_are_read_only(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            for runtime, session_ref in (("codex", "sender"), ("claude-code", "target")):
                assert client.post("/relay/turn", json={"runtime": runtime, "session_ref": session_ref, "container_ref": "c"}).status_code == 200
            sent = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender", "recipient": "claude-code:target", "container_ref": "c", "payload": "expiring", "expires_in_seconds": 60}).json()
            storage = app.state.pallium_service._storage
            with storage._relay_session_factory() as session:
                session.execute(text("UPDATE relay_messages SET expires_at=:past WHERE id=:id"), {"past": datetime.now(timezone.utc) - timedelta(seconds=1), "id": sent["message_id"]})
                session.commit()
            expired = client.get("/dashboard/api/relay/messages", params={"delivery_state": "expired"}).json()
            assert expired["total"] == 1 and expired["messages"][0]["deliveries"][0]["state"] == "expired"
            assert client.get("/dashboard/api/relay/messages", params={"delivery_state": "pending"}).json()["total"] == 0
            with storage._relay_session_factory() as session:
                assert session.scalar(text("SELECT state FROM relay_deliveries WHERE message_id=:id"), {"id": sent["message_id"]}) == "pending"
            assert client.get("/dashboard/api/relay/messages", params={"until": "2026-09-07T12:00:00", "since": "2026-09-07T11:00:00"}).status_code == 200
            future_utc = datetime.now(timezone.utc) + timedelta(minutes=5)
            future_offset = future_utc.astimezone(timezone(timedelta(hours=2)))
            utc_bound = client.get("/dashboard/api/relay/messages", params={"until": future_utc.isoformat()}).json()
            offset_bound = client.get("/dashboard/api/relay/messages", params={"until": future_offset.isoformat()}).json()
            assert [item["id"] for item in utc_bound["messages"]] == [sent["message_id"]]
            assert [item["id"] for item in offset_bound["messages"]] == [sent["message_id"]]
            assert client.get("/dashboard/api/relay/messages", params={"before_created_at": "2026-09-07T12:00:00", "before_id": "x"}).status_code == 200

    def test_relay_fixed_window_excludes_concurrent_insert(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            for runtime, session_ref in (("codex", "sender"), ("claude-code", "target")):
                client.post("/relay/turn", json={"runtime": runtime, "session_ref": session_ref, "container_ref": "c"})
            first_id = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender", "recipient": "claude-code:target", "container_ref": "c", "payload": "first"}).json()["message_id"]
            second_id = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender", "recipient": "claude-code:target", "container_ref": "c", "payload": "second"}).json()["message_id"]
            first = client.get("/dashboard/api/relay/messages", params={"limit": 1}).json()
            inserted_id = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender", "recipient": "claude-code:target", "container_ref": "c", "payload": "new"}).json()["message_id"]
            second = client.get("/dashboard/api/relay/messages", params={"limit": 1, "until": first["until"], "before_created_at": first["next_before_created_at"], "before_id": first["next_before_id"]}).json()
        assert first["messages"][0]["id"] == second_id
        assert second["messages"][0]["id"] == first_id
        assert inserted_id not in {first["messages"][0]["id"], second["messages"][0]["id"]}

class TestDashboardRelayOverview:
    def test_overview_owner_allowlist_facets_and_read_only_split_store(self, tmp_path: Path) -> None:
        app = create_app(replace(_test_config(tmp_path), relay_sqlite_url=f"sqlite:///{tmp_path / 'relay-overview.db'}"))
        now = datetime.now(timezone.utc)
        with TestClient(app) as client:
            for runtime, session_ref, container, actor in (
                ("codex", "same-native", "git:alpha", "owner-a"),
                ("claude-code", "same-native", "git:alpha", "owner-b"),
                ("codex", "dormant", "git:zeta", "owner-a"),
                ("codex", "recent-unreachable", "git:omega", "owner-a"),
                ("opencode", "closed", "git:東京", "owner-a"),
            ):
                assert client.post("/relay/turn", json={"runtime": runtime, "session_ref": session_ref,
                    "container_ref": container, "actor_ref": actor}).status_code == 200
            sent = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "same-native",
                "recipient": "opencode:closed", "container_ref": "git:alpha", "actor_ref": "owner-a",
                "payload": "overview-secret"}).json()
            storage = app.state.pallium_service._storage
            with storage._relay_session_factory() as session:
                rows = {row.session_ref: row for row in session.query(RelaySessionRecord).filter_by(actor_ref="owner-a")}
                rows["dormant"].last_seen_at = now - timedelta(days=2)
                rows["dormant"].state = "unreachable"
                rows["recent-unreachable"].state = "unreachable"
                rows["closed"].state = "closed"
                session.add(RelayDeliveryRecord(id="fanout-overview", message_id=sent["message_id"], recipient_runtime="codex",
                    recipient_session_ref="same-native", recipient_endpoint_id=rows["same-native"].id,
                    recipient_container_ref="git:alpha", state="pending", attempts=0))
                session.commit()
                before = [(row.id, row.state, row.last_seen_at) for row in session.query(RelaySessionRecord).all()]
            overview = client.get("/dashboard/api/relay/overview").json()
            assert set(overview) == {"as_of", "owners", "offset", "limit", "has_more", "next_offset"}
            owner = next(row for row in overview["owners"] if row["actor_ref"] == "owner-a")
            assert set(owner) == {"actor_ref", "session_count", "message_count", "last_seen_at", "last_message_at", "active_session_count", "recent_session_count", "dormant_session_count", "closed_session_count", "unreachable_session_count"}
            assert owner["message_count"] == 1 and "overview-secret" not in str(overview) and "git:alpha" not in str(overview)
            assert owner["active_session_count"] == 1 and owner["recent_session_count"] == 2 and owner["unreachable_session_count"] == 2
            selected = client.get("/dashboard/api/relay/overview", params={"actor_ref": "owner-a", "limit": 1}).json()
            assert selected["owner"]["session_count"] == 4 and selected["owner"]["message_count"] == 1
            assert selected["owner"]["active_session_count"] == 1 and selected["containers"][0]["container_ref"] == "git:alpha"
            assert selected["has_more"] is True and selected["next_offset"] == 1
            next_page = client.get("/dashboard/api/relay/overview", params={"actor_ref": "owner-a", "limit": 1, "offset": 1}).json()
            assert next_page["containers"][0]["container_ref"] != selected["containers"][0]["container_ref"]
            search = client.get("/dashboard/api/relay/overview", params={"actor_ref": "owner-a", "container_search": "東京"}).json()
            assert [row["container_ref"] for row in search["containers"]] == ["git:東京"]
            unicode_facet = search["containers"][0]
            assert unicode_facet["closed_session_count"] == 1 and unicode_facet["unreachable_session_count"] == 0
            dormant = next(row for row in client.get("/dashboard/api/relay/overview", params={"actor_ref": "owner-a"}).json()["containers"] if row["container_ref"] == "git:zeta")
            assert dormant["dormant_session_count"] == 1 and dormant["unreachable_session_count"] == 1
            unknown = client.get("/dashboard/api/relay/overview", params={"actor_ref": "unknown"}).json()
            assert unknown["owner"]["session_count"] == unknown["owner"]["message_count"] == 0 and unknown["containers"] == []
            assert client.get("/dashboard/api/relay/overview?actor_ref=").status_code == 422
            assert client.get("/dashboard/api/relay/overview?limit=201").status_code == 422
            assert client.get("/dashboard/api/relay/overview?limit=200").status_code == 200
            assert client.get("/dashboard/api/relay/sessions").status_code == 422
            assert client.get("/dashboard/api/relay/messages?actor_ref=").status_code == 422
            client.get("/dashboard/api/relay/overview", params={"actor_ref": "owner-a"})
            with storage._relay_session_factory() as session:
                after = [(row.id, row.state, row.last_seen_at) for row in session.query(RelaySessionRecord).all()]
            normalize = lambda value: value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
            assert [(row_id, state, normalize(last_seen_at)) for row_id, state, last_seen_at in before] == [(row_id, state, normalize(last_seen_at)) for row_id, state, last_seen_at in after]

    def test_overview_container_ties_are_deterministic(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        at = datetime.now(timezone.utc)
        with TestClient(app) as client:
            for container in ("git:tie-b", "git:tie-a"):
                assert client.post("/relay/turn", json={"runtime": "codex", "session_ref": "same", "container_ref": container, "actor_ref": "ties"}).status_code == 200
            storage = app.state.pallium_service._storage
            with storage._relay_session_factory() as session:
                session.execute(text("UPDATE relay_sessions SET last_seen_at=:at WHERE actor_ref='ties'"), {"at": at})
                session.commit()
            first = client.get("/dashboard/api/relay/overview", params={"actor_ref": "ties", "limit": 1}).json()
            second = client.get("/dashboard/api/relay/overview", params={"actor_ref": "ties", "limit": 1, "offset": 1}).json()
        assert first["containers"][0]["container_ref"] == "git:tie-a"
        assert second["containers"][0]["container_ref"] == "git:tie-b"
