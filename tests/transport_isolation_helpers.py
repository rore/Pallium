from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest


@pytest.fixture
def isolated_hook_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Keep hook profile state private and record any attempted urllib traffic."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    missing = object()
    previous_stop = sys.modules.get("integrations.codex.hooks.stop", missing)
    previous_common = sys.modules.get("codex_common", missing)
    hooks_package = sys.modules.get("integrations.codex.hooks")
    previous_stop_attr = getattr(hooks_package, "stop", missing)
    for module in {
        candidate
        for candidate in (
            previous_common,
            getattr(previous_stop, "_common", None),
        )
        if candidate is not missing and candidate is not None
    }:
        if hasattr(module, "STATE_DIR"):
            monkeypatch.setattr(
                module,
                "STATE_DIR",
                tmp_path / ".pallium" / "hooks" / "state",
            )
        if hasattr(module, "SESSIONS_DIR"):
            monkeypatch.setattr(
                module,
                "SESSIONS_DIR",
                tmp_path / ".pallium" / "hooks" / "state" / "sessions",
            )
    denied: list[str] = []

    def deny(operation: str):
        def blocked(*_args, **_kwargs):
            denied.append(operation)
            raise urllib.error.URLError("unexpected hook HTTP request")

        return blocked

    monkeypatch.setattr(urllib.request, "urlopen", deny("urlopen"))
    monkeypatch.setattr(
        urllib.request.OpenerDirector, "open", deny("OpenerDirector.open")
    )
    yield denied
    if previous_stop is missing:
        sys.modules.pop("integrations.codex.hooks.stop", None)
        package = sys.modules.get("integrations.codex.hooks")
        if package is not None and getattr(package, "stop", missing) is not previous_stop_attr:
            if previous_stop_attr is missing:
                delattr(package, "stop")
            else:
                package.stop = previous_stop_attr
    else:
        sys.modules["integrations.codex.hooks.stop"] = previous_stop
        if hooks_package is not None:
            if previous_stop_attr is missing:
                if hasattr(hooks_package, "stop"):
                    delattr(hooks_package, "stop")
            else:
                hooks_package.stop = previous_stop_attr
    if previous_common is missing:
        sys.modules.pop("codex_common", None)
    else:
        sys.modules["codex_common"] = previous_common
    assert denied == [], f"unexpected hook HTTP attempts: {denied}"
