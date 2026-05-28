# `same_thread_skip_override` — offline replay analysis

Read-only analysis to test whether `same_thread_context_sufficient` skip
decisions in `query_audit_log` over-suppress useful cross-thread carry-forward.

## What it does

1. Pulls every `query_audit_log` row since `2026-05-18` whose
   `decision_reason = 'same_thread_context_sufficient'` from the live DB at
   `~/.pallium/data/pallium.db`.
2. For each row, classifies every candidate in `candidate_scores_json` as
   same-thread or cross-thread by joining `memory_object_id` →
   `relations.supported_by` → `source_items.thread_ref`.
3. Computes query-token overlap with each candidate's subject (subject derived
   via `core.subject.subject_text_for_payload`, tokens via
   `core.text.normalize_for_index`).
4. Applies Codex's proposed override rule (3 conjunctive conditions on
   overlap, low-value, and supported-type/payload).
5. Cross-tabulates the would-be-promoted memories against `memory_feedback`
   ratings as a precision proxy.
6. Writes:
   - `.local/research/same_thread_skip_override_2026-05-28.md` — summary report.
   - `.local/research/_same_thread_override_run.md` — raw run log + sample shapes.

## Important constraint

`source_evidence` candidates have `memory_object_id = NULL` in the audit log,
so this replay can't classify them by thread. Only structured-memory
candidates (decision, investigation_outcome, task_checkpoint,
thread_summary, constraint_memory, atomic_fact) participate in the
override decision. The report makes this caveat explicit.

## Run

From the repo root:

```bash
python -m evals.same_thread_skip_override.replay
```

No LLM calls. No production code changes. Read-only on the DB.
