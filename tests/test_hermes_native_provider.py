"""Pure checks for the isolated built-in OpenAI-compatible provider proof."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.fixtures import hermes_tui_driver as driver


def _provider_env(base_url="http://127.0.0.1:43127/v1"):
    env = {"PALLIUM_TUI_ALLOWED_ENDPOINTS": json.dumps([["127.0.0.1", 43127]])}
    env.update(driver.synthetic_openai_environment(base_url))
    return env


def test_synthetic_openai_environment_is_exact_loopback_and_allowlisted():
    driver.assert_synthetic_openai_environment(_provider_env(), "http://127.0.0.1:43127/v1")
    driver.assert_synthetic_openai_environment({"PALLIUM_TUI_ALLOWED_ENDPOINTS": "[]"})
    with pytest.raises(AssertionError, match="owned provider"):
        driver.assert_synthetic_openai_environment(_provider_env(), "http://127.0.0.1:43128/v1")
    for url in ("http://localhost:43127/v1", "https://127.0.0.1:43127/v1",
                "http://127.0.0.1:43127/other", "http://127.0.0.1:43127/v1?x=1"):
        with pytest.raises(AssertionError):
            driver.synthetic_openai_environment(url)


def test_synthetic_openai_request_records_only_route_model_and_auth_match():
    body = {"model": "pallium-local"}
    valid = driver.synthetic_openai_request_evidence(
        "/v1/chat/completions", body, f"Bearer {driver.SYNTHETIC_OPENAI_API_KEY}")
    assert valid == {"path": "/v1/chat/completions", "model": "pallium-local", "auth_matched": True}
    invalid_auth = driver.synthetic_openai_request_evidence(
        "/v1/chat/completions", body, "Bearer not-the-synthetic-key")
    assert invalid_auth["auth_matched"] is False
    with pytest.raises(AssertionError, match="route"):
        driver.synthetic_openai_request_evidence("/v1/responses", body, None)
    with pytest.raises(AssertionError, match="model"):
        driver.synthetic_openai_request_evidence("/v1/chat/completions", {"model": "other"}, None)


def test_environment_rejects_partial_or_unexpected_openai_values_and_keeps_windows_contract(tmp_path, monkeypatch):
    with pytest.raises(AssertionError, match="selected together"):
        driver.assert_synthetic_openai_environment({"OPENAI_API_KEY": driver.SYNTHETIC_OPENAI_API_KEY})
    unexpected = _provider_env()
    unexpected["OPENAI_API_KEY"] = "inherited-real-key"
    with pytest.raises(AssertionError, match="unexpected OpenAI credential"):
        driver.assert_synthetic_openai_environment(unexpected)

    home = tmp_path / "user-profile"
    windows_env = {
        "HOME": str(home), "USERPROFILE": str(home),
        "APPDATA": str(home / "AppData" / "Roaming"), "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "TEMP": str(home / "Temp"), "TMP": str(home / "Temp"),
        "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CACHE_HOME": str(home / ".cache"), "XDG_STATE_HOME": str(home / ".local" / "state"),
        "HERMES_HOME": str(home / ".hermes"), "HERMES_MANAGED_DIR": str(home / "managed-empty"),
    }
    monkeypatch.setattr(driver, "os", SimpleNamespace(name="nt"))
    driver.assert_isolated_env(windows_env, home)
    with pytest.raises(AssertionError):
        driver.assert_isolated_env({**windows_env, "OPENAI_API_KEY": "unexpected"}, home)
