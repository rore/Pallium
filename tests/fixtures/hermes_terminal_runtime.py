"""Prepare a hash-pinned test observer only in the disposable Hermes venv."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from tests.fixtures.hermes_desktop_driver import contained_path, require_runner_gate


REQUIREMENT = "pyte==0.8.2 --hash=sha256:85db42a35798a5aafa96ac4d8da78b090b2c933248819157fc0e6f78876a0135\n"
PROBE = """import hashlib,importlib.metadata,importlib.util,json,pathlib,sys
info={'prefix':sys.prefix,'base_prefix':sys.base_prefix,'modules':{}}
for name in ('wcwidth','pyte'):
    spec=importlib.util.find_spec(name)
    if spec is None:
        info['modules'][name]=None
        continue
    dist=importlib.metadata.distribution(name)
    files={str(p):hashlib.sha256(pathlib.Path(dist.locate_file(p)).read_bytes()).hexdigest()
           for p in dist.files if p.parts[0]==name and p.suffix=='.py'}
    info['modules'][name]={'version':dist.version,'path':spec.origin,'files':files}
print(json.dumps(info))
"""


def prepare_terminal_runtime(python, source, home, artifacts, env):
    require_runner_gate(env, home, artifacts, source)
    python = Path(python)
    runner_temp = Path(env["RUNNER_TEMP"])
    contained_path(runner_temp, python)
    bootstrap_env = {key: env[key] for key in (
        "SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP",
        "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    ) if key in env}
    manifest = runner_temp / "hermes-terminal-observer.json"
    cache = runner_temp / "hermes-terminal-observer-cache"
    contained_path(runner_temp, manifest)
    contained_path(runner_temp, cache)
    requirements = Path(__file__).with_name("hermes_terminal_requirements.txt")
    assert requirements.read_text(encoding="utf-8") == REQUIREMENT, "observer requirement drift"

    def inspect():
        reply = subprocess.run([str(python), "-I", "-c", PROBE], env=bootstrap_env,
                               capture_output=True, text=True, timeout=20, check=True)
        info = json.loads(reply.stdout)
        prefix = Path(info["prefix"])
        assert prefix != Path(info["base_prefix"]), "observer target must be a venv"
        contained_path(runner_temp, prefix)
        assert python.resolve().is_relative_to(prefix.resolve()), "interpreter outside target venv"
        for name, module in info["modules"].items():
            if module is not None:
                contained_path(prefix, Path(module["path"]))
                assert module["version"] and module["files"], (name, module)
        assert info["modules"]["wcwidth"] is not None, "locked Hermes wcwidth is required"
        info["python_sha256"] = hashlib.sha256(python.read_bytes()).hexdigest()
        return info

    before = inspect()
    if manifest.exists():
        accepted = json.loads(manifest.read_text(encoding="utf-8"))
        assert accepted.get("state") == "ready", "prior observer preparation is unresolved"
        assert accepted["requirement"] == REQUIREMENT and accepted["runtime"] == before, "observer runtime drift"
        return accepted
    assert before["modules"]["pyte"] is None, "refusing unowned observer installation"
    pip_version = subprocess.run([sys.executable, "-I", "-m", "pip", "--version"],
        env=bootstrap_env, capture_output=True, text=True, timeout=20, check=True).stdout.strip()
    command = [sys.executable, "-I", "-m", "pip", "--isolated", "--disable-pip-version-check",
        "--python", str(python), "install", "--no-input", "--no-deps", "--only-binary=:all:",
        "--require-hashes", "--index-url", "https://pypi.org/simple", "--keyring-provider", "disabled",
        "--cache-dir", str(cache), "-r", str(requirements)]
    manifest.write_text(json.dumps({"state": "installing", "requirement": REQUIREMENT}), encoding="utf-8")
    subprocess.run(command, env=bootstrap_env, capture_output=True, text=True, timeout=120, check=True)
    after = inspect()
    assert after["modules"]["pyte"]["version"] == "0.8.2", after
    assert after["modules"]["wcwidth"] == before["modules"]["wcwidth"], "locked wcwidth changed"
    assert after["prefix"] == before["prefix"] and after["python_sha256"] == before["python_sha256"], after
    accepted = {"state": "ready", "requirement": REQUIREMENT, "pip_version": pip_version, "runtime": after}
    manifest.write_text(json.dumps(accepted, indent=2), encoding="utf-8")
    return accepted
