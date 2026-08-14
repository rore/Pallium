---
name: pallium-memory
description: Use when you need to explicitly search, store, look back at prior work, or debug Pallium memory beyond what automatic injection provides. Triggers on: "remember this", "why don't you remember", "what do you know about", resuming or continuing prior work, memory debugging, or when injected context is insufficient.
---

# Pallium Memory Workflow

## When to use this skill
- User asks you to remember something explicitly
- User asks why you don't remember something
- Injected memory context is empty but you expect it shouldn't be
- You need to search for a specific past decision or outcome
- You are resuming or building on prior work and want the raw earlier turns
- You need to debug retrieval (why was something missed)

## Steps

1. **Identify the need**: Is this a store, search, historical-lookup, or debug operation?

2. **For storing** (user says "remember this", "save this"):
   - Call `pallium_ingest` with the content
   - **Always pass `artifact_kind: "note"`** — this preserves the content faithfully
   - Pass `visibility: "private"` and `container_ref` for project-scoped memory
   - If user says "across all projects" or "globally": use `visibility: "global"` with `actor_ref`
   - Confirm to the user what was stored

3. **For searching** (user asks about past context):
   - Call `pallium_query` with a natural-language description
   - Pass `visibility: "private"` and `container_ref`
   - If results have `[+expand]`, call `pallium_expand` for richer context

4. **For historical lookup** (resuming/continuing prior work, or you want the
   raw turns rather than distilled memory):
   - Call `pallium_search_history` with a natural-language description of the
     prior work. Unlike `pallium_query` (which surfaces distilled memory and can
     abstain), this returns the raw source turns themselves, most-relevant
     first. Each result carries a stable `source_item_id`.
   - Reach for this deliberately at the start of a task or when you pick up
     related/prior work — don't assume earlier context is gone.
   - When a hit looks promising, call `pallium_expand_source` with its
     `source_item_id` to read the surrounding thread turns (the raw neighbors
     just before/after it) in context before acting.
   - Pass `visibility: "private"` and `container_ref` (from the injection
     header) on both `pallium_search_history` and `pallium_expand_source` —
     missing these returns empty results.

5. **For debugging** (user says "why don't you remember X"):
   - Call `pallium_query_debug` with the expected query
   - Report: was it found but filtered? Never stored? Low relevance score?
   - Suggest remediation (re-ingest, flag stale memory, etc.)

## Do not
- Use this skill for routine retrieval — hooks handle that automatically
- Ingest every conversation turn — hooks already do this
- Re-query for something already in the injected context (deliberate historical
  pulls when resuming prior work are fine and encouraged)
