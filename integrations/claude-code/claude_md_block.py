"""CLAUDE.md instruction block for Pallium integration."""

CLAUDE_MD_BLOCK = """\
<!-- pallium:start -->
## Memory (Pallium)

You have access to Pallium, a memory system that remembers decisions, outcomes,
constraints, and context across sessions.

**Automatic (every turn):** Relevant memories are injected into context via hooks.
Trust this — it handles ~90% of cases. Don't duplicate it with manual queries.

**When to use explicit tools:**
- `pallium_query` — injected context is empty or missing something the user asked about
- `pallium_get_evidence` — you need the original conversation behind a memory card
- `pallium_flag_memory` — a memory contradicts what you now know to be true
- `pallium_rate_memory` — rate every injected memory each turn: "relevant" if it informed your response, "not_relevant" if off-topic. Always include a brief reason and the user's message as query_context (required). This feedback loop trains retrieval quality — both signals matter equally.
- `pallium_ingest` — user explicitly asks to remember something (hooks already ingest automatically)

**Do not:**
- Query every turn — automatic injection handles routine retrieval
- Re-query for something already in the injected Pallium block
- Ingest routine conversation — hooks do this automatically
- Flag speculatively — only flag when you have concrete contrary evidence
<!-- pallium:end -->
"""
