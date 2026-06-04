# session_replay

Offline eval runner that takes any Claude Code or Codex session JSONL
transcript and produces labeled miss-case rows joined to the Pallium
`query_audit_log`.

The runner answers two related questions:

1. *Did the right memory get injected for this turn?* — by checking the
   transcript itself (the literal `[Pallium memory ...]` block reaches the
   model in the Claude Code `UserPromptSubmit` hook attachment, or in a
   developer/user message on the Codex side).
2. *If not — which stage of the Pallium pipeline failed?* — by joining
   each user turn to its `query_audit_log` row, decoding
   `candidate_scores_json`, and labeling one of:

       injected_ok          ✓ memory was injected
       no_audit_match       no audit row matched this turn at all
       not_ingested         audit row exists, candidate set empty
       superseded           rank-1 candidate has lifecycle=superseded
       routing_suppressed   top candidates dropped by a named routing code
       retrieval_low_score  decision_reason ∈ {low_score, no_relevant_memory}
                            and no top candidate scored above zero
       unknown              no named drop code; surface for manual review

Pure offline. No LLM calls. Read-only on the live DB.

## Why this complements existing evals

`evals/post_routing_selection_audit/audit.py` already pivots audit rows by
`excluded_reason_code` / `suppression_reason_code` — but only for
`decision_reason='carry_forward_available'` rows.
`evals/agent_correction_analysis.py` already classifies user corrections
from `source_items` using an LLM. Neither tool reads the raw session
JSONL transcripts, so neither can:

- recover the actual `tool_use`/`tool_result` traces that drive
  `repeated_work` and `future_oracle` signals (those events live only in
  the transcript, not in the DB)
- attribute a miss to `superseded` (rank-1 candidate has
  `lifecycle=superseded`) — distinct from a routing-stage drop
- answer "was Pallium injected for THIS turn?" against the literal
  injection text the model received

This runner fills exactly those gaps. It does not replace the existing
audit; it composes with it.

## Usage

Single transcript file:

    python -m evals.session_replay path/to/session.jsonl

Whole directory tree (recursive `*.jsonl` glob):

    python -m evals.session_replay --dir ~/.claude/projects/c--Dev-rore-Pallium

Multiple `--dir` flags compose. Per-file paths and `--dir` can mix.

Override the Pallium DB:

    python -m evals.session_replay path/... --db ~/.pallium/data/pallium.db

Restrict audit-row matching to a single container:

    python -m evals.session_replay path/... --container-ref git:github.com/rore/pallium

Enable a subset of signals:

    python -m evals.session_replay path/... --signal recall_intent --signal repeated_work

Output directory (default `evals/session_replay/output/`):

    python -m evals.session_replay path/... --out .local/research/replay-2026-06-04

## Output

The runner writes two files into `--out`:

- `miss_cases.jsonl` — one JSON object per (turn × signal). Top-level
  fields:

      session_file, session_id, cwd, source_format, turn_index, turn_ts,
      user_text, miss_signal, matched_phrase,
      was_injected_observed, n_pallium_blocks_observed, pallium_refs_observed,
      audit_match: { audit_id, container_ref, should_inject,
                     decision_reason, n_candidates, n_injected, created_at },
      failure_stage, failure_evidence,
      top_candidates: [{ memory_id, type, rank, routing_score,
                         lexical_score, vector_score, layer, support_grade,
                         suppression_reason, excluded_reason, drop_reason,
                         injected }, ...]

- `summary.md` — counts by signal, by failure stage, per-file breakdown,
  and a small sample of `routing_suppressed` cases for human review.

## Signals

| Signal | What it flags | Why transcript-only |
|--------|--------------|---------------------|
| `recall_intent` | User prompt is a continuation/recall request ("continue", "what did we decide", "summarize", "next tasks", ...) | Could be done from `source_items`; keeping it here so all signals share one mining pass over real prompts. |
| `repeated_work` | Same `Read.file_path` or `Grep.pattern` appears in 2+ turns of the same session | Tool-call traces are not stored in `source_items` or `query_audit_log` — they live only in the transcript. |
| `future_oracle` | A vague continuation prompt is followed by ≥2 discovery tool calls and zero productive actions in the same turn | Same — needs the tool-call sequence per turn. |

User-correction phrase mining is intentionally **not** in this module.
`evals/agent_correction_analysis.py` does it better against the DB with an
LLM classifier; reusing its output is preferred over rebuilding with regex.

## Determinism and side effects

- Read-only on `~/.pallium/data/pallium.db` (or whatever `--db` points
  at). The connection is opened with the SQLite URI mode `?mode=ro`.
- Zero network calls. Zero LLM calls.
- Output files are overwritten on each run; deletion is the user's
  responsibility.

## Tests

    python -m pytest tests/test_session_replay.py -x -q

Tests build synthesized Claude Code and Codex JSONL fixtures and a small
SQLite DB matching the columns the runner reads. They do **not** depend
on any real session file or the real production DB.

## Known limitations

- Audit-row matching is by `query_text LIKE <prefix>%`. Two different
  user turns whose prompts share a long common prefix may match the same
  audit row; the runner picks the most recent. For tightest matching,
  pass `--container-ref`.
- The Pallium `UserPromptSubmit` hook deduplicates prompts within a
  session for 5 minutes. A repeated identical prompt in the same window
  produces no audit row and will surface as `no_audit_match`.
- Memory state is whatever is in the DB *now*. Point-in-time freezing
  (`memory_objects.created_at <= turn_ts`) is a planned phase-2 addition
  — see [`c:/tmp/pallium-replay-feasibility/REPORT.md`](../../../tmp/pallium-replay-feasibility/REPORT.md)
  for the longer roadmap.
