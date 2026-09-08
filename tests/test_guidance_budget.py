from pathlib import Path
import ast
import importlib.util


def test_rendered_guidance_and_tool_descriptions_stay_under_measured_ceilings() -> None:
    spec = importlib.util.spec_from_file_location("claude_block", "integrations/claude-code/claude_md_block.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert len(module.get_claude_md_block("base")) <= 3736
    assert len(module.get_claude_md_block("strong")) <= 3962
    assert len(Path("integrations/codex/AGENTS.md").read_text(encoding="utf-8")) <= 3620
    assert len(Path("integrations/claude-code/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8")) <= 2530
    assert len(Path("integrations/codex/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8")) <= 2530
    assert len(Path("integrations/opencode/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8")) <= 2530
    tree = ast.parse(Path("app/mcp/server.py").read_text(encoding="utf-8"))
    names = {node.name for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in {"pallium_search_history_by_work_ref", "pallium_search_history", "pallium_expand_source"}}
    assert names == {"pallium_search_history_by_work_ref", "pallium_search_history", "pallium_expand_source"}
    combined = sum(len(ast.get_docstring(node) or "") for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names)
    assert combined <= 1300


def test_all_guidance_surfaces_present_pallium_capabilities() -> None:
    spec = importlib.util.spec_from_file_location(
        "claude_block_capabilities", "integrations/claude-code/claude_md_block.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    surfaces = (
        module.get_claude_md_block("base"),
        Path("integrations/codex/AGENTS.md").read_text(encoding="utf-8"),
        Path("integrations/opencode/AGENTS.md").read_text(encoding="utf-8"),
        Path("integrations/claude-code/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8"),
        Path("integrations/codex/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8"),
        Path("integrations/opencode/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8"),
        Path("integrations/opencode/.opencode/command/pallium-memory.md").read_text(encoding="utf-8"),
    )
    for rendered in surfaces[:3]:
        assert "two primary capabilities" in rendered
        assert "three separate uses" not in rendered
    for rendered in surfaces:
        assert "Relay" in rendered
        assert "Session History" in rendered
        assert "Derived memory" in rendered or "derived memory" in rendered
        assert "Pallium Memory Workflow" not in rendered


def test_all_guidance_surfaces_preserve_search_to_expansion_telemetry_link() -> None:
    spec = importlib.util.spec_from_file_location("claude_block_linkage", "integrations/claude-code/claude_md_block.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    linkage = ("After a promising search hit, call `pallium_expand_source` with its "
               "`source_item_id` and pass the search result's `lookup_event_id` as "
               "`parent_lookup_id`.")
    surfaces = (
        module.get_claude_md_block("base"),
        module.get_claude_md_block("strong"),
        Path("integrations/codex/AGENTS.md").read_text(encoding="utf-8"),
        Path("integrations/claude-code/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8"),
        Path("integrations/codex/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8"),
    )
    assert all(linkage in rendered for rendered in surfaces)
    assert all("never derive, guess, or normalize" in rendered for rendered in surfaces)

def test_relay_stale_delivery_guidance_stops_only_that_delivery() -> None:
    skills = (
        Path("integrations/claude-code/skills/pallium-memory/SKILL.md"),
        Path("integrations/codex/skills/pallium-memory/SKILL.md"),
        Path("integrations/opencode/skills/pallium-memory/SKILL.md"),
    )
    rule = ("only that delivery copy is stale: do not retry/reply/use its payload, but "
            "continue the surrounding user task and independently established work")
    assert all(rule in skill.read_text(encoding="utf-8") for skill in skills)

def test_history_guidance_distinguishes_modes_without_dropping_safety() -> None:
    paths = (
        Path("integrations/claude-code/skills/pallium-memory/SKILL.md"),
        Path("integrations/codex/skills/pallium-memory/SKILL.md"),
        Path("integrations/opencode/skills/pallium-memory/SKILL.md"),
    )
    for path in paths:
        rendered = path.read_text(encoding="utf-8")
        lines = rendered.splitlines()
        exact_line = lines.index("- `pallium_search_history_by_work_ref`")
        broad_line = lines.index("- `pallium_search_history`")
        assert lines[exact_line + 1].startswith("  Current-work search")
        assert lines[broad_line + 1].startswith("  Broad topic search")
        assert "Copy injected `work_ref`" in rendered
        assert "never guess" in rendered
        assert "compatibility-only" in rendered
        assert "only to either history search" in rendered
        assert "Flag bad cards with `pallium_flag_memory`" in rendered
        assert "Do not ingest routine turns" in rendered
        assert "use forget as vote suppression" in rendered
        for tool in (
            "pallium_remember",
            "pallium_correct",
            "pallium_supersede",
            "pallium_forget",
            "pallium_record_outcome",
        ):
            assert f"`{tool}`" in rendered


def test_field_feedback_guidance_is_lazy_aligned_and_safe() -> None:
    skill_paths = [
        Path(f"integrations/{runtime}/skills/pallium-memory/SKILL.md")
        for runtime in ("codex", "claude-code", "opencode")
    ]
    reference_paths = [path.parent / "references" / "field-feedback.md" for path in skill_paths]
    skills = [path.read_bytes() for path in skill_paths]
    references = [path.read_bytes() for path in reference_paths]

    assert skills[1:] == skills[:-1]
    assert references[1:] == references[:-1]
    for path in skill_paths:
        rendered = path.read_text(encoding="utf-8")
        assert "[field feedback](references/field-feedback.md)" in rendered
        assert (path.parent / "references" / "field-feedback.md").is_file()
        assert "200 words" not in rendered
        assert "gh issue create" not in rendered

    detail = reference_paths[0].read_text(encoding="utf-8")
    for required in (
        "only when all are true",
        "another agent, task, or supported runtime can repeat",
        "upstream change in `rore/Pallium`",
        "Drop one-off environment, tool, or network failures",
        "A memory-quality miss",
        "`pallium_query_debug`",
        "`pallium_flag_memory`",
        "`pallium_rate_memory`",
        "Never include raw prompts, transcripts",
        "credentials",
        "local paths",
        "organization instructions",
        "200 words and 2,000 Unicode characters",
        "ask for explicit approval",
        "Only after approval, search for duplicates",
        "If a duplicate exists",
        "do not create or comment unless separately approved",
        "`gh` is missing or unauthenticated",
        "## Field feedback (unsent)",
        "Do not add telemetry, service APIs, or feedback storage",
    ):
        assert required in detail
