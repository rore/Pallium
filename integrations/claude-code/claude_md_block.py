"""CLAUDE.md instruction block for Pallium integration."""

CLAUDE_MD_BLOCK = """\
<!-- pallium:start -->
## Memory (Pallium)

Use Pallium for deliberate memory work; automatic injection handles routine retrieval.

Picking up prior work? Call `pallium_search_history` first. After a promising search hit, call `pallium_expand_source` with its `source_item_id` and pass the search result's `lookup_event_id` as `parent_lookup_id`. Copy the injected `container_ref` exactly—never derive, guess, or normalize it. Pass the active `thread_ref` to both tools for telemetry; it is not authorization or the historical source identity.
- Search distilled memory with `pallium_query`; use `pallium_search_history` for raw turns and `pallium_expand_source` for bounded context.
- Store turns with `pallium_ingest` (`artifact_kind="note"`, `visibility: "private"`, and the injected `container_ref`). Use global visibility only when explicitly requested, with `actor_ref`.
- Use `pallium_query_debug` to distinguish filtered, missing, and low-relevance results; use `pallium_expand` when a memory card offers expansion.
- Use `pallium_flag_memory` for incorrect or obsolete memories. `pallium_rate_memory` is optional, non-blocking feedback; never require a rating for every injected block.
- For explicit remember, supersede, and record-outcome writes, copy exact Pallium scope values for container_ref, thread_ref, actor_ref, agent_ref, and visibility; pass all five exactly, never raw cwd. Default to private; use global only when explicitly requested. Correction and forget retain the original creation provenance.
- Explicit writes are compact and deliberate: `pallium_remember` stores a durable fact; `pallium_correct` fixes it; `pallium_supersede` replaces an obsolete fact; `pallium_forget` hides it; `pallium_record_outcome` records a procedure result. Retrieval is not use: these writes do not update accessibility or ranking from retrieval alone.
- Do not ingest routine turns or re-query for something already in the injected block; use forget only for direct hiding, not vote suppression; use `pallium_flag_memory` for that.
<!-- pallium:end -->
"""

# Appended to the base block for the "strong" guidance-strength arm. Authored
# to avoid the token "MANDATORY" and the banned legacy strings so the block
# invariants still hold on the strong variant.
_STRONG_DIRECTIVE = """\

### Resuming prior work

When you resume or continue prior work on this task, call
`pallium_search_history` first — before assuming that earlier context is gone.
Pull the raw prior turns (a past discussion, an earlier attempt, the original
context of a decision) and read them before acting, rather than starting cold.

"""


def get_claude_md_block(strength: str = "base") -> str:
    """Return the CLAUDE.md block variant for the given guidance strength.

    - ``"base"`` (default): the block as-is. It already carries a block-level
      permit nudge to call ``pallium_search_history`` when resuming prior work;
      it is NOT a zero-guidance baseline.
    - ``"strong"``: the base block plus an appended "call it first" resume
      directive. The measured contrast between the two arms is therefore
      *permit-nudge* vs *permit-nudge + call-first*, not presence-vs-absence of
      guidance.

    An arm-marker comment recording the chosen arm is embedded inside the
    marker-bounded block so an operator can read which arm was installed.
    """
    if strength not in ("base", "strong"):
        raise ValueError(f"unknown guidance strength: {strength!r}")

    arm_marker = f"<!-- pallium:guidance-strength={strength} -->"
    block = CLAUDE_MD_BLOCK.replace(
        "<!-- pallium:start -->\n",
        f"<!-- pallium:start -->\n{arm_marker}\n",
        1,
    )
    if strength == "strong":
        block = block.replace(
            "<!-- pallium:end -->",
            _STRONG_DIRECTIVE + "<!-- pallium:end -->",
            1,
        )
    return block

