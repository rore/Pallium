# continuous-eval-lookup-population

The continuous RAW/DERIVED/HYBRID evaluator draws its query population **only** from `query_audit_log`,
which ships **off by default** (`app/config.py` `ObservabilityConfig.query_audit_log = False`). The
always-on funnel lookup event carries no query text, so on a default install the evaluator runs over zero
queries and silently reports as if there were no activity.

Fix (decided with the user): the search phrase is not otherwise stored (it's the agent's own search
wording, not a stored turn, and can't be reconstructed from stored turns), so persist a **redacted**
query representation on the always-on funnel lookup event — the same secret-scrubbing every stored turn
gets — and repoint the evaluator at that authoritative, always-on population, reporting population size +
exclusions instead of a silent zero.

External-review register item 6 (P2). Red path (`core/service.py` + schema); the evaluator itself
(`evals/raw_derived_hybrid/`) is not a guarded path.

<!-- agent-workflow:start -->
**Outcome:**
On a default install (audit logging off), the RAW/DERIVED/HYBRID evaluator finds every eligible historical
lookup exactly once, drawn from the always-on funnel event (which now carries a redacted `query_text`),
and reports the population size + excluded-record reasons rather than silently emitting zero. Turning
audit logging on/off does not change the population (the funnel is the single source).

**Target:**
`storage/sqlite_schema.py` (new nullable `query_text` column on `historical_lookup_reuse_event` +
migration entry in the existing `_HISTORICAL_LOOKUP_COLUMN_MIGRATIONS` / ensure method),
`core/service.py` (the lookup event write persists `redact_sensitive(text)`),
`evals/raw_derived_hybrid/runner.py` (`load_query_rows` reads the funnel event; add a population/exclusion
report). Offline eval + red write path; no retrieval-behavior change.

**Scope:**
- Add nullable `query_text` to the funnel event; write `redact_sensitive(text)` at the existing
  unconditional lookup-write site (best-effort, unchanged failure isolation). Empty/None text → NULL.
- Repoint `load_query_rows` to read the always-on funnel lookup events (`event_type='lookup'`,
  `query_text IS NOT NULL`), selecting `query_text, container_ref, session_id AS thread_ref, actor_ref,
  visibility, trigger_origin` — the existing `QueryRow` shape. Same container/thread/actor/origin filters.
- Add a population report (total lookup events, included = has query_text, excluded = NULL query_text with
  reason "legacy/pre-query_text event") surfaced in the `run_eval` output; the evaluator states which seam
  it measures (candidate recovery vs representation vs cost) — already present, keep it honest.

**Constraints:**
- `query_text` is the FIRST content persisted on the funnel event — it MUST pass `redact_sensitive`
  (the same scrubbing stored turns get). No raw query text on the always-on event.
- Telemetry write stays best-effort: a failure must never fail the query (existing try/except).
- No retrieval/injection behavior change; no change to what proactive injection measures.
- Do NOT gate the query_text write on `query_audit_log` (it must be always-on to be authoritative).
- No internal codenames / third-party product names.

**Completion criteria:**
1. Default-config (audit off) E2E: source_only searches via the API/MCP → each writes a funnel lookup with
   a redacted `query_text`; the evaluator represents every eligible lookup exactly once and reports
   population size + exclusion reasons.
2. Config-equivalence: same logical population with audit on vs off (no KPI change caused solely by the
   toggle) — satisfied because the evaluator reads the always-on funnel, not `query_audit_log`.
3. Redaction: a lookup whose query text contains a secret persists a scrubbed `query_text` (no raw
   secret on the funnel event).
4. Population honesty: legacy events with NULL `query_text` are excluded and counted with a reason; the
   evaluator never silently emits 0 for a non-empty table.
5. Migration applies on a pre-`query_text` DB; existing funnel/eval tests still pass.

**Risk:** High

**Complexity:** Moderate

**Reason:** Edits the guarded red path (`core/service.py`) and adds a schema column that, for the first
time, stores content on the always-on telemetry event — redaction correctness matters. Localized (one
write line + one column + one loader repoint + a report), so Moderate not Large.

**Discovery:**
- `evals/raw_derived_hybrid/runner.py:79-131` `load_query_rows` selects `query_text,…` exclusively from
  `query_audit_log`; `run_eval:400-409` calls it only when no explicit `queries` list is passed.
- `evals/raw_derived_hybrid/runner.py:443` test note: `run_eval` accepts explicit `QueryRow`s with no
  `query_audit_log` dependency — so no test pins the loader to the audit table; repoint is safe.
- `core/service.py` `query()` has `text` (the search string) in scope at the funnel lookup-write block
  (`if source_only:` ~710-745); `redact_sensitive` already imported (`:35`) and used throughout.
- Funnel event columns (post-#46): id, created_at, event_type, session_id, container_ref, actor_ref,
  trigger_origin, parent_lookup_id, exposed_json, visibility, source_session_ref. `exposed_json` stores
  ids only — `query_text` will be the first content column (hence the redaction constraint).
- Migration mechanism: `_HISTORICAL_LOOKUP_COLUMN_MIGRATIONS` + `_ensure_historical_lookup_columns()`
  (added in #46), registered in `_initialize_schema`. Add the `query_text` ALTER to the existing dict.

**Material assumptions:**
- *The agent's search phrase is not otherwise persisted unconditionally.* If a stored turn already holds
  the exact query string, prefer referencing it over a second copy. Evidence checked: the search string
  is a derived MCP/agent search phrase, not ingested as a turn; only `query_audit_log` (off) holds it.
- *`load_query_rows` has no production caller besides `run_eval`.* Disproved if another module imports it
  → keep a compatibility path. Action: grep before repointing (done: eval-only).

**Plan:**
1. Schema: add `query_text = Column(Text, nullable=True)` to the event model + a `query_text` entry in
   `_HISTORICAL_LOOKUP_COLUMN_MIGRATIONS` (ALTER … ADD COLUMN query_text TEXT). Confirm applied on an
   existing DB.
2. `core/service.py` lookup write: add `"query_text": redact_sensitive(text) if text else None`.
3. `runner.py`: repoint `load_query_rows` to the funnel event (query_text not null); add
   `count_lookup_population(db_path,…)` → {total, with_query_text, without_query_text}; surface a
   `population` block in `run_eval`'s report.
4. Tests: redaction on the persisted query_text; default-off E2E population; migration; population report
   counts + exclusion reason.
Stop condition: if redaction of the query would break retrieval replay in a way that changes the measured
seam materially, pause and record it.

**Verification plan:**
- Criterion 1 → E2E test: audit off, source_only search, funnel has query_text, loader returns it.
- Criterion 2 → the loader reads the funnel regardless of the audit flag (assert same rows on/off).
- Criterion 3 → a secret-bearing query persists a scrubbed query_text (no raw secret).
- Criterion 4 → population report counts included/excluded with a reason; NULL-query_text row excluded.
- Criterion 5 → pre-column DB migration test; full `pytest tests/ -q` (known `test_config` env-leak only).
- redline + agent-workflow CI predicates.

**Plan review:**
Clean-context agent review required (red path). Reference recorded under `## Plan review` below.

**Approvals:**
Approved by user 2026-08-18: "built it" — approving building the decided fix (persist a redacted query
representation on the always-on funnel event and repoint the evaluator at it), per the plain-language
plan the user accepted in the preceding turns.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Plan review

Clean-context Explore reviewer (2026-08-18). Verdict: **plan sound — proceed with tightenings**. Field
coverage (QueryRow's 6 fields all present; `session_id AS thread_ref` alias; `thread_ref` is
filter-only, never passed to retrieval), privacy (redaction = same barrier as stored turns +
`_redact_query_result`), config-equivalence (funnel is the sole population reader — no double-count),
determinism (stable `ORDER BY created_at, id`), measurement-only, and the two-ALTER migration all verified
OK. Required tightenings, applied to the plan:

- **SELECT must guard `event_type='lookup'` AND `query_text IS NOT NULL`** — expansion rows (NULL
  query_text) would otherwise pollute the population *count* even though the NULL filter drops them.
- **`count_lookup_population` must scope to `event_type='lookup'` and apply the SAME
  container/thread/actor/trigger_origin filters** as the loader, or reported total ≠ sampled population
  (DoD #4). The "legacy/pre-query_text" excluded reason is only truthful for lookup rows.
- **Model column required** — `write_historical_lookup_event_row` does `Record(**row)`, so the model must
  declare `query_text` or the new key raises.
- **trigger_origin caveat**: the default filter is `agent_pull/mcp_pull`; MCP source-only searches send
  `agent_pull` (pass). A source_only search with a different/None origin is dropped by the default filter
  → the default-off E2E test asserts the funnel row's `trigger_origin` is in the default set, so
  "never silently 0" is verified for the real (MCP) path.

**Edge-case DoD dispositions** (ticket "Additional DoD detail"): Unicode query + missing-session
(`session_id` NULL) → covered by tests. Over-maximum length → WONTFIX: `query_text` is unbounded TEXT, no
truncation path to test. Malformed/legacy event → the NULL-query_text exclusion IS the legacy case;
covered.

## Implementation

- **Schema** (`storage/sqlite_schema.py`): added `query_text` (nullable `Text`) to the event model + a
  `query_text` ALTER in `_HISTORICAL_LOOKUP_COLUMN_MIGRATIONS` (applied by the existing
  `_ensure_historical_lookup_columns`, already registered).
- **Service** (`core/service.py`): the lookup event write now sets
  `"query_text": redact_sensitive(text) if text else None` — the first content on the funnel event,
  scrubbed the same way stored turns are; still inside the best-effort try/except.
- **Eval** (`evals/raw_derived_hybrid/runner.py`): `load_query_rows` reads the always-on funnel event
  (`event_type='lookup' AND query_text IS NOT NULL`, `session_id AS thread_ref`, stable
  `ORDER BY created_at, id`) instead of `query_audit_log`; added `count_lookup_population` (lookup-only,
  same filters, with/without split) and a `population` block in the `run_eval` report.
- **Fixture** (`tests/test_raw_derived_hybrid.py`): `synthetic_db` now seeds a funnel lookup event with
  query_text instead of a `query_audit_log` row (the loader's new source), so the existing runner tests
  keep exercising the load path.

## Evidence

`pytest tests/ -q` → **3617 passed, 15 skipped, 2 xfailed, 1 failed**. The single failure is the
pre-existing env-leak `test_config.py::test_prompt_variants_legacy_fallback_unaffected` (unrelated).
Affected slices (`test_raw_derived_hybrid`, `test_historical_lookup_funnel_e2e`,
`test_historical_lookup_storage`) → 51 passed. New tests: redacted-query-text + audit-off eval population
(E2E), lookup-only population counts + exclusion reporting, run_eval population block, query_text
migration on a pre-column DB.
