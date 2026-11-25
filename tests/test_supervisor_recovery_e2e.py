"""Real-loopback regression for readiness attributed to the wrong API process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.supervisor import _wait_for_api


def test_replacement_cannot_borrow_existing_listener_readiness(tmp_path):
    """A candidate whose bind failed must not borrow the old listener's health."""
    received = []
    terminal = False

    class ExistingAPI(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(list(self.headers.items()))
            health = (
                {"status": "failed", "initialized": False, "ready": False,
                 "initialization_error": "service_initialization_failed"} if terminal
                else {"status": "ok", "initialized": True, "ready": True}
            )
            body = json.dumps(health).encode()
            self.send_response(503 if terminal else 200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    listener = ThreadingHTTPServer(("127.0.0.1", 0), ExistingAPI)
    thread = threading.Thread(target=listener.serve_forever, daemon=True)
    thread.start()
    home = tmp_path / "isolated-home"
    run_dir = home / "run"
    run_dir.mkdir(parents=True)
    token_path = run_dir / "api_token"
    token_path.write_text(json.dumps({"nonce": "previous-launch", "pid": os.getpid()}))
    release = tmp_path / "release-constructor"
    entered = tmp_path / "constructor-entered"
    # Only construction is replaced. Real app.main.app lifespan, token writing,
    # Uvicorn bind failure/shutdown, and supervisor TCP/HTTP probes all run.
    child = """
import os, time
from pathlib import Path
from fastapi import FastAPI
from app import main
from app.run import _serve
def held_constructor(**kwargs):
    Path(os.environ["TEST_ENTERED"]).touch()
    deadline = time.monotonic() + 20
    while not Path(os.environ["TEST_RELEASE"]).exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("isolated constructor barrier timed out")
        time.sleep(.01)
    return FastAPI()
main.create_app = held_constructor
_serve(host="127.0.0.1", port=int(os.environ["TEST_PORT"]), reload=False)
"""
    env = {key: value for key, value in os.environ.items() if not key.startswith("PALLIUM_")}
    env.update(
        PALLIUM_HOME=str(home), PALLIUM_API_LAUNCH_TOKEN="replacement-launch",
        PALLIUM_CONFIG_FILE=str(tmp_path / "absent.toml"),
        PALLIUM_ENV_FILE=str(tmp_path / "absent.env"),
        WEB_CONCURRENCY="1", TEST_PORT=str(listener.server_port),
        TEST_ENTERED=str(entered), TEST_RELEASE=str(release),
    )
    process = None
    log_path = tmp_path / "replacement.log"
    try:
        with log_path.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                [sys.executable, "-c", child], cwd=Path(__file__).resolve().parents[1],
                env=env, stdout=output, stderr=subprocess.STDOUT,
            )
            deadline = time.monotonic() + 15
            while True:
                log = log_path.read_text(encoding="utf-8")
                if entered.exists() and "error while attempting to bind" in log:
                    break
                assert process.poll() is None, log
                assert time.monotonic() < deadline, log
                time.sleep(.01)
            token = json.loads(token_path.read_text())
            assert token == {"pid": process.pid}
            assert process.pid != os.getpid()
            assert process.poll() is None
            for receipt in (json.dumps({**token, "nonce": "replacement-launch"}), None, "bad JSON"):
                if receipt is None:
                    token_path.unlink()
                else:
                    token_path.write_text(receipt)
                for terminal in (False, True):
                    elapsed = [0.0]
                    assert not _wait_for_api(
                        "127.0.0.1", listener.server_port, timeout=1,
                        process=process, expected_nonce="replacement-launch",
                        sleep_fn=lambda delay: elapsed.__setitem__(0, elapsed[0] + delay),
                        clock=lambda: elapsed[0],
                    ), "replacement with failed bind borrowed the previous listener's HTTP health"
                    assert elapsed == [1.0], "the old listener must not trigger terminal fail-fast"
            assert len(received) == 12 and "replacement-launch" not in str(received)
            assert "replacement-launch" not in log_path.read_text(encoding="utf-8")
    finally:
        release.touch()
        if process is not None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            assert process.poll() is not None
        listener.shutdown()
        listener.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
