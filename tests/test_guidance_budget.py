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
    assert len(Path("integrations/claude-code/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8")) <= 2170
    assert len(Path("integrations/codex/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8")) <= 2170
    tree = ast.parse(Path("app/mcp/server.py").read_text(encoding="utf-8"))
    names = {node.name for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in {"pallium_search_history", "pallium_expand_source"}}
    assert names == {"pallium_search_history", "pallium_expand_source"}
    combined = sum(len(ast.get_docstring(node) or "") for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names)
    assert combined <= 980

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
