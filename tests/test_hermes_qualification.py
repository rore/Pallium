import builtins
import hashlib
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from evals.hermes import qualification


def test_missing_source_fails_before_exec(tmp_path):
    with patch.object(builtins, "exec", side_effect=AssertionError("source executed")):
        with pytest.raises(qualification.SourceError, match="missing pinned source"):
            qualification.run_qualification(tmp_path)


def test_all_hashes_are_checked_before_any_source_exec(tmp_path, monkeypatch):
    registry = b"matching first source"
    middleware = b"mismatching second source"
    (tmp_path / "tools").mkdir()
    (tmp_path / "hermes_cli").mkdir()
    (tmp_path / "tools" / "registry.py").write_bytes(registry)
    (tmp_path / "hermes_cli" / "middleware.py").write_bytes(middleware)
    monkeypatch.setattr(qualification, "PINNED", {
        "tools/registry.py": hashlib.sha256(registry).hexdigest(),
        "hermes_cli/middleware.py": hashlib.sha256(b"different expected source").hexdigest(),
    })
    with patch.object(builtins, "exec", side_effect=AssertionError("source executed")):
        with pytest.raises(qualification.SourceError, match="hash mismatch for hermes_cli/middleware.py"):
            qualification.run_qualification(tmp_path)


@pytest.mark.parametrize("prior", [qualification._ABSENT, None, types.ModuleType("prior-hermes-fixture")])
def test_fixture_module_cleanup_on_return_and_exception(monkeypatch, prior):
    key = "hermes_cli.plugins"
    manager = qualification._FixtureManager()
    if prior is qualification._ABSENT:
        monkeypatch.delitem(sys.modules, key, raising=False)
    else:
        monkeypatch.setitem(sys.modules, key, prior)
    assert qualification._with_manager(manager, lambda: "ok") == "ok"
    assert sys.modules.get(key, qualification._ABSENT) is prior
    with pytest.raises(RuntimeError, match="callback failure"):
        qualification._with_manager(
            manager, lambda: (_ for _ in ()).throw(RuntimeError("callback failure"))
        )
    assert sys.modules.get(key, qualification._ABSENT) is prior
    assert manager.module_restored == [True, True]


def test_explicit_cached_release_source_runs_probe_when_supplied():
    source_root = os.environ.get("PALLIUM_HERMES_SOURCE_ROOT")
    if not source_root:
        pytest.skip("set PALLIUM_HERMES_SOURCE_ROOT to the cached exact-tag source tree")
    report = qualification.run_qualification(Path(source_root))
    assert report["evidence_level"] == "source_function_probe"
    assert report["qualified_host"] is False
    assert not report["failures"]
