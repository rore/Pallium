# Work Reference — Cross-Surface Work Continuity

Date: 2026-04-14
Status: Draft (revised after architect review)

## Problem

Pallium preserves reusable memory (decisions, investigations, checkpoints, facts) within scoped conversational contexts. The scoping model uses `container_ref` (workspace/channel) and `thread_ref` (conversation thread) to organise and retrieve memories.

This works when a piece of work lives inside a single container and thread. But real agent work often spans multiple surfaces:

- A user discusses a Jira ticket in a DM thread, then a colleague asks about the same ticket in a channel thread. These are different containers (`dm:U123` vs `channel:C456`), with different visibility (`private` vs `public`). The memories cannot reach each other.

- An investigation starts in one Slack thread, gets interrupted, and resumes in a new thread a day later. The memories from the first thread are retrievable only through semantic/lexical similarity and routing relaxation — there is no structural signal connecting them.

- The agent creates a Jira ticket via an MCP tool in one session. Later, a different user asks about that ticket. The ticket ID appears in the original tool use summary text, but nothing links the derived memory to the ticket identity.

- The same work is discussed in three threads over a week. Each thread produces its own thread_summary, task_checkpoint, and decisions. At query time, the routing pipeline may surface memories from the most recent or most semantically similar thread — but it has no way to know these threads are about the same work, and the packaging locality gate (`routing_selection.py:192-216`) actively prevents cross-thread packaging unless thread_refs overlap.

The gap is not about richer memory types. Pallium's existing types (decision, investigation_outcome, task_checkpoint, atomic_fact, etc.) cover the semantic content well. The gap is a missing structural signal that connects related work across threads and containers.

## Goals

1. Give Pallium a way to know that memories from different threads and containers are about the same piece of work.
2. Derive this signal primarily from content that Pallium already receives — without requiring the integrating agent to provide it.
3. Use this signal to improve retrieval precision and cross-thread packaging for work-related queries.
4. Keep the design minimal — one concept, integrated into existing mechanisms, not a new subsystem.

## Non-Goals

- Building a task graph or project management layer inside Pallium.
- Requiring the integrating agent to always provide work identity. It may provide it as a hint, but Pallium should extract it from content when present.
- Replacing container_ref or thread_ref scoping. Work_ref is an additional affinity signal, not a replacement for visibility rules.
- Handling work identity for all possible external systems. The initial scope is identifiers that appear naturally in conversation and tool use content (ticket IDs, PR numbers, issue keys).

## What "work reference" means

A work reference is a durable external identifier for a unit of work. It typically comes from an external system: a Jira ticket key (`PROJ-123`), a GitHub issue or PR number (`org/repo#456`), an incident ID (`INC-789`), or similar. It may also be a runtime-generated identifier when the integrating agent wants to group work that has no external system.

Work references are:
- **Strings**, not structured objects. `"PROJ-123"`, `"org/repo#456"`, `"INC-789"`.
- **Multi-valued per item**. A single message can reference multiple work items: "I fixed PROJ-123 and updated PROJ-456".
- **Optional**. Most conversational messages will not mention any work reference. The field is empty when nothing is detected.
- **Durable across surfaces**. The same `PROJ-123` appears in a DM, a channel, a tool summary, a PR description. That is the whole point.

Work references are NOT:
- Internal Pallium identifiers.
- Semantic descriptions (those are subject anchors — workstream, component, surface).
- Conversation metadata (those are container_ref, thread_ref).

### Multilingual considerations

Work identifiers from external systems (Jira, GitHub, incident trackers, project management tools) are typically ASCII-based, even in organisations where all other communication is in a non-Latin language. A Hebrew-speaking team still uses `PROJ-123` as their Jira key, not a Hebrew transliteration. This means:

- The normalisation function must be Unicode-safe (`casefold()`, not `upper()`) but will in practice operate on mostly-ASCII values.
- The extraction prompt must be language-neutral — it must extract identifiers from content in any language without assuming English context.
- The negative validation must include non-English content with numeric patterns that are not work identifiers (version numbers, error codes, counts in non-Latin text).
- If a future system uses non-Latin work identifiers, the design accommodates them — work_refs are opaque strings with no format assumption. Normalisation is case-fold + trim, not ASCII-only.
- Matching is exact (casefold equality), not token-overlap. This is correct for both Latin and non-Latin identifiers.

## Where work references come from

### Source 1: LLM extraction from content (primary)

Pallium's extraction prompt already receives the full item content, artifact_kind, and metadata. The LLM extracts decisions, investigations, constraints, work-state signals, and subject hints from this content. Work reference extraction follows the same pattern.

When the LLM sees content like:
- `"Decision: use event-time ordering for PROJ-123 to avoid duplicate holds"` → extracts `["PROJ-123"]`
- `"Tool summary: jira_create_issue [done]: Created PROJ-456"` → extracts `["PROJ-456"]`
- `"We need to revisit the auth changes from PR #89"` → extracts `["#89"]` (or a fuller form if context provides the repo)
- `"The overdue notice batching is ready for review"` → extracts `[]` (no external identifier)

This is content the LLM already sees. Adding "extract any external work identifiers" to the extraction prompt is the same kind of change as adding constraint_text or next_step_text.

### Source 2: Runtime hints from the integrating agent (supplementary)

The integrating agent may know the work context before sending the item — for example, if a channel is dedicated to a project, or if the agent parsed a tool result containing a ticket ID. It can pass this knowledge via item metadata.

Pallium already has a mechanism for this: `pallium_subject_hints` in source item metadata. The design extends this mechanism (or adds an analogous `pallium_work_refs` key) so the runtime can provide known work references that get merged with LLM-extracted ones.

This is a supplement, not the primary path. Most of the time, the content itself contains the references.

## Scenarios — how this works in practice

### Scenario 1: Same ticket discussed in DM and channel

**Setup:**
- Thread A (DM, private): User asks the agent to investigate why PROJ-123 is failing. Agent investigates, finds the root cause, records a decision.
- Thread B (channel, public): A colleague asks "what's the status of PROJ-123?"

**Today:**
- Thread A memories are in container `dm:U123` with `visibility=private`. Thread B query is in container `channel:C456`.
- Cross-container retrieval only returns public memories with no actor_ref. The DM memories are invisible.
- The colleague gets no useful context.

**With work_ref:**
- Thread A's extraction detects `PROJ-123` in the content. The decision and investigation_outcome memories get `work_refs=["PROJ-123"]`.
- Thread B's query content also mentions `PROJ-123`. The query carries `work_refs=["PROJ-123"]`.
- **But visibility rules still apply.** Private DM memories stay private. The work_ref signal does not override visibility.
- **This scenario is NOT solved by work_ref alone.** It requires the DM memories to be explicitly shared (visibility escalation) or for the agent to re-derive the conclusions in a public context.
- **What work_ref does help with:** If the same ticket was also discussed in a prior channel thread (public), those memories ARE retrievable, and work_ref makes that retrieval precise rather than relying on lexical similarity.

**Honest assessment:** Work_ref does not solve the private-to-public bridge. That is a visibility/sharing problem. Work_ref helps within the same visibility boundary or across public contexts.

### Scenario 2: Work resumed in a new thread

**Setup:**
- Thread A: Agent investigates a sync failure, gets blocked on an expired token, creates a task_checkpoint.
- Thread B (same channel, next day): User says "let's continue the catalog sync investigation".

**Today:**
- Routing detects `new_thread` turn_kind and relaxes thread_ref filter when local context is insufficient.
- Retrieval finds Thread A's memories via semantic/lexical similarity to "catalog sync investigation".
- But the packaging locality gate blocks cross-thread packaging: Thread A's task_checkpoint and Thread A's investigation_outcome cannot be bundled together in the response because Thread B has a different thread_ref.
- Result: fragmented injection — the user gets either the checkpoint OR the investigation, not both.

**With work_ref:**
- Thread A's items mention a specific work context (e.g., the sync failure, possibly referencing a ticket or incident ID).
- If both threads share a work_ref (extracted from content or provided by the runtime), the packaging locality gate can allow cross-thread bundling for items that share work_ref.
- Result: the resumption query returns the checkpoint AND the investigation packaged together, because work_ref proves they are about the same work.

**What if there is no external ticket ID?** The user just says "catalog sync investigation" with no ticket number. The LLM extraction returns empty work_refs. The system falls back to the current behaviour — semantic similarity and routing relaxation. Work_ref provides a structural shortcut when identifiers are present, but does not degrade the current path when they are absent.

### Scenario 3: Tool use produces a ticket ID

**Setup:**
- Turn 1: User asks the agent to file a Jira ticket about the sync issue.
- Turn 1 result: Agent creates ticket, tool_use_summary says `"jira_create_issue [done]: Created SYNC-42"`.
- Turn 5 (same thread): User says "add the root cause analysis to SYNC-42".
- A week later, Thread C: Someone asks "what was the outcome of SYNC-42?"

**Today:**
- The tool summary text "Created SYNC-42" is ingested as content. Pallium may extract a decision or investigation from it, but does not recognise SYNC-42 as a structural identifier.
- A week later, the query "outcome of SYNC-42" relies on lexical match against "SYNC-42" appearing in the text_view of indexed memories. This may work if SYNC-42 appears in enough indexed text, but it is fragile — the lexical match competes with all other tokens.

**With work_ref:**
- The extraction prompt detects `SYNC-42` in the tool summary and in the user's follow-up message. Memories from this thread get `work_refs=["SYNC-42"]`.
- A week later, the query "outcome of SYNC-42" also yields `work_refs=["SYNC-42"]` at query time. Retrieval uses this as a strong narrowing signal — prefer memories with matching work_ref.
- Result: precise retrieval of the investigation and decision linked to SYNC-42, without depending on lexical token overlap.

### Scenario 4: One message references multiple work items

**Content:** `"The auth migration (AUTH-100) is blocked by the token service (SYNC-42)."`

**Extraction:** `work_refs=["AUTH-100", "SYNC-42"]`

Both identifiers are attached to the source item and any memories derived from it. Queries about either AUTH-100 or SYNC-42 can find this memory. This is why work_refs must be a list, not a single value.

### Scenario 5: Casual mention vs. actual work context

**Content:** `"We saw something similar in PROJ-999 last year, but that's not relevant here."`

**Risk:** The LLM extracts `PROJ-999` even though it is a passing reference, not the current work context.

**Mitigation:** This is an extraction quality problem, same as with any LLM-derived field. The prompt should instruct: "extract identifiers that the message is actively working on or discussing, not casual historical mentions." Some noise is acceptable — a stale work_ref in a memory is harmless at retrieval time because the ranking pipeline still uses semantic relevance, freshness, and other signals. Work_ref is a ranking boost, not a hard filter.

### Scenario 6: Format inconsistency

**Content variations:** `"PROJ-123"`, `"proj-123"`, `"Proj 123"`, `"ticket PROJ-123"`, `"the PROJ-123 issue"`

**Mitigation:** Normalize work_refs at extraction time. Case-fold, strip whitespace, apply known patterns. The LLM extraction prompt should output the canonical form (e.g., uppercase, hyphen-separated: `"PROJ-123"`). A post-extraction normalisation step can clean up variations the LLM misses.

## Design

The design is split into two slices. Slice 1 is write-time enrichment: extract and store work_refs. Slice 2 is read-time integration: use work_refs in retrieval scoring and packaging. Slice 1 ships first and is validated independently. Slice 2 depends on extraction quality data from slice 1.

### Slice 1: Write-time extraction and storage

#### Extraction: prompt cycle for work_refs (completed)

Adding `work_refs` to the extraction prompt followed the established prompt-change loop. Six variants were tested through a fast evaluator (18 snippets), full bakeoff (59 items × 2 variants), and stability testing (3 runs × 12 decision items).

**Key finding: prompt section placement matters.** Adding work_refs instructions inside the Work-State Signals section caused decision recall to regress (avg 3-6/12 vs 8/12 baseline). The LLM conflated work_ref extraction with signal extraction, reducing attention to the Typed Memory Classification section above. Moving work_refs to its own section after Language eliminated the interference.

**Winner: `strict_typed_memory_v8b_work_refs_separate`** — 867 tokens (+86 vs v7 baseline, +11%).

Prompt structure (additions to v7 baseline):
```
## External References

work_refs: list of external work identifiers (e.g. PROJ-123, INC-789, org/repo#456)
that this message is actively about, regardless of language. NOT work_refs: version
numbers (v2.3.1), error codes (401, E-500), port numbers (8080), batch/record counts
(batch 313, 312 records), casual historical mentions. [] if none.
```

Validation results:

| Metric | v7 baseline | v8b separate |
|--------|-------------|--------------|
| Decision recall (3-run avg) | 8.0/12 | 9.0/12 (no regression) |
| Work_ref positive extraction | N/A | 7/7 (100%) |
| Work_ref negative (false positives) | 3 FP | 0 FP (100%) |
| Multilingual extraction | N/A | 4/4 (Hebrew + Japanese) |
| Token overhead | — | +86 tokens (+11%) |
| Signal metrics (all fields) | Baseline | Identical |

**SemanticExtraction change** (in `semantic/common.py`):

```python
work_refs: tuple[str, ...] = ()  # extracted external work identifiers
```

**Normalisation** (in `semantic/llm_agent_memory.py`, post-extraction):

Normalisation uses `casefold()` instead of `upper()` for Unicode correctness. While most work identifiers are ASCII, the normalisation must not break non-Latin characters if a system uses them.

Normalisation also canonicalises separators so that `PROJ-123`, `PROJ 123`, `proj_123`, and `Proj - 123` all resolve to the same canonical form. This is applied consistently at three points: stored work_refs (extraction time), runtime hints (ingest time), and query text (query time).

```python
import re

_WORK_REF_SEPARATOR_RE = re.compile(r"[\s_\-]+")

def _normalize_work_ref(raw: str) -> str | None:
    value = raw.strip().casefold()
    if not value or len(value) > 128:
        return None
    # Collapse whitespace, underscores, hyphens to a single hyphen
    value = _WORK_REF_SEPARATOR_RE.sub("-", value)
    # Strip leading/trailing separators
    value = value.strip("-")
    return value if value else None
```

Examples:
- `"PROJ-123"` → `"proj-123"`
- `"PROJ 123"` → `"proj-123"`
- `"proj_123"` → `"proj-123"`
- `"Proj - 123"` → `"proj-123"`
- `"org/repo#456"` → `"org/repo#456"` (slash and hash are not separators — they carry meaning)

The same normalisation is applied to query text before matching. At query time, the original query text is normalised with `_normalize_work_ref` applied to each candidate work_ref, and the query text is also passed through a matching normalisation so that substring comparison works across surface variants. Concretely: `_normalize_work_ref_for_query(query_text)` applies casefold and separator canonicalisation to the full query string, then checks whether any candidate's normalised work_ref appears as a substring.

#### Storage: work_refs on MemoryEnvelopeScope

Work_refs are **not stored in envelope subjects**. Subject anchors (`workstream`, `component`, `surface`) are semantic descriptors designed for fuzzy token-overlap matching in the anchor prefilter. Work_refs are opaque structural identifiers that need exact-match semantics. Mixing them would cause the anchor prefilter to match on individual tokens of the identifier (e.g., "proj" and "123" from "PROJ-123"), creating false alignment signals.

Instead, work_refs are stored on `MemoryEnvelopeScope`, which already holds `container_ref` and `thread_ref` — the other structural scoping fields:

```python
@dataclass(frozen=True)
class MemoryEnvelopeScope:
    container_ref: str | None = None
    thread_ref: str | None = None
    work_refs: tuple[str, ...] = ()  # new
```

This keeps structural identifiers (container, thread, work) separate from semantic descriptors (workstream, component, surface). The scope is already persisted in `envelope_json` — no schema migration needed. Routing code can access work_refs via `item.envelope.scope.work_refs`.

#### Source item metadata: runtime hints

Add a `pallium_work_refs` metadata key, parallel to `pallium_subject_hints`:

```python
metadata = {
    "pallium_work_refs": ["PROJ-123", "SYNC-42"]
}
```

During processing, merge runtime-provided work_refs with LLM-extracted ones (union, deduplicated, normalised). Same merge pattern as subject hints in `_subject_anchors_from_metadata()`.

#### Thread aggregation: scoped union

Thread aggregation should carry work_refs into the thread_summary envelope. However, naive union of all work_refs from all source items in a long thread dilutes the signal — a thread that touches 5 different tickets over its lifetime would match queries about any of them equally.

Mitigation: union only work_refs from source items whose extraction produced non-empty work_refs (i.e., items the LLM judged to be actively about those work items), and cap the set at a reasonable bound (e.g., 5 most recent distinct refs). If a thread genuinely spans many work items, the per-item memories remain precise — the thread_summary becomes a weaker signal, which is correct.

#### Consolidation: work_ref pass-through

FactConsolidationStrategy continues to group by `(container_ref, subject, category)`. Work_ref does not change this grouping. The consolidated fact_summary inherits work_refs from its input facts (union, same capped approach as thread aggregation).

#### Slice 1 validation

See the Validation plan section below for the full data-driven validation strategy, including regression on existing corpora, negative/positive extraction snippets, multilingual cases, and extraction frequency measurement.

### Slice 2: Retrieval integration (after slice 1 validation)

Slice 2 depends on data from slice 1. If extraction quality is poor or work_refs are too rare in real content, this slice may be descoped or redesigned. The design below is directional — specific scoring values should be calibrated against eval data once slice 1 provides it.

#### Query-time work_ref matching: structural, not regex

Pallium does not use language-specific cues or pattern matching in the query path. The cue-free control plane decision (2026-03-22) established that routing uses typed structure and retrieval evidence, not text parsing. Detecting work_refs in query text via regex would reintroduce language-specific cues.

Instead, work_ref matching at query time follows the same pattern as the subject anchor prefilter: look at what the candidates carry, check if it appears in the query, and use matches to adjust scoring. The difference is that subject anchors use fuzzy token-overlap matching (suitable for semantic descriptors), while work_refs use exact normalised-string matching (suitable for structural identifiers).

**Concrete mechanism — work_ref affinity detection:**

1. After retrieval returns candidates, collect all distinct `work_refs` from the candidate set (from `envelope.scope.work_refs`). These are already normalised at extraction time.
2. Normalise the query text with the same canonical normalisation (casefold + separator collapse). This produces a normalised query string where `"What was the outcome of SYNC-42?"` becomes `"what was the outcome of sync-42?"` and `"status of PROJ 123"` becomes `"status of proj-123"`.
3. For each candidate work_ref, check if it appears as a **substring** of the normalised query text. Because both sides are normalised with the same function, `"proj-123"` matches regardless of whether the user typed `"PROJ-123"`, `"PROJ 123"`, or `"proj_123"`.
4. Matched work_refs become the **query work_refs** — the set of work identifiers this query is about, derived from evidence in the candidate set.

This is data-driven, not pattern-based. We are not scanning for "things that look like ticket IDs." We are checking whether known structural identifiers from the memory store appear in the query. This is analogous to the anchor prefilter checking whether known subject anchors from candidates match query tokens — but with exact-string matching instead of token-overlap matching, because work_refs are opaque identifiers, not semantic phrases.

**High-confidence path: integrating agent provides work_refs.** The integrating agent may provide known work_refs in the query request, same as it provides `container_ref` and `thread_ref`:

```python
@dataclass(frozen=True)
class QueryFilters:
    # ... existing fields ...
    work_refs: tuple[str, ...] = ()  # optional, from integrating agent
```

When the integrating agent provides work_refs, the candidate-side detection is skipped — the provided values are used directly. This is the same pattern as container_ref: the integrating agent provides it, Pallium uses it for scoping.

**When neither source produces work_refs:** No work_ref affinity is applied. The system falls back to current behaviour — semantic similarity, lexical matching, and routing relaxation. Work_ref is additive. It improves precision when identifiers are present but does not degrade the existing path when they are absent.

#### Scoring integration

Add work_ref affinity as a scoring signal in `routing_scoring.py`. The specific bonus value should be calibrated against the routing eval suite once slice 1 provides real extraction data. As a starting point for calibration:

- Shared work_ref between query and candidate → positive affinity (provisionally comparable to same-thread boost for continuity_memory, but tuned from eval data)
- No shared work_ref → no change to existing scoring

Work_ref affinity applies across all memory layers, not just continuity_memory. A decision from a different thread about the same ticket should benefit from the affinity signal.

#### Packaging gate relaxation

Extend `_candidate_locality_compatible_for_packaging()` in `routing_selection.py`:

```python
if primary_work_refs and candidate_work_refs and primary_work_refs.intersection(candidate_work_refs):
    return True  # allow cross-thread packaging for shared work identity
# ... existing thread/container logic unchanged
```

This is the key change that unblocks Scenario 2 — cross-thread packaging when work_refs match. A task_checkpoint and an investigation_outcome from different threads can be packaged together if they share a work_ref.

#### Query-time hard filtering (future, not initial scope)

Adding `work_refs` to QueryFilters as a hard filter (e.g., "show me only PROJ-123 context") is possible but not needed initially. The ranking signal and packaging relaxation are sufficient. Hard filtering can be added later without changing the storage model.

## Edge cases

| Case | Behaviour | Rationale |
|------|-----------|-----------|
| No work_ref in content | `work_refs=()`, no effect on scoring | Most messages have no external ID. System falls back to current behaviour. |
| Multiple work_refs in one message | All stored, all used for matching | Real messages can reference multiple tickets. |
| Same work_ref across containers | Scoring boost applies, but visibility still enforced | Work_ref does not override private/public boundaries. |
| LLM hallucinates a work_ref | Noise in work_refs list | Ranking boost for a non-existent ID is harmless — no real query will match it. |
| LLM misses a work_ref in content | Falls back to current retrieval | Partial extraction is acceptable. Runtime hints can supplement. |
| Casual mention ("we saw this in PROJ-999 last year") | May be extracted | Prompt instructs to prefer active work. Some noise acceptable — ranking dilutes stale refs. |
| Runtime provides work_ref but content has no mention | Accepted as-is | Runtime may have external knowledge (e.g., channel-to-project mapping). |
| work_ref format varies ("PROJ-123" vs "proj 123" vs "proj_123") | All normalise to same canonical form ("proj-123") | Casefold + separator collapse applied at extraction, ingest, and query time. |
| Very long work_ref (>128 chars) | Dropped during normalisation | Likely not a real identifier. |
| Query mentions work_ref but no memories have it | No matches from work_ref signal; falls back to semantic | Graceful degradation. |
| work_ref collides across projects ("PROJ-123" in two orgs) | Scoped by container_ref | Within a container, PROJ-123 is unambiguous. Cross-container collisions are unlikely in practice and mitigated by visibility rules. |
| Long-running thread touches many tickets | Thread_summary gets capped set of most recent work_refs | Prevents dilution. Per-item memories remain precise. |
| Query has no work_refs and candidates do | Candidate-side clustering may still detect shared work_ref signal from evidence | Structural signal from candidates, no query parsing needed. |
| Non-English content with ASCII work ID | Extracted normally — "בוא נמשיך על PROJ-123" yields `["proj-123"]` | Work IDs are typically ASCII regardless of surrounding language. LLM handles mixed-script content. |
| Non-English content with numeric patterns | Not extracted — version numbers, port numbers, batch counts in any language are not work_refs | Negative validation includes multilingual snippets. |

## What does NOT change

- Memory types — no new memory types are introduced.
- Visibility rules — work_ref does not bypass private/container/public boundaries.
- Container/thread scoping — these remain the primary structural scope.
- Consolidation strategy — fact consolidation still groups by (container_ref, subject, category).
- Subject anchors — work_refs are NOT stored in envelope.subjects. The anchor prefilter is unaffected.
- FTS5 indexing — work_refs are not added to the lexical index.
- Cue-free control plane — no regex or language-specific pattern matching at query time.
- API contract — no new required fields. `pallium_work_refs` in metadata is optional. `work_refs` in QueryFilters is optional.

## Files changed

### Slice 1 (extraction and storage)

| File | Change |
|------|--------|
| `semantic/llm_agent_memory.py` | Add work_refs to extraction prompt, add normalisation, add to SemanticExtraction parsing |
| `semantic/common.py` | Add `work_refs` field to SemanticExtraction dataclass |
| `core/models.py` | Add `work_refs: tuple[str, ...] = ()` to `MemoryEnvelopeScope` |
| `semantic/agent_conversation_memory_memory.py` | Propagate work_refs from extraction + metadata into envelope.scope.work_refs |
| `semantic/agent_conversation_memory_anchors.py` | Add `_work_refs_from_metadata()` for runtime hints (parallel to subject hints) |
| `semantic/agent_conversation_memory_threads.py` | Union work_refs from source items into thread_summary envelope scope (capped) |

### Slice 2 (retrieval integration — after slice 1 validation)

| File | Change |
|------|--------|
| `core/models.py` | Add `work_refs` to `QueryFilters` (optional) |
| `api/schemas.py` | Expose `work_refs` in query request schema |
| `semantic/agent_conversation_memory_routing_scoring.py` | Add work_ref affinity in scoring |
| `semantic/agent_conversation_memory_routing_selection.py` | Extend `_candidate_locality_compatible_for_packaging()` for work_ref match |
| `semantic/agent_conversation_memory_routing_signals.py` | Add work_ref clustering detection in candidate evidence |

## Validation plan

### Existing data that already contains work identifiers

The eval corpus already contains external work identifiers — no need to invent purely synthetic data:

- **`evals/work_resumption/scenarios.json`** — 3 scenarios reference `LIB-241`, 1 references `LIB-314`. The `wrong-thread-implementation-guard` scenario explicitly tests cross-ticket contamination: queries about LIB-241 must not retrieve LIB-314 state from a different thread. This is exactly the scenario work_ref improves — today it relies on semantic/lexical discrimination, with work_ref it becomes a structural signal.
- **`evals/integration_readiness/scenarios.json`** — 1 scenario references `LIB-241` in a privacy isolation context.
- **`evals/semantic/input/items.jsonl`** — 59 items with no work identifiers today. Baseline for negative validation: extraction on this corpus must produce `work_refs=()` for all items.
- **`evals/semantic/input/items_multilingual.jsonl`** — 14 items in Hebrew, English, and mixed. No work identifiers today. Baseline for multilingual negative validation.

### Slice 1

**Step 1: Fast work_ref extraction evaluator**

Build the focused evaluator described in the prompt cycle section above. Run both candidate variants against 15-20 snippets. This is the first gate — if neither variant can extract work_refs without false positives, stop and redesign the prompt before proceeding.

**Step 2: Comparative bakeoff on existing corpus (regression + token budget)**

Run the semantic extraction runner with both new variants and the current baseline against `items.jsonl` (59 items) and `items_multilingual.jsonl` (14 items). Compare correctness on all existing fields, false positive rate for work_refs, and token metrics. Choose the winner per the prompt improvement working rules: smallest variant that preserves all existing behaviour and adds correct work_ref extraction.

**Step 3: Negative extraction snippets (committed to fast evaluator)**

Add to the fast evaluator (and later committed to `evals/prompt_variant_eval.py`):

- `"Root cause: version 2.3.1 introduced a regression in the sync path"` → expect `work_refs=[]`
- `"Blocked: catalog API returned 401 because the service token expired"` → expect `work_refs=[]`
- `"Partial progress: refreshed 312 reservation records before failure"` → expect `work_refs=[]`
- `"Next step: refresh the catalog service token and rerun from batch 313"` → expect `work_refs=[]`
- `"The admin toggle wiring is ready, but kiosk fallback coverage is still missing"` → expect `work_refs=[]`
- `"We saw something similar in PROJ-999 last year, but that's not relevant here"` → expect `work_refs=[]`
- `"Tool summary: Bash [done]: git commit -m 'Update docs'"` → expect `work_refs=[]`
- `"Constraint: do not open a browser or use SSO-backed tools"` → expect `work_refs=[]`
- Multilingual: `"בדקנו את הבעיה בגרסה 2.3.1 ומצאנו שגיאה בסנכרון"` (Hebrew, version number) → expect `work_refs=[]`
- Multilingual: `"サーバーがポート8080でエラーを返しました"` (Japanese, port number) → expect `work_refs=[]`

**Step 4: Positive extraction snippets (committed to fast evaluator)**

- `"Decision: use event-time ordering for PROJ-123 to avoid duplicate holds"` → expect `["proj-123"]`
- `"Tool summary: jira_create_issue [done]: Created SYNC-42"` → expect `["sync-42"]`
- `"The auth migration (AUTH-100) is blocked by the token service (SYNC-42)"` → expect `["auth-100", "sync-42"]`
- `"The overdue notice batching is ready for review"` → expect `work_refs=[]`
- Multilingual: `"בוא נמשיך לעבוד על PROJ-123"` (Hebrew) → expect `["proj-123"]`
- Multilingual: `"SYNC-42のチケットを確認してください"` (Japanese) → expect `["sync-42"]`

**Step 5: Extraction frequency measurement on existing work_resumption data**

Run extraction on the work_resumption scenario content items that contain `LIB-241` / `LIB-314` in their text. Measure: does the LLM reliably extract these identifiers from content that clearly contains them? This is the viability check — if extraction is unreliable on content that obviously has identifiers, the feature needs a different approach.

Also run on `items.jsonl` (59 items with no identifiers) and confirm 0% extraction rate.

**Step 6: Unit tests**

- Normalisation: case folding, separator canonicalisation (`"PROJ-123"` == `"PROJ 123"` == `"proj_123"`), length guard, dedup
- Query-time normalisation: same normalisation applied to query text for substring matching
- Metadata merge: runtime hints + LLM extraction → union
- Envelope scope: work_refs stored and retrievable via `envelope.scope.work_refs`
- Thread aggregation: union from source items, capping
- Serialisation round-trip: envelope_json with work_refs

### Slice 2 (contingent on slice 1 data)

**Step 7: Quantitative gate — work resumption benchmark**

The `wrong-thread-implementation-guard` scenario is the natural before/after test:

- Run the work resumption benchmark as baseline (current behaviour, no work_ref)
- Run again with work_ref extraction and affinity enabled
- Measure: does `LIB-314` get a lower affinity score when the query targets `LIB-241`?
- Verify: all existing passing scenarios still pass (regression check)

This is a real measurement on existing authored scenarios, not synthetic data.

**Step 8: Cross-thread packaging scenario**

Create a new scenario modelling Scenario 2 (work resumed in new thread):
- Thread A: investigation + decision about `LIB-241`
- Thread B (same container, new thread): query "What state were we in on LIB-241?"
- Assert: Thread A's investigation AND decision are packaged together (not fragmented)

**Step 9: Scoring calibration**

Use the benchmark results from step 6 to calibrate the work_ref affinity score:
- Measure score gap between same-work-ref and different-work-ref candidates
- Set value to reliably outscore different-work-ref without overwhelming other signals
- Verify calibrated value causes no regressions

**Step 10: Negative validation**

- Work_ref does NOT allow cross-container retrieval of private memories
- Empty work_refs do not affect scoring or packaging
- Spurious work_refs do not contaminate unrelated queries
- `same-thread-no-value-continuation` scenario still suppresses injection when thread already has the context (work_ref must not override local-context-sufficient gate)

### Eval extensions (durable regression coverage)

Validation proves the feature works at ship time. Eval extensions make it stay working — they become permanent regression coverage in the repo. Each slice should leave behind authored eval scenarios that catch future regressions.

**Slice 1 eval extensions:**

1. **Prompt variant eval snippets** — the negative and positive extraction cases from steps 2-3 above are committed as permanent snippets in `evals/prompt_variant_eval.py`. They protect against future prompt changes that break work_ref extraction or introduce false positives. This includes the multilingual cases.

2. **Semantic extraction fixtures** — add 4-6 items to `evals/semantic/input/items.jsonl` that contain work identifiers in their content (e.g., decisions about `LIB-241`, tool summaries creating tickets). These become part of the standard extraction regression set and verify that work_refs are extracted alongside existing fields (candidate_type, decision_text, etc.).

3. **Multilingual extraction fixtures** — add 2-3 items to `evals/semantic/input/items_multilingual.jsonl` with work identifiers in non-English content. Verifies cross-language extraction stays correct as prompts evolve.

**Slice 2 eval extensions:**

4. **Work resumption scenario: cross-thread with shared work_ref** — add a new scenario to `evals/work_resumption/scenarios.json` that specifically tests Scenario 2 from this design: work in Thread A with `LIB-241`, resumption query in Thread B mentioning `LIB-241`. Expected outcome: memories from Thread A packaged together. This is different from existing scenarios which test within the same thread or use `wrong-thread-implementation-guard` as a negative case.

5. **Work resumption scenario: work_ref disambiguation** — extend or create a scenario where two tickets coexist in the same container across different threads, and the query targets one by identifier. Similar to `wrong-thread-implementation-guard` but with work_ref affinity as the primary discrimination signal rather than semantic/lexical matching. This scenario should pass more reliably than the current guard_terms approach.

6. **Exploratory QA seed scenarios** — add 2-3 seed scenarios to `evals/generated_exploratory/scenarios/seed_invariant_scenarios.json` that exercise work_ref isolation invariants:
   - INV: memories with `work_refs=["X"]` should not be injected when the query targets `work_refs=["Y"]` (cross-work contamination)
   - INV: empty work_refs must not affect injection decisions (graceful degradation)

7. **Memory routing scenarios** — add 1-2 scenarios to `evals/memory_routing/scenarios.json` testing that work_ref affinity influences routing correctly (same-work-ref memories ranked higher than different-work-ref memories).

**Committed eval artifacts checklist:**

| Artifact | Location | Slice | Purpose |
|----------|----------|-------|---------|
| Extraction snippets (positive + negative + multilingual) | `evals/prompt_variant_eval.py` | 1 | Prompt regression |
| Semantic input items with work_refs | `evals/semantic/input/items.jsonl` | 1 | Extraction regression |
| Multilingual items with work_refs | `evals/semantic/input/items_multilingual.jsonl` | 1 | Cross-language regression |
| Cross-thread resumption scenario | `evals/work_resumption/scenarios.json` | 2 | Packaging gate regression |
| Work_ref disambiguation scenario | `evals/work_resumption/scenarios.json` | 2 | Affinity scoring regression |
| Exploratory QA seed scenarios | `evals/generated_exploratory/scenarios/` | 2 | Invariant regression |
| Memory routing scenarios | `evals/memory_routing/scenarios.json` | 2 | Routing regression |

## Known limitations

| Limitation | Severity | Mitigation |
|-----------|----------|-----------|
| LLM extraction is not 100% reliable for work_ref detection | Medium | Runtime hints supplement LLM. Extraction frequency measured before committing to slice 2. |
| Private-to-public bridge is not solved | Known | This is a visibility problem, not a work_ref problem. Noted explicitly in Scenario 1. |
| No query-time work_ref detection from query text | By design | Consistent with cue-free control plane. Work_ref detection at query time is data-driven: candidate work_refs are matched as substrings of normalised query text, or integrating agent provides them directly. No regex or pattern-based detection. |
| No formal work_ref registry or validation | Low | Work_refs are opaque strings. No correctness guarantee beyond normalisation. |
| Thread aggregation union dilutes with many tickets | Low | Capped at N most recent distinct refs. Per-item memories remain precise. |
| Extraction prompt change requires prompt version bump | Expected | Standard practice — bump schema version, track with prompt provenance. |
| Extraction adds token overhead to every LLM call | Low | One additional field in a 14-field schema. Cost proportional to prompt instruction tokens, not content. Measured in slice 1. |
| Slice 2 scoring values are provisional | Expected | Calibrated from eval data, not assumed. Flagged as provisional until calibration. |

## Open questions

1. **Should work_ref extraction also run in the conversational_knowledge package (fact extraction)?** Currently scoped to agent_conversation_memory only. If facts about PROJ-123 should also carry work_refs, the fact extraction prompt needs the same addition.

2. **How often do real integrating-agent conversations contain structured work IDs?** This determines whether slice 2 is worth building. If most work discussions reference tickets/PRs, the feature is high-value. If they rarely do, work_ref helps edge cases only. Slice 1's extraction frequency measurement is the gate.

3. **Should candidate-side work_ref clustering be a new signal in the signal envelope, or a direct scoring input?** The signal envelope approach is more consistent with existing architecture but adds complexity. A direct scoring input is simpler but less traceable. Decide when designing slice 2.

## Revision history

- 2026-04-14: Initial draft.
- 2026-04-14: Revised after architect review. Key changes: (a) work_refs stored on MemoryEnvelopeScope, not in envelope subjects — subject anchors use token-overlap matching unsuitable for structural identifiers; (b) removed regex-based query-time detection — conflicts with cue-free control plane decision, replaced with integrating-agent query parameter and candidate-side clustering; (c) split into two slices — extraction validated independently before retrieval integration; (d) thread aggregation capped to prevent signal dilution.
- 2026-04-14: Strengthened slice 1 validation. Prompt change is a migration — negative cases (false positive prevention) are highest priority. Full existing fixture set regression required before shipping. Specific negative snippets added for version numbers, error codes, batch numbers, and other non-ticket patterns.
- 2026-04-14: Multilingual as core capability. Added multilingual considerations section. Prompt is language-neutral. Normalisation uses casefold() not upper(). Validation includes non-English negative cases (Hebrew, Japanese) and mixed-script positive cases. Matching is exact casefold equality, not token-overlap.
- 2026-04-14: Concrete query-time mechanism. Work_ref matching follows the anchor prefilter pattern — look at candidates, find what matches the query — but uses exact normalised-string matching (substring of casefold query text) instead of token-overlap. Data-driven (matches against known values from candidate set), not pattern-based (no regex). Integrating agent can also pass work_refs directly in QueryFilters as the high-confidence path. Normalisation canonicalises separators (hyphens, spaces, underscores → single hyphen) so "PROJ-123", "PROJ 123", "proj_123" all match. Same normalisation applied to stored work_refs, runtime hints, and query text.
- 2026-04-14: Data-driven validation plan. Replaced synthetic-only validation with plan grounded in existing eval data. work_resumption scenarios already contain LIB-241/LIB-314 — used for extraction viability check and as quantitative before/after gate for slice 2. `wrong-thread-implementation-guard` scenario is the natural test for work_ref discrimination. Existing corpus (items.jsonl, items_multilingual.jsonl) used as negative baseline. Validation plan now has 9 steps with concrete data sources for each.
- 2026-04-14: Eval extensions as deliverable. Each slice must leave behind committed eval scenarios that become durable regression coverage. 7 eval artifacts across prompt variant eval, semantic input fixtures, work resumption scenarios, exploratory QA seeds, and memory routing scenarios. Checklist added to validation plan.
- 2026-04-14: Prompt cycle treatment. work_refs extraction follows the established prompt-change loop (docs/context/prompt-improvement.md): at least two candidate variants (inline vs with-example), fast focused evaluator before full benchmark, comparative bakeoff against current baseline, token budget check. Winner selected by smallest-variant-that-wins rule. Prompt schema version bumped.
