# Tiered Memory Research Guidance

## Executive Takeaway

The current Pallium direction for tiered memory is broadly validated by recent memory-system research and more serious product architectures.

The strongest validated choices are:

- tiered memory as a reusable **capability**, not a universal core behavior
- consolidation from **trusted lower-level semantic units** rather than directly from all raw events
- additive, evidence-backed higher-level memory with explicit lineage
- lifecycle-managed higher-level memory using supersession rather than destructive overwrite
- explicit, testable consolidation strategies rather than one opaque clustering policy

The main unresolved problem remains the same one already identified inside the repo:

- **principled memory selection and grouping for consolidation**

This remains an open challenge in the broader field.

## What External Systems Suggest

### Intermediate units before higher-level abstraction

Recent systems and papers trend toward:

1. compress raw interactions into trusted intermediate memory units
2. consolidate those units into higher-level abstractions
3. keep lower-level detail archived and retrievable

This reinforces Pallium's decision to consolidate from:

- `thread_summary`
- `decision`
- `investigation_outcome`

rather than directly from raw `SourceItem` events.

### Bounded consolidation beats global clustering

The stronger systems use bounded constraints such as:

- time
- context container
- type
- semantic affinity
- explicit prior memory similarity

This reinforces Pallium's current strategy design and the current default:

- `thread_summary_anchored`

### Additive lifecycle is the right shape

The field leans toward:

- immutable or auditable history
- superseding outdated memory
- preserving provenance and support

This validates Pallium's:

- `active`
- `superseded`

lifecycle model for promoted and higher-level memory.

## What This Means For Pallium

### Validated choices

The following should be treated as established design direction:

- keep tiered memory in the **capabilities** layer
- keep package policy responsible for:
  - eligible lower-level memory types
  - grouping rules
  - output types
  - retrieval preference
- keep higher-level memory additive and evidence-backed
- continue evaluating strategy tradeoffs explicitly

### Main unresolved risk

The main risk remains:

- choosing the right memories to aggregate

That is where false patterns and misleading higher-level memory are most likely to appear.

Implications:

- keep hard symbolic guards before synthesis
- use time and container boundaries as primary constraints
- use lexical/topic overlap as a supporting signal, not the only one
- avoid broad unconstrained semantic grouping

### `pattern_memory` is v1, not final ontology

`pattern_memory` is a good first higher-level type, but it should not become the permanent catch-all for every higher-level abstraction.

Likely future splits may include:

- `pattern_memory`
- `topic_summary`
- `design_evolution`
- `playbook_memory`

### Operationalization should stay conservative

Research supports asynchronous or explicitly triggered consolidation more than mandatory inline higher-level synthesis.

That reinforces the current Pallium posture:

- keep tiered memory implemented
- keep strategy comparison
- do not yet treat always-on consolidation as proven product behavior

## Recommended Follow-Up Work

The report points to two concrete follow-up improvements for Pallium:

### 1. Consolidation trace and merge rationale

For each higher-level memory, record:

- strategy name and version
- grouping signals that fired
- anchor memory where applicable
- confidence / merge rationale
- rejected candidates in eval/debug output where useful

This makes false merges much easier to debug and evaluate.

### 2. Retrieval policy evaluation for higher-level memory

Tiered memory is only valuable if retrieval uses it correctly.

Pallium should explicitly test:

- broad recurring questions should prefer `pattern_memory`
- precise factual questions should still prefer lower-level memory or source evidence
- higher-level memory should not overtake evidence when concrete traceability is needed

## Current Pallium Judgment

Tiered memory in Pallium is:

- **implemented**
- **promising**
- **architecturally sound**
- **not yet fully product-proven**

The current conservative posture is a strength.

The next question is no longer "should Pallium have tiered memory?"

It is:

- how should consolidation be traced, selected, and retrieved so higher-level memory improves downstream answers without inventing false patterns?
