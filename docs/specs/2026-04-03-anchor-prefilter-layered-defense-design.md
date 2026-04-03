# Anchor Prefilter Layered Defense — Design

**Date:** 2026-04-03
**Status:** Draft
**Roadmap:** add this as a new item in the `Later` queue (does not block the current `Next` items)

## Problem

The anchor prefilter (`_anchor_prefilter_candidates`) is the system's primary mechanism for routing
retrieval candidates to the right domain. It uses subject hints extracted by the LLM at write time
to classify each candidate as `anchored_aligned`, `anchored_insufficient`, `anchored_conflicting`,
or `unanchored_legacy`, then gates the candidate pool to the best available tier.

The prefilter is a **single-layer binary gate with no scoring influence**. This design has two
compounding properties that become problematic under the assumption that LLM extraction is
probabilistic and will always produce some misses and some spurious extractions:

1. **Hard exclusion.** Three of the four states can be hard-excluded with no fallback. When even
   one memory has a correctly-extracted anchor, all non-aligned candidates are dropped — including
   correctly-relevant memories whose anchors were missed or extracted wrongly.

2. **No score layer.** `anchor_prefilter_status` is set on each candidate but never read by
   `_score_routed_candidate`. Anchor alignment has zero influence on routing scores. The only
   lever is inclusion vs. exclusion — there is no graduated response.

3. **No intra-secondary discrimination.** Once a memory survives past the gate, all secondary
   candidates compete on the same footing as each other. There is no mechanism within the
   fallback pool to prefer memories whose content actually matches the query over those that
   landed in the fallback pool coincidentally.

The Pallium premise — wrong memory is worse than no memory — was written assuming correct anchors.
Under probabilistic extraction, that premise applies equally to the anchor system itself: if the
selected query anchor is wrong (because a spurious extraction in the candidate pool biased it),
aligned memories are the wrong-domain ones, and the correct memories are in the dropped tiers.

## Full Failure Surface

Given any extraction error:

| Error | Memory state | Any aligned exist? | Outcome |
|---|---|---|---|
| Miss (no hints extracted) | `unanchored_legacy` | No | Retained as last resort |
| Miss (no hints extracted) | `unanchored_legacy` | **Yes** | **Hard dropped** |
| Spurious (wrong anchor attached) | `anchored_conflicting` | Any | **Always hard dropped** |
| Partial miss (right value, wrong kind) | `anchored_insufficient` | **Yes** | **Hard dropped** |
| Partial miss (right value, wrong kind) | `anchored_insufficient` | No | Retained |

The worst case: when some memories have correct anchors and others don't, the prefilter is
maximally discriminative. A single correctly-anchored memory causes all under-extracted and
spuriously-extracted memories to be dropped, regardless of content relevance.

## Key Code Locations

| Component | File | Lines | Current behavior |
|---|---|---|---|
| `_classify_memory_candidate_anchor_state` | `semantic/agent_conversation_memory_anchors.py` | 203–220 | Produces four states; `conflicting` when same-kind subjects exist but none match |
| `_anchor_prefilter_candidates` | `semantic/agent_conversation_memory_routing.py` | 510–602 | Binary cascade: aligned-only → insufficient+legacy → legacy. Conflicting always excluded. |
| `_score_routed_candidate` | `semantic/agent_conversation_memory_routing_scoring.py` | — | Never reads `anchor_prefilter_status`; score is anchor-blind |
| `ROUTING_FOCUS_BOOST` | `semantic/agent_conversation_memory_routing_constants.py` | — | Focus boost applied to preferred-layer candidates; tier penalty must be calibrated relative to this |

## Principles

**Extraction is probabilistic.** There will always be misses and spurious anchors. The system
must not treat extraction output as ground truth for permanent exclusion.

**Layers over single gates.** A wrong anchor at write time should not permanently remove a
memory. Anchor alignment, retrieval quality, and content relevance are independent signals that
should each contribute.

**Aligned memories still win.** The aligned tier remains the primary signal. The layering only
affects what happens in remaining result slots when aligned cannot fill the requested limit, and
in fallback scenarios when no aligned candidates exist.

**Secondary tier complements, does not compete.** Secondary-tier candidates surface only in slots
that the aligned tier cannot fill. If aligned candidates exhaust the requested limit, no secondary
candidates surface. This preserves the "wrong memory is worse than no memory" premise for the
primary result slots while recovering correctly-relevant memories in remaining slots.

**Retrieval score is the intra-secondary discriminator.** The IDF-weighted lexical score and
vector similarity score already encode how well a candidate's content matches the query.
A correctly-missed memory about the right domain will score higher on retrieval than a
wrong-domain memory that happens to be in the fallback pool — because it was retrieved precisely
due to content-token overlap with the query. No separate content-overlap computation is needed.

## Proposed Changes

Four changes are proposed. Changes 2 and 3 are sequenced. Change 1 is independent and
can be implemented in parallel with the subject hints prompt loop.

---

### Change 1: Demote `anchored_conflicting` → `anchored_insufficient` unconditionally

**File:** `semantic/agent_conversation_memory_routing.py` — `_anchor_prefilter_candidates`

**What changes:** `anchored_conflicting` memories enter the `insufficient` bucket instead of
the excluded list. They participate in the existing fallback cascade: retained when no aligned
candidates exist, still dropped when aligned candidates exist (the latter is addressed in
Change 3).

**What it fixes:** the no-aligned-candidates scenario where a spuriously-extracted anchor on a
correct memory permanently hides it. When there is nothing better, the memory gets a chance.

**What it does not fix alone:** when aligned candidates exist and the incorrectly-anchored memory
is dropped anyway because insufficient is dropped when aligned exist. That requires Change 3.

**Why this is safe now:** when aligned candidates exist, this change has no observable effect.
The new behavior only fires in the fallback path, where the candidate pool was already empty
or thin. Risk is low and bounded.

**Timing:** can be implemented in parallel with the subject hints prompt validation loop
(`docs/specs/2026-04-03-subject-hints-prompt-validation-loop-design.md`) — does not depend
on Changes 2–4.

**Trace:** in `_anchor_prefilter_candidates`, previously-conflicting candidates that are demoted
should carry `anchor_prefilter_status = "insufficient_retained_demoted"` in the candidate state
dict, distinct from `"anchor_insufficient"` (natively insufficient), so the demotion is visible
in the `/query/debug` trace.

**Acceptance criteria:**
- A memory with a spurious anchor that conflicts with the query anchor is retained in the
  fallback pool when no aligned candidates exist.
- A memory with a spurious anchor is still absent from results when aligned candidates exist
  (Change 3 is required to change this).
- `anchor_prefilter_status = "insufficient_retained_demoted"` appears in debug trace for
  demoted candidates.
- Existing test `test_workstream_anchor_prefilter_excludes_same_surface_off_topic_memory` passes
  unchanged (it has aligned candidates; conflicting exclusion is unaffected by this change).

---

### Change 2: Make anchor tier a scoring signal via a calibrated tier penalty

**File:** `semantic/agent_conversation_memory_routing_scoring.py` — `_score_routed_candidate`
**File:** `semantic/agent_conversation_memory_routing_constants.py` — add `ANCHOR_SECONDARY_TIER_PENALTY`

**What changes:** `_score_routed_candidate` reads `anchor_prefilter_status` from the candidate
dict. Candidates with status `insufficient_retained`, `legacy_fallback_retained`,
`insufficient_retained_demoted` (from Change 1), or `secondary_tier` (from Change 3) receive
a flat score deduction of `ANCHOR_SECONDARY_TIER_PENALTY`. Aligned candidates are unaffected.

**Calibration:** the penalty must ensure that no secondary-tier candidate can outrank an aligned
candidate through the focus-boost path. The invariant is:

```
ANCHOR_SECONDARY_TIER_PENALTY ≥ ROUTING_FOCUS_BOOST
```

`ROUTING_FOCUS_BOOST` is the maximum score addition any candidate can receive from the
focus-layer adjustment (`_routing_focus_adjustment`). Setting the penalty at or above this
value guarantees that an aligned candidate with zero focus boost still outranks a secondary
candidate with maximum focus boost. Read the current value of `ROUTING_FOCUS_BOOST` from
`routing_constants.py` before setting this constant; do not guess.

**Why the retrieval score provides intra-secondary discrimination:** the IDF-weighted lexical
score and vector similarity are already part of `base_routing_score`. Within the secondary tier
— where all candidates receive the same flat `ANCHOR_SECONDARY_TIER_PENALTY` — candidates sort
by their existing retrieval-derived score. A correctly-missed memory about the right domain
received a high retrieval score because its content matched the query tokens (that is precisely
why it was retrieved). A wrong-domain memory in the fallback pool has a lower retrieval score
because its content is less relevant. No additional content-overlap computation is needed; the
retrieval signal already discriminates correctly within the secondary tier.

**This closes the original "Change 4" concern.** The pre-existing `content_overlap_tokens` field
remains unused and should be removed to avoid confusion rather than populated with a redundant
signal.

**Trace:** the routing score breakdown in the debug trace should show `anchor_tier_penalty`
as a named component alongside existing score components, with value 0 for aligned and
`ANCHOR_SECONDARY_TIER_PENALTY` for secondary. This makes the tier influence directly
observable in `/query/debug`.

**Why this must precede Change 3:** without a tier penalty in place, expanding the candidate
pool in Change 3 allows high-retrieval secondary candidates to displace aligned candidates.

**Acceptance criteria:**
- An `aligned` candidate with a lower retrieval score ranks above an `insufficient` or
  `legacy` candidate with a higher retrieval score.
- An `aligned` candidate with zero focus boost outranks a secondary candidate with maximum
  focus boost (`ANCHOR_SECONDARY_TIER_PENALTY ≥ ROUTING_FOCUS_BOOST` invariant holds).
- `anchor_tier_penalty` is visible in the routing score breakdown in the debug trace.
- `ANCHOR_SECONDARY_TIER_PENALTY` is defined in `routing_constants.py`, not hardcoded.
- Routing benchmark passes at current baseline.

---

### Change 3: Retain a secondary tier alongside aligned candidates

**File:** `semantic/agent_conversation_memory_routing.py` — `_anchor_prefilter_candidates`

**What changes:** the aligned-only cutoff is softened. When aligned candidates exist, the
`retained_memory_ids` set expands to also include:
- All `anchored_insufficient` candidates (including those demoted from `conflicting` by Change 1)
- All `unanchored_legacy` candidates

These secondary-tier candidates are annotated with `anchor_prefilter_status = "secondary_tier"`
so Change 2's penalty applies. The existing per-status trace entries are preserved for the more
specific statuses set earlier in the loop (insufficient, legacy, demoted-conflicting); the
`"secondary_tier"` status overrides only the final inclusion annotation used by the scorer.

The fallback cascade becomes:

```
primary tier (always):    aligned
secondary tier (always):  insufficient + legacy (penalized by Change 2)
never retained:           conflicting — unless demoted to insufficient by Change 1
```

**Result slot behavior:** aligned candidates receive higher routing scores and fill the top
slots. Secondary candidates fill remaining slots up to `requested_limit`. When aligned
candidates alone satisfy the requested limit, no secondary candidates surface — the secondary
tier costs nothing in that case. Secondary candidates only surface in the slots that extraction
gaps would have otherwise left empty.

**Processing overhead:** the secondary tier is bounded by the total retrieval pool size, which
is itself bounded by the retrieval provider's result cap. No additional retrieval calls are made.

**What it fixes:** the most impactful failure case — under-extracted memories that are currently
invisible the moment any correctly-anchored memory exists in the pool.

**Test updates required:** tests that assert "only the aligned memory is returned" (when the
requested limit exceeds the aligned count) need updating. The correct assertion is "aligned
memories rank above all secondary candidates." Tests asserting N total results may also need
updating if the secondary tier provides additional candidates. Audit before merging:
`tests/test_agent_conversation_memory_routing_recall.py`,
`tests/test_agent_conversation_memory_routing_resumption.py`.

**Trace:** `anchor_prefilter_summary` should gain `secondary_tier_count` (count of candidates
admitted as secondary alongside aligned), distinct from the existing
`insufficient_candidate_count` and `legacy_fallback_count` fields which reflect the no-aligned
fallback path.

**Acceptance criteria:**
- A memory with no anchor is retained and ranked below an aligned memory in the same result set.
- A memory with a spurious anchor (demoted by Change 1 to insufficient) is retained and ranked
  below aligned memories.
- Aligned memories always occupy the top routing ranks when competing with secondary-tier
  candidates (invariant from Change 2 holds).
- When aligned candidates alone reach `requested_limit`, no secondary candidates appear in
  final results.
- `secondary_tier_count` appears in the anchor prefilter trace summary.
- Typed-memory classification benchmark (`items.jsonl`) unchanged within ±1 per category.
- Memory routing benchmark passes at current baseline.
- Work resumption benchmark passes at current baseline.

---

### Change 4: Remove `content_overlap_tokens` (cleanup)

**File:** `semantic/agent_conversation_memory_routing_scoring.py`

**What changes:** the `content_overlap_tokens` field, currently initialized to `[]` and never
populated, is removed from the candidate dict and from trace output. It was a placeholder for
a signal that Change 2 makes unnecessary: the IDF-weighted retrieval score already encodes
content-query overlap more accurately than raw token intersection would, and the tier penalty
structure (Change 2) causes it to discriminate within the secondary tier automatically.

Keeping an empty placeholder field that is never set misleads readers into thinking a content
rescue mechanism exists when it does not. Removing it is the honest position.

**Acceptance criteria:**
- `content_overlap_tokens` does not appear in candidate dicts or trace output.
- No other code reads or writes the field.
- No test references the field.

---

## Interaction Map

```
Change 1:  independent, can ship with prompt loop work
           effect limited to no-aligned fallback path

Change 2:  independent of Change 1, but should ship before Change 3
           makes anchor tier a score signal, enables safe pool expansion

Change 3:  requires Change 2 to be live
           Change 1 recommended — without it, demoted-conflicting memories
           don't reach secondary tier when aligned exist

Change 4:  independent cleanup, can ship at any time
           cleans up the dead placeholder that Change 2's design makes unnecessary
```

Minimum viable multi-layer improvement: Changes 1 + 2 + 3.

## Sequencing and Scope

Change 1 is self-contained and low-risk. It can be implemented and shipped alongside the
subject hints prompt validation loop.

Changes 2 + 3 are a coherent unit — implement and benchmark together. Change 3 should not
ship without Change 2 already live and validated.

Change 4 is cleanup that can ship independently at any time.

This work addresses system resilience for both new data and historical data with imperfect
anchors. The subject hints prompt loop
(`docs/specs/2026-04-03-subject-hints-prompt-validation-loop-design.md`) addresses root-cause
extraction quality for new data. Both are needed; they are complementary, not alternatives.

## What Is Not In Scope

- Changing `_infer_selected_query_anchor` — query anchor selection is unchanged. A wrong
  selected anchor caused by a spurious extraction biasing the candidate pool remains a root
  cause addressed by the prompt fix.
- Re-extracting anchors for existing memories — a separate migration concern.
- Multi-pass retrieval (a second retrieval call without anchor filtering) — all changes are
  within the single existing retrieval pass.
- FTS5 / PostgreSQL matched-token propagation — deferred to the FTS5 migration milestone.
