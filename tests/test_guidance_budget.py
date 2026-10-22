from pathlib import Path
import ast
import importlib.util


def test_rendered_guidance_and_tool_descriptions_stay_under_measured_ceilings() -> None:
    spec = importlib.util.spec_from_file_location("claude_block", "integrations/claude-code/claude_md_block.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert len(module.get_claude_md_block("base")) <= 2858
    assert len(module.get_claude_md_block("strong")) <= 3274
    assert len(Path("integrations/codex/AGENTS.md").read_text(encoding="utf-8")) <= 2819
    assert len(Path("integrations/opencode/AGENTS.md").read_text(encoding="utf-8")) <= 2819
    for runtime in ("claude-code", "codex", "opencode"):
        skill = Path(f"integrations/{runtime}/skills/pallium-memory/SKILL.md")
        assert len(skill.read_bytes().replace(b"\r\n", b"\n")) <= 3072
    relay_rule = "- Reconcile work/state; keep late findings. Skip completed actions/routine replies; follow authorized work. Reply on completion/blocker."
    skills = [Path(f"integrations/{runtime}/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8")
              for runtime in ("claude-code", "codex", "opencode")]
    assert all(relay_rule in skill.splitlines() for skill in skills)
    assert skills[1:] == skills[:-1]
    guide = " ".join(Path("docs/agent-relay.md").read_text(encoding="utf-8").split())
    assert "Check prior handling of the exact stable `delivery_id` in the current context or existing work artifacts." in guide
    assert "A first claim does not prove that no equivalent business action happened elsewhere." in guide
    assert "Different IDs identify separate deliveries, not necessarily separate business actions or new authority." in guide
    assert "Reconcile each message with the current authorized task known to you and verified work state." in guide
    assert "Age or arrival order alone does not establish supersession." in guide
    tree = ast.parse(Path("app/mcp/server.py").read_text(encoding="utf-8"))
    names = {node.name for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in {"pallium_search_history_by_work_ref", "pallium_search_history", "pallium_expand_source"}}
    assert names == {"pallium_search_history_by_work_ref", "pallium_search_history", "pallium_expand_source"}
    combined = sum(len(ast.get_docstring(node) or "") for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names)
    assert combined <= 1300

def test_cross_project_relay_discovery_is_bundled_and_safe() -> None:
    references = []
    for runtime in ("claude-code", "codex", "opencode"):
        skill = Path(f"integrations/{runtime}/skills/pallium-memory/SKILL.md")
        assert "load [global discovery](references/global-relay-discovery.md)" in skill.read_text(encoding="utf-8")
        reference = skill.parent / "references/global-relay-discovery.md"
        assert reference.is_file()
        references.append(reference.read_bytes())
    assert references[1:] == references[:-1]
    guidance = references[0].decode("utf-8")
    for required in (
        "pallium_relay_discover_recipients",
        "target container is unknown",
        "all matching containers",
        "match_status=ambiguous",
        "next_offset",
        "not a frozen snapshot",
        "title_hint",
        "not observed live reachability",
        "Even `single_candidate` does not establish ownership",
        "exact_selector",
        "GET /dashboard/api/relay/sessions",
        "maximum 200",
        "All history",
        "verified canonical `relay-session-...`",
        "current `@name`",
        "sender's injected `container_ref`",
        "inspect the returned admission destination",
        "pallium_relay_address",
        "saved or uncertain send",
    ):
        assert required in guidance


def test_all_guidance_surfaces_present_pallium_capabilities() -> None:
    spec = importlib.util.spec_from_file_location(
        "claude_block_capabilities", "integrations/claude-code/claude_md_block.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    global_surfaces = (
        module.get_claude_md_block("base"),
        Path("integrations/codex/AGENTS.md").read_text(encoding="utf-8"),
        Path("integrations/opencode/AGENTS.md").read_text(encoding="utf-8"),
    )
    detail_surfaces = (
        Path("integrations/claude-code/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8"),
        Path("integrations/codex/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8"),
        Path("integrations/opencode/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8"),
        Path("integrations/opencode/.opencode/command/pallium-memory.md").read_text(encoding="utf-8"),
    )
    for rendered in global_surfaces:
        assert "Pallium provides:" in rendered
        assert "**Relay:** coordinate independent agent sessions" in rendered
        assert "**Session History:** resume earlier work" in rendered
        assert "**Derived memory:** optional compact context" in rendered
        assert "Load the `pallium-memory` skill when any applies" in rendered
        assert "When no capability applies, answer normally without loading the skill" in rendered
    for rendered in (*global_surfaces, *detail_surfaces):
        assert "Relay" in rendered
        assert "Session History" in rendered
        assert "Derived memory" in rendered or "derived memory" in rendered
        assert "Pallium Memory Workflow" not in rendered

def test_all_guidance_surfaces_preserve_search_to_expansion_telemetry_link() -> None:
    spec = importlib.util.spec_from_file_location("claude_block_linkage", "integrations/claude-code/claude_md_block.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    global_surfaces = (
        module.get_claude_md_block("base"),
        module.get_claude_md_block("strong"),
        Path("integrations/codex/AGENTS.md").read_text(encoding="utf-8"),
        Path("integrations/opencode/AGENTS.md").read_text(encoding="utf-8"),
    )
    skill_surfaces = (
        Path("integrations/claude-code/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8"),
        Path("integrations/codex/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8"),
    )
    for rendered in global_surfaces:
        assert all(token in rendered for token in (
            "`source_item_id`",
            "`lookup_event_id`",
            "`parent_lookup_id`",
        ))
        assert "Never derive identity or scope" in rendered
    linkage = ("After a promising search hit, call `pallium_expand_source` with its "
               "`source_item_id` and pass the search result's `lookup_event_id` as "
               "`parent_lookup_id`.")
    assert all(linkage in rendered for rendered in skill_surfaces)
    assert all("never derive, guess, or normalize" in rendered for rendered in skill_surfaces)


def test_global_guidance_surfaces_preserve_compact_safeguards() -> None:
    spec = importlib.util.spec_from_file_location("claude_block_safeguards", "integrations/claude-code/claude_md_block.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    surfaces = (
        module.get_claude_md_block("base"),
        Path("integrations/codex/AGENTS.md").read_text(encoding="utf-8"),
        Path("integrations/opencode/AGENTS.md").read_text(encoding="utf-8"),
    )
    required = (
        "If required scope is missing, skip that scoped call",
        "never call it with guessed or absent values",
        "The hook owns claim and ACK, so never call receive for it",
        "Never ACK through raw HTTP",
        "A trace state of `delivered` does not make its payload stale",
        "claim/ACK/reply operation marks that copy stale",
        "Queued or wake evidence is not receipt",
        "pass its supplied `relay-delivery-*` identifier as Relay trace's `message_id`; do not receive or resend",
        "Never guess a History search filter",
        "omit `actor_ref` unless an exact metadata filter is requested",
        "Retrieval alone never changes accessibility or ranking",
        "New memory writes copy exact injected provenance",
        "correction and forget retain existing provenance",
        "Work associations are optional, grant no access or ownership",
    )
    for rendered in surfaces:
        assert all(rule in rendered for rule in required)

def test_relay_guidance_covers_stale_delivery_and_recipient_identity() -> None:
    skills = (
        Path("integrations/claude-code/skills/pallium-memory/SKILL.md"),
        Path("integrations/codex/skills/pallium-memory/SKILL.md"),
        Path("integrations/opencode/skills/pallium-memory/SKILL.md"),
    )
    rule = ("only that delivery copy is stale: do not retry/reply/use its payload, but "
            "continue the surrounding user task and independently established work")
    assert all(rule in skill.read_text(encoding="utf-8") for skill in skills)
    routing = "Role target: current `@name`; rediscover before endpoint reuse"
    snapshot = "Check returned admission session/container if scope matters"
    movement = "Aliases/endpoints move; neither proves scope"
    stale_trigger = "On `already_delivered=true` or conflict"
    assert all(all(item in skill.read_text(encoding="utf-8") for item in (routing, snapshot, movement, stale_trigger)) for skill in skills)
    sender_rules = (
        "Send=saved, not started",
        "`busy_queue`=capability, not observed busyness",
        "pending unconfirmed",
        "let work finish",
        "ordinary turn if needed",
        "do not resend",
    )
    assert all(all(rule in skill.read_text(encoding="utf-8") for rule in sender_rules) for skill in skills)
    lease_rule = "MCP: reply/ACK before source TTL or 60s lease ends; ACK permits later reply."
    assert all(lease_rule in skill.read_text(encoding="utf-8") for skill in skills)

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


def test_work_association_guidance_is_lazy_aligned_and_safe() -> None:
    skill_paths = [
        Path(f"integrations/{runtime}/skills/pallium-memory/SKILL.md")
        for runtime in ("codex", "claude-code", "opencode")
    ]
    reference_paths = [path.parent / "references" / "work-associations.md" for path in skill_paths]
    skills = [path.read_bytes() for path in skill_paths]
    references = [path.read_bytes() for path in reference_paths]

    assert skills[1:] == skills[:-1]
    assert references[1:] == references[:-1]
    for path in skill_paths:
        skill = path.read_text(encoding="utf-8")
        assert "On pickup, resume, departure, or exact link correction" in skill
        assert "follow canonical [work participation](references/work-associations.md)" in skill
        assert "Accepted assigned implementation, investigation, testing, and substantive review qualify" in skill
        assert "casual browsing, passive inspection, and clerical edits do not" in skill
        assert (path.parent / "references" / "work-associations.md").is_file()

    detail = reference_paths[0].read_text(encoding="utf-8")
    generic, minimap = detail.split("## Explicit Minimap workflow", 1)
    assert "## Generic exact-work workflow" in generic
    assert "explicitly assigned Minimap implementation, investigation, testing, or substantive review" in minimap
    assert "For every accepted explicitly assigned Minimap" in minimap
    assert "where exact association or History continuity would help" not in minimap
    assert "Casual browsing, passive inspection, and clerical edits do not qualify" in minimap
    assert "node <skill>/runtime/cli.js roadmap item-ref <item-id> --repo <absolute-repo-path> --json" in detail
    assert "returned exact `scope_ref` and `local_ref`" in detail
    assert detail.index("If the exact pair is absent") < detail.index("attach the exact CLI-returned pair")
    assert "A successful list proves observed state" in generic
    assert "Invoke each named Pallium MCP operation only when callable" in generic
    assert "only its successful result is authoritative" in generic
    assert "This applies to list, attach, detach, participants, and History operations named here" in generic
    for operation in ("pallium_relay_work_refs", "pallium_relay_attach_work_ref", "pallium_relay_detach_work_ref", "pallium_relay_participants", "pallium_search_history_by_work_ref", "pallium_search_history"):
        assert operation in detail or all(operation in path.read_text(encoding="utf-8") for path in skill_paths)
    assert "only a successful mutation proves attachment or detachment" in generic
    assert "required tool is unavailable or fails" in generic
    assert "missing or invalid scope/local refs" in minimap
    assert "continue ordinary work and report the limitation when relevant" in generic
    assert "capacity prevents attach" in generic
    assert "at most three explicit references in addition to its structural references" in generic
    assert "never evict an unrelated reference" in generic
    assert "stable, exact `scope_ref`/`local_ref` pair from its authoritative source" in generic
    assert "a tracker key needs its project scope" in generic
    assert "identifiers must never be guessed" in generic
    assert "Do not claim success, invent references, use shell/HTTP substitutes" in generic
    assert "This read does not send or wake agents" in generic
    assert "include_closed=true` only when closed sessions matter" in generic
    assert "route with the returned canonical selector" in generic
    assert "A successful attach does not backfill untagged prior turns" in minimap
    assert "Older eligible items already carrying the same canonical key" in minimap
    assert "eligible later turns can carry it only when per-turn association lookup succeeds" in minimap
    for requirement in (
        "On pickup or resume, call `pallium_relay_work_refs`",
        "actual accepted substantive assignments",
        "Reuse an exact listed association",
        "current-session explicit origin successfully attached in an earlier turn",
        "Attach an absent exact assigned pair",
        "Keep each explicit association throughout its assignment, including ordinary waits",
        "When that assignment ends, is cancelled, or transfers away",
        "for its exact current-session explicit origin, even if the feature remains unfinished",
        "Preserve unrelated references and other sessions' links",
        "unknown assignment state is not permission to detach",
        "Branch and Agent Workflow references are hook-owned structural origins",
        "do not attach explicit duplicates or attempt to detach structural origins manually",
        "Producers refresh them from the current branch and matching Work Record",
        "ending an assignment alone does not clear them while that structural context remains",
        "does not resolve custom/resumed Work Record discovery gaps",
    ):
        assert requirement in generic
    assert "API removes only the current session's explicit origin" in detail
    assert "may report `structural_remains`" in detail
    assert "or detach merely because an optional provider is absent" in generic
    for correction_rule in (
        "For exact link correction, compare a successful list with the assignment's authoritative exact pair",
        "Detach only a proven erroneous current-session explicit origin not required by another current accepted assignment",
        "unknown or structural origins are not correction targets",
        "After successful detachment, attach or reuse the authoritative pair",
        "Preserve active assignments, unrelated references, other sessions' links, and structural origins",
        "If detachment fails, report the limitation and do not claim correction",
        "claim correction only after successful mutation results and readback confirming the authoritative pair is present and the erroneous explicit origin is absent",
    ):
        assert correction_rule in generic
    assert "task ownership, activity, acceptance, completion, receipt, or History/memory access" in detail
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
        "passes arguments without a shell",
        "If a duplicate exists",
        "do not create or comment unless separately approved",
        "--body-file",
        "Never interpolate draft, title, search, or path text",
        "`gh` is missing or unauthenticated",
        "## Field feedback (unsent)",
        "Do not add telemetry, service APIs, or feedback storage",
    ):
        assert required in detail


def test_history_guidance_preserves_replay_ledger_and_live_verification_contract() -> None:
    spec = importlib.util.spec_from_file_location("claude_block_replay", "integrations/claude-code/claude_md_block.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    surfaces = (
        module.get_claude_md_block("base"),
        module.get_claude_md_block("strong"),
        Path("integrations/codex/AGENTS.md").read_text(encoding="utf-8"),
        Path("integrations/opencode/AGENTS.md").read_text(encoding="utf-8"),
        *(Path(f"integrations/{runtime}/skills/pallium-memory/SKILL.md").read_text(encoding="utf-8")
          for runtime in ("claude-code", "codex", "opencode")),
        Path("integrations/opencode/.opencode/command/pallium-memory.md").read_text(encoding="utf-8"),
        Path("docs/claude-code-integration.md").read_text(encoding="utf-8"),
        Path("docs/codex-integration.md").read_text(encoding="utf-8"),
    )
    required = (
        "delivered-page ledger",
        "query repair",
        "retry the same failed page",
        "unread pages",
        "bounded retries",
        "page-specific lookup lineage",
        "content revision",
        "historical recap",
        "verify current state live",
    )
    for rendered in surfaces:
        assert all(term.lower() in rendered.lower() for term in required)
    assert all("Revalidate completed sources by content revision" in rendered for rendered in surfaces[4:7])

def test_history_replay_procedure_is_linked_and_complete() -> None:
    skill_paths = tuple(
        Path(f"integrations/{runtime}/skills/pallium-memory/SKILL.md")
        for runtime in ("claude-code", "codex", "opencode")
    )
    reference_paths = tuple(path.parent / "references" / "history-replay.md" for path in skill_paths)
    references = tuple(path.read_bytes() for path in reference_paths)
    assert references[1:] == references[:-1]
    procedure = references[0].decode("utf-8")
    required = (
        "delivered-page ledger",
        "successful caller delivery",
        "identical arguments: initial call plus at most two retries",
        "exact unread result/content offset and revision",
        "page-specific `lookup_event_id`",
        "terminal-probe its recorded total length with its recorded content revision",
        "unchanged probe stays complete",
        "stale response resets and restarts",
        "offset-zero response with a changed revision is consumed",
        "at most two query repairs",
        "two stale restarts per query window and per source",
        "historical recap is evidence about the past, not live state",
        "omit `role` unless the user explicitly asks for one author's turns",
        "`role=user` is not a human-authorship filter",
        "topic anchors",
        "proposals, qualifications, and acceptance",
        "not proof that the source was never stored",
        "counts toward the two query repairs",
    )
    assert all(term in procedure for term in required)
    assert all("[procedure](references/history-replay.md)" in path.read_text(encoding="utf-8")
               for path in skill_paths)

    installed_procedure = "Load the installed `pallium-memory` skill's History replay procedure."
    spec = importlib.util.spec_from_file_location("claude_block_procedure", "integrations/claude-code/claude_md_block.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert installed_procedure in module.get_claude_md_block("base")
    for path in (
        Path("integrations/codex/AGENTS.md"),
        Path("integrations/opencode/AGENTS.md"),
        Path("integrations/opencode/.opencode/command/pallium-memory.md"),
    ):
        assert installed_procedure in path.read_text(encoding="utf-8")
    assert "[procedure](../integrations/claude-code/skills/pallium-memory/references/history-replay.md)" in Path(
        "docs/claude-code-integration.md"
    ).read_text(encoding="utf-8")
    assert "[procedure](../integrations/codex/skills/pallium-memory/references/history-replay.md)" in Path(
        "docs/codex-integration.md"
    ).read_text(encoding="utf-8")
