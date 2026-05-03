<!-- pallium:start -->
# Memory (Pallium)

You have access to Pallium, a memory system that remembers decisions, outcomes,
constraints, and context across sessions.

**Automatic (every turn):** Relevant memories are injected into context via hooks.
Trust this — it handles ~90% of cases. Don't duplicate it with manual queries.

**Feedback (non-blocking):**
When an injected memory is clearly useful or clearly off-topic and the MCP tool is
available, call `pallium_rate_memory` with `container_ref` from the injection
header and the user's message as `query_context`. Do not add latency or fail the
turn solely to rate memory.

**When to use other explicit tools:**
- `pallium_query` — injected context is empty or missing something the user asked about
- `pallium_get_evidence` — you need the original conversation behind a memory card.
  If a `[+source]` card summary is sufficient, trust the card; fetch evidence only
  when you need the original conversation to answer accurately.
- `pallium_flag_memory` — a memory contradicts what you now know to be true
- `pallium_ingest` — user explicitly asks to remember something (hooks already
  ingest automatically)

**Required parameters for manual tool calls:**
When calling `pallium_query`, `pallium_get_evidence`, or `pallium_ingest`, always pass:
- `container_ref`: use the value from the injection header (e.g. "git:github.com/user/repo")
- `visibility`: "private" for project-scoped memory (default)

Without these parameters, queries will return empty results. The automatic hooks
pass them correctly — you only need to worry about this for explicit tool calls.

**Do not:**
- Query every turn — automatic injection handles routine retrieval
- Re-query for something already in the injected Pallium block
- Ingest routine conversation — hooks do this automatically
- Flag speculatively — only flag when you have concrete contrary evidence
<!-- pallium:end -->
