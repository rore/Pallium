"""Real-shape parser tests for Claude Code AND Codex transcripts.

Pins behavior on:
  - Claude Code per-block-line JSONL with assistant tool_use lines and
    user tool_result lines anchored by tool_use_id.
  - Codex OpenAI Responses rollout JSONL with response_item.payload.type
    in {message, function_call, function_call_output, shell_call,
    shell_call_output, apply_patch_call, apply_patch_call_output, ...}.
  - Turn bracketing across multiple turns.
  - apply_patch destination (patch_bodies metadata field).

Per-test fixture is loaded from tests/fixtures/transcripts/*.jsonl.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "transcripts"

cc_common = _load_module(
    str(ROOT / "integrations" / "claude-code" / "hooks" / "common.py"),
    "cc_common_real_shape",
)
codex_common = _load_module(
    str(ROOT / "integrations" / "codex" / "hooks" / "common.py"),
    "codex_common_real_shape",
)


# ---------------------------------------------------------------------------
# Claude Code real-shape tests
# ---------------------------------------------------------------------------


class TestClaudeCodeRealShape:
    def test_real_turn_extracts_all_tool_uses(self):
        """The real on-disk shape (per-block-line) yields >=3 tool calls.

        Fixture has Read, Bash, Grep, Edit tool_uses in a single turn —
        previously the parser returned 0 tool_calls because it only
        looked at the last assistant line.
        """
        turn = cc_common.read_turn(str(FIXTURES / "claude_code_real_turn.jsonl"))
        assert turn is not None
        tools = [c["tool"] for c in turn.tool_calls]
        # Edit is in PRODUCTIVE_TOOLS but EXCLUDED_TOOLS so it's filtered.
        # Read, Bash, Grep should all appear.
        assert "Read" in tools
        assert "Bash" in tools
        assert "Grep" in tools

    def test_real_turn_pairs_results(self):
        """tool_result blocks on user lines pair with tool_use blocks on
        assistant lines via tool_use_id (the bug E1 caught)."""
        turn = cc_common.read_turn(str(FIXTURES / "claude_code_real_turn.jsonl"))
        assert turn is not None
        bash = next((c for c in turn.tool_calls if c["tool"] == "Bash"), None)
        assert bash is not None
        # The Bash tool_result was on a user line; the parser must have
        # paired it via tool_use_id and run _extract_tool_call.
        assert bash["exit_code"] == 1
        assert "failed" in bash["output_tail"].lower()
        assert bash["failure_class"] == "test_failure"

    def test_real_turn_text_aggregated_across_lines(self):
        """assistant_text contains text from multiple assistant lines, not just
        the last."""
        turn = cc_common.read_turn(str(FIXTURES / "claude_code_real_turn.jsonl"))
        assert turn is not None
        # Fixture has text "Reading retrieval.py first.", "Now I'll fix it.",
        # "Done. 1 file modified." on three different assistant lines.
        assert "Reading retrieval.py first." in turn.assistant_text
        assert "Now I'll fix it." in turn.assistant_text
        assert "Done. 1 file modified." in turn.assistant_text

    def test_turn_bracketing_returns_only_second_turn(self):
        """When the file has two turns, only the SECOND turn's tool_calls
        are returned."""
        turn = cc_common.read_turn(str(FIXTURES / "claude_code_two_turns.jsonl"))
        assert turn is not None
        # Second turn reads bar.py, not foo.py.
        reads = [c for c in turn.tool_calls if c["tool"] == "Read"]
        assert len(reads) == 1
        assert "bar.py" in reads[0]["file_path"]
        assert "Read bar.py." in turn.assistant_text
        assert "foo.py" not in turn.assistant_text

    def test_real_turn_files_modified_captured(self):
        """productive Edit tool_use (even in EXCLUDED_TOOLS for tool_calls
        list) still contributes to files_modified."""
        turn = cc_common.read_turn(str(FIXTURES / "claude_code_real_turn.jsonl"))
        assert turn is not None
        assert turn.has_productive_action is True
        assert "src/retrieval.py" in turn.files_modified


# ---------------------------------------------------------------------------
# Codex real-shape tests
# ---------------------------------------------------------------------------


class TestCodexRealShape:
    def test_function_call_shell_command_extracts_bash(self):
        """Codex function_call.name=='shell_command' → Bash tool call with
        exit code parsed from 'Exit code: N' prefix."""
        turn = codex_common.read_turn(str(FIXTURES / "codex_real_turn.jsonl"))
        assert turn is not None
        bash_calls = [c for c in turn.tool_calls if c["tool"] == "Bash"]
        # Two shell_commands + one shell_call = 3 Bash entries.
        assert len(bash_calls) >= 3
        commands = [c["command"] for c in bash_calls]
        assert any("git status --short" in c for c in commands)
        assert any("pytest" in c for c in commands)

    def test_function_call_exec_command_alias(self):
        """exec_command also maps to Bash via alias set."""
        # Build a synthetic line in-memory and feed _decode_line directly.
        entry = {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "call_id": "call_x",
                "arguments": '{"cmd": "ls -la"}',
            },
        }
        line = codex_common._decode_line(entry)
        assert line is not None
        assert line.role == "assistant"
        block = line.content[0]
        assert block["type"] == "tool_use"
        assert block["name"] == "Bash"
        assert block["input"]["command"] == "ls -la"

    def test_toplevel_shell_call_extracts_bash(self):
        """payload.type=='shell_call' (Responses native shell tool) →
        Bash via shape (no name match)."""
        turn = codex_common.read_turn(str(FIXTURES / "codex_real_turn.jsonl"))
        assert turn is not None
        bash_calls = [c for c in turn.tool_calls if c["tool"] == "Bash"]
        # The shell_call ran "python -m pytest tests/ -x" with exit 0.
        success_pytest = [
            c for c in bash_calls if "pytest" in c["command"] and c["exit_code"] == 0
        ]
        assert len(success_pytest) >= 1

    def test_function_call_apply_patch_preserves_freeform_body(self):
        """apply_patch (function_call) freeform DSL body survives in
        agent_work_trace_turn['patch_bodies']."""
        turn = codex_common.read_turn(str(FIXTURES / "codex_real_turn.jsonl"))
        assert turn is not None
        meta = codex_common.build_work_trace_metadata(turn)
        assert meta is not None
        assert "patch_bodies" in meta
        bodies_with_freeform = [
            pb for pb in meta["patch_bodies"]
            if "body" in pb and "*** Begin Patch" in pb["body"]
        ]
        assert len(bodies_with_freeform) >= 1
        assert "src/y.py" in bodies_with_freeform[0]["body"]

    def test_toplevel_apply_patch_call_preserves_operation(self):
        """apply_patch_call (top-level Responses item) preserves the
        structured operation in patch_bodies AND populates files_modified."""
        turn = codex_common.read_turn(str(FIXTURES / "codex_real_turn.jsonl"))
        assert turn is not None
        meta = codex_common.build_work_trace_metadata(turn)
        assert meta is not None
        ops = [pb["operation"] for pb in meta.get("patch_bodies", []) if "operation" in pb]
        assert len(ops) >= 1
        update_op = next((o for o in ops if o.get("type") == "update_file"), None)
        assert update_op is not None
        assert update_op.get("path") == "src/x.py"
        # files_modified picks up the structured-form path.
        assert "src/x.py" in turn.files_modified
        assert turn.has_productive_action is True

    def test_excluded_tools_filtered(self):
        """update_plan, view_image, and unknown function names are dropped."""
        turn = codex_common.read_turn(str(FIXTURES / "codex_real_turn.jsonl"))
        assert turn is not None
        names = [c["tool"] for c in turn.tool_calls]
        assert "update_plan" not in names
        assert "view_image" not in names
        assert "TodoWrite" not in names
        assert "mcp__some_server__some_tool" not in names

    def test_image_array_output_handled(self):
        """function_call_output.output as list of typed image blocks does not
        raise; result is empty string after image data is dropped."""
        # Test the normalizer directly.
        out = codex_common._codex_normalize_output(
            [{"type": "input_image", "image_url": "data:image/png;base64,abc"}]
        )
        assert out == ""

    def test_user_message_turn_boundary(self):
        """Two response_item.message(role=user) items split the file into
        two turns; only the second turn's calls are returned."""
        turn = codex_common.read_turn(str(FIXTURES / "codex_two_turns.jsonl"))
        assert turn is not None
        commands = [c["command"] for c in turn.tool_calls if c["tool"] == "Bash"]
        assert any("git status" in c for c in commands)
        assert not any("ls -la" in c for c in commands)

    def test_event_msg_user_message_fallback(self, tmp_path):
        """When no response_item.message(role=user) exists, an
        event_msg.user_message acts as the turn boundary."""
        path = tmp_path / "codex_event_only.jsonl"
        with open(path, "w") as f:
            for entry in [
                {"type": "session_meta", "payload": {"id": "x"}},
                {"type": "event_msg", "payload": {"type": "user_message",
                                                  "message": "First prompt"}},
                {"type": "response_item", "payload": {
                    "type": "function_call", "name": "shell_command",
                    "call_id": "c1",
                    "arguments": '{"command": "echo first"}',
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call_output", "call_id": "c1",
                    "output": "Exit code: 0\nOutput:\nfirst",
                }},
                {"type": "event_msg", "payload": {"type": "user_message",
                                                  "message": "Second prompt"}},
                {"type": "response_item", "payload": {
                    "type": "function_call", "name": "shell_command",
                    "call_id": "c2",
                    "arguments": '{"command": "echo second"}',
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call_output", "call_id": "c2",
                    "output": "Exit code: 0\nOutput:\nsecond",
                }},
            ]:
                f.write(json.dumps(entry) + "\n")
        turn = codex_common.read_turn(str(path))
        assert turn is not None
        commands = [c["command"] for c in turn.tool_calls if c["tool"] == "Bash"]
        assert "echo second" in commands
        assert "echo first" not in commands

    def test_developer_role_not_a_turn_boundary(self, tmp_path):
        """role=='developer' messages do NOT bound turns; tool calls before
        and after a developer message remain in the same turn."""
        path = tmp_path / "codex_developer.jsonl"
        with open(path, "w") as f:
            for entry in [
                {"type": "response_item", "payload": {
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": "Do something"}],
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call", "name": "shell_command",
                    "call_id": "c1",
                    "arguments": '{"command": "echo first"}',
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call_output", "call_id": "c1",
                    "output": "Exit code: 0",
                }},
                # developer message in the middle — must not split the turn
                {"type": "response_item", "payload": {
                    "type": "message", "role": "developer",
                    "content": [{"type": "input_text", "text": "<env update>"}],
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call", "name": "shell_command",
                    "call_id": "c2",
                    "arguments": '{"command": "echo second"}',
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call_output", "call_id": "c2",
                    "output": "Exit code: 0",
                }},
            ]:
                f.write(json.dumps(entry) + "\n")
        turn = codex_common.read_turn(str(path))
        assert turn is not None
        commands = [c["command"] for c in turn.tool_calls if c["tool"] == "Bash"]
        assert "echo first" in commands
        assert "echo second" in commands

    def test_unknown_tool_name_dropped(self, tmp_path):
        """Unknown function names (e.g. mcp__server__tool) are dropped."""
        path = tmp_path / "codex_unknown.jsonl"
        with open(path, "w") as f:
            for entry in [
                {"type": "response_item", "payload": {
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": "Do it"}],
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call", "name": "mcp__some_server__some_tool",
                    "call_id": "c1", "arguments": '{"x": 1}',
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call_output", "call_id": "c1",
                    "output": "result",
                }},
                {"type": "response_item", "payload": {
                    "type": "message", "role": "assistant",
                    "content": [{"type": "output_text", "text": "Done."}],
                }},
            ]:
                f.write(json.dumps(entry) + "\n")
        turn = codex_common.read_turn(str(path))
        # Either None (if no other tool calls and text empty) or empty tool_calls.
        if turn is not None:
            assert all(c["tool"] != "mcp__some_server__some_tool" for c in turn.tool_calls)
            # The unknown call was dropped, but the assistant text should remain.
            assert "Done." in turn.assistant_text

    def test_shell_call_output_structured_decoded(self):
        """Responses-style shell_call_output {outcome:{exit:1}, stdout, stderr}
        synthesizes 'Exit code: 1' string parseable by _infer_exit_code."""
        out = codex_common._codex_normalize_output({
            "outcome": {"exit": 1},
            "stdout": "FAILED test",
            "stderr": "error",
        })
        assert "Exit code: 1" in out
        assert codex_common._infer_exit_code(out) == 1

    def test_apply_patch_call_output_status_decoded(self):
        """apply_patch_call_output {status, output} flattens to 'Status: X\\n...'."""
        out = codex_common._codex_normalize_output({
            "status": "completed",
            "output": "Patch applied",
        })
        assert out.startswith("Status: completed")
        assert "Patch applied" in out

    def test_anthropic_style_message_block_resolved(self, tmp_path):
        """Forward-compat: a Codex response_item.message whose content list
        contains Anthropic-style tool_use/tool_result blocks resolves
        identically to Claude Code (§3.6 claim regression guard)."""
        path = tmp_path / "codex_anthropic_shape.jsonl"
        with open(path, "w") as f:
            for entry in [
                {"type": "response_item", "payload": {
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": "Read x.py"}],
                }},
                {"type": "response_item", "payload": {
                    "type": "message", "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "t1", "name": "Read",
                         "input": {"file_path": "x.py"}},
                        {"type": "tool_result", "tool_use_id": "t1",
                         "content": "x content"},
                    ],
                }},
            ]:
                f.write(json.dumps(entry) + "\n")
        turn = codex_common.read_turn(str(path))
        assert turn is not None
        reads = [c for c in turn.tool_calls if c["tool"] == "Read"]
        assert len(reads) == 1
        assert reads[0]["file_path"] == "x.py"

    def test_call_id_collision_isolation(self, tmp_path):
        """Two unrelated function_calls with distinct call_ids each pair to
        their own output without collisions."""
        path = tmp_path / "codex_collision.jsonl"
        with open(path, "w") as f:
            for entry in [
                {"type": "response_item", "payload": {
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": "Run two."}],
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call", "name": "shell_command",
                    "call_id": "call_AAA",
                    "arguments": '{"command": "echo aaa"}',
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call", "name": "shell_command",
                    "call_id": "call_BBB",
                    "arguments": '{"command": "echo bbb"}',
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call_output", "call_id": "call_AAA",
                    "output": "Exit code: 0\nOutput:\nout-aaa",
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call_output", "call_id": "call_BBB",
                    "output": "Exit code: 0\nOutput:\nout-bbb",
                }},
            ]:
                f.write(json.dumps(entry) + "\n")
        turn = codex_common.read_turn(str(path))
        assert turn is not None
        bashes = [c for c in turn.tool_calls if c["tool"] == "Bash"]
        assert len(bashes) == 2
        # Verify each command paired with its own output.
        by_cmd = {b["command"]: b["output_tail"] for b in bashes}
        assert "out-aaa" in by_cmd["echo aaa"]
        assert "out-bbb" in by_cmd["echo bbb"]
        # No cross-contamination.
        assert "out-bbb" not in by_cmd["echo aaa"]
        assert "out-aaa" not in by_cmd["echo bbb"]


# ---------------------------------------------------------------------------
# Cross-parser apply_patch destination contract
# ---------------------------------------------------------------------------


class TestApplyPatchDestination:
    """The patch_bodies field is the contract the operational-fact spec reads.
    Pin it on both copies (Claude Code rarely sees apply_patch but the
    extractor branch is shared)."""

    def test_codex_freeform_body_metadata_field(self, tmp_path):
        path = tmp_path / "codex_apply_patch_freeform.jsonl"
        with open(path, "w") as f:
            for entry in [
                {"type": "response_item", "payload": {
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": "Fix it."}],
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call", "name": "apply_patch",
                    "call_id": "ap1",
                    "arguments": "*** Begin Patch\n*** Update File: a.py\n+x\n*** End Patch",
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call_output", "call_id": "ap1",
                    "output": "Patch applied",
                }},
            ]:
                f.write(json.dumps(entry) + "\n")
        turn = codex_common.read_turn(str(path))
        assert turn is not None
        meta = codex_common.build_work_trace_metadata(turn)
        assert meta is not None
        assert "patch_bodies" in meta
        assert len(meta["patch_bodies"]) == 1
        pb = meta["patch_bodies"][0]
        assert "body" in pb
        assert "*** Begin Patch" in pb["body"]
        assert "operation" not in pb  # freeform form has no operation

    def test_codex_structured_operation_metadata_field(self, tmp_path):
        path = tmp_path / "codex_apply_patch_call.jsonl"
        with open(path, "w") as f:
            for entry in [
                {"type": "response_item", "payload": {
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": "Fix it."}],
                }},
                {"type": "response_item", "payload": {
                    "type": "apply_patch_call", "call_id": "ap2",
                    "operation": {
                        "type": "create_file",
                        "path": "new.py",
                        "diff": "+content",
                    },
                }},
                {"type": "response_item", "payload": {
                    "type": "apply_patch_call_output", "call_id": "ap2",
                    "output": {"status": "completed"},
                }},
            ]:
                f.write(json.dumps(entry) + "\n")
        turn = codex_common.read_turn(str(path))
        assert turn is not None
        meta = codex_common.build_work_trace_metadata(turn)
        assert meta is not None
        assert "patch_bodies" in meta
        pb = meta["patch_bodies"][0]
        assert "operation" in pb
        assert pb["operation"]["type"] == "create_file"
        assert pb["operation"]["path"] == "new.py"
        # Path also lands in files_modified.
        assert "new.py" in turn.files_modified
        assert turn.has_productive_action is True
