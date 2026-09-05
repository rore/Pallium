"""Verify that Claude Code and Codex common.py stay in sync for work trace features."""
from __future__ import annotations

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

def _git_result(root: Path, branch: str, returncode: int = 0):
    class Result:
        pass

    result = Result()
    result.returncode = returncode
    result.stdout = f"{root}\n{branch}\n"
    return result


def test_work_refs_metadata_signature_order_and_git_call_match(monkeypatch, tmp_path):
    record_dir = tmp_path / ".agent-workflow" / "tasks"
    record_dir.mkdir(parents=True)
    (record_dir / "item.md").write_text(
        "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->",
        encoding="utf-8",
    )
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return _git_result(tmp_path, "demo/item")

    monkeypatch.setattr(cc_common.subprocess, "run", run)
    monkeypatch.setattr(codex_common.subprocess, "run", run)
    expected = {
        "pallium_work_refs": [
            "git-branch:demo/item",
            "agent-workflow:item",
            "Ticket_Ünicode",
        ]
    }
    assert cc_common.build_work_refs_metadata(str(tmp_path), ["Ticket_Ünicode"]) == expected
    assert codex_common.build_work_refs_metadata(str(tmp_path), ["Ticket_Ünicode"]) == expected
    assert len(calls) == 2
    for command, kwargs in calls:
        assert command == ["git", "rev-parse", "--show-toplevel", "--abbrev-ref", "HEAD"]
        assert kwargs["timeout"] == cc_common.SUBPROCESS_TIMEOUT


def test_work_refs_metadata_skips_base_detached_missing_and_malformed(monkeypatch, tmp_path):
    tasks = tmp_path / ".agent-workflow" / "tasks"
    tasks.mkdir(parents=True)
    for branch in ("main", "master", "develop", "trunk", "HEAD"):
        monkeypatch.setattr(cc_common.subprocess, "run", lambda *a, _branch=branch, **k: _git_result(tmp_path, _branch))
        assert cc_common.build_work_refs_metadata(str(tmp_path), ["ISSUE-1"]) == {
            "pallium_work_refs": ["ISSUE-1"]
        }

    cases = {
        "fix/missing": None,
        "feature/partial": "<!-- agent-workflow:start -->",
        "bug/directory": "directory",
        "codex/unstripped": "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->",
    }
    for branch, content in cases.items():
        slug = branch
        for prefix in cc_common._WORK_REF_PREFIXES:
            if slug.startswith(prefix):
                slug = slug[len(prefix):]
                break
        slug = slug.replace("/", "-")
        record = tasks / f"{slug}.md"
        if content == "directory":
            record.mkdir()
        elif content is not None:
            record.write_text(content, encoding="utf-8")
        monkeypatch.setattr(cc_common.subprocess, "run", lambda *a, _branch=branch, **k: _git_result(tmp_path, _branch))
        result = cc_common.build_work_refs_metadata(str(tmp_path))
        assert result["pallium_work_refs"][0] == f"git-branch:{branch}"
        assert ("agent-workflow:" + slug in result["pallium_work_refs"]) is (
            content is not None and content != "directory" and "agent-workflow:end" in content
        )


def test_work_refs_metadata_rejects_non_git_and_record_symlink_escape(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cc_common.subprocess,
        "run",
        lambda *a, **k: _git_result(tmp_path, "", returncode=128),
    )
    assert cc_common.build_work_refs_metadata(str(tmp_path), ["X"]) == {
        "pallium_work_refs": ["X"]
    }

    tasks = tmp_path / ".agent-workflow" / "tasks"
    tasks.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text(
        "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->",
        encoding="utf-8",
    )
    record = tasks / "escape.md"
    try:
        record.symlink_to(outside)
    except OSError:
        return
    monkeypatch.setattr(
        cc_common.subprocess,
        "run",
        lambda *a, **k: _git_result(tmp_path, "fix/escape"),
    )
    assert cc_common.build_work_refs_metadata(str(tmp_path)) == {
        "pallium_work_refs": ["git-branch:fix/escape"]
    }
