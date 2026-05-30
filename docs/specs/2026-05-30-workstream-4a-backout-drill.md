# Phase 4A Workstream Backout Drill (design 014)

Date: 2026-05-30
Status: Procedure documented; the env-var disable hook is intentionally NOT
shipped in 4A — the architect will wire it if/when needed.

## What this verifies

Phase 4A is **additive**: schema and code paths populate diagnostic data
but never alter retrieval, routing, or consolidation behavior. The backout
drill confirms that disabling population at a single guard leaves the
schema in place inert, and that no test breaks when nothing is being
populated.

## Single guard location

The intended guard sits at the entry point of
`capabilities/workstreams.py`. The cascade is invoked exclusively through
`WorkstreamCapability` (and the thread-rebuild hook
`ThreadRebuilder._maybe_assign_workstreams`). Disabling either of:

- `_build_workstream_capability(...)` in `core/service.py` (returns
  `None` instead of constructing the capability), or
- `ThreadRebuilder.__init__(workstream_capability=None)`
  (caller passes `None` instead of the live capability),

will short-circuit every population path. Both `_maybe_assign_workstreams`
and the audit-log workstream lookups guard on
`self._workstream_capability is None`.

A future env-var flag (`pallium.workstreams.enabled`, default `true`)
should branch in `_build_workstream_capability` and return `None`
when disabled. **Not shipped in 4A.**

## Drill steps

1. **Disable population.** In a staging DB, edit
   `_build_workstream_capability` in `core/service.py` to return `None`.
   Restart the service.

2. **Run the existing test suite.**

   ```bash
   python -m pytest tests/ -x -q
   ```

   Expected: zero regressions. Phase 4A code paths handle a `None`
   capability gracefully at every entry point:
   - `ThreadRebuilder._maybe_assign_workstreams` returns early.
   - Audit-log writes set `query_workstream_id=None` and per-candidate
     `workstream_id=None` in `candidate_scores_json`.
   - Consolidation runs without emitting the dry-run metric (the helper
     `emit_dryrun_metrics` is a no-op when capability is `None`).

3. **Verify queries still produce audit-log rows.** Issue a `/query` call
   against the staging service and confirm `query_audit_log` rows appear
   without `query_workstream_id` populated:

   ```sql
   SELECT id, query_workstream_id FROM query_audit_log ORDER BY created_at DESC LIMIT 5;
   ```

   Readers (`evals/post_routing_selection_audit/audit.py`,
   `evals/workstream_consolidation/audit.py`) tolerate the absence of
   the field on rows where it was not populated.

4. **Verify thread-rebuild still runs cleanly without populating
   junction tables.** Ingest a fixture, drain the queue, and confirm
   the `workstreams`, `memory_workstreams`, and
   `source_item_workstreams` tables remain empty (or unchanged from
   pre-drill state).

5. **Verify consolidation runs cleanly without emitting dry-run metric.**
   Trigger a consolidation pass and confirm no rows appear with
   `category='consolidation' AND event_type IN ('workstream_aware_dryrun',
   'workstream_homogeneity')` in the `metrics` table for the drill
   window.

## Re-enable

Revert the local edit to `_build_workstream_capability` (or, in a future
flagged version, set the env var back to `true`) and restart. New writes
populate again; the existing rows are untouched.

## Production-class instances

Per the 4A backout principle (design 014, §"Phase 4A backout — disable,
don't drop"), production-class instances should not need to drop tables
to back out behavior-neutral diagnostics. Schema retention is the default
backout; only a fresh-DB reset chosen by the operator drops the additive
columns and tables.

## References

- Design: `docs/designs/014-workstream-consolidation-rekey.md`
- Implementation log: `.local/research/phase_4a_implementation_log.md`
- Roadmap entry: `roadmap/features/add-workstream-rolling-topic.md`
