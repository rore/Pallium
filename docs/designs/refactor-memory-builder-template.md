# Refactor: Memory Builder Template Pattern

**Status:** Proposal
**Scope:** `semantic/agent_conversation_memory_threads.py` (1,382 lines)
**Affected builders:** `build_thread_summary`, `build_task_checkpoint_memory`, `build_pattern_memory`, `build_continuity_memory`

## 1. Current Duplication Pattern

The four builder functions follow the same six-phase structure:

1. **Collect materials** -- gather text from the input (thread aggregate or consolidation group), truncate to a per-builder char budget.
2. **Invoke LLM** -- call `provider.generate_json()` with a builder-specific system prompt, user prompt, and schema description.
3. **Parse and validate response** -- extract `summary` (mandatory for all four), plus builder-specific fields; apply defaults for missing/empty fields.
4. **Build memory object** -- construct a `MemoryObject` with builder-specific payload shape, then attach a `MemoryEnvelope` via `_build_memory_envelope()`.
5. **Build index entries** -- create a lexical `IndexEntry` from `normalize_for_index(index_source)`, apply inline enrichment via `_apply_inline_enrichment()`, and optionally create a vector embedding entry via `build_embedding_text()`.
6. **Assemble result** -- return `ProcessResult` (or a `(MemoryObject, list)` tuple for `build_task_checkpoint_memory` since it is nested inside `build_thread_summary`).

Each builder repeats phases 4-5 almost verbatim. The diff between `build_pattern_memory` (lines 570-693) and `build_continuity_memory` (lines 695-822) is particularly striking: the structure is identical line-for-line, with only the prompt constants, memory type string, output field names, and index text-view name swapped.

### Line-count breakdown (approximate)

| Builder                      | Lines | Material prep | LLM call | Parse/validate | MemoryObject + envelope | Indexing + enrichment | Result assembly |
|------------------------------|-------|---------------|----------|----------------|------------------------|-----------------------|-----------------|
| `build_thread_summary`       | 208   | 18            | 14       | 17             | 34                     | 33                    | 7 (+50 for checkpoint sub-call) |
| `build_task_checkpoint_memory`| 124  | 9             | 12       | 17             | 30                     | 23                    | 2               |
| `build_pattern_memory`       | 124   | 12            | 12       | 6              | 38                     | 26                    | 6               |
| `build_continuity_memory`    | 128   | 14            | 12       | 9              | 36                     | 26                    | 6               |

The indexing + enrichment tail (build lexical entry, apply inline enrichment, build vector entry) is nearly character-for-character identical across all four. The MemoryObject + envelope block is identical in shape, differing only in the field names and constant references.

## 2. What Is Shared vs. What Varies

### Shared (template-safe)

These steps are structurally identical across all four builders and only differ by substituting constants:

| Phase | Shared logic |
|-------|-------------|
| LLM invocation | `provider.generate_json(system_prompt=..., user_prompt=..., schema_description=...)` |
| Summary validation | `parsed_summary = response.parsed_json.get("summary")` + non-empty guard + `.strip()` |
| Semantic provenance dict | `{"semantic_plugin": plugin_name, "prompt_variant": prompt_variant}` (pattern/continuity also add consolidation provenance) |
| MemoryObject construction | `MemoryObject(type=..., schema_id=..., schema_version="v1", payload=..., container_visibility=..., container_ref=..., freshness_at=...)` |
| Envelope attachment | `replace(memory_object, envelope=_build_memory_envelope(kind=..., container_ref=..., thread_ref=..., confidence=..., producer_kind=..., producer_schema_id=..., producer_schema_version=..., prompt_variant=..., kind_basis=..., subjects=...))` |
| Lexical index entry | `build_index_entry(target_kind="memory_object", target_id=..., index_type="lexical", text_view=normalize_for_index(index_source), text_view_name=...)` |
| Inline enrichment | `_apply_inline_enrichment(memory_object=..., retrieval_context=..., plugin_name=..., prompt_variant=..., llm_metadata=response.metadata)` |
| Vector embedding entry | `build_embedding_text()` guard + `build_index_entry(..., index_type=VECTOR_INDEX_TYPE, ...)` |
| ProcessResult assembly | `ProcessResult(annotations=[], memory_objects=[memory_object], relations=[], index_entries=index_entries)` |

### Varies (must remain builder-specific)

| Phase | What varies | Examples |
|-------|------------|---------|
| **Input shape** | Thread aggregate vs. consolidation group vs. pre-digested summary | `build_thread_summary` takes `ThreadAggregate` + `list[MemoryObject]`; consolidation builders take `ConsolidationGroup`; `build_task_checkpoint_memory` takes pre-processed strings |
| **Material collection** | How text is assembled before the LLM call | Thread builder filters artifacts, formats work items, builds thread material. Pattern/continuity iterate `group.candidates`. Task checkpoint receives pre-digested text. |
| **Prompt constants** | System prompt, schema description, user prompt preamble, char budget | All four have distinct system prompts, schema descriptions, and user prompt framing |
| **Response parsing beyond summary** | Extra fields, defaults, normalization | Thread: `retrieval_context`. Task checkpoint: `task`, `current_state`, `key_findings`, `blocker_state`, `next_step`, `evidence`, `freshness_signal` (each with its own default function). Pattern: `pattern_label`. Continuity: `continuity_question`, `carry_forward_answer`. |
| **Payload shape** | The dict structure stored on `MemoryObject.payload` | Each builder has a different set of fields |
| **Index text composition** | Which fields go into `index_source` | Thread: summary + conclusions + work artifacts. Task checkpoint: summary + task + state + all detail fields. Pattern: summary + conclusions. Continuity: summary + question + answer + conclusions. |
| **Relations** | Evidence relations back to source items and conclusions | Thread builder creates `supported_by` and `relates_to` relations; consolidation builders currently return empty relations |
| **Nested sub-call** | Thread summary conditionally invokes task checkpoint | Unique to `build_thread_summary` |
| **Subject anchors** | Source of constraint/subject metadata | Thread: merged from conclusions + source items. Pattern/continuity: from group candidates. Task checkpoint: inherited from parent thread call. |
| **Producer kind** | `"thread_aggregation"` vs `"consolidation"` | Controls envelope derivation metadata |

## 3. Proposed Template Pattern

### Approach: Generic helper function, not a base class

A base class would force an inheritance hierarchy onto what are currently simple module-level functions. The builders are called from a thin semantic-package facade (`agent_conversation_memory.py`) that delegates to them; adding a class hierarchy here would pull weight into the wrong layer.

Instead, extract a **`_finalize_memory_builder`** helper function that owns the shared tail: envelope attachment, lexical indexing, enrichment, vector embedding, and result assembly. Each builder stays a standalone function with its own material collection, LLM call, and response parsing -- then calls the shared tail.

### Proposed shape

```
def _finalize_memory_builder(
    *,
    # The constructed MemoryObject (before envelope)
    memory_object: MemoryObject,
    # Envelope parameters
    container_ref: str | None,
    thread_ref: str | None,
    producer_kind: str,              # "thread_aggregation" or "consolidation"
    producer_schema_id: str,
    producer_schema_version: str,
    prompt_variant: str,
    subjects: list[MemorySubjectAnchor],
    # Indexing parameters
    index_source: str,               # raw text to normalize for lexical index
    text_view_name: str,             # e.g. THREAD_SUMMARY_TEXT_VIEW
    # Enrichment parameters
    retrieval_context: str | None,
    plugin_name: str,
    llm_metadata: object | None,
    # Optional extras
    relations: list[Relation] | None = None,
) -> ProcessResult:
    """
    Shared tail for all memory builder functions.

    Attaches envelope, builds lexical + vector index entries,
    applies inline enrichment, assembles ProcessResult.
    """
```

Each existing builder would:
1. Keep its own material collection, LLM call, and response parsing (the "head").
2. Construct the `MemoryObject` with its type-specific payload (unchanged).
3. Call `_finalize_memory_builder(...)` to get back a `ProcessResult`.

### Why not a Protocol or dataclass-based spec

A `MemoryBuilderSpec` dataclass holding prompt constants, parse functions, and payload constructors was considered. This would let you write `build_memory(spec, inputs)`. However:

- The input shapes diverge too much (thread aggregate vs. consolidation group vs. pre-digested strings) to unify into one input protocol without an `Any`-flavored adapter layer.
- The parse/validate step for `build_task_checkpoint_memory` has 8 fields with individual default-fallback functions. Encoding that as a spec would trade procedural clarity for declarative complexity.
- The material collection for `build_thread_summary` is the most complex (artifact filtering, work artifact selection, conclusion formatting) and would not fit a generic "collect" step.

The shared-tail helper avoids these problems by leaving the divergent head untouched and only extracting the convergent tail.

## 4. Migration Path

### Phase 1: Extract `_finalize_memory_builder` (low risk)

1. Write `_finalize_memory_builder` as a private function in the same module.
2. Migrate `build_pattern_memory` first -- it is the simplest and most "canonical" shape.
3. Migrate `build_continuity_memory` next -- nearly identical to pattern.
4. Migrate `build_task_checkpoint_memory` -- slightly different because it returns `(MemoryObject, list)` instead of `ProcessResult`. The helper should return both, or the checkpoint builder can unwrap.
5. Migrate `build_thread_summary` last -- it has the nested checkpoint sub-call and relation assembly, so the migration is more involved.
6. Run the full test suite after each individual migration.

### Phase 2: Adapt `build_task_checkpoint_memory` return type (optional, low risk)

`build_task_checkpoint_memory` currently returns `tuple[MemoryObject, list]` because it is called from inside `build_thread_summary`, which assembles the combined `ProcessResult`. Consider having it return `ProcessResult` directly and letting the parent merge results. This would make all four builders consistent and let the shared tail own the full shape.

### Phase 3: Extract prompt constant bundles (optional, cosmetic)

Group each builder's prompt constants (`PROMPT_SCHEMA_ID`, `PROMPT_SCHEMA_VERSION`, `SCHEMA_DESCRIPTION`, `SYSTEM_PROMPT`, `MAX_TEXT_CHARS`, `TEXT_VIEW`) into a named tuple or frozen dataclass. This reduces the constant-name proliferation at the top of the file but is purely cosmetic and can be done independently.

### Expected line reduction

- Phases 4-5 (envelope + indexing + enrichment + vector embedding) are ~25-30 lines per builder.
- With 4 builders, the shared tail eliminates ~75-90 lines of near-duplicate code.
- The helper itself would be ~30-35 lines.
- Net reduction: ~45-60 lines, from 1,382 to roughly 1,320-1,335.

The primary value is not line reduction -- it is eliminating the risk that a future change to the indexing or enrichment protocol is applied to 3 of 4 builders but not the 4th.

## 5. Risk Assessment

### LLM hot-path impact: None

The shared tail covers post-LLM work only (envelope attachment, index entry construction, enrichment application). The LLM call itself (`provider.generate_json`) and all material preparation stay in each builder's head. There is no change to what prompts are sent, how responses are parsed, or when the LLM is called.

### Behavioral regression risk: Low

- The extracted logic is pure data transformation (no I/O, no state mutation beyond constructing new objects).
- Each builder's test coverage already exercises the full output shape (MemoryObject payload, index entries, relations, enrichment).
- The migration can be verified by asserting output equality: run the existing builder and the refactored builder on the same inputs and compare `ProcessResult` field-by-field.

### Specific risks to monitor

| Risk | Mitigation |
|------|-----------|
| `build_task_checkpoint_memory` returns a different shape | Phase 2 addresses this; or the helper can have a `skip_process_result=True` mode |
| `build_thread_summary` nested checkpoint call breaks if the tail changes | Keep checkpoint assembly in the thread summary function; only extract its own tail |
| Prompt provenance divergence (thread builders include `prompt_schema_id`/`version` in payload; consolidation builders embed it in `consolidation_provenance`) | The helper does not touch payload construction -- provenance in payload stays builder-specific |
| Enrichment or vector embedding behavior changes | The helper owns this exactly once; changes propagate to all builders automatically (this is the goal) |

### Test strategy

- Existing tests cover all four builders and their output shapes.
- Add one explicit regression test that calls `_finalize_memory_builder` directly with known inputs and asserts the exact output.
- Run the full 631-test suite after each builder migration.

## 6. What NOT to Abstract

### Material collection must stay per-builder

The "head" of each builder -- how it gathers and formats text for the LLM -- is where the semantic meaning lives. Abstracting this would make each builder harder to read and harder to debug when prompt quality regresses. The thread summary builder's artifact filtering, work artifact selection, conclusion formatting, and char-budget truncation are specific, intentional, and should remain inline.

### Response parsing must stay per-builder

`build_task_checkpoint_memory` has 8 parsed fields, each with its own default-fallback function (`_default_task_checkpoint_task`, `_default_task_checkpoint_state`, etc.). `build_continuity_memory` has `continuity_question` and `carry_forward_answer` with their own defaults. These are the semantic contracts of each memory type. Pushing them behind a generic parse interface would obscure what each builder actually requires from the LLM.

### Payload construction must stay per-builder

Each builder's payload dict is the schema of its memory type. These payloads are consumed by routing, ranking, embedding, and the query result packaging layer. They must remain explicit and readable in each builder, not assembled by a generic payload factory.

### The nested thread-summary-to-checkpoint call should stay explicit

`build_thread_summary` conditionally calls `build_task_checkpoint_memory` and merges the results. This nesting is intentional (task checkpoints are derived from thread context, not from raw source items). Abstracting the nesting would add indirection without value.

### Relations should stay per-builder

Thread builders create `supported_by` and `relates_to` relations; consolidation builders currently return empty relations. The relation shapes may diverge further as the system evolves. Keep them in the builder heads.

## Summary

Extract a `_finalize_memory_builder` shared tail that owns envelope attachment, lexical indexing, inline enrichment, vector embedding, and ProcessResult assembly. Leave material collection, LLM invocation, response parsing, payload construction, and relations in each builder. Migrate one builder at a time, starting with pattern memory. Net reduction is modest (~50 lines) but the real value is eliminating protocol-level drift across four near-identical tails on the LLM write path.
