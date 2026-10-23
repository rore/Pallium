from __future__ import annotations

import copy
import errno
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import shutil
import sys
from types import ModuleType

import pytest

from app.cli import setup_hermes


PLUGIN = setup_hermes.PLUGIN_ID
SETTINGS = {
    "service_url": "http://127.0.0.1:29999",
    "container_ref": "git:example.test/team/hermes-e2e",
    "mcp_python": str(Path(sys.executable).resolve()),
    "mcp_repo": "C:/disposable/Pallium",
    "actor_ref": "hermes-test",
    "visibility": "private",
}


def _config() -> dict:
    return {
        "plugins": {"enabled": ["user-plugin"], "entries": {"user-plugin": {"settings": {"keep": "me"}}}},
        "platform_toolsets": {"cli": ["hermes-cli", "custom-tools"]},
        "tools": {"tool_search": {"enabled": "auto"}, "other": {"keep": True}},
        "model": {"default": "ordinary-model", "provider": "anthropic",
                  "base_url": "https://api.example.test/v1", "api_mode": "anthropic_messages",
                  "api_key": "leave-this-alone"},
        "fallback_providers": ["backup-provider"],
        "fallback_model": "backup-model",
        "unrelated": {"nested": {"value": "preserved"}},
    }


def _install_fake_hermes(monkeypatch, home: Path):
    state = {"config": _config(), "raw": b"# preserve formatting and secrets\n"}
    config_path = home / "config.yaml"
    home.mkdir(parents=True, exist_ok=True)
    config_path.write_bytes(state["raw"])

    def digest():
        return hashlib.sha256(config_path.read_bytes()).hexdigest()

    def invoke(_python, _home, action, request=None):
        request = request or {}
        config = state["config"]
        plugins = config.get("plugins", {})
        enabled = plugins.get("enabled", [])
        entries = plugins.get("entries", {})
        entry = entries.get(PLUGIN)
        if action in {"validate", "install"}:
            assert enabled.count(PLUGIN) <= 1
        if action in {"validate", "status"}:
            return {"ok": True, "config_sha256": digest(), "enabled_present": "enabled" in plugins,
                    "enabled": copy.deepcopy(enabled), "entry": copy.deepcopy(entry), "mcp_version": "2.0.0"}
        assert request["expected_sha256"] == digest()
        old = request.get("old_settings")
        if entry is not None:
            assert entry["settings"] == old
        if action == "install":
            if request.get("enable_plugin") and PLUGIN not in enabled:
                plugins["enabled"] = [*enabled, PLUGIN]
            entries[PLUGIN] = {"allow_gateway_injection": True, "settings": copy.deepcopy(request["settings"])}
            config_path.write_bytes(b"# preserve formatting and secrets\n# public writer updated owned keys\n")
        else:
            remaining = [item for item in enabled if item != PLUGIN]
            baseline = request.get("enabled_before", {})
            expected = list(baseline.get("value", [])) if baseline.get("present") else []
            if PLUGIN not in expected:
                expected.append(PLUGIN)
            if enabled == expected:
                if baseline.get("present"):
                    plugins["enabled"] = copy.deepcopy(baseline.get("value", []))
                else:
                    plugins.pop("enabled", None)
            elif remaining or request.get("enabled_present"):
                plugins["enabled"] = remaining
            else:
                plugins.pop("enabled", None)
            entries.pop(PLUGIN)
            config_path.write_bytes(b"# preserve formatting and secrets\n# public writer removed owned keys\n")
        return {"ok": True, "config_sha256": digest()}

    monkeypatch.setattr(setup_hermes, "_run_hermes", invoke)
    monkeypatch.setattr(setup_hermes, "_validate_pallium_mcp", lambda _python: None)
    return state, config_path


def _source(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    source = tmp_path / "source"
    (source / "skills" / "pallium-memory" / "references").mkdir(parents=True)
    (source / "plugin.yaml").write_text("name: pallium-hermes-relay\n", encoding="utf-8")
    (source / "__init__.py").write_text("# plugin\n", encoding="utf-8")
    (source / "mcp_bridge.py").write_text("# bridge\n", encoding="utf-8")
    skill = source / "skills" / "pallium-memory"
    (skill / "SKILL.md").write_text("# Pallium Relay\nשלום 🌍\n", encoding="utf-8")
    (skill / "references" / "guide.md").write_text("unicode reference\n", encoding="utf-8")
    repo = tmp_path / "Pallium"
    (repo / "app" / "mcp").mkdir(parents=True)
    (repo / "app" / "mcp" / "hermes.py").write_text("# adapter\n", encoding="utf-8")
    monkeypatch.setattr(setup_hermes, "_integration_dir", lambda: source)
    return source, repo


def _install_args(home: Path, repo: Path, *, hermes_python: Path | None = None) -> list[str]:
    return ["--home", str(home), "--hermes-python", str(hermes_python or Path(sys.executable)),
            "--service-url", SETTINGS["service_url"], "--container-ref", SETTINGS["container_ref"],
            "--actor-ref", SETTINGS["actor_ref"], "--visibility", SETTINGS["visibility"],
            "--mcp-python", sys.executable, "--mcp-repo", str(repo)]


def test_setup_status_repeat_and_remove_preserve_unrelated_profile(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    state, config_path = _install_fake_hermes(monkeypatch, home)
    _, repo = _source(tmp_path, monkeypatch)
    unrelated_file = home / "data" / "keep.json"
    unrelated_file.parent.mkdir()
    unrelated_file.write_text('{"keep": true}', encoding="utf-8")

    assert setup_hermes.main(_install_args(home, repo)) == 0
    plugin, skill = setup_hermes._profile_paths(home)
    assert (plugin / "mcp_bridge.py").is_file()
    assert (skill / "SKILL.md").read_text(encoding="utf-8").endswith("שלום 🌍\n")
    assert (skill / "references" / "guide.md").is_file()
    assert state["config"]["plugins"]["enabled"] == ["user-plugin", PLUGIN]
    assert state["config"]["plugins"]["entries"]["user-plugin"] == {"settings": {"keep": "me"}}
    assert state["config"]["model"]["api_key"] == "leave-this-alone"
    assert state["config"]["tools"]["tool_search"]["enabled"] == "auto"
    assert state["config"]["fallback_providers"] == ["backup-provider"]
    assert state["config"]["unrelated"]["nested"]["value"] == "preserved"
    before = {p: p.stat().st_mtime_ns for p in (plugin / "__init__.py", skill / "SKILL.md")}

    assert setup_hermes.main(_install_args(home, repo)) == 0
    assert {p: p.stat().st_mtime_ns for p in before} == before
    assert setup_hermes.main(["--home", str(home), "--hermes-python", sys.executable, "--status"]) == 0

    # A user-added enabled plugin and unrelated config edit survive package removal.
    state["config"]["plugins"]["enabled"].append("new-plugin")
    state["config"]["unrelated"]["after_install"] = "preserve"
    assert setup_hermes.main(["--home", str(home), "--hermes-python", sys.executable, "--uninstall"]) == 0
    assert not plugin.exists() and not skill.exists()
    assert state["config"]["plugins"]["enabled"] == ["user-plugin", "new-plugin"]
    assert "pallium-hermes-relay" not in state["config"]["plugins"]["entries"]
    assert state["config"]["plugins"]["entries"]["user-plugin"] == {"settings": {"keep": "me"}}
    assert state["config"]["unrelated"]["after_install"] == "preserve"
    assert state["config"]["model"]["api_key"] == "leave-this-alone"
    assert unrelated_file.read_text(encoding="utf-8") == '{"keep": true}'
    assert config_path.read_bytes().startswith(b"# preserve formatting")


def test_setup_accepts_existing_plugins_provider_and_default_tool_search(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    state, _config_path = _install_fake_hermes(monkeypatch, home)
    _, repo = _source(tmp_path, monkeypatch)
    plugin_dir, skill_dir = setup_hermes._profile_paths(home)
    assert setup_hermes.main(_install_args(home, repo)) == 0
    assert plugin_dir.exists() and skill_dir.exists()
    assert state["config"]["plugins"]["enabled"] == ["user-plugin", PLUGIN]
    assert state["config"]["tools"]["tool_search"]["enabled"] == "auto"
    assert state["config"]["model"]["provider"] == "anthropic"


def test_memory_opt_in_update_and_disable_preserve_profile(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    state, _ = _install_fake_hermes(monkeypatch, home)
    _, repo = _source(tmp_path, monkeypatch)
    original = copy.deepcopy(state["config"])
    args = _install_args(home, repo)
    assert setup_hermes.main(args) == 0
    settings = state["config"]["plugins"]["entries"][PLUGIN]["settings"]
    assert not settings.get("memory_enabled", False)
    assert setup_hermes.main([*args, "--memory-enabled"]) == 0
    assert state["config"]["plugins"]["entries"][PLUGIN]["settings"]["memory_enabled"] is True
    assert setup_hermes.main(args) == 0
    assert state["config"]["plugins"]["entries"][PLUGIN]["settings"]["memory_enabled"] is True
    assert setup_hermes.main([*args, "--memory-enabled"]) == 0
    assert setup_hermes.main([*args, "--no-memory-enabled"]) == 0
    assert not state["config"]["plugins"]["entries"][PLUGIN]["settings"].get("memory_enabled", False)
    for key in ("model", "tools", "platform_toolsets", "fallback_providers", "unrelated"):
        assert state["config"][key] == original[key]
    assert setup_hermes.main(["--home", str(home), "--hermes-python", sys.executable, "--uninstall"]) == 0
    assert state["config"]["plugins"] == original["plugins"]


def test_setup_removal_restores_absent_enabled_key(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    state, _config_path = _install_fake_hermes(monkeypatch, home)
    state["config"]["plugins"].pop("enabled")
    _, repo = _source(tmp_path, monkeypatch)

    assert setup_hermes.main(_install_args(home, repo)) == 0
    assert state["config"]["plugins"]["enabled"] == [PLUGIN]
    assert setup_hermes.uninstall(home, Path(sys.executable)) == 0
    assert "enabled" not in state["config"]["plugins"]


def test_unowned_collision_and_changed_owned_files_are_preserved(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    _install_fake_hermes(monkeypatch, home)
    _, repo = _source(tmp_path, monkeypatch)
    plugin_dir, skill_dir = setup_hermes._profile_paths(home)
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "user.txt").write_text("do not replace", encoding="utf-8")
    with pytest.raises(ValueError, match="unowned or unsafe"):
        setup_hermes.install(home, Path(sys.executable), SETTINGS["service_url"],
                             SETTINGS["container_ref"], SETTINGS["actor_ref"], "private",
                             Path(sys.executable), repo)
    assert (plugin_dir / "user.txt").read_text(encoding="utf-8") == "do not replace"
    shutil.rmtree(plugin_dir)

    assert setup_hermes.install(home, Path(sys.executable), SETTINGS["service_url"],
                                SETTINGS["container_ref"], SETTINGS["actor_ref"], "private",
                                Path(sys.executable), repo) == 0
    edited = skill_dir / "SKILL.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "user edit\n", encoding="utf-8")
    assert setup_hermes.uninstall(home, Path(sys.executable)) == 2
    assert "user edit" in edited.read_text(encoding="utf-8")
    assert plugin_dir.exists()


def test_owned_config_edit_blocks_removal_without_touching_files(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    state, _ = _install_fake_hermes(monkeypatch, home)
    _, repo = _source(tmp_path, monkeypatch)
    args = _install_args(home, repo)
    assert setup_hermes.main(args) == 0
    plugin_dir, skill_dir = setup_hermes._profile_paths(home)
    state["config"]["plugins"]["entries"][PLUGIN]["settings"]["actor_ref"] = "user-edit"
    assert setup_hermes.uninstall(home, Path(sys.executable)) == 2
    assert plugin_dir.exists() and skill_dir.exists()


def test_install_cas_refusal_rolls_back_files_without_clobbering_new_config(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    _state, config_path = _install_fake_hermes(monkeypatch, home)
    _, repo = _source(tmp_path, monkeypatch)
    newer = b"# newer user config after installer preflight\n"

    def fail_after_write(_python, _home, action, request=None):
        if action == "validate":
            return {"ok": True, "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                    "enabled_present": True, "enabled": [], "entry": None}
        config_path.write_bytes(newer)
        raise ValueError("Hermes profile refused the operation (config_changed_during_operation)")

    monkeypatch.setattr(setup_hermes, "_run_hermes", fail_after_write)
    with pytest.raises(RuntimeError, match="current config bytes were preserved"):
        setup_hermes.install(home, Path(sys.executable), SETTINGS["service_url"],
                             SETTINGS["container_ref"], SETTINGS["actor_ref"], "private",
                             Path(sys.executable), repo)
    plugin_dir, skill_dir = setup_hermes._profile_paths(home)
    assert not plugin_dir.exists() and not skill_dir.exists()
    assert config_path.read_bytes() == newer


def test_remove_rolls_back_owned_files_but_preserves_uncertain_config_bytes(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    _state, config_path = _install_fake_hermes(monkeypatch, home)
    _, repo = _source(tmp_path, monkeypatch)
    assert setup_hermes.main(_install_args(home, repo)) == 0
    plugin_dir, skill_dir = setup_hermes._profile_paths(home)
    original_skill = (skill_dir / "SKILL.md").read_bytes()
    marker = json.loads((plugin_dir / setup_hermes.MARKER).read_text(encoding="utf-8"))

    def fail_after_write(_python, _home, action, request=None):
        if action == "status":
            return {"ok": True, "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                    "enabled_present": True, "enabled": [PLUGIN],
                    "entry": {"allow_gateway_injection": True, "settings": marker["settings"]}}
        config_path.write_bytes(b"newer config observed during failed remove")
        raise ValueError("simulated remove writer failure")

    monkeypatch.setattr(setup_hermes, "_run_hermes", fail_after_write)
    assert setup_hermes.uninstall(home, Path(sys.executable)) == 2
    assert plugin_dir.exists() and skill_dir.exists()
    assert (skill_dir / "SKILL.md").read_bytes() == original_skill
    assert config_path.read_bytes() == b"newer config observed during failed remove"


def test_extra_owned_entry_key_blocks_reinstall_and_removal(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    state, _ = _install_fake_hermes(monkeypatch, home)
    _, repo = _source(tmp_path, monkeypatch)
    args = _install_args(home, repo)
    assert setup_hermes.main(args) == 0
    plugin_dir, skill_dir = setup_hermes._profile_paths(home)
    state["config"]["plugins"]["entries"][PLUGIN]["user_note"] = "preserve me"

    assert setup_hermes.main(args) == 2
    assert setup_hermes.uninstall(home, Path(sys.executable)) == 2
    assert plugin_dir.exists() and skill_dir.exists()
    assert state["config"]["plugins"]["entries"][PLUGIN]["user_note"] == "preserve me"


def test_user_disabled_owned_plugin_can_be_removed_without_reenabling_or_losing_list(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    state, _ = _install_fake_hermes(monkeypatch, home)
    _, repo = _source(tmp_path, monkeypatch)
    assert setup_hermes.main(_install_args(home, repo)) == 0
    plugin_dir, skill_dir = setup_hermes._profile_paths(home)
    state["config"]["plugins"]["enabled"] = []

    assert setup_hermes.status(home, Path(sys.executable)) == 0
    assert setup_hermes.uninstall(home, Path(sys.executable)) == 0
    assert not plugin_dir.exists() and not skill_dir.exists()
    assert state["config"]["plugins"]["enabled"] == []


def test_malformed_marker_and_profile_symlink_fail_closed(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    _install_fake_hermes(monkeypatch, home)
    plugin_dir, skill_dir = setup_hermes._profile_paths(home)
    plugin_dir.mkdir(parents=True)
    (plugin_dir / setup_hermes.MARKER).write_text("not-json", encoding="utf-8")
    assert setup_hermes.status(home, Path(sys.executable)) == 2
    assert (plugin_dir / setup_hermes.MARKER).read_text(encoding="utf-8") == "not-json"
    shutil.rmtree(plugin_dir)
    plugin_dir.parent.rmdir()

    target = tmp_path / "outside"
    target.mkdir()
    try:
        (home / "plugins").symlink_to(target, target_is_directory=True)
    except OSError as exc:
        if os.name == "nt" and (exc.errno in {errno.EACCES, errno.EPERM} or getattr(exc, "winerror", None) == 1314):
            pytest.skip("directory symlinks are unavailable on this Windows account")
        raise
    with pytest.raises(ValueError, match="symlink"):
        setup_hermes._profile_paths(home)


def test_setup_dispatch_routes_hermes_target(monkeypatch):
    from app import run as app_run

    seen = []
    monkeypatch.setattr(setup_hermes, "main", lambda args: seen.append(args) or 23)
    assert app_run.run(["setup", "hermes", "--home", "profile"]) == 23
    assert seen == [["--home", "profile"]]


def test_invalid_scope_and_visibility_refuse_before_writing(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    _install_fake_hermes(monkeypatch, home)
    _, repo = _source(tmp_path, monkeypatch)
    args = _install_args(home, repo)
    args[args.index("--service-url") + 1] = "https://relay.example"
    assert setup_hermes.main(args) == 2
    assert not setup_hermes._profile_paths(home)[0].exists()
    with pytest.raises(ValueError, match="private"):
        setup_hermes.install(home, Path(sys.executable), SETTINGS["service_url"],
                             SETTINGS["container_ref"], SETTINGS["actor_ref"], "global",
                             Path(sys.executable), repo)


@pytest.mark.parametrize("option,value", [
    ("--service-url", "http://127.0.0.1:29999/other"),
    ("--container-ref", "C:\\data"),
    ("--container-ref", "/var/data"),
])
def test_setup_rejects_adapter_incompatible_scope_before_mutation(tmp_path, monkeypatch, option, value):
    home = tmp_path / "hermes-home"
    _, config_path = _install_fake_hermes(monkeypatch, home)
    _, repo = _source(tmp_path, monkeypatch)
    original = config_path.read_bytes()
    args = _install_args(home, repo)
    args[args.index(option) + 1] = value
    assert setup_hermes.main(args) == 2
    assert config_path.read_bytes() == original
    assert not setup_hermes._profile_paths(home)[0].exists()


def test_setup_uses_common_canonical_container_scope(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    state, _ = _install_fake_hermes(monkeypatch, home)
    _, repo = _source(tmp_path, monkeypatch)
    args = _install_args(home, repo)
    args[args.index("--container-ref") + 1] = "git:github.com/Team/Project.git"
    assert setup_hermes.main(args) == 0
    settings = state["config"]["plugins"]["entries"][PLUGIN]["settings"]
    assert settings["container_ref"] == "git:github.com/team/project"


def test_normal_setup_uses_session_scope_and_preserves_profile_on_update(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    state, _ = _install_fake_hermes(monkeypatch, home)
    original = copy.deepcopy(state["config"])
    _, repo = _source(tmp_path, monkeypatch)
    args = ["--home", str(home), "--hermes-python", sys.executable,
            "--service-url", SETTINGS["service_url"], "--mcp-repo", str(repo)]
    assert setup_hermes.main([*args, "--memory-enabled"]) == 0
    settings = state["config"]["plugins"]["entries"][PLUGIN]["settings"]
    assert settings["scope_mode"] == "cwd"
    assert "container_ref" not in settings and "actor_ref" not in settings
    assert setup_hermes.main(args) == 0
    assert state["config"]["plugins"]["entries"][PLUGIN]["settings"]["memory_enabled"] is True
    assert setup_hermes.main([*args, "--no-memory-enabled"]) == 0
    assert not state["config"]["plugins"]["entries"][PLUGIN]["settings"].get("memory_enabled", False)
    assert setup_hermes.main(["--home", str(home), "--hermes-python", sys.executable, "--status"]) == 0
    assert setup_hermes.main(["--home", str(home), "--hermes-python", sys.executable, "--uninstall"]) == 0
    assert state["config"] == original


@pytest.mark.parametrize("error", ["hermes_session_cwd_api_required", "hermes_bound_session_key_api_required"])
def test_unsupported_session_scope_fails_before_install_mutation(tmp_path, monkeypatch, error):
    home = tmp_path / "hermes-home"
    state, config_path = _install_fake_hermes(monkeypatch, home)
    original, raw = copy.deepcopy(state), config_path.read_bytes()
    _, repo = _source(tmp_path, monkeypatch)
    original_run = setup_hermes._run_hermes

    def unsupported(python, profile, action, request=None):
        if action == "validate" and request.get("scope_mode") == "cwd":
            raise ValueError(error)
        return original_run(python, profile, action, request)

    monkeypatch.setattr(setup_hermes, "_run_hermes", unsupported)
    assert setup_hermes.main(["--home", str(home), "--hermes-python", sys.executable,
                             "--service-url", SETTINGS["service_url"], "--mcp-repo", str(repo)]) == 2
    assert state == original and config_path.read_bytes() == raw
    assert not any(p.exists() for p in setup_hermes._profile_paths(home))


@pytest.mark.parametrize("route_api", ["missing", "not-callable", "callable"])
def test_config_helper_checks_route_capability_without_reading_a_route(
    tmp_path, monkeypatch, capsys, route_api,
):
    import mcp.client.stdio

    path = tmp_path / "config.yaml"
    original = b"# unchanged profile\n"
    path.write_bytes(original)

    def forbidden(*args, **kwargs):
        raise AssertionError("validation must not invoke session accessors or write config")

    for name in ("hermes_cli", "gateway"):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    config = ModuleType("hermes_cli.config")
    config.get_config_path = lambda: path
    config.require_readable_config_before_write = lambda _path: {}
    config.atomic_config_write = config.atomic_config_replace = forbidden
    plugins = ModuleType("hermes_cli.plugins")
    plugins.PluginContext = type("PluginContext", (), {
        "session_cwd": forbidden, "session_surface": forbidden,
    })
    context = ModuleType("gateway.session_context")
    if route_api != "missing":
        context.bound_session_key = forbidden if route_api == "callable" else None
    for module in (config, plugins, context):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "2.0.0")
    monkeypatch.setattr(sys, "argv", ["qualification-helper", "validate"])
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"scope_mode":"cwd"}'))
    with pytest.raises(SystemExit) as stopped:
        exec(compile(setup_hermes._CONFIG_HELPER, "<config-helper>", "exec"), {})
    result = json.loads(capsys.readouterr().out)
    assert stopped.value.code == (0 if route_api == "callable" else 2)
    assert result["ok"] is (route_api == "callable")
    if route_api != "callable":
        assert result["error"] == "hermes_bound_session_key_api_required"
    assert path.read_bytes() == original and list(tmp_path.iterdir()) == [path]
