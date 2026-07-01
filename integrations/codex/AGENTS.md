<!-- pallium:start -->
# Memory (Pallium)

Pallium remembers decisions, constraints, and context across sessions.

**Automatic:** hooks inject relevant memories every turn. Trust this — it
handles ~90% of cases. Don't duplicate with manual queries.

**Feedback (non-blocking):** when an injected memory is clearly useful or
clearly off-topic and the MCP tool is available, call `pallium_rate_memory`
with `container_ref` from the injection header and the user's message as
`query_context`. Don't add latency or fail the turn just to rate memory.

If a `[+expand]` card summary is enough, trust the card; fetch the source
via `pallium_expand` only when you need the original conversation to answer.

## Reach for these when you need them

- `pallium_query` — injected context is empty or missing something specific
- `pallium_expand` — see original conversation behind a memory card
- `pallium_flag_memory` — a memory contradicts what you now know is true
  (votes-based; several flags → auto-suppress)
- `pallium_ingest` — the user explicitly asks to remember something. Pass
  `artifact_kind="note"` to preserve their words verbatim; omit it to let
  extraction produce typed memory objects. Do not use for routine
  conversation — hooks handle that.

## Deliberate memory writes (use sparingly, high confidence only)

These tools let you shape memory directly. Only use when a fact is worth
keeping AND automatic extraction may miss it. Do not call them on every
turn — the hook pipeline is already capturing conversation.

- `pallium_remember(text, type, ...)` — durable fact. `type` is one of:
  `decision`, `investigation_outcome`, `constraint_memory`,
  `operational_fact`, `note`. Use when the user has just stated an
  architectural decision, hard constraint, or investigation conclusion that
  should survive compaction.
- `pallium_correct(memory_id, corrected_text, reason)` — fix a wrong memory
  in place (extraction was mislabeled or partial). For fully obsolete
  memories, use `pallium_supersede` instead. Returns 409 if the memory is
  already superseded — walk the chain via `pallium_expand` and correct the
  head.
- `pallium_supersede(new_text, supersedes_id, reason?)` — replace an
  obsolete memory. Both rows persist; retrieval hides the old. Use when the
  old was correct at the time but a different fact now applies. Returns 409
  on double-supersede.
- `pallium_forget(memory_id, reason)` — soft-delete. Retrieval hides it;
  audit trail preserved. Use when a memory is misleading or no longer
  relevant. This is agent-decisive and immediate — use `pallium_flag_memory`
  instead when you're one voter among many. Idempotent.
- `pallium_record_outcome(procedure_id, outcome, ...)` — record success /
  failure / inconclusive for an operational_fact procedure.

Confidence you pass to `pallium_remember` is audit-only. It does not boost
retrieval ranking — ranking updates need evidence of downstream use (you
cited it, action changed, user confirmed, procedure outcome recorded).

## Required parameters for manual calls

When calling `pallium_query`, `pallium_expand`, `pallium_ingest`, or
`pallium_remember`:

- `container_ref` — take from the injection header
  (e.g., `git:github.com/user/repo`)
- `visibility` — `"private"` (project-scoped, default) or `"global"` when
  the user asks to remember across all projects (requires `actor_ref`)

Missing these → empty results. Automatic hooks pass them correctly; you
only need them for manual calls.

## Do not

- Query every turn or re-query for something already in the injected block
- Ingest routine conversation (hooks do this)
- Flag speculatively — only on concrete contrary evidence
- Call `pallium_remember` on every turn — deliberate writes only
- Use `pallium_forget` for votes-based suppression — that's `pallium_flag_memory`

## Abstention policy (opt-in, TOML)

An `[injection.policy]` config can demote types like `task_checkpoint`,
`investigation_outcome`, `thread_summary`, `fact_summary` from proactive
injection to event- or on-demand mode. When enabled you'll see fewer cards
auto-injected — by design, not by failure. Reach for `pallium_query` more
aggressively when stuck (failed tool calls, repeated retries, "have we hit
this before"). Default install does NOT enable the policy. See
`docs/specs/2026-06-27-injection-policy-abstention.md`.
<!-- pallium:end -->
