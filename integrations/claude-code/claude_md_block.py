"""CLAUDE.md instruction block for Pallium integration."""

CLAUDE_MD_BLOCK = """\
<!-- pallium:start -->

## Pallium

Pallium has two primary capabilities: Relay and Session History.
It also has optional derived memory:

- **Relay** sends useful context to another agent session when its work should change.
- **Session History** finds relevant work from earlier sessions.
- **Derived memory** is optional compact context that may be injected or queried.

### Relay

- Discover recipients with `pallium_relay_recipients`; name a session with `pallium_relay_name`.
- Send with `pallium_relay_send` to a runtime, exact session, or alias. Runtime-wide sends need explicit user intent.
- Treat delivered messages as current-turn work. Complete actionable payloads now; reply with `pallium_relay_reply` after completion or a genuine blocker, not with a status-only acknowledgment.
- Injected `agent_ref` and `thread_ref` identify this session; never infer self from recipient lists.
- Do not reply to terminal ACK-only deliveries. If a delivery is already delivered or conflicting, only that copy is stale: do not retry, reply, or use its payload; continue independently established work.

### Session History

Picking up prior work? Choose the narrow or broad search below.

`pallium_search_history_by_work_ref`
Narrow exact-ref continuity. Pass a valid structural ref; Pallium normalizes it. It can miss related work under another/no ref. Omit `query` for newest eligible items.

`pallium_search_history`
Broad topic search across eligible history/work items. Its `work_refs` filter is compatibility-only.

`pallium_expand_source`
After a promising search hit, call `pallium_expand_source` with its `source_item_id` and pass the search result's `lookup_event_id` as `parent_lookup_id`.

Copy the injected `container_ref` exactly—never derive, guess, or normalize it. Pass the active `thread_ref` to search and expansion for telemetry. Pass an injected `request_source_item_id` only to either history search. These values are not authorization or the historical source identity.

### Derived memory

- Search distilled memory with `pallium_query`; use `pallium_query_debug` to distinguish filtered, missing, and low-relevance results. Use `pallium_expand` when a memory card offers expansion.
- Store a deliberate note with `pallium_ingest`, `artifact_kind="note"`, `visibility: "private"`, and the injected `container_ref`. Use global visibility only when explicitly requested, with `actor_ref`.
- Flag incorrect or obsolete memory with `pallium_flag_memory`. `pallium_rate_memory` is optional feedback.
- `pallium_remember` stores a durable fact; `pallium_correct` fixes it; `pallium_supersede` replaces it; `pallium_forget` hides it; `pallium_record_outcome` records a procedure result.
- Remember, supersede, and record-outcome writes copy exact `container_ref`, `thread_ref`, `actor_ref`, `agent_ref`, and `visibility`. Never use cwd. Default private; correction and forget retain provenance.
- Retrieval alone never updates accessibility or ranking. Do not ingest routine turns, re-query for something already in the injected block, or use forget as vote suppression.
<!-- pallium:end -->"""

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
