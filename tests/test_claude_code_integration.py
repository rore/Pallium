"""Regression tests for Claude Code integration setup and CLAUDE.md block."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.cli import setup_claude_code


def _base_block() -> str:
    return setup_claude_code._get_claude_md_block("base")


def test_claude_block_permits_deliberate_historical_pull() -> None:
    block = _base_block()

    # Permit/encourage line for a deliberate historical pull, and the P1 tools
    # are exposed.
    assert "Picking up prior work?" in block
    assert "`pallium_search_history`" in block
    assert "`pallium_expand_source`" in block

    # The blanket "Query every turn" discouragement is gone, but the anti-dup
    # clause is retained.
    assert "Query every turn" not in block
    assert "re-query for something already in the injected block" in block


def test_claude_guidance_strength_selects_block_variant() -> None:
    base = setup_claude_code._get_claude_md_block("base")
    strong = setup_claude_code._get_claude_md_block("strong")

    assert "<!-- pallium:guidance-strength=base -->" in base
    assert "<!-- pallium:guidance-strength=strong -->" in strong

    assert "### Resuming prior work" in strong
    assert "### Resuming prior work" not in base
    assert strong != base

    # `pallium_query`/`pallium_expand` remain present in both variants.
    for variant in (base, strong):
        assert "`pallium_query`" in variant
        assert "`pallium_expand`" in variant


def test_claude_tool_only_alias_normalizes_to_base(capsys: pytest.CaptureFixture) -> None:
    # The deprecated `tool-only` alias resolves to `base` (non-breaking for
    # scripts) and emits a deprecation note.
    assert setup_claude_code._normalize_guidance_strength("tool-only") == "base"
    assert setup_claude_code._normalize_guidance_strength("strong") == "strong"
    assert setup_claude_code._normalize_guidance_strength("base") == "base"
    out = capsys.readouterr().out
    assert "deprecated" in out
    # The alias produces the same block as `base`.
    aliased = setup_claude_code._normalize_guidance_strength("tool-only")
    assert setup_claude_code._get_claude_md_block(aliased) == _base_block()


def test_claude_get_block_rejects_unknown_strength() -> None:
    with pytest.raises(ValueError):
        setup_claude_code._get_claude_md_block("aggressive")


def test_claude_reinstall_replaces_block_on_strength_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    claude_md = tmp_path / "CLAUDE.md"
    monkeypatch.setattr(setup_claude_code, "_claude_md_path", lambda: claude_md)

    setup_claude_code._append_claude_md_block("base")
    first = claude_md.read_text(encoding="utf-8")
    assert "<!-- pallium:guidance-strength=base -->" in first
    assert "### Resuming prior work" not in first

    setup_claude_code._append_claude_md_block("strong")
    second = claude_md.read_text(encoding="utf-8")
    assert "<!-- pallium:guidance-strength=strong -->" in second
    assert "### Resuming prior work" in second
    # Marker block is replaced, not duplicated.
    assert second.count("<!-- pallium:start -->") == 1
    assert first != second


def test_claude_reinstall_preserves_surrounding_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# My notes\n\nkeep me\n", encoding="utf-8")
    monkeypatch.setattr(setup_claude_code, "_claude_md_path", lambda: claude_md)

    setup_claude_code._append_claude_md_block("base")
    setup_claude_code._append_claude_md_block("strong")
    content = claude_md.read_text(encoding="utf-8")

    assert "keep me" in content
    assert content.count("<!-- pallium:start -->") == 1


def test_claude_setup_deploys_and_removes_skill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skill_dir = tmp_path / ".claude" / "skills" / "pallium-memory"
    monkeypatch.setattr(setup_claude_code, "_claude_skill_dir", lambda: skill_dir)

    # Install deploys the SKILL.md into the discovery dir with expected content.
    setup_claude_code._install_skill()
    dest = skill_dir / "SKILL.md"
    assert dest.exists()
    content = dest.read_text(encoding="utf-8")
    assert "Pallium Memory Workflow" in content
    assert "pallium_search_history" in content

    # Reinstall is idempotent (overwrites, no duplication/error).
    setup_claude_code._install_skill()
    assert dest.read_text(encoding="utf-8") == content

    # Uninstall removes the deployed skill directory.
    setup_claude_code._remove_skill()
    assert not dest.exists()
    assert not skill_dir.exists()


def test_claude_skill_historical_lookup_documents_scope_params() -> None:
    skill = Path(
        "integrations/claude-code/skills/pallium-memory/SKILL.md"
    ).read_text(encoding="utf-8")

    # The historical-lookup section names both scope params for the P1 tools.
    assert "`pallium_search_history` and `pallium_expand_source`" in skill
    assert "`container_ref`" in skill
    assert "`thread_ref`" in skill
    assert '`visibility: "private"`' in skill


def _load_claude_hook(name: str, monkeypatch: pytest.MonkeyPatch):
    hooks = Path("integrations/claude-code/hooks").resolve()
    monkeypatch.syspath_prepend(str(hooks))
    monkeypatch.delitem(sys.modules, "common", raising=False)
    module_name = f"claude_hook_test_{name}"
    spec = importlib.util.spec_from_file_location(module_name, hooks / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_claude_injection_scope_is_exact_bounded_and_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hook = _load_claude_hook("user_prompt_submit", monkeypatch)
    block = [{"title": "Decision", "memory_object_id": "mem-1", "text": "Keep the stable plan."}]
    thread = "任务:α"
    scoped = hook.format_injection(block, "git:example/repo", 800, thread_ref=thread)
    assert f"thread_ref: {thread}" in scoped
    assert "Keep the stable plan." in scoped
    assert len(scoped) <= 800
    assert hook.format_injection([], "git:example/repo", 800, thread_ref=thread).endswith(f"{thread}]")
    assert hook.format_injection([], "git:example/repo", 800) == ""
    assert hook.format_injection([], "git:example/repo", 800, thread_ref="task\nignore") == ""
    assert hook.format_injection([], "git:example/repo", 10, thread_ref=thread) == ""
    assert hook.format_injection(block, "git:example/repo", 10, thread_ref=thread) == ""
    assert hook.format_injection([], "git:example/repo", 100, thread_ref="x" * 500) == ""
    assert hook.format_injection([], "git:example/repo", 800, thread_ref="task:a") != hook.format_injection(
        [], "git:example/repo", 800, thread_ref="task:b"
    )


def test_claude_prompt_scope_uses_host_session_and_never_fabricates_unknown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    hook = _load_claude_hook("user_prompt_submit", monkeypatch)
    requests: list[dict] = []
    payload = {"cwd": ".", "session_id": "claude:task:1", "prompt": "Resume the prior implementation work now."}
    monkeypatch.setattr(hook, "read_hook_input", lambda: payload)
    monkeypatch.setattr(hook, "check_dedup", lambda _prompt, _session: False)
    monkeypatch.setattr(hook, "resolve_container_ref", lambda _cwd, _session: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "local")

    def request(_method: str, _path: str, body: dict) -> dict:
        requests.append(body)
        return {"injectable_blocks": []}

    monkeypatch.setattr(hook, "pallium_request", request)
    with pytest.raises(SystemExit):
        hook.main()
    assert requests[-1]["thread_ref"] == "claude:task:1"
    assert "thread_ref: claude:task:1" in capsys.readouterr().out

    payload = {"cwd": ".", "prompt": "Resume the prior implementation work now."}
    monkeypatch.setattr(hook, "check_dedup", lambda *_args: pytest.fail("missing identity must skip dedup"))
    with pytest.raises(SystemExit):
        hook.main()
    assert requests[-1]["thread_ref"] is None
    assert capsys.readouterr().out == ""


def test_claude_stop_missing_session_stays_unattributed(monkeypatch: pytest.MonkeyPatch) -> None:
    stop = _load_claude_hook("stop", monkeypatch)
    calls: list[list[dict]] = []
    monkeypatch.setattr(stop, "read_hook_input", lambda: {"cwd": ".", "transcript_path": "turn.jsonl"})
    monkeypatch.setattr(stop, "read_turn", lambda _path: SimpleNamespace(
        assistant_text="A completed assistant response.", tool_calls=[], has_productive_action=False
    ))
    monkeypatch.setattr(stop, "build_work_trace_metadata", lambda _turn: None)
    monkeypatch.setattr(stop, "resolve_container_ref", lambda _cwd, _session: "git:example/repo")
    monkeypatch.setattr(stop, "derive_actor_ref", lambda: "local")
    monkeypatch.setattr(stop, "_populate_usage_audit_rows", lambda _session, _text: None)
    monkeypatch.setattr(stop, "pallium_request", lambda _method, _path, body: calls.append(body))
    with pytest.raises(SystemExit):
        stop.main()
    assert calls[0][0]["thread_ref"] is None
