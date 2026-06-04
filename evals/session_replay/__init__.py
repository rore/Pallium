"""Session replay eval runner.

Ingests real Claude Code or Codex session JSONL transcripts and pivots each
user turn to:

  * the matching ``query_audit_log`` row in the Pallium DB,
  * miss-signal flags derived from the transcript,
  * a failure-stage classification derived from ``candidate_scores_json``.

Output is a ``miss_cases.jsonl`` row per (turn × signal) plus a markdown
summary for human review.

This is an offline-only evaluation utility — read-only on the live DB,
no production code paths, no LLM calls.
"""
from __future__ import annotations
