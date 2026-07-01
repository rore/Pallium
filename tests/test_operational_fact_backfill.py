"""W4 PR 3 — tests for the operational_fact backfill CLI.

Covers:
- run_dry_run report shape + histogram accuracy.
- Dry-run marker file creation and same-day discovery.
- CLI guard: --commit refuses without a marker.
- CLI guard: --commit refuses without --yes-i-ran-dry-run.
- --dry-run produces marker; --commit path is scaffolding (documented).
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.tools.operational_fact_backfill import (
    build_parser,
    find_today_dry_run_marker,
    main,
    run_dry_run,
    summarize_candidates,
    write_dry_run_marker,
)
from semantic.operational_fact import (
    CommandRecord,
    OperationalFactCandidate,
    TurnRecord,
    build_default_scope_resolver,
)


def _fake_scope_resolver(container_ref, artifact_path):
    if artifact_path and (
        (len(artifact_path) >= 2 and artifact_path[1] == ":")
        or artifact_path.startswith("/")
    ):
        return ("machine_repo", f"{container_ref}@machine:testhash")
    return ("repo", container_ref)


def _seed_uv_turn_stream() -> list[TurnRecord]:
    return [
        TurnRecord(
            turn_index=0,
            source_item_id="src-0",
            timestamp="2026-07-01T00:00:00Z",
            commands=(
                CommandRecord(cmd="uv sync ./pyproject.toml", exit_code=0),
            ),
        ),
        TurnRecord(
            turn_index=1,
            source_item_id="src-1",
            timestamp="2026-07-01T00:01:00Z",
            commands=(
                CommandRecord(cmd="uv run pytest ./pyproject.toml", exit_code=0),
            ),
        ),
    ]


class TestSummarizeCandidates:
    def test_empty_returns_zeros(self):
        s = summarize_candidates([])
        assert s == {"total": 0, "by_family": {}, "by_scope_kind": {}, "by_role": {}}

    def test_histogram_shape(self):
        cand = OperationalFactCandidate(
            command_family="uv",
            artifact_role="runner",
            scope_kind="repo",
            scope_ref="git:example/repo",
            subject="uv: pyproject.toml",
            artifact="./pyproject.toml",
            artifact_normalized="pyproject.toml",
            evidence=(),
        )
        s = summarize_candidates([cand, cand])
        assert s["total"] == 2
        assert s["by_family"] == {"uv": 2}
        assert s["by_scope_kind"] == {"repo": 2}
        assert s["by_role"] == {"runner": 2}


class TestRunDryRun:
    def test_zero_containers_zero_candidates(self):
        report = run_dry_run({}, scope_resolver=_fake_scope_resolver)
        assert report["containers_scanned"] == 0
        assert report["summary"]["total"] == 0

    def test_single_container_uv_derivation(self):
        turns = {"git:example/repo": _seed_uv_turn_stream()}
        report = run_dry_run(turns, scope_resolver=_fake_scope_resolver)
        assert report["containers_scanned"] == 1
        assert report["summary"]["total"] >= 1
        assert "uv" in report["summary"]["by_family"]

    def test_report_schema_version_pinned(self):
        report = run_dry_run({}, scope_resolver=_fake_scope_resolver)
        assert report["schema_version"] == "operational_fact_backfill.v1"

    def test_report_has_generated_at_iso8601(self):
        report = run_dry_run({}, scope_resolver=_fake_scope_resolver)
        # Round-trip parse — ISO 8601 with timezone.
        datetime.fromisoformat(report["generated_at"])

    def test_report_deterministic_over_two_runs(self):
        # generated_at differs, but the summary counts must be identical.
        turns = {"git:example/repo": _seed_uv_turn_stream()}
        a = run_dry_run(turns, scope_resolver=_fake_scope_resolver)
        b = run_dry_run(turns, scope_resolver=_fake_scope_resolver)
        assert a["summary"] == b["summary"]
        assert a["per_container"] == b["per_container"]


class TestMarkerFile:
    def test_write_marker_creates_dir_and_file(self, tmp_path):
        marker_dir = tmp_path / "backfill-markers"
        report = run_dry_run({}, scope_resolver=_fake_scope_resolver)
        path = write_dry_run_marker(report, marker_dir)
        assert path.exists()
        assert path.parent == marker_dir
        # Contents round-trip as JSON.
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["schema_version"] == "operational_fact_backfill.v1"

    def test_find_today_marker(self, tmp_path):
        marker_dir = tmp_path / "backfill-markers"
        report = run_dry_run({}, scope_resolver=_fake_scope_resolver)
        write_dry_run_marker(report, marker_dir)
        found = find_today_dry_run_marker(marker_dir)
        assert found is not None
        assert found.parent == marker_dir

    def test_find_returns_none_if_no_marker_dir(self, tmp_path):
        marker_dir = tmp_path / "does-not-exist"
        assert find_today_dry_run_marker(marker_dir) is None

    def test_find_returns_none_if_dir_empty(self, tmp_path):
        marker_dir = tmp_path / "empty"
        marker_dir.mkdir()
        assert find_today_dry_run_marker(marker_dir) is None


class TestParserMutuallyExclusive:
    def test_no_action_flags_errors(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_both_action_flags_errors(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--dry-run", "--commit"])


class TestCLI:
    def test_dry_run_produces_marker_and_zero_exit(self, tmp_path):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = main(["--dry-run", "--marker-dir", str(tmp_path)])
        assert rc == 0
        # Report is on stdout as JSON.
        report = json.loads(stdout.getvalue())
        assert report["schema_version"] == "operational_fact_backfill.v1"
        # Marker written to disk under the requested dir.
        found = find_today_dry_run_marker(tmp_path)
        assert found is not None
        # Stderr mentions marker path.
        assert "dry-run marker written" in stderr.getvalue()

    def test_commit_without_marker_refuses(self, tmp_path):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = main(["--commit", "--yes-i-ran-dry-run", "--marker-dir", str(tmp_path)])
        assert rc == 2
        assert "no same-day dry-run marker" in stderr.getvalue()

    def test_commit_without_ack_flag_refuses(self, tmp_path):
        # Seed a marker first via dry-run.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            main(["--dry-run", "--marker-dir", str(tmp_path)])
        # Now try commit without --yes-i-ran-dry-run.
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = main(["--commit", "--marker-dir", str(tmp_path)])
        assert rc == 2
        assert "--yes-i-ran-dry-run is required" in stderr.getvalue()

    def test_commit_with_marker_and_ack_zero_corpus(self, tmp_path):
        # Seed a marker.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            main(["--dry-run", "--marker-dir", str(tmp_path)])
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = main([
                "--commit", "--yes-i-ran-dry-run",
                "--marker-dir", str(tmp_path),
            ])
        # Corpus is empty (no fixture env var); commit is a no-op zero exit.
        assert rc == 0
        assert "no candidates to commit" in stderr.getvalue()

    def test_dry_run_with_fixture_env_derives(self, tmp_path, monkeypatch):
        fixture = {
            "git:example/repo": [
                {
                    "turn_index": 0,
                    "source_item_id": "src-0",
                    "timestamp": "2026-07-01T00:00:00Z",
                    "commands": [
                        {"cmd": "uv sync ./pyproject.toml", "exit_code": 0}
                    ],
                    "files_read": [],
                    "files_modified": [],
                    "grep_patterns": [],
                },
                {
                    "turn_index": 1,
                    "source_item_id": "src-1",
                    "timestamp": "2026-07-01T00:01:00Z",
                    "commands": [
                        {"cmd": "uv run pytest ./pyproject.toml", "exit_code": 0}
                    ],
                    "files_read": [],
                    "files_modified": [],
                    "grep_patterns": [],
                },
            ]
        }
        fixture_path = tmp_path / "fixture.json"
        fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
        monkeypatch.setenv("PALLIUM_BACKFILL_FIXTURE", str(fixture_path))
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            rc = main(["--dry-run", "--marker-dir", str(tmp_path)])
        assert rc == 0
        report = json.loads(stdout.getvalue())
        assert report["containers_scanned"] == 1
        assert report["summary"]["total"] >= 1
        assert "uv" in report["summary"]["by_family"]
