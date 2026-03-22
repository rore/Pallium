---
id: add-language-agnostic-query-signals-and-typed-constraint-state
title: "Cue-free routing, compatibility, and work-state typing for agent_conversation_memory"
status: done
priority: high
commitment: committed
milestone: Next
lane: stabilization-foundation
---

## Summary

Remove English cue-table dependence from the `agent_conversation_memory` package
control plane. The package should route queries, evaluate constraint compatibility,
and classify work-state signals using typed structure and retrieval evidence — not
English phrase matching.

This is one explicit committed feature, not scattered cleanup. Success means the
control plane is cue-free, not that every English string in the repo is deleted.

## What shipped so far

- `QuerySignalEnvelope` as canonical routing authority (Tier 1 structural, no Tier 3
  English fallback — cue tables removed)
- Structural lane narrowing with 3 lanes: `work_resumption`, `evidence_trace`,
  `residual_recall`
- `constraint_policy` lane removed — Pallium remembers and returns constraints but
  does not enforce them (constraint boundary correction, ~1000 lines removed)
- Recall modes (weight-only preferences from candidate evidence)
- Evidence_trace detection consolidated into existing resolver seam
- Constraint over-promotion fix (candidate-set evidence is shape hint, not structural)
- Scoring formula simplified from 7 to 5 components
- ~40 English cue constants eliminated from the control plane
- Cue-free control plane: routing uses typed structure and retrieval evidence throughout

## What remains

### 1. Query hot-path cue removal

Remove English cue dependence from residual routing and candidate scoring:

- **Query-shape token/phrase control logic** (`ROUTING_QUERY_SHAPE_TOKENS`,
  `ROUTING_QUERY_SHAPE_PHRASES`): still used in source suppression and lane
  narrowing. Replace with candidate-type evidence (typed memory layer, retrieval
  source, envelope signals).
- **Specificity bonus cues** (`WORK_RESUMPTION_NEXT_STEP_CUES`,
  `BROAD_RECALL_CONCLUSION_CUES`, etc.): boost candidates based on English query
  words. Replace with typed-field presence scoring (if candidate has `blocker_state`
  and lane is work_resumption, boost).
- **Latest-status wording logic** (`LATEST_STATUS_*_PHRASES`,
  `_has_latest_status_wording`): English-only disambiguation. Move to envelope
  structural detection or remove if envelope already handles it.
- **Summary suppression** (`WEAK_THREAD_SUMMARY_TEXT`, `QUERY_ONLY_SUMMARY_MARKERS`,
  `UNRESOLVED_SUMMARY_MARKERS`): English phrase matching on LLM-generated text.
  Replace with structured quality fields from extraction (see §3).
- **Greeting/noise detection** (`LOW_VALUE_GREETING_NOISE_*`, inline patterns):
  English phrase matching. Move to write-time classification or score-floor gate.
- **Source noise suppression** (heartbeat, capability, request/question detection):
  inline English patterns. Move to write-time tagging.
- **Stopword filtering** (`ROUTING_META_QUERY_TOKENS`,
  `ROUTING_TOPIC_LOW_SIGNAL_TOKENS`): English tokenization assumption. Accept as
  last-mile item — embedding-based scoring is the natural replacement, depends on
  vector retrieval maturity.

### ~~2. Constraint-path cue removal~~ — DONE (removed)

The constraint compatibility engine was removed entirely as part of the constraint
boundary correction. Pallium no longer evaluates constraint compatibility at query
time. Constraint memories route through `residual_recall`. The typed constraint
extraction fields remain in the write-path schema for consuming agents to use.

### 3. Write-path schema work to make removal honest

The query path can't stop reading English text unless the write path produces typed
fields instead. Required additions to extraction output:

- **Summary quality fields**: `is_resolved: bool`, `has_actionable_content: bool`,
  `content_quality: "empty" | "query_only" | "unresolved" | "substantive"` on thread
  summaries. Replaces `WEAK_THREAD_SUMMARY_TEXT`, `QUERY_ONLY_SUMMARY_MARKERS`,
  `UNRESOLVED_SUMMARY_MARKERS` matching at query time.
- **Work-signal typed fields**: the LLM extraction already produces `next_step_text`,
  `blocker_text`, `progress_text`, `key_finding_text`. Ensure these are the
  authoritative source for work-state routing, not English prefix matching
  (`WORK_SIGNAL_PREFIX_TO_TYPE`).
- **Source item classification tags**: `is_low_value_meta`, `is_greeting`,
  `is_heartbeat` as write-time tags. Replaces query-time English pattern matching
  against source content.
- **Constraint normalization completeness**: ensure `constraint_candidates` extraction
  produces `action_class`, `polarity`, `target_anchor` reliably enough that
  query-time English scanning is not needed as fallback.

### 4. Trace and regression proof

- Trace must show typed/structural source of every routing decision — no hidden
  English fallback paths.
- Replay coverage must prove non-English cases work through the typed path.
- English cases must stay stable without hidden fallback dependence.
- Benchmark suite must pass with English cue tables emptied (not deleted — emptied)
  to prove the typed path is actually authoritative.

## Boundary

Remove English cue dependence from the current package control plane. Not:
- Rewrite every extraction prompt
- Delete every English string in the repo
- Full multilingual parity across the entire system
- Rewrite the lexical retrieval tokenizer

The right boundary is: **queries route correctly, constraints evaluate correctly,
and work-state classifies correctly using typed structure alone.** English cue
tables may remain in the codebase as dead code or documentation, but must not be
on any decision path.

## Done When

1. Query routing hot path makes no decisions based on English cue tables or phrase
   matching. Envelope, lane narrowing, recall modes, and candidate scoring all
   consume typed structure. **DONE** — cue tables removed, routing is cue-free.
2. ~~Constraint compatibility evaluates using typed profiles (action_class, polarity,
   target_anchor), not English text scanning.~~ **REMOVED** — constraint compatibility
   engine removed; enforcement is the consumer's job.
3. Work-state classification (next_step, blocker, progress) reads typed extraction
   fields, not English prefix patterns.
4. Summary quality assessment reads typed extraction fields, not English phrase
   markers.
5. Source noise suppression uses write-time classification tags, not query-time
   English pattern matching.
6. Non-English queries reach the correct routing outcome through the typed path
   without requiring English wording.
7. Emptying English cue tables does not degrade benchmark results (proving the typed
   path is authoritative). **DONE** — cue tables removed, not just emptied.
8. Existing English regressions remain stable.
9. Trace shows typed/structural decision source throughout.

## Notes

Sequencing within this feature:

1. Write-path schema additions first (S3) — the query path can't stop reading
   English until typed alternatives exist.
2. ~~Constraint-path cue removal (S2) — highest query-time impact, typed profiles
   already partially exist.~~ Done — constraint compatibility engine removed entirely.
3. Query hot-path cue removal (S1) — largest surface area, depends on S3. Core
   routing cues removed; remaining items are write-path schema and noise suppression.
4. Trace and regression proof (S4) — acceptance gate.

Stopword filtering (`ROUTING_META_QUERY_TOKENS`) is accepted as last-mile. The
natural replacement is embedding-based candidate scoring, which depends on vector
retrieval maturity. Not blocking this feature on that.
