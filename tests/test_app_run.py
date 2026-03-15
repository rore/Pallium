from __future__ import annotations

from app import run as app_run


def test_run_default_invokes_supervisor_with_processors_and_cleaner(monkeypatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run_supervisor(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(app_run, "run_supervisor", fake_run_supervisor)

    exit_code = app_run.run(["--host", "127.0.0.1", "--port", "8010", "--processors", "2"])

    assert exit_code == 0
    assert captured["args"] == ["--host", "127.0.0.1", "--port", "8010", "--processors", "2", "--cleaners", "1"]


def test_run_processor_mode_invokes_processor(monkeypatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run_processor(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(app_run, "run_processor", fake_run_processor)

    exit_code = app_run.run(["processor", "--processor-id", "proc-1", "--once"])

    assert exit_code == 0
    assert captured["args"] == ["--processor-id", "proc-1", "--poll-interval-seconds", "1.0", "--once"]


def test_run_cleaner_mode_invokes_cleaner(monkeypatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run_cleaner(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(app_run, "run_cleaner", fake_run_cleaner)

    exit_code = app_run.run(["cleaner", "--cleaner-id", "cleaner-1", "--batch-size", "50", "--once"])

    assert exit_code == 0
    assert captured["args"] == ["--cleaner-id", "cleaner-1", "--batch-size", "50", "--once"]


def test_run_serve_mode_configures_timestamped_uvicorn_logging(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_uvicorn_run(app, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(app_run.uvicorn, "run", fake_uvicorn_run)

    exit_code = app_run.run(["serve", "--host", "127.0.0.1", "--port", "8011"])

    assert exit_code == 0
    assert captured["app"] == "app.main:app"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8011
    log_config = captured["log_config"]
    assert log_config["formatters"]["pallium_default"]["()"] == "app.runtime_logging.RuntimeLogFormatter"
    assert log_config["formatters"]["pallium_default"]["component"] == "api"
    assert log_config["loggers"]["uvicorn.error"]["handlers"] == ["default"]
    assert log_config["loggers"]["uvicorn.access"]["handlers"] == ["access"]