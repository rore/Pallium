"""CLAUDE.md instruction block for Pallium integration."""

CLAUDE_MD_BLOCK = """\
<!-- pallium:start -->
## Memory (Pallium)

You have access to Pallium, a memory system that remembers decisions, outcomes,
constraints, and context across sessions.

**Automatic (every turn):** Relevant memories are injected into context via hooks.
Trust this — it handles ~90% of cases. Don't duplicate it with manual queries.

**MANDATORY — every turn with injected memories:**
You MUST call `pallium_rate_memory` for EACH injected memory block before or alongside
your response. Rate "relevant" if it informed your work, "not_relevant" if off-topic.
Always include: a brief reason, the user's message as `query_context`, and `container_ref`
from the injection header. Both signals matter equally — this feedback loop trains
retrieval quality. Do not skip this even when focused on implementation work.

**When to use other explicit tools:**
- `pallium_query` — injected context is empty or missing something the user asked about
- `pallium_get_evidence` — you need the original conversation behind a memory card, or when a card has `[+source]` and is relevant to the current task (signals the source is substantially richer than the card)
- `pallium_flag_memory` — a memory contradicts what you now know to be true
- `pallium_ingest` — user explicitly asks to remember something (hooks already ingest automatically)

**Required parameters for manual tool calls:**
When calling `pallium_query`, `pallium_get_evidence`, or `pallium_ingest`, always pass:
- `visibility`: "private" (all memories in this integration are private)
- `container_ref`: use the value from the injection header (e.g. "git:github.com/rore/pallium")

Without these, queries will return empty results. The automatic hooks pass them
correctly — you only need to worry about this for explicit tool calls.

**Do not:**
- Query every turn — automatic injection handles routine retrieval
- Re-query for something already in the injected Pallium block
- Ingest routine conversation — hooks do this automatically
- Flag speculatively — only flag when you have concrete contrary evidence
<!-- pallium:end -->
"""
