"""CLAUDE.md instruction block for Pallium integration."""

CLAUDE_MD_BLOCK = """\
<!-- pallium:start -->
## Pallium

Pallium provides:

- **Relay:** coordinate independent agent sessions.
- **Session History:** resume earlier work.
- **Derived memory:** optional compact context.

Load the `pallium-memory` skill when any applies. When no capability applies, answer normally without loading the skill.

### Always-safe rules

- Copy injected `container_ref`, `thread_ref`, `actor_ref`, `agent_ref`, `request_source_item_id`, and `work_ref` exactly when required. Never derive identity or scope from cwd, recipients, or history. If required scope is missing, skip that scoped call; never call it with guessed or absent values.
- For hook-injected Relay payloads: The hook owns claim and ACK, so never call receive for it. Act or report a blocker; ignore ACK-only deliveries. Never ACK through raw HTTP; use Relay tools. A trace state of `delivered` does not make its payload stale. Only an explicit `already_delivered` or conflict from a claim/ACK/reply operation marks that copy stale; do not reuse it.
- Relay sends only to canonical `relay-session-...` or global `@name`; no broadcast/bare runtime. Ask before takeover. Cross-container routing never changes History or memory scope. Queued or wake evidence is not receipt. For an exact empty-wake instruction, pass its supplied `relay-delivery-*` identifier as Relay trace's `message_id`; do not receive or resend.
- Picking up prior work? Search the injected exact `work_ref` when present; otherwise search broadly. Never guess a History search filter. Work associations use only exact provider-returned references.
- For History searches, pass injected `request_source_item_id` only there, expand a returned `source_item_id` with its `lookup_event_id` as `parent_lookup_id`, and omit `actor_ref` unless an exact metadata filter is requested.
- History retry: keep a delivered-page ledger across query repair; retry the same failed page at most twice, continue unread pages, and keep page-specific lookup lineage. Revalidate completed sources by content revision; use bounded retries. A historical recap is not live state; verify current state live. Load the installed `pallium-memory` skill's History replay procedure.
- Retrieval alone never changes accessibility or ranking. Derived memory is optional and private by default; global writes require intent. New memory writes copy exact injected provenance; correction and forget retain existing provenance. Work associations are optional, grant no access or ownership, and are skipped without exact identity/tools. Do not ingest routine turns or re-query content already injected.

Use skill/tool descriptions for procedures.
<!-- pallium:end -->"""

# Appended to the base block for the "strong" guidance-strength arm. Authored
# to avoid the token "MANDATORY" and the banned legacy strings so the block
# invariants still hold on the strong variant.
_STRONG_DIRECTIVE = """\

### Resuming prior work

When you resume or continue prior work on this task, call
`pallium_search_history_by_work_ref` first when a valid structural work ref is
known; otherwise call `pallium_search_history` before assuming that earlier
context is gone.
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
