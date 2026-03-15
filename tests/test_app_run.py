from __future__ import annotations

from app import run as app_run


def test_run_default_invokes_supervisor_with_processors(monkeypatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run_supervisor(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(app_run, "run_supervisor", fake_run_supervisor)

    exit_code = app_run.run(["--host", "127.0.0.1", "--port", "8010", "--processors", "2"])

    assert exit_code == 0
    assert captured["args"] == ["--host", "127.0.0.1", "--port", "8010", "--processors", "2"]


def test_run_processor_mode_invokes_processor(monkeypatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run_processor(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(app_run, "run_processor", fake_run_processor)

    exit_code = app_run.run(["processor", "--processor-id", "proc-1", "--once"])

    assert exit_code == 0
    assert captured["args"] == ["--processor-id", "proc-1", "--poll-interval-seconds", "1.0", "--once"]
