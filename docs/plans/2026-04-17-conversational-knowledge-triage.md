# Conversational Knowledge Triage Plan (2026-04-17)

This file is a durable working plan for the conversational-knowledge triage
work. It is intentionally stored in `docs/context/` rather than `roadmap/`
because it is execution context for an already-identified problem set, not a
new product feature.

Related durable context:

- this plan file

External working sources (not committed, local only):

- triage records file (local)
- triage report file (local)

## Purpose

Preserve the detailed triage remediation plan across chat compactions without
committing raw triage artifacts into the repo.

Raw triage files are temporary working inputs only. They may be kept locally,
including as temporary repo-local working files, while we are still deriving
neutralized regressions, but they must not become durable repo truth and must
never be committed in the Pallium repo.

Operational rule:

- keep raw triage artifacts available only until the implementation loop has
  converted them into neutralized tests, evals, and distilled plan notes
- remove any repo-local copies before commit once those neutralized assets
  exist

## Current Status

- Phase 1 regression baseline is complete for the structural slice.
- Phase 2 deterministic structural hardening is complete for markdown cleanup,
  subject-presence gating, and grounded statement canonicalization.
- Phase 2b narrow same-thread burst handling is complete with explicit
  regression and eval coverage.
- Phase 2c deterministic acceptance gating revised: the English-cue
  `_looks_like_control_plane_meta_artifact` function was removed from
  `semantic/common.py` because it violated the cue-free architecture decision
  and encoded the integrating agent's internal `[pallium-flag]` protocol in the shared write
  path. Replaced with `is_low_value_meta` checks on the decision,
  investigation_outcome, and interest typed-memory branches — when the LLM
  classifies content as low-value meta, no typed memory is promoted. The
  question-shaped fact rejection and subject-prefixed vague-status rejection
  remain unchanged.
- Phase 3 lever selection is complete: conversational permission, pending
  status, and momentary debug state should be rejected at write time in
  `conversational_knowledge`, while freshness demotion remains with
  task-checkpoint and routing paths that already model transient work state.
- Phase 3+4 implementation is complete: the `FACT_EXTRACTION_SYSTEM_PROMPT`
  skip list was expanded with transient-state categories (hypothetical or
  conditional future states, current runtime/deployment/debug status, one-off
  failures, monitoring chatter, generic platform behavior instructions) and a
  self-contained subject requirement. Validated with 3 new focused LLM eval
  scenarios in `evals/prompt_variant_eval.py` (transient runtime state,
  hypothetical future state, conversational approval). All 3 pass: transient
  content is correctly skipped while durable facts in the same thread are
  preserved.
- The repo-local raw triage working copies were removed before the first phase
  commit; use the external working sources above if rehydration is required.

The plan is deliberately phased:

- freeze and classify the current draft diff before adding more code
- convert the external triage incidents into generic regression assets
- land deterministic structural fixes first
- evaluate narrow duplicate-burst handling alongside the structural slice
- decide explicitly whether stale transient facts are an extraction-gate or
  lifecycle/supersession problem before implementing that slice
- run a governed `fact_extraction` prompt loop only if deterministic phases
  leave residual failures

## Why

A live integrating-agent session exposed a concentrated set of trust failures in
`conversational_knowledge`:

- markdown list and table fragments were promoted as durable memory
- subject-bearing facts lost their subject and became misleading fragments
- vague conversational approvals, questions, and safety checks collapsed into
  context-free pseudo-facts
- transient runtime or deployment state was stored as if it were durable fact
- hypothetical or generic platform-behavior statements were stored as facts
- triage commentary, flag tags, and test-control text fed back into memory as
  if they were real findings
- one deploy event expanded into a duplicate fact flood

The initial draft implementation mixed three change classes in one pass:

- deterministic structural sanitation
- lifecycle or consolidation behavior
- live prompt text edits

That violated the repo's prompt-governance process and blurred package
boundaries. This plan exists to restore methodical execution and preserve the
agreed sequence.

## Current Draft Diff Classification

Current draft changes should be split this way before implementation resumes.

Structural keep-candidates:

- `semantic/common.py`
  - `clean_markdown_artifacts(...)`
  - sanitation before quality checks
  - sanitation before containment normalization
  - sanitation before persisting decision and investigation text
- `semantic/conversational_knowledge.py`
  - `_clean_fact_text(...)`
  - `_fact_subject_is_present(...)`
  - `_statement_mentions_subject(...)`
  - `_iter_source_sentences(...)`
  - `_best_grounded_fact_sentence(...)`
  - `_canonicalize_fact_statement(...)`
  - subject-presence gate in the fact build loop
  - `clean_markdown_artifacts` integration
- `capabilities/consolidation.py`
  - same-thread burst allowance in `FactConsolidationStrategy`, pending narrow
    regression proof

Park for prompt-governed cycle only:

- the two `FACT_EXTRACTION_SYSTEM_PROMPT` text edits in
  `semantic/conversational_knowledge.py`

Key rule:

- do not park the whole `semantic/conversational_knowledge.py` diff; only park
  the prompt text edits

## Rich Report Delta

The richer triage report changes the plan materially. It does not just restate
the original incidents; it expands the taxonomy and clarifies ownership.

New information added by the rich report:

- the original fragment cases are confirmed with stronger provenance and repeat
  impact data
- a new feedback-loop class is explicit: flag tags and triage commentary are
  being re-ingested as new memories
- the original "subject loss" bucket was too narrow; several failures are not
  just subjectless, they are conversation-bound approvals or review questions
  that became vague, context-free durable facts
- the stale-state set is wider than the original deployment trio and includes
  short-lived permission asks, pending-QA status, and temporary MCP/session
  registration state
- one critical manifestation is outside Pallium's write-time policy boundary:
  the integrating agent currently ingests raw assistant output before flag-tag stripping

The rich report also exposes one important split:

- Pallium scope: reject or down-rank meta-analysis, vague conversational state,
  fragments, and transient runtime state during extraction, storage, lifecycle,
  and selection
- external dependency outside this repo: the integrating agent should stop raw control-plane
  tags from entering Pallium ingest in the first place

## Failure Classes

The combined triage artifacts now collapse into these generalized failure
classes.

1. Markdown fragment and formatting leakage
   Affected records:
   `a8efd630`, `00fc1a9e`, `117c4594`, `ee372fc0`

2. Meta-artifact and control-plane re-ingestion
   Affected records:
   `ee372fc0`, `117c4594`, `ebb2e3da`, `be863fdf`

   Generalized class:
   flag tags, triage verdicts, and test-control text should not be promoted as
   reusable factual memory.

3. Subject loss and context collapse in stored facts
   Affected records:
   `66bca613`, `bf4df289`, `07e192cd`, `1dbf2cd0`, `388d47fc`

   Generalized class:
   the extracted text may be grammatical enough to survive a pure fragment
   check, but still lacks the referent needed to be useful outside its source
   thread.

4. Transient runtime, deployment, or approval state stored as durable fact
   Affected records:
   `369f8997`, `960984bf`, `4ba9353d`, `cafd72b3`, `0a747f70`, `b14c030d`

5. Hypothetical or generic platform behavior misclassified as fact
   Affected records:
   `96a2eb30`, `5203060a`

6. Duplicate event flood and overpromotion
   Affected records:
   deploy-event cluster

## Ownership Split

The revised plan has to track two separate remediation streams.

Pallium-owned remediation:

- write-time structural rejection of fragments and formatting residue
- package-local rejection of under-specified conversational facts
- explicit handling for transient runtime or approval state
- duplicate-burst consolidation and any later supersession/lifecycle work
- verification that bad low-value memories do not dominate injection

Out-of-scope external remediation:

- sanitize or split assistant output before `ingest_notification_artifacts`
  sends `assistant_output` into Pallium
- ensure `[pallium-flag: ...]` tags are not included in the text payload that
  Pallium ingests

Important rule:

- do not implement integrating-agent changes from this workspace
- do not treat the external raw-output ingestion bug as evidence that
  Pallium's acceptance policy can remain lax; the Pallium-side acceptance seam
  still needs coverage

## Phases

### Phase 0 - Freeze and classify current draft diff

Goal:
split the existing draft into structural keep-candidates, parked prompt edits,
and verify-only candidates.

Output:

- hunk-by-hunk keep/park/verify disposition for the current draft diff

### Phase 1 - Regression baseline first

Goal:
translate the external triage incidents into repo-owned neutral regressions.

Initial regression targets:

- markdown list fragment rejection
- markdown table fragment rejection
- formatting leak cleanup
- triage-commentary rejection
- flag-tag/control-text rejection
- subjectless fact rejection
- vague conversational approval/question rejection
- subject-preserving canonicalization
- short-lived runtime or approval state rejection or later suppression
- stale contradiction visibility behavior
- duplicate event flood shape

External dependency to track separately:

- the integrating agent's raw assistant output should not send flag-tag payloads into Pallium,
  but that work is out of scope for this repo plan

Primary files:

- `tests/test_semantic_llm_plugin.py`
- `tests/test_conversational_knowledge.py`

### Phase 2 - Deterministic structural hardening

Goal:
land the sanitation and fact-completeness fixes first.

Primary targets:

- `semantic/common.py`
- `semantic/conversational_knowledge.py`

Expected closures:

- `a8efd630`
- `00fc1a9e`
- `117c4594`
- `ee372fc0` at Pallium acceptance layer as far as this repo can reasonably
  defend; full prevention also depends on external integrating-agent ingest sanitization
- `66bca613`
- `bf4df289`
- initial coverage for `07e192cd`, `1dbf2cd0`, `388d47fc` if package-local
  completeness tests prove the facts remain too vague after canonicalization

### Phase 2b - Narrow duplicate-burst handling alongside Phase 2

Goal:
evaluate the same-thread burst fact-consolidation draft as a small,
package-owned candidate with explicit regression proof.

Primary target:

- `capabilities/consolidation.py`

Constraint:

- do not broaden beyond the current small guard relaxation unless tests justify
  it

### Phase 2c - Meta-artifact and vague-fact acceptance gate

Goal:
add deterministic guards for content that is not a pure markdown fragment but
still should not harden into durable memory.

Status:
- complete with typed-memory suppression for control-plane/meta verdicts and
  package-local rejection of question-shaped and subject-prefixed vague facts

Primary questions:

- can typed-memory acceptance distinguish an investigation finding from a
  triage verdict about another memory object?
- can conversational fact acceptance reject facts whose usefulness depends on
  omitted referents like "this", "something", or an uncarried review context?
- should low-value meta detection be widened for triage/control artifacts, or
  should that remain package-local to avoid over-suppressing legitimate
  investigation findings?

Target records:

- `ee372fc0`
- `117c4594`
- `ebb2e3da`
- `be863fdf`
- `07e192cd`
- `1dbf2cd0`
- `388d47fc`

### Phase 3 - Choose the stale transient fact lever before coding

Goal:
decide whether the residual stale transient failures are primarily caused by:

- facts that should never be promoted as durable in the first place
- or facts that can be promoted initially but should later be suppressed by
  supersession or contradiction handling

Target records:

- `369f8997`
- `960984bf`
- `4ba9353d`
- `b14c030d`
- `cafd72b3`
- `0a747f70`

Decision criterion:

- if the fact is conversational permission, pending status, or momentary debug
  state, default to "should never be promoted as durable" unless evidence shows
  the package explicitly needs that class for later work resumption

Status:
- lever selected: package-local write-time rejection in
  `semantic/conversational_knowledge.py`

Decision notes:
- repo evidence already assigns transient work state and freshness handling to
  `task_checkpoint` plus routing freshness/demotion logic, so atomic facts do
  not need to carry pending approvals or momentary runtime/debug state
- contradiction-based supersession remains the right tool for durable facts
  that later conflict, not for conversational state that was never durable to
  begin with

No implementation should start in this phase until the lever is named.

### Phase 4 - Conditional prompt-governed fact-extraction loop

Entry condition:

- only enter if residual failures remain after deterministic structural work
  and the stale transient lever decision

Expected targets if entered:

- `96a2eb30`
- `5203060a`

Secondary targets if deterministic guards do not close them cleanly:

- `07e192cd`
- `1dbf2cd0`
- `388d47fc`

Workflow requirements:

- extend focused evaluator coverage for the exact behavior under review
- compare candidate prompt variants rather than editing the live prompt ad hoc
- check token budget and prompt metrics
- change prompt defaults only after comparative validation

## Verification Sequence

1. targeted deterministic regressions
2. package-local replay or focused evaluator slices
3. broader semantic or integration slices only after the local evidence is
  clean

External follow-up, not verified here:

- the integrating agent should add an ingest-path regression proving raw flag-tag payloads do
  not reach Pallium, but that verification is outside this repo

## Architect Review

The revised plan is stronger, but only if these review findings stay explicit.

What the prior plan missed:

- it treated `context_dropped` mostly as subject loss, but the rich report shows
  a broader under-specification class: approvals, test questions, and safety
  review remarks that remain useless even when grammatical
- it did not explicitly separate meta-analysis re-ingestion from normal
  fragment cleanup
- it did not name the cross-repo integration defect in the integrating agent, so Pallium-only
  work would have left one critical feedback loop open

Why the revised plan is now defensible:

- deterministic structural hardening still remains the smallest valuable slice
- the new Phase 2c isolates the real acceptance-policy gap without immediately
  widening prompt scope
- the integrating-agent seam is called out as integration follow-up rather than being
  hidden inside a Pallium-only phase
- retrieval and ranking changes remain deferred until after write-time and
  consolidation evidence is re-measured

Places that still need deeper investigation before implementation:

- verify whether typed-memory extraction already emits semantic signals that can
  distinguish triage/meta verdicts from true investigation outcomes without a
  prompt change
- inspect whether vague conversational facts are best rejected in
  `conversational_knowledge.py` or later suppressed in routing/selection when
  their lexical payload is too unspecific
- confirm whether stale-state handling needs package-local rejection,
  contradiction-based supersession, or both
- verify whether ranking-overpromotion disappears once fragment, duplicate, and
  vague-fact write-time failures are removed; do not assume a retrieval-layer
  change up front

## Working Rules

- Preserve Pallium's multilingual, cue-free design: do not reintroduce English
  cue tables, language-specific production gates, or lexical heuristics that
  assume one language.
- Keep package-specific fact policy in `semantic/conversational_knowledge.py`
  unless reuse is clearly justified.
- Prompt edits must follow `docs/context/prompt-improvement.md` and require a
  full implementation loop: architect-reviewed plan, regression baseline,
  candidate comparison, targeted evals, implementation review, and explicit
  verification before any prompt default changes.
- Every plan revision and every code change must receive full architect review
  before sign-off.
- Follow the full execution loop for non-trivial work: plan, architect review,
  regression coverage, implementation, implementation review, and verification.
- Every test, eval, fixture, replay asset, and benchmark added or changed for
  this work must use neutralized, domain-generic language. Do not encode SAP
  internal terms, internal product names, ticket IDs, or one-off scenario
  phrasing in Pallium tests or evals.
- Keep this file updated when the agreed plan changes so future sessions do not
  have to reconstruct it from chat history.
- Raw triage artifacts are temporary working inputs only. They may stay
  available locally during regression authoring, but any repo-local copy must
  be removed before commit once the findings are distilled into neutralized
  tests, evals, this plan, and repo memory.

Pre-commit cleanup rule:

- before any commit for this work, confirm that no raw triage artifacts
  remain in the repo after their coverage has been translated into
  neutralized repo assets

Structural phase status:

- completed and architect-reviewed before the first phase commit
- covered by targeted regressions plus `evals/conversational_knowledge`
  structural scenarios

## Source References

- Original triage records: local file (not committed)
- Rich triage report: local file (not committed)