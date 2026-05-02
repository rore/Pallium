# Investigation: User Profile Consolidation

**Date:** 2026-05-02  
**Status:** Deferred — interesting but premature

## Bottom Line

**Don't build this now.** The concept is sound — consolidating scattered user-related
memories (interests, constraints, user facts) into a single compact profile card — but it
conflicts with two accepted architectural stances and isn't on the current roadmap.

The idea has merit for a future where containers are long-lived and user profiles are rich.
The existing consolidation machinery (`FactConsolidationStrategy`, `ConsolidationRunner`)
means this would be straightforward to build when the time comes. No urgency to commit now.

**Architectural tensions that must be resolved first:**

1. `scope.md` explicitly lists "replacing lower-level evidence-backed memory with only
   higher-level summaries" as out of scope. A profile card that supersedes individual
   interest/constraint memories and suppresses their injection is exactly this.

2. The injection precision principle (2026-04-05) states "wrong memory is worse than no
   memory" and injection gates should err toward not injecting. An "always-inject" profile
   card bypasses this safety gate.

**When to revisit:** After lifecycle hardening ships (stale/superseded memory handling)
and if real-world usage shows containers regularly accumulate 5+ user-personal memories
competing for injection slots.

## Current Landscape of User-Related Memories

### Types that capture user info

| Type | What it stores | Created when | Role guard | Container guard |
|------|---------------|--------------|------------|-----------------|
| `interest` | Named subject user wants to explore | User mentions future-oriented curiosity | user-only | private-only |
| `constraint_memory` | Operational rule/prohibition user commits to | User states definitive constraint | user-only | private-only |
| `atomic_fact` | Per-thread factual extraction (some about user) | Thread processing | none | none |
| `fact_summary` | Cross-thread consolidated facts | FactConsolidationStrategy | none | none |
| `continuity_memory` | Repeated-answer carry-forward | Consolidation | none | none |

Of these, `interest` and `constraint_memory` are explicitly user-personal. `atomic_fact`
and `fact_summary` are mixed — some facts are about the user ("user is a data scientist"),
some about the work ("the API uses PostgreSQL").

### How they're injected today

Each type gets its own injectable block with a distinct title:

```
[Interest | ref:abc123] Chroma vector database for future evaluation
[Active Constraint | ref:def456] Constraint: don't mention the internal project name in public docs
[Fact Summary | ref:ghi789] User is a senior engineer working on memory systems...
```

With the current system:
- **Injection cap**: 3-5 blocks total (floor=3, ceiling=5)
- **Per-block cost**: 60-300 characters depending on type
- **Framing overhead**: ~30 chars per block (title + ref + brackets)

A container with 3 interests + 2 constraints + 2 fact_summaries about the user has
7 user-related memories competing for 5 injection slots. Some will be dropped by the
dynamic cap, leading to inconsistent user profile delivery across queries.

### Token cost analysis (realistic)

The injection cap means at most 5 blocks inject regardless of how many user-related
memories exist. A profile card wouldn't reduce total injection volume (still 5 blocks) —
it would reallocate slots from user-context to work-context. The real value is
**coherence** (unified profile vs. fragmented signals) and **slot reallocation**
(more room for decisions/investigations), not raw token savings.

## Options Considered

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| A: New memory type (`user_profile`) | Follows consolidation pattern, persisted | Supersedes individual memories (violates scope stance), always-inject bypasses safety gate | Premature |
| B: Virtual card (on-the-fly) | Always fresh | LLM cost per query, latency on hot path | Too expensive |
| C: Cached virtual (TTL) | Fresh-ish | Adds caching layer Pallium doesn't have | Over-engineered |
| **D: Packaging optimization** | No new type, no supersession, no gate bypass | Doesn't work when individual memories don't pass the gate | **Smallest future slice** |

**Option D explained:** At injection time, if multiple user-personal memories (interests,
constraints, user-facts) independently pass the injection gate, render them as one
combined block instead of N separate blocks. No new memory type. No supersession.
Individual memories keep their lifecycle. The optimization is purely presentational.

## Prior Art Research

Another memory system implements a similar concept using:
- Two-tier caching (permanent identity + 1hr TTL context)
- LLM synthesis with temperature 0.3, max 100 tokens
- Top 10 memories from relevant collections
- Always-available to the routing/agent layer

Key differences from Pallium's architecture:
- That system uses recency-based retrieval (not relevance-gated injection)
- No injection precision principle — synopsis is always surfaced
- No evidence-backing requirement on the synthesized output
- Simpler lifecycle model (no supersession, no flagging)

## Risks of Building Now

| Risk | Why it matters |
|------|---------------|
| Conflicts with scope.md out-of-scope stance | Would require explicit scope change and rationale |
| Bypasses injection precision principle | Stale/hallucinated profile injected without gate verification |
| Supersession recovery unclear | Flagging a profile card leaves constituent memories in `superseded` state with no un-supersede path |
| Limited applicability | 4+ user-personal memories per container requires sustained multi-thread usage; most containers won't hit this |
| Lifecycle hardening ships first | Better stale/superseded handling would make this safer to build |

## Recommended Path Forward

1. **Don't build now.** Current roadmap priorities (routing calibration, lifecycle hardening,
   thread-level interest) are higher value and would make profile consolidation safer later.

2. **If revisited, start with Option D** — a packaging-only optimization that combines
   multiple user-personal injection blocks into one rendered block at injection time.
   No new memory type, no supersession, no gate bypass.

3. **Prerequisites before any version ships:**
   - Lifecycle hardening (stale/superseded memory handling)
   - Quantitative evidence that slot competition is a real problem (query audit log analysis)
   - Resolution of scope.md "no higher-level synthesis replacing lower-level evidence" stance

4. **The consolidation machinery makes this low-risk to defer.** When the time comes,
   `FactConsolidationStrategy` provides an exact template. Nothing needs to be built
   speculatively now to preserve the option later.
