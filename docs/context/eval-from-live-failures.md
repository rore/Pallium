# Eval From Live Failures

Pallium quality work is driven by observed live audit failures, not speculative
knobs. This doc codifies the loop from live DB / audit traces, to normalized
failure rows, to a bounded offline replay, to a pass/fail verdict, to a
production proposal. The verdict is on the proposed change, not on the audit
data.

## 1. Purpose

Routing, scoring, and extraction tuning in Pallium has historically yielded
negative or noise-floor results when proposed in isolation. A knob is added to
fix one trace, the aggregate score moves by less than the slice's natural
variance, and the change either ships invisibly or is reverted later when an
unrelated regression surfaces.

The reusable corrective is structural, not numerical:

1. Observe the failure in the live audit log — not in a synthetic scenario, not
   in an aggregate dashboard, but in a specific row with a specific candidate
   and a specific decision.
2. Normalize the observed failures into a small JSONL eval slice with a fixed
   schema (§4) and controlled-vocabulary labels (§5, §6).
3. Run a deterministic offline replay against that slice.
4. Render a pass / fail / uncertain verdict on the change proposal, with the
   thresholds declared before results are seen.
5. Only after the verdict is PASS, write a separate design document and propose
   production work.

This prevents two failure modes that have recurred in this repo:

- **Speculative knobs** — a tuning parameter is introduced without a bounded
  slice that can fail it. The knob's effect on real traffic is unobservable.
- **Self-cleared verdicts** — the same person who proposes the change also
  decides whether it worked, using metrics defined after seeing the data.
  Architect sign-off between layers (§3) is the structural fix.

## 2. When to use this process

Use this loop when:

- live memory injection quality regresses
- broad-container contamination is observed (memory from one workstream
  surfaces in an unrelated workstream)
- routing / selection / extraction / consolidation behavior is disputed and
  the dispute cannot be resolved from existing replay artifacts
- an architectural change is being considered, especially anything that
  changes a hard scoping or grouping key (container, thread, topic, actor)
- prior replay or audit data is insufficient and a structured slice must be
  cut from live traces before any code change is reasonable

Do **not** use this loop for:

- routine bugfixes with a clear unit-test reproduction
- typos, refactors, or pure cleanup with no behavior change
- documentation work
- changes whose effect is fully captured by an existing eval in
  `evals/` (consult `docs/context/validation.md` Eval Toolbox first)

## 3. Standard workflow

1. Inspect live DB / audit traces. Use `sqlite3` read-only over
   `query_audit_log`, `memory_feedback`, and the relations tables. Do not
   modify the live DB. Capture the rows of interest into a working file under
   `.local/research/<topic>-<YYYY-MM-DD>/`.
2. Normalize the observed failures into a `failure_rows.jsonl` using the
   schema in §4. One JSON object per line. Apply the privacy contract in §8
   at this step, not later.
3. Assign each row a `failure_stage` (§5) and `failure_family` (§6) from the
   controlled vocabularies. If a row does not fit, use `unknown` and record a
   note — do not invent a new label without architect review.
4. Build a local replay under `.local/research/<topic>-<YYYY-MM-DD>/`. The
   harness reads the JSONL slice and the relevant memory objects, replays the
   pipeline stage under test, and emits per-row decisions.
5. Define metrics, slices, and pass/fail thresholds **before** looking at
   results. Write them into `README.md` in the research folder. Numerator and
   denominator must be explicit. Aggregate metrics across heterogeneous
   slices are not allowed (§7).
6. Run focused, broad, regression-guard, and (if available) self-referential
   slices. Each slice gets its own threshold. A change that improves the
   focused slice but regresses the regression-guard slice is a FAIL.
7. Produce `RESULTS.md` with PASS / FAIL / UNCERTAIN. The verdict applies to
   the architecture or fix proposal under test, not to the audit data itself.
   The audit data is the input, not the subject.
8. Only after PASS, propose production work via a separate design doc under
   `docs/specs/`. The design doc cites the replay folder and the verdict.

Architect sign-off is required at two layer boundaries:

- Between **Layer 1** (structural feasibility — does the proposed key /
  scoping / signal even exist in the data with usable cardinality?) and
  **Layer 2** (changed-decision quality — does the proposed change move the
  per-row decision in the right direction on the focused slice?).
- Between **Layer 2** and **Layer 3** (design-doc commitment — is the change
  worth the integration cost, the migration risk, and the new surface area?).

Self-clear is forbidden. The author of the proposal is not the architect of
record for the layer boundary they are crossing.

## 4. Standard failure row shape

Each row in `failure_rows.jsonl` follows this schema:

```jsonl
{
  "row_id": "auto-generated, stable across runs",
  "query_audit_id": "from query_audit_log.id",
  "container_ref_hash": "sha256[:12] of raw container_ref",
  "thread_ref_hash": "sha256[:12] of raw thread_ref or null",
  "slice": "broad|focused|self_referential|slack_style|unknown",
  "query_text_redacted": "first 40 chars after scrub",
  "candidate_memory_id": "memory_objects.id (UUID, opaque) — keep as-is",
  "actual_decision": "injected|skipped|dropped|candidate_only",
  "expected_decision": "unknown|should_inject|should_not_inject|missing_relevant",
  "failure_stage": "from §5",
  "failure_family": "from §6",
  "rating": "relevant|not_relevant|unrated|judgement_pending",
  "evidence_ids": ["source_item.id (UUID, opaque)"],
  "notes": "short free text — also scrubbed"
}
```

Field rules:

- `row_id` is generated by the normalizer and must be stable across reruns of
  the normalizer over the same input window. A reasonable choice is
  `sha256(query_audit_id + ":" + candidate_memory_id)[:16]`.
- `query_audit_id` is the integer or UUID from `query_audit_log.id`. Keep
  as-is; it is opaque.
- `container_ref_hash` and `thread_ref_hash` are `sha256[:12]` of the raw
  ref string. Never store the raw ref. Use the same hash function and
  truncation everywhere so hashes are comparable across slices.
- `slice` is the anonymized slice label. Use generic labels: `broad_A`,
  `focused_A`, `self_referential_A`, `slack_style_A`, etc. The mapping from
  label to container hash lives only inside the research folder, not in
  committed files.
- `query_text_redacted` is the first 40 chars of the query string after the
  scrub regex in §8. Truncation comes after redaction, not before.
- `candidate_memory_id` is the `memory_objects.id` UUID. UUIDs are opaque and
  safe to keep as-is.
- `actual_decision` is what the live system did at the time of the audit row.
- `expected_decision` is the human triage call. `unknown` is allowed and is
  not a free pass — it is a flag that the row needs more context before it
  can be used as ground truth.
- `failure_stage` and `failure_family` come from §5 and §6.
- `rating` is the existing memory_feedback rating if present, otherwise
  `unrated`. Use `judgement_pending` when triage is in flight.
- `evidence_ids` is the list of `source_items.id` UUIDs that backed the
  candidate memory. Opaque, keep as-is.
- `notes` is short free text. Apply the §8 scrub.

UUIDs (`memory_objects.id`, `source_items.id`, `query_audit_log.id`) are
opaque identifiers and are safe to keep verbatim. Refs
(`container_ref`, `thread_ref`, `actor_ref`) and human-language fields
(`query_text`, `query_context`, `notes`) must be hashed or redacted.

## 5. Standard failure stages

Controlled vocabulary. Pick exactly one per row. Definitions:

- **extraction** — wrong or missing memory was written from a `source_item`.
  The error is upstream of retrieval. Includes title-only memories, missing
  evidence fields, type misclassification, and consolidation that loses a
  needed distinction.
- **routing** — the candidate set returned to the selector was wrong. The
  right memory was not in the candidates, or the candidates were dominated by
  off-topic memories. Lexical / vector / hybrid scoring lives here.
- **selection** — the selector picked the wrong candidate from a correct set.
  The right memory was a candidate; another one was chosen.
- **continuity** — `same_thread_context_sufficient` or another continuity
  gate fired wrongly. Either suppressed a needed cross-thread memory or
  injected a redundant one.
- **consolidation** — `fact_summary` or another consolidation step merged
  across topics, lost a distinction, or produced a stale fact that
  superseded a fresher one.
- **no_value_query** — the query had no useful injection target. Chitchat,
  acknowledgements ("ok", "thanks"), or a clearly new task that should not
  surface old memory. Recording these explicitly prevents them from inflating
  recall denominators.
- **audit_gap** — the audit row predates the fields needed to classify the
  failure (e.g. before Goal A annotations, before orientation_recency
  candidate pool was captured). The row is set aside, not used as ground
  truth.
- **unknown** — exhaustive triage failed. Use sparingly and surface in
  `RESULTS.md`. A high `unknown` rate is itself a finding.

## 6. Standard failure families

Controlled vocabulary. Pick exactly one per row. Definitions:

- **wrong_topic_injection** — injected memory belongs to a different
  workstream than the one the query is in. The canonical broad-container
  contamination case.
- **missing_relevant_memory** — relevant memory existed in the container but
  was not retrieved or not injected. Pair with `routing` or `selection` in
  §5.
- **same_thread_wrong_skip** — `same_thread_context_sufficient` suppressed a
  cross-thread memory that the query needed. Pair with `continuity` in §5.
- **cross_topic_consolidation** — a consolidated fact mixes two distinct
  workstreams. Often produces `wrong_topic_injection` downstream. Pair with
  `consolidation` in §5.
- **title_only_extraction** — the candidate memory has only a title and no
  usable evidence or payload. Selector cannot judge it; injection is a
  coin-flip. Pair with `extraction` in §5.
- **no_value_query** — the query did not call for memory injection at all.
  Pair with `no_value_query` in §5. These rows do not count toward
  `missing_relevant_memory` denominators.
- **selection_drop_unexplained** — a known-good candidate was present in the
  candidate set, dropped by the selector, with no reason code in the audit
  row. Pair with `selection` in §5.
- **orientation_recency_blind_spot** — a recent same-thread or
  near-thread memory should have surfaced via the Goal B orientation
  recency layer but did not. Pair with `routing` in §5. Requires a
  post-Goal-B audit window.
- **audit_gap** — see §5.
- **unknown** — see §5.

A row may need both labels updated when the harness changes — e.g. a row
labeled `routing` / `missing_relevant_memory` may move to
`extraction` / `title_only_extraction` once a richer audit field reveals the
candidate was a title-only memory all along. Reclassification is allowed and
expected; the row's `row_id` stays stable.

## 7. Eval / replay requirements

Every replay must state, **before** results are visible:

- **Hypothesis** — one sentence. "Adding signal X to the routing scorer will
  reduce wrong_topic_injection rate on broad_A without regressing
  missing_relevant_memory rate on focused_A." If you cannot write the
  hypothesis in one sentence, the replay is not yet bounded.
- **Data slices** — anonymized labels (broad_A, focused_A,
  self_referential_A, ...) plus container hashes plus row counts per slice.
  Slice composition is fixed before the run; rows are not re-balanced after
  results are seen.
- **Source tables / files** — which sqlite tables were read, which
  `metadata_json` paths were extracted, and the audit window
  (start / end timestamps, hashed if needed).
- **Metrics** — numerator, denominator, threshold, pass condition. One
  metric per slice. Aggregate metrics across heterogeneous slices are
  forbidden — `wrong_topic_injection` on a broad slice is not comparable to
  `missing_relevant_memory` on a focused slice, and averaging them hides
  regressions.
- **Pass / fail thresholds** — numeric, declared up front. A threshold of
  "the change should help" is not a threshold.
- **Audit limitations** — which window each metric used, which rows were
  excluded and why (e.g. `audit_gap` rows excluded from
  `missing_relevant_memory` denominator).
- **Exact command to rerun** — a single shell line that reproduces the
  numbers in `RESULTS.md` from the same input window. Reproducibility is a
  precondition for the verdict.
- **Privacy / scrub constraints** — explicit citation of §8. The harness
  must refuse to write committed artifacts that contain raw refs or
  un-redacted query text.

A replay that fails any of these requirements is not a replay; it is a one-off
investigation and its result is not a verdict.

## 8. Privacy and public-repo rules

This repo will be public. The privacy contract is non-negotiable.

- No live DB excerpts in committed files. Ever.
- No internal project, product, customer, employee, or proxy names anywhere
  in committed files — including docs, designs, context, tests, examples,
  comments, or commit messages.
- Hash all container, thread, and actor refs as `sha256[:12]`. Use a single
  helper so the truncation length is consistent across the codebase.
- Redact `query_text` and `query_context` to at most 40 characters **after**
  a regex sweep for: internal product names, internal project names,
  customer names, email addresses, employee identifiers (numeric or
  alphanumeric), and internal proxy or service URLs. Truncation does not
  substitute for redaction.
- All generated live-data artifacts stay under `.local/`. The `.local/`
  prefix is gitignored and must remain so. Do not move artifacts out of
  `.local/` "to share" — share the schema and the verdict, not the rows.
- If a replay later graduates to `evals/`, it must use anonymized fixtures
  only. No live DB reads at test time. The graduation step is a deliberate
  rewrite that synthesizes neutral, public-safe fixtures from the schema
  and the observed failure shapes — not a copy of the live rows.

When in doubt, hash. A hash that is not strictly required is harmless. A raw
ref that leaks into a committed file is a public disclosure.

## 9. Relationship to `.local/research/`

The boundary between this doc and a specific research run:

- This project doc (`docs/context/eval-from-live-failures.md`) describes the
  **process**. It is committed and public-safe.
- `.local/research/<topic>-<date>/README.md` describes one specific run:
  hypothesis, slices, commands, audit window. It is local and private.
- `.local/research/<topic>-<date>/RESULTS.md` records the verdict for that
  run: PASS / FAIL / UNCERTAIN, per-slice numbers, what changed if anything.
  Local and private.
- `.local/research/<topic>-<date>/` holds all live-data outputs (JSONL
  slices, sqlite excerpts, intermediate artifacts) and the harness scripts
  that produced them. Local and private.

The split exists so the process is reusable and auditable while the run
artifacts stay protected. Do not mix them. Do not write run-specific verdicts
into this doc. Do not write process rules into a single run's `README.md`.

## 10. Relationship to implementation

A production change must not be proposed from a live failure until:

- The failure has a normalized row or slice (§4), with a controlled-vocabulary
  stage and family (§5, §6).
- The replay or eval shows measurable lift on the relevant slice without
  regression on the regression-guard slice. "Measurable" means the
  pre-declared threshold from §7, not a post-hoc reading.
- The regression-guard slice (typically a focused container known to behave
  well today) is checked separately from the slice the change targets, not
  aggregated with it. Aggregation hides the case where a change improves
  broad_A by trading away focused_A.
- Architect review confirms the change generalizes beyond the originating
  incident. A change that fixes exactly one trace and nothing else is a
  patch, not a design. Patches are fine, but they do not need this loop.

Once those conditions are met, the production proposal lives in
`docs/specs/<topic>-<date>.md` and cites the research folder. The spec is
where production design happens; the research folder is where the verdict
was earned.

---

For the first instance of this pattern, see
`.local/research/workstream_replay_2026-05-30/` — workstream / topic
architecture Layer-1 feasibility replay. Class B and Class C metrics are
explicitly deferred until Class A passes; the layer order is part of the
discipline, not an accident of scheduling.
