from __future__ import annotations

from pathlib import Path

import pytest

from app.cli import setup_claude_code, setup_codex


RUNTIMES = ("codex", "claude-code")


def _write_skill_tree(root: Path, revision: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(f"managed skill {revision}\n", encoding="utf-8")
    nested = root / "references" / "深い"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "résumé 東京.md").write_bytes(f"revision={revision} café\n".encode())
    (root / "payload.bin").write_bytes(b"\x00\x80\xff\x00managed\x7f")
    (root / "empty directory").mkdir(exist_ok=True)


def _tree(root: Path) -> dict[Path, tuple[str, bytes | None]]:
    return {
        item.relative_to(root): ("directory", None) if item.is_dir()
        else ("file", item.read_bytes())
        for item in root.rglob("*")
    }


def _prepare(monkeypatch, tmp_path: Path, runtime: str):
    home = tmp_path / f"private home {runtime} 東京"
    home.mkdir()
    source = tmp_path / f"private skill source {runtime} café" / "pallium-memory"
    _write_skill_tree(source, "one")
    monkeypatch.setattr(Path, "home", lambda: home)

    if runtime == "codex":
        setup = setup_codex
        monkeypatch.setattr(setup, "_verify_service", lambda _port: False)
        monkeypatch.setattr(setup, "_codex_skill_src", lambda: source / "SKILL.md")
        monkeypatch.setattr(setup, "_codex_skill_dir", lambda: home / ".codex" / "skills" / "pallium-memory")
        installed = setup._codex_skill_dir()

        def run(*, uninstall: bool = False) -> int:
            return setup.main(["--uninstall"] if uninstall else ["--port", "19836"])
    else:
        setup = setup_claude_code
        monkeypatch.delenv("PALLIUM_CLAUDE_WAKE_DIR", raising=False)
        monkeypatch.setenv(
            "PALLIUM_RELAY_SQLITE_URL",
            f"sqlite:///{(home / '.pallium' / 'data' / 'relay.db').as_posix()}",
        )
        monkeypatch.setattr(setup, "_verify_service", lambda _port: False)
        monkeypatch.setattr(setup, "_register_mcp", lambda _port: None)
        monkeypatch.setattr(setup, "_unregister_mcp", lambda: None)
        monkeypatch.setattr(setup, "_claude_skill_src", lambda: source / "SKILL.md")
        monkeypatch.setattr(setup, "_claude_skill_dir", lambda: home / ".claude" / "skills" / "pallium-memory")
        installed = setup._claude_skill_dir()

        def run(*, uninstall: bool = False) -> int:
            args = ["claude-code"]
            if uninstall:
                args.append("--uninstall")
            return setup.main(args)

    return setup, source, installed, run


def _staging_dirs(installed: Path) -> list[Path]:
    return sorted(installed.parent.glob(".pallium-memory-*"))


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_setup_skill_create_replace_repeat_and_uninstall(
    monkeypatch, tmp_path: Path, runtime: str,
) -> None:
    _setup, source, installed, run = _prepare(monkeypatch, tmp_path, runtime)

    assert run() == 0
    first = _tree(source)
    assert _tree(installed) == first
    assert not _staging_dirs(installed)

    (installed / "SKILL.md").write_text("local edit", encoding="utf-8")
    (installed / "stale.txt").write_bytes(b"remove me")
    (installed / "payload.bin").unlink()
    _write_skill_tree(source, "two")
    second = _tree(source)
    assert run() == 0
    assert _tree(installed) == second
    assert not _staging_dirs(installed)

    assert run() == 0
    assert _tree(installed) == second
    assert not _staging_dirs(installed)
    assert run(uninstall=True) == 0
    assert not installed.exists()
    assert not _staging_dirs(installed)


@pytest.mark.parametrize(
    ("runtime", "had_previous"),
    [(runtime, had_previous) for runtime in RUNTIMES for had_previous in (False, True)],
    ids=("codex-first-install", "codex-replacement", "claude-code-first-install", "claude-code-replacement"),
)
def test_setup_skill_copy_failure_preserves_existing_tree_or_cleans_first_install(
    monkeypatch, tmp_path: Path, runtime: str, had_previous: bool,
) -> None:
    setup, source, installed, run = _prepare(monkeypatch, tmp_path, runtime)
    if had_previous:
        assert run() == 0
    old_tree = _tree(installed) if had_previous else None
    _write_skill_tree(source, "replacement")
    error = OSError("controlled copy failure")
    real_copytree = setup.shutil.copytree

    def fail_copytree(src, dst, *args, **kwargs):
        if Path(src) == source:
            raise error
        return real_copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(setup.shutil, "copytree", fail_copytree)
    with pytest.raises(OSError) as failure:
        run()
    assert failure.value is error
    if had_previous:
        assert _tree(installed) == old_tree
    else:
        assert not installed.exists()
    assert not _staging_dirs(installed)


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_setup_skill_backup_move_failure_retains_stage_without_moving_old_tree(
    monkeypatch, tmp_path: Path, runtime: str,
) -> None:
    setup, source, installed, run = _prepare(monkeypatch, tmp_path, runtime)
    assert run() == 0
    old_tree = _tree(installed)
    _write_skill_tree(source, "replacement")
    error = OSError("controlled backup move failure")
    real_rename = Path.rename
    containers: list[Path] = []

    def fail_backup(path: Path, target: Path) -> Path:
        if path == installed and target.name == "previous":
            containers.append(target.parent)
            raise error
        return real_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_backup)
    with pytest.raises(OSError) as failure:
        run()
    assert failure.value is error
    container, = containers
    assert _tree(installed) == old_tree
    assert not (container / "previous").exists()
    assert _tree(container / "skill") == _tree(source)
    notes = "\n".join(failure.value.__notes__)
    assert container.is_dir() and str(container) in notes
    assert "Previous installation retained" not in notes
    assert _staging_dirs(installed) == [container]


@pytest.mark.parametrize(
    ("runtime", "had_previous"),
    [(runtime, had_previous) for runtime in RUNTIMES for had_previous in (False, True)],
    ids=("codex-first-install", "codex-replacement", "claude-code-first-install", "claude-code-replacement"),
)
def test_setup_skill_activation_failure_cleans_or_restores(
    monkeypatch, tmp_path: Path, runtime: str, had_previous: bool,
) -> None:
    setup, source, installed, run = _prepare(monkeypatch, tmp_path, runtime)
    if had_previous:
        assert run() == 0
    old_tree = _tree(installed) if had_previous else None
    _write_skill_tree(source, "replacement")
    error = OSError("controlled activation failure")
    real_rename = Path.rename
    containers: list[Path] = []

    def fail_activation(path: Path, target: Path) -> Path:
        if path.name == "skill" and target == installed:
            containers.append(path.parent)
            raise error
        return real_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_activation)
    with pytest.raises(OSError) as failure:
        run()
    assert failure.value is error
    if had_previous:
        assert _tree(installed) == old_tree
    else:
        assert not installed.exists()
    container, = containers
    assert not container.exists()
    assert not _staging_dirs(installed)


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_setup_skill_restore_failure_retains_exact_previous_tree_and_errors(
    monkeypatch, tmp_path: Path, runtime: str,
) -> None:
    setup, source, installed, run = _prepare(monkeypatch, tmp_path, runtime)
    assert run() == 0
    old_tree = _tree(installed)
    _write_skill_tree(source, "replacement")
    activation_error = OSError("controlled activation failure")
    restore_error = OSError("controlled restoration failure")
    real_rename = Path.rename
    container: Path | None = None
    restore_attempts = []

    def fail_activation_and_restore(path: Path, target: Path) -> Path:
        nonlocal container
        if path.name == "skill" and target == installed:
            container = path.parent
            raise activation_error
        if path.name == "previous" and target == installed:
            restore_attempts.append(path)
            raise restore_error
        return real_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_activation_and_restore)
    with pytest.raises(OSError) as failure:
        run()
    assert failure.value is activation_error
    assert failure.value.__cause__ is restore_error
    assert repr(restore_error) in "\n".join(failure.value.__notes__)
    retained, = restore_attempts
    assert container is not None
    assert retained == container / "previous"
    assert _tree(retained) == old_tree
    assert not installed.exists()
    notes = "\n".join(failure.value.__notes__)
    assert str(retained) in notes and str(container) in notes
    assert _staging_dirs(installed) == [container]


@pytest.mark.parametrize(
    ("runtime", "had_previous"),
    [(runtime, had_previous) for runtime in RUNTIMES for had_previous in (False, True)],
    ids=("codex-first-install", "codex-replacement", "claude-code-first-install", "claude-code-replacement"),
)
def test_setup_skill_primary_failure_survives_cleanup_failure(
    monkeypatch, tmp_path: Path, runtime: str, had_previous: bool,
) -> None:
    setup, source, installed, run = _prepare(monkeypatch, tmp_path, runtime)
    if had_previous:
        assert run() == 0
    old_tree = _tree(installed) if had_previous else None
    _write_skill_tree(source, "replacement")
    activation_error = OSError("controlled activation failure")
    cleanup_error = PermissionError("controlled cleanup failure")
    real_rename, real_rmtree = Path.rename, setup.shutil.rmtree
    containers: list[Path] = []

    def fail_activation(path: Path, target: Path) -> Path:
        if path.name == "skill" and target == installed:
            containers.append(path.parent)
            raise activation_error
        return real_rename(path, target)

    def fail_cleanup(path, *args, **kwargs):
        candidate = Path(path)
        if candidate.parent == installed.parent and candidate.name.startswith(".pallium-memory-"):
            containers.append(candidate)
            raise cleanup_error
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(Path, "rename", fail_activation)
    monkeypatch.setattr(setup.shutil, "rmtree", fail_cleanup)
    with pytest.raises(OSError) as failure:
        run()
    assert failure.value is activation_error
    assert failure.value.__cause__ is None
    container, = set(containers)
    assert _tree(container / "skill") == _tree(source)
    if had_previous:
        assert _tree(installed) == old_tree
    else:
        assert not installed.exists()
    notes = "\n".join(failure.value.__notes__)
    assert str(container) in notes and repr(cleanup_error) in notes
    assert _staging_dirs(installed) == [container]


@pytest.mark.parametrize(
    ("runtime", "had_previous"),
    [(runtime, had_previous) for runtime in RUNTIMES for had_previous in (False, True)],
    ids=("codex-first-install", "codex-replacement", "claude-code-first-install", "claude-code-replacement"),
)
def test_setup_skill_success_surfaces_cleanup_failure(
    monkeypatch, tmp_path: Path, runtime: str, had_previous: bool,
) -> None:
    setup, source, installed, run = _prepare(monkeypatch, tmp_path, runtime)
    if had_previous:
        assert run() == 0
    old_tree = _tree(installed) if had_previous else None
    if had_previous:
        _write_skill_tree(source, "replacement")
    cleanup_error = PermissionError("controlled cleanup failure")
    real_rmtree = setup.shutil.rmtree
    containers: list[Path] = []

    def fail_cleanup(path, *args, **kwargs):
        candidate = Path(path)
        if candidate.parent == installed.parent and candidate.name.startswith(".pallium-memory-"):
            containers.append(candidate)
            raise cleanup_error
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(setup.shutil, "rmtree", fail_cleanup)
    with pytest.raises(PermissionError) as failure:
        run()
    assert failure.value is cleanup_error
    container, = containers
    assert _tree(installed) == _tree(source)
    assert container.is_dir()
    assert str(container) in "\n".join(failure.value.__notes__)
    if had_previous:
        assert _tree(container / "previous") == old_tree
    else:
        assert not (container / "previous").exists()
    assert _staging_dirs(installed) == [container]


@pytest.mark.parametrize(
    ("runtime", "stage"),
    [(runtime, stage) for runtime in RUNTIMES for stage in ("backup", "activation", "restore")],
    ids=("codex-backup", "codex-activation", "codex-restore", "claude-code-backup", "claude-code-activation", "claude-code-restore"),
)
def test_setup_skill_keyboard_interrupt_preserves_recovery_state(
    monkeypatch, tmp_path: Path, runtime: str, stage: str,
) -> None:
    setup, source, installed, run = _prepare(monkeypatch, tmp_path, runtime)
    assert run() == 0
    old_tree = _tree(installed)
    _write_skill_tree(source, "replacement")
    interrupt = KeyboardInterrupt(f"controlled {stage} interruption")
    activation_error = OSError("activation before restore interruption")
    real_rename = Path.rename
    container: Path | None = None

    def interrupt_move(path: Path, target: Path) -> Path:
        nonlocal container
        if stage == "backup" and path == installed and target.name == "previous":
            container = target.parent
            raise interrupt
        if stage == "activation" and path.name == "skill" and target == installed:
            container = path.parent
            raise interrupt
        if stage == "restore" and path.name == "skill" and target == installed:
            container = path.parent
            raise activation_error
        if stage == "restore" and path.name == "previous" and target == installed:
            raise interrupt
        return real_rename(path, target)

    monkeypatch.setattr(Path, "rename", interrupt_move)
    if stage == "restore":
        with pytest.raises(OSError) as failure:
            run()
        assert failure.value is activation_error
        assert failure.value.__cause__ is interrupt
    else:
        with pytest.raises(KeyboardInterrupt) as failure:
            run()
        assert failure.value is interrupt

    assert container is not None
    if stage == "activation":
        assert _tree(installed) == old_tree
        assert not container.exists()
    elif stage == "backup":
        assert _tree(installed) == old_tree
        assert not (container / "previous").exists()
        assert container.is_dir()
    else:
        assert not installed.exists()
        assert _tree(container / "previous") == old_tree
        assert str(container / "previous") in "\n".join(failure.value.__notes__)
    assert _staging_dirs(installed) == ([] if stage == "activation" else [container])
