from pathlib import Path
import ast
import importlib.util


def test_rendered_guidance_and_tool_descriptions_stay_under_measured_ceilings() -> None:
    spec = importlib.util.spec_from_file_location("claude_block", "integrations/claude-code/claude_md_block.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert len(module.get_claude_md_block("base")) <= 3736
    assert len(module.get_claude_md_block("strong")) <= 3962
    assert len(Path("integrations/codex/AGENTS.md").read_text()) <= 3620
    assert len(Path("integrations/claude-code/skills/pallium-memory/SKILL.md").read_text()) <= 2112
    assert len(Path("integrations/codex/skills/pallium-memory/SKILL.md").read_text()) <= 2127
    tree = ast.parse(Path("app/mcp/server.py").read_text())
    names = {"pallium_search_history", "pallium_expand_source"}
    combined = sum(len(ast.get_docstring(node) or "") for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names)
    assert combined <= 980