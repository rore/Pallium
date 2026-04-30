# Design Proposal: Fix Core/Semantic Architecture Boundary Violations

## Status

Proposed — 2026-03-23

## Problem

The architecture document (`docs/context/architecture.md`) states that the generic core remains domain-agnostic. The `core/` layer should contain only generic primitives, contracts, and orchestration — never package-specific memory types or semantic constants. Three files currently violate this boundary:

### Violation 1: `core/retention.py` imports from `semantic.common`

Line 7 imports `SEMANTIC_SIGNAL_METADATA_KEY` from `semantic.common`. This is a direct dependency from core into the semantic layer, reversing the intended dependency direction.

The constant is used in `is_low_value_meta_source()` (line 35) to inspect package-specific metadata embedded in `SourceItem.metadata` and decide source-item retention TTL. The observability fallback path (line 38-42) already reads the same signal from a different metadata key, so the semantic import exists only to support the primary lookup path.

### Violation 2: `core/retention.py` hardcodes memory type sets

Lines 11-13 define three frozensets of memory types that are specific to `agent_conversation_memory`:

```python
DURABLE_MEMORY_TYPES = frozenset({"decision", "investigation_outcome"})
FRESH_WORKING_MEMORY_TYPES = frozenset({"thread_summary", "task_checkpoint", "continuity_memory", "pattern_memory"})
ORPHAN_DELETE_MEMORY_TYPES = frozenset({"turn_summary"})
```

These are consumed by `storage/sqlite_retention.py` to drive retention policy: durable types are never expired, fresh working types expire after 30 days, orphan discussion summaries can be deleted. If a new semantic package defines different memory types, these constants would be wrong for it.

### Violation 3: `core/service.py` hardcodes thread conclusion types

Line 29 defines `THREAD_CONCLUSION_TYPES = {"decision", "investigation_outcome"}` and line 30 defines `THREAD_SUMMARY_TYPE = "thread_summary"`. These are used in:

- `_collect_thread_conclusions()` (line 1125): filters memory objects to pass as `conclusions` to the plugin's `build_thread_summary()` method.
- `_preferred_active_summary_ref()` (lines 135-148): hardcodes a priority ordering over `thread_summary`, `task_checkpoint`, `continuity_memory`, `pattern_memory` for observability logging.

Both functions embed knowledge about which memory types carry which semantic meaning — knowledge that belongs inside the semantic package.

### Summary of violations

| Location | What leaks | Consumed by |
|---|---|---|
| `core/retention.py:7` | `SEMANTIC_SIGNAL_METADATA_KEY` import | `is_low_value_meta_source()` |
| `core/retention.py:11-13` | Memory type classification sets | `storage/sqlite_retention.py` |
| `core/service.py:29-30` | Thread conclusion + summary types | `_collect_thread_conclusions()`, `_preferred_active_summary_ref()` |
| `core/service.py:135-148` | Memory type priority ordering | `_emit_thread_rebuild_outcome()` |

## Design Principles

1. **Core never imports from semantic.** Dependency direction is always semantic -> core, never the reverse.
2. **Core should not know memory type names.** The set of valid memory types is a semantic-package concern. Core should receive classification through a generic interface, not by hard-coding strings.
3. **Smallest valuable change.** Each fix should be independently mergeable and testable. No big-bang refactor.
4. **Plugin interface extensions must stay optional.** Existing plugins (demo, generic LLM) that do not need retention or thread conclusion awareness should not be forced to implement new methods.

## Proposed Solution

### Part A: Move `SEMANTIC_SIGNAL_METADATA_KEY` into core

The string `"pallium_semantic_signals"` is a metadata key convention, not semantic logic. It names a well-known metadata slot that both the semantic layer writes and the core retention layer reads.

**Action:** Define `SEMANTIC_SIGNAL_METADATA_KEY = "pallium_semantic_signals"` in `core/retention.py` (or a small `core/metadata_keys.py` if we want a single canonical location for cross-layer metadata keys). Then change `semantic/common.py` to import it from core instead of defining it.

This is the simplest fix and does not change any interface. The string is already a stable cross-layer convention; giving it a home in core just corrects the import direction.

### Part B: Retention classification via plugin interface

Add an optional method to `SemanticPlugin` that returns the retention classification for the plugin's memory types:

```python
# In semantic/base.py

from dataclasses import dataclass

@dataclass(frozen=True)
class MemoryRetentionPolicy:
    """Package-declared retention classification for memory types."""
    durable_types: frozenset[str] = frozenset()
    working_types: frozenset[str] = frozenset()
    orphan_delete_types: frozenset[str] = frozenset()


class SemanticPlugin(ABC):
    # ... existing methods ...

    @property
    def memory_retention_policy(self) -> MemoryRetentionPolicy | None:
        """Return retention classification for this package's memory types.
        Default: None (no package-specific retention policy declared)."""
        return None
```

`PalliumService` already holds the `_semantic_plugins` dict. At construction time (or lazily on first retention pass), it can merge the retention policies from all registered plugins into the sets that `sqlite_retention.py` needs. The merged sets replace the current module-level constants in `core/retention.py`.

The merge is straightforward: union each category across all plugins. If a type appears in conflicting categories across two plugins, that is a configuration error and should raise at startup.

Current constants move into `AgentConversationMemoryPlugin.memory_retention_policy` as the only current implementation.

### Part C: Thread conclusion types via plugin interface

Add an optional property to `ThreadAggregationSemanticPlugin` that declares which memory types count as "conclusions" for thread aggregation:

```python
class ThreadAggregationSemanticPlugin(SemanticPlugin):
    # ... existing methods ...

    @property
    def thread_conclusion_types(self) -> frozenset[str]:
        """Memory types that represent thread conclusions.
        Core uses this to filter memory objects before passing them to
        build_thread_summary(). Default: empty (no conclusion filtering)."""
        return frozenset()
```

`_collect_thread_conclusions()` in `core/service.py` replaces its hardcoded `THREAD_CONCLUSION_TYPES` check with a call to `plugin.thread_conclusion_types`. If the set is empty, all active memory objects for the thread are passed through (backward-compatible).

`THREAD_CONCLUSION_TYPES` and `THREAD_SUMMARY_TYPE` are deleted from `core/service.py`.

### Part D: Remove summary priority ordering from core

`_preferred_active_summary_ref()` hardcodes a priority mapping over four memory type strings. This function exists solely for observability logging in `_emit_thread_rebuild_outcome()`.

Two options:

**Option D1 (preferred): Move the priority into the plugin.** Add an optional method to `ThreadAggregationSemanticPlugin`:

```python
def preferred_summary_type_priority(self) -> tuple[str, ...]:
    """Memory type preference order for observability summary selection.
    First type is highest priority. Default: empty (no preference)."""
    return ()
```

Core uses this tuple to sort, falling back to creation time if the tuple is empty.

**Option D2: Remove the priority entirely.** The function is only used for observability emit fields (`final_active_summary_kind`, `final_active_summary_id`). If the observability consumer does not depend on deterministic priority ordering, core can pick the newest active memory object and log its type. This avoids adding interface surface for a logging-only concern.

Recommendation: Option D2 is simpler and sufficient. The observability fields are diagnostic, not behavioral. Simplify `_preferred_active_summary_ref` to select by `created_at` only, removing the type-priority map.

## Where Constants Should Live

| Constant | Current location | Target location |
|---|---|---|
| `SEMANTIC_SIGNAL_METADATA_KEY` | `semantic/common.py` | `core/retention.py` or `core/metadata_keys.py` |
| `DURABLE_MEMORY_TYPES` | `core/retention.py` | `AgentConversationMemoryPlugin.memory_retention_policy` |
| `FRESH_WORKING_MEMORY_TYPES` | `core/retention.py` | `AgentConversationMemoryPlugin.memory_retention_policy` |
| `ORPHAN_DELETE_MEMORY_TYPES` | `core/retention.py` | `AgentConversationMemoryPlugin.memory_retention_policy` |
| `THREAD_CONCLUSION_TYPES` | `core/service.py` | `AgentConversationMemoryPlugin.thread_conclusion_types` |
| `THREAD_SUMMARY_TYPE` | `core/service.py` | Deleted (only used alongside `THREAD_CONCLUSION_TYPES`) |
| Summary priority map | `core/service.py` (in `_preferred_active_summary_ref`) | Deleted; fall back to creation time |

## Migration Path

Each step is independently mergeable and testable. Steps 1-2 are mechanical. Steps 3-4 involve interface changes.

### Step 1: Move `SEMANTIC_SIGNAL_METADATA_KEY` to core

1. Define `SEMANTIC_SIGNAL_METADATA_KEY = "pallium_semantic_signals"` in `core/retention.py` (it is already imported there).
2. Change `semantic/common.py` to `from core.retention import SEMANTIC_SIGNAL_METADATA_KEY`.
3. Update `semantic/agent_conversation_memory_threads.py` and test files to import from the new canonical location (or continue importing from `semantic.common` which re-exports it).
4. Remove the definition from `semantic/common.py`.
5. Run full test suite.

**Risk:** Near zero. String constant, no behavioral change, import-only refactor.

### Step 2: Simplify `_preferred_active_summary_ref` (Option D2)

1. Replace the hardcoded priority map in `_preferred_active_summary_ref` with selection by `created_at` only.
2. Run full test suite. Verify no test depends on the specific priority ordering (only observability tests, if any, would break).

**Risk:** Low. Only affects observability emit content, not behavioral outcomes.

### Step 3: Add `memory_retention_policy` to plugin interface

1. Add `MemoryRetentionPolicy` dataclass and `memory_retention_policy` property to `SemanticPlugin` in `semantic/base.py`, defaulting to `None`.
2. Implement `memory_retention_policy` in `AgentConversationMemoryPlugin`, returning the current type sets.
3. Add a merge helper in `core/retention.py` or `core/service.py` that unions policies from all registered plugins at service construction time.
4. Change `storage/sqlite_retention.py` to accept the merged type sets as constructor/method parameters instead of importing module-level constants.
5. Remove `DURABLE_MEMORY_TYPES`, `FRESH_WORKING_MEMORY_TYPES`, `ORPHAN_DELETE_MEMORY_TYPES` from `core/retention.py`.
6. Run full test suite. Update retention tests to construct policies explicitly.

**Risk:** Medium. Retention is a critical correctness path. The merge logic must handle the case where no plugin declares a policy (empty sets, retention becomes conservative). Tests must verify that the wired behavior is identical before and after.

### Step 4: Add `thread_conclusion_types` to plugin interface

1. Add `thread_conclusion_types` property to `ThreadAggregationSemanticPlugin` in `semantic/base.py`, defaulting to `frozenset()`.
2. Implement it in `AgentConversationMemoryPlugin`, returning `frozenset({"decision", "investigation_outcome"})`.
3. Change `_collect_thread_conclusions()` in `core/service.py` to use `plugin.thread_conclusion_types` instead of the module-level constant.
4. Remove `THREAD_CONCLUSION_TYPES` and `THREAD_SUMMARY_TYPE` from `core/service.py`.
5. Run full test suite.

**Risk:** Low-medium. Thread rebuild is well-tested. The behavioral outcome is identical as long as the plugin returns the same set. Test plugins in `test_async_worker.py` may need to implement the new property (default is empty frozenset, which changes conclusion-filtering behavior for those tests).

## Risk Assessment

### What could go wrong

1. **Retention regression.** If the policy merge silently produces empty type sets (e.g., no plugins registered, or the default plugin does not declare a policy), retention could delete durable memories or fail to expire working memories. **Mitigation:** The merge helper should log a warning when the merged set is empty and no plugins declare a policy. Retention tests must cover this edge case. Conservative default: if no policy is declared, treat all memory types as durable (never expire).

2. **Test plugin breakage.** Several test files define minimal `SemanticPlugin` subclasses. Adding required-looking methods could break them. **Mitigation:** All new methods have defaults (`None` or `frozenset()`), so existing test plugins continue to work without changes.

3. **Multi-package conflict.** When two plugins declare the same memory type in different retention categories, the merge must fail loudly. **Mitigation:** Startup-time validation with a clear error message.

4. **Thread conclusion filtering regression.** If a test's thread aggregation plugin does not override `thread_conclusion_types`, the default empty frozenset means no conclusions are collected, changing thread rebuild behavior for that test. **Mitigation:** Review every `ThreadAggregationSemanticPlugin` subclass in tests and add the property where needed.

### What is not at risk

- **No API changes.** All changes are internal to the service and plugin interface.
- **No storage schema changes.** Memory types in the database are strings; no migration needed.
- **No semantic extraction changes.** The extraction logic in `semantic/common.py` and `agent_conversation_memory` is untouched.
- **No query path changes.** Query routing and reranking are unaffected.

### Estimated scope

- Step 1: ~15 minutes, trivial
- Step 2: ~15 minutes, trivial
- Step 3: ~2 hours, moderate (retention wiring, test updates)
- Step 4: ~1 hour, moderate (thread rebuild wiring, test review)
- Total: roughly half a day of focused work
