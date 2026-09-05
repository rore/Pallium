"""Verify that Claude Code and Codex common.py stay in sync for work trace features."""
from __future__ import annotations

import pytest

import importlib.util
import inspect
import sys
from pathlib import Path


def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ROOT = Path(__file__).resolve().parent.parent

cc_common = _load_module(str(ROOT / "integrations" / "claude-code" / "hooks" / "common.py"), "cc_common_parity")
codex_common = _load_module(str(ROOT / "integrations" / "codex" / "hooks" / "common.py"), "codex_common_parity")


class TestCommonParity:
    def test_read_turn_signature_matches(self):
        cc_sig = inspect.signature(cc_common.read_turn)
        codex_sig = inspect.signature(codex_common.read_turn)
        assert str(cc_sig) == str(codex_sig)

    def test_redaction_patterns_match(self):
        cc_patterns = [(p.pattern, r) for p, r in cc_common.REDACTION_PATTERNS]
        codex_patterns = [(p.pattern, r) for p, r in codex_common.REDACTION_PATTERNS]
        assert cc_patterns == codex_patterns

    def test_redact_sensitive_signature_matches(self):
        cc_sig = inspect.signature(cc_common.redact_sensitive)
        codex_sig = inspect.signature(codex_common.redact_sensitive)
        assert str(cc_sig) == str(codex_sig)

    def test_build_work_trace_metadata_signature_matches(self):
        cc_sig = inspect.signature(cc_common.build_work_trace_metadata)
        codex_sig = inspect.signature(codex_common.build_work_trace_metadata)
        assert str(cc_sig) == str(codex_sig)

    def test_build_work_trace_metadata_produces_same_output(self):
        """Behavioral parity: same input produces same output in both copies."""
        for files_modified in [[], ["src/b.py", "src/c.py"]]:
            cc_turn = cc_common.TurnData(
                assistant_text="test",
                tool_calls=[
                    {"tool": "Read", "file_path": "src/x.py"},
                    {"tool": "Bash", "command": "ls", "exit_code": 0, "output_tail": "", "failure_class": "success"},
                ],
                has_productive_action=bool(files_modified),
                files_modified=files_modified,
            )
            codex_turn = codex_common.TurnData(
                assistant_text="test",
                tool_calls=[
                    {"tool": "Read", "file_path": "src/x.py"},
                    {"tool": "Bash", "command": "ls", "exit_code": 0, "output_tail": "", "failure_class": "success"},
                ],
                has_productive_action=bool(files_modified),
                files_modified=files_modified,
            )
            assert cc_common.build_work_trace_metadata(cc_turn) == codex_common.build_work_trace_metadata(codex_turn)

    def test_tool_constants_match(self):
        assert cc_common.DISCOVERY_TOOLS == codex_common.DISCOVERY_TOOLS
        assert cc_common.PRODUCTIVE_TOOLS == codex_common.PRODUCTIVE_TOOLS
        assert cc_common.EXCLUDED_TOOLS == codex_common.EXCLUDED_TOOLS
        assert cc_common.BASH_OUTPUT_LIMIT == codex_common.BASH_OUTPUT_LIMIT

    def test_redact_sensitive_behavioral_parity(self):
        """Same inputs produce same outputs."""
        test_strings = [
            "Bearer sk-12345",
            "DB_PASSWORD=secret",
            "postgres://user:pass@host/db",
            "clean text here",
        ]
        for s in test_strings:
            assert cc_common.redact_sensitive(s) == codex_common.redact_sensitive(s), f"Mismatch on: {s}"

    def test_turn_data_fields_match(self):
        """TurnData dataclass fields are identical in both copies."""
        import dataclasses
        cc_fields = {f.name: f.type for f in dataclasses.fields(cc_common.TurnData)}
        codex_fields = {f.name: f.type for f in dataclasses.fields(codex_common.TurnData)}
        assert cc_fields == codex_fields


def test_cc_build_work_trace_metadata_captures_files_modified():
    """Edit/Write tool calls produce files_modified in turn metadata."""
    turn = cc_common.TurnData(
        assistant_text="done",
        tool_calls=[{"tool": "Read", "file_path": "src/a.py"}],
        has_productive_action=True,
        files_modified=["src/b.py"],
    )
    result = cc_common.build_work_trace_metadata(turn)
    assert result is not None
    assert result["files_modified"] == ["src/b.py"]


def test_codex_build_work_trace_metadata_captures_files_modified():
    """Codex common.py also captures files_modified."""
    turn = codex_common.TurnData(
        assistant_text="done",
        tool_calls=[{"tool": "Read", "file_path": "src/a.py"}],
        has_productive_action=True,
        files_modified=["src/b.py"],
    )
    result = codex_common.build_work_trace_metadata(turn)
    assert result is not None
    assert result["files_modified"] == ["src/b.py"]

def _make_repo(root: Path, branch: str = "feature/item", *, record: bool = True) -> None:
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
    if record:
        slug = branch
        for prefix in cc_common._WORK_REF_PREFIXES:
            if slug.startswith(prefix):
                slug = slug[len(prefix):]
                break
        slug = slug.replace("/", "-")
        tasks = root / ".agent-workflow" / "tasks"
        tasks.mkdir(parents=True)
        (tasks / f"{slug}.md").write_text(
            "before\n<!-- agent-workflow:start -->\nstate\n<!-- agent-workflow:end -->\nafter",
            encoding="utf-8",
        )


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_reads_local_metadata_without_spawning(monkeypatch, tmp_path, module):
    _make_repo(tmp_path)
    nested = tmp_path / "src" / "nested"
    nested.mkdir(parents=True)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("structural resolver spawned a process"),
    )

    assert module.build_work_refs_metadata(
        str(nested), ["Ticket_Ünicode", 42, "Ticket_Ünicode"]
    ) == {
        "pallium_work_refs": [
            "git-branch:feature/item",
            "agent-workflow:item",
            "Ticket_Ünicode",
            "Ticket_Ünicode",
        ]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
@pytest.mark.parametrize(
    "cwd",
    [
        None,
        "",
        ".",
        "relative/path",
        r"\\server\share\repo",
        r"\\?\C:\repo",
        r"\\.\C:\repo",
        "x" * 4097,
    ],
)
def test_work_refs_rejects_unsafe_cwd_and_preserves_explicit(module, cwd):
    assert module.build_work_refs_metadata(cwd, ["ISSUE-1"]) == {
        "pallium_work_refs": ["ISSUE-1"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_nonexistent_and_permission_error_fail_open(monkeypatch, tmp_path, module):
    missing = tmp_path / "missing"
    assert module.build_work_refs_metadata(str(missing), ["ISSUE-1"]) == {
        "pallium_work_refs": ["ISSUE-1"]
    }

    original = module._safe_lstat
    def deny_marker(path):
        if path.name == ".git":
            raise PermissionError("denied")
        return original(path)
    monkeypatch.setattr(module, "_safe_lstat", deny_marker)
    assert module.build_work_refs_metadata(str(tmp_path), ["ISSUE-2"]) == {
        "pallium_work_refs": ["ISSUE-2"]
    }


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive classification")
@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_rejects_mapped_remote_drive_before_filesystem_access(monkeypatch, module):
    monkeypatch.setattr(module, "_windows_drive_is_local", lambda _path: False)
    monkeypatch.setattr(
        module,
        "_safe_directory_chain",
        lambda _path: pytest.fail("mapped drive was probed"),
    )
    assert module.build_work_refs_metadata(r"Z:\repo", ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_rejects_non_link_reparse_attribute(monkeypatch, tmp_path, module):
    class CloudPlaceholder:
        st_mode = module.stat.S_IFREG
        st_file_attributes = 0x400

    monkeypatch.setattr(module.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400, raising=False)
    monkeypatch.setattr(module.Path, "lstat", lambda _path: CloudPlaceholder())
    with pytest.raises(OSError, match="unsafe reparse point"):
        module._safe_lstat(tmp_path / "cloud-placeholder")


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_stops_parent_walk_at_64(tmp_path, module):
    _make_repo(tmp_path)
    deep = tmp_path
    for _ in range(65):
        deep = deep / "d"
        deep.mkdir()
    assert module.build_work_refs_metadata(str(deep), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
@pytest.mark.parametrize(
    "head",
    [
        "0123456789abcdef\n",
        "ref: refs/tags/release\n",
        "ref: refs/heads/main\n",
        "ref: refs/heads/feature/../escape\n",
        "ref: refs/heads/bad branch\n",
        "ref: refs/heads/feature/item\nsecond\n",
        "ref: refs/heads/fix/.hidden\n",
        "\ufeffref: refs/heads/fix/item\n",
    ],
)
def test_work_refs_rejects_detached_base_and_malformed_head(tmp_path, module, head):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text(head, encoding="utf-8")
    assert module.build_work_refs_metadata(str(tmp_path), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_accepts_crlf_and_unicode_branch(tmp_path, module):
    _make_repo(tmp_path, "feature/任务", record=False)
    (tmp_path / ".git" / "HEAD").write_bytes("ref: refs/heads/feature/任务\r\n".encode())
    tasks = tmp_path / ".agent-workflow" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "任务.md").write_text(
        "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->",
        encoding="utf-8",
    )
    assert module.build_work_refs_metadata(str(tmp_path)) == {
        "pallium_work_refs": ["git-branch:feature/任务", "agent-workflow:任务"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_linked_worktree_local_gitdir(tmp_path, module):
    worktree = tmp_path / "checkout"
    git_dir = tmp_path / "metadata" / "worktrees" / "one"
    worktree.mkdir()
    git_dir.mkdir(parents=True)
    (worktree / ".git").write_text(
        f"gitdir: {git_dir}\n", encoding="utf-8"
    )
    (git_dir / "HEAD").write_text("ref: refs/heads/fix/linked\n", encoding="utf-8")
    tasks = worktree / ".agent-workflow" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "linked.md").write_text(
        "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->",
        encoding="utf-8",
    )
    assert module.build_work_refs_metadata(str(worktree)) == {
        "pallium_work_refs": ["git-branch:fix/linked", "agent-workflow:linked"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
@pytest.mark.parametrize(
    "pointer",
    [
        "gitdir:",
        r"gitdir: \\server\share\repo" + "\n",
        "gitdir: C:\\repo\nextra\n",
        "other: metadata\n",
        "\ufeffgitdir: metadata\n",
    ],
)
def test_work_refs_rejects_malformed_or_remote_gitdir(tmp_path, module, pointer):
    (tmp_path / ".git").write_text(pointer, encoding="utf-8")
    assert module.build_work_refs_metadata(str(tmp_path), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_record_is_rechecked_and_must_be_complete(tmp_path, module):
    _make_repo(tmp_path)
    record = tmp_path / ".agent-workflow" / "tasks" / "item.md"
    expected_branch = {"pallium_work_refs": ["git-branch:feature/item"]}

    record.unlink()
    assert module.build_work_refs_metadata(str(tmp_path)) == expected_branch
    record.write_text("<!-- agent-workflow:end -->\n<!-- agent-workflow:start -->", encoding="utf-8")
    assert module.build_work_refs_metadata(str(tmp_path)) == expected_branch
    record.write_bytes(b"x" * (256 * 1024 + 1))
    assert module.build_work_refs_metadata(str(tmp_path)) == expected_branch
    record.write_bytes(b"\xff\xfe")
    assert module.build_work_refs_metadata(str(tmp_path)) == expected_branch
    record.write_text(
        "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->", encoding="utf-8"
    )
    assert module.build_work_refs_metadata(str(tmp_path)) == {
        "pallium_work_refs": ["git-branch:feature/item", "agent-workflow:item"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_rejects_symlink_marker_head_and_record(tmp_path, module):
    cases = ("marker", "head", "record")
    for index, case in enumerate(cases):
        root = tmp_path / str(index)
        root.mkdir()
        _make_repo(root)
        if case == "marker":
            target = root / "git-target"
            (root / ".git").rename(target)
            try:
                (root / ".git").symlink_to(target, target_is_directory=True)
            except OSError:
                pytest.skip("symlinks unavailable")
        elif case == "head":
            head = root / ".git" / "HEAD"
            target = root / "head-target"
            head.rename(target)
            try:
                head.symlink_to(target)
            except OSError:
                pytest.skip("symlinks unavailable")
        else:
            record = root / ".agent-workflow" / "tasks" / "item.md"
            target = root / "record-target"
            record.rename(target)
            try:
                record.symlink_to(target)
            except OSError:
                pytest.skip("symlinks unavailable")
        result = module.build_work_refs_metadata(str(root), ["KEEP"])
        if case == "record":
            assert result == {
                "pallium_work_refs": ["git-branch:feature/item", "KEEP"]
            }
        else:
            assert result == {"pallium_work_refs": ["KEEP"]}


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_checkout_race_fails_open(monkeypatch, tmp_path, module):
    _make_repo(tmp_path)
    original = module._bounded_text
    def disappear(path, limit):
        if path.name == "HEAD":
            raise FileNotFoundError
        return original(path, limit)
    monkeypatch.setattr(module, "_bounded_text", disappear)
    assert module.build_work_refs_metadata(str(tmp_path), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_rejects_intermediate_symlink_components(tmp_path, module):
    real = tmp_path / "real"
    _make_repo(real)
    nested = real / "nested"
    nested.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert module.build_work_refs_metadata(str(alias / "nested"), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    metadata = tmp_path / "metadata"
    git_dir = metadata / "one"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/fix/link\n", encoding="utf-8")
    metadata_alias = tmp_path / "metadata-alias"
    metadata_alias.symlink_to(metadata, target_is_directory=True)
    (checkout / ".git").write_text(
        f"gitdir: {metadata_alias / 'one'}\n", encoding="utf-8"
    )
    assert module.build_work_refs_metadata(str(checkout), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_git_path_environment_fails_open(monkeypatch, tmp_path, module):
    _make_repo(tmp_path)
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere"))
    assert module.build_work_refs_metadata(str(tmp_path), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_head_change_during_record_lookup_fails_open(monkeypatch, tmp_path, module):
    _make_repo(tmp_path)
    original = module._bounded_text
    reads = 0

    def change_head(path, limit):
        nonlocal reads
        text = original(path, limit)
        if path.name == "HEAD" and reads == 0:
            reads += 1
            path.write_text("ref: refs/heads/fix/other\n", encoding="utf-8")
        return text

    monkeypatch.setattr(module, "_bounded_text", change_head)
    assert module.build_work_refs_metadata(str(tmp_path), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_large_explicit_list_does_not_suppress_metadata(module):
    explicit = ["KEEP"] * 200_000
    result = module.build_work_refs_metadata("", explicit)
    assert result["pallium_work_refs"] == explicit
