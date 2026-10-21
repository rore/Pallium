"""Pure checks for the Linux TUI's contained Hermes state directory."""
from pathlib import Path
from types import SimpleNamespace

import pytest

import tests.fixtures.hermes_tui_driver as driver


def _profile_env(home: Path) -> dict[str, str]:
    return {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": str(home / "Temp"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "HERMES_HOME": str(home / "hermes-profile"),
        "HERMES_MANAGED_DIR": str(home / "managed-empty"),
    }


def test_linux_profile_uses_contained_nondefault_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setattr(driver, "os", SimpleNamespace(name="posix"))
    home = tmp_path / "fresh-profile"
    env = _profile_env(home)

    driver.assert_isolated_env(env, home)

    profile = Path(env["HERMES_HOME"]).resolve()
    assert profile == (home / "hermes-profile").resolve()
    assert (profile / "state.db").resolve().is_relative_to(home.resolve())
    assert not profile.is_relative_to((home / ".hermes").resolve())


@pytest.mark.parametrize(
    "change",
    [
        lambda env, home: env.update(HERMES_HOME=str(home / ".hermes")),
        lambda env, home: env.update(HERMES_HOME=str(home.parent / "escaped-profile")),
        lambda env, _home: env.update(HERMES_STATE_DB_GUARD_BYPASS="1"),
    ],
    ids=["platform-default-collision", "escaped-profile", "guard-bypass"],
)
def test_linux_profile_rejects_default_escape_and_guard_bypass(tmp_path, monkeypatch, change):
    monkeypatch.setattr(driver, "os", SimpleNamespace(name="posix"))
    home = tmp_path / "fresh-profile"
    env = _profile_env(home)
    change(env, home)

    with pytest.raises(AssertionError):
        driver.assert_isolated_env(env, home)
