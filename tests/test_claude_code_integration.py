"""Regression tests for Claude Code integration setup and CLAUDE.md block."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.cli import setup_claude_code


def _base_block() -> str:
    return setup_claude_code._get_claude_md_block("tool-only")


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
    tool_only = setup_claude_code._get_claude_md_block("tool-only")
    strong = setup_claude_code._get_claude_md_block("strong")

    assert "<!-- pallium:guidance-strength=tool-only -->" in tool_only
    assert "<!-- pallium:guidance-strength=strong -->" in strong

    assert "### Resuming prior work" in strong
    assert "### Resuming prior work" not in tool_only
    assert strong != tool_only

    # `pallium_query`/`pallium_expand` remain present in both variants.
    for variant in (tool_only, strong):
        assert "`pallium_query`" in variant
        assert "`pallium_expand`" in variant


def test_claude_get_block_rejects_unknown_strength() -> None:
    with pytest.raises(ValueError):
        setup_claude_code._get_claude_md_block("aggressive")


def test_claude_reinstall_replaces_block_on_strength_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    claude_md = tmp_path / "CLAUDE.md"
    monkeypatch.setattr(setup_claude_code, "_claude_md_path", lambda: claude_md)

    setup_claude_code._append_claude_md_block("tool-only")
    first = claude_md.read_text(encoding="utf-8")
    assert "<!-- pallium:guidance-strength=tool-only -->" in first
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

    setup_claude_code._append_claude_md_block("tool-only")
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
    assert '`visibility: "private"`' in skill
