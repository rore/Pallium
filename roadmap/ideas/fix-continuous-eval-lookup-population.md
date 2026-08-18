---
id: fix-continuous-eval-lookup-population
title: Continuous RAW/DERIVED/HYBRID eval needs an authoritative lookup population
status: done
priority: medium
commitment: uncommitted
---

## Summary

The continuous RAW/DERIVED/HYBRID evaluator sources its query population **exclusively** from
`query_audit_log`, which is **off by default**. The always-on funnel event has no query text, so it
can't substitute. On a default install the evaluator runs over zero queries and silently reports as if
there were no activity.

## Why

Verified against the code:
- `evals/raw_derived_hybrid/runner.py:79-131` — `load_query_rows()` selects `query_text, ...` only from `query_audit_log`; no fallback (`run_eval` at `:400-409`).
- `app/config.py:80` — `ObservabilityConfig.query_audit_log: bool = False` (default); writes gated at `api/routes.py:292-293, 435`.
- `storage/sqlite_schema.py:309-350` — the unconditional `HistoricalLookupReuseEventRecord` has no `query_text` column; `QueryAuditLogRecord:191` does.

Severity is **P2, not P1**: this is an offline, opt-in research eval (`python -m evals.raw_derived_hybrid`,
DATA-READ-ONLY), and query auditing is its documented prerequisite. The real gap is that the evaluator
treats a missing population as "no activity" instead of reporting coverage.

## In Scope

- One authoritative lookup-attempt population. Options: persist a privacy-safe query representation on
  the unconditional lookup event; or a stable reference from the event to a protected query record; or
  make the audit record mandatory for historical lookup with configurable content redaction.
- Evaluator visibly reports population size and excluded-record reasons rather than silently emitting 0.

## Out of Scope

- Changing what proactive injection measures.
- Retrieval behavior changes.

## Done When

1. Default-config E2E: lookups via MCP with auditing off → evaluator represents every eligible lookup exactly once and reports population size + exclusion reasons.
2. Config-equivalence: same logical population with auditing on/off; no KPI change caused solely by the toggle; sensitive text follows the privacy policy.
3. Measurement honesty: each output states whether it measures candidate recovery, injection precision, or downstream effect — a shadow replay is never labeled observed downstream improvement.

## Notes

External-review register item 6 (reviewer said High; downgraded to Medium/P2 on verification). Related:
`idea-raw-derived-hybrid-shadow-eval` (Done), `idea-measurement-contract-honesty`.

## Additional DoD detail (external review item 6 — population integrity)

Cover: empty population; one lookup; repeated identical query; retried request; lookup with zero
results; lookup followed by expansion; lookup with missing session attribution; malformed or legacy
event; Unicode query; maximum query length; over-maximum query rejected or safely truncated.

**Measurement honesty:** every output states whether it measures candidate recovery, injection
precision, or downstream task effect. A shadow replay must not be labeled observed downstream
improvement.
