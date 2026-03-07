# Ideas

## Keep

### Tiered Memory Extension

Take many low-level source items or direct memory objects and periodically
create higher-level reusable memory objects.

Expected benefits:

- noisy history compression
- grouping of related memories
- recurring pattern detection
- stronger long-horizon retrieval

Possible object types:

- `topic_summary`
- `pattern_memory`
- `consolidated_discussion`
- `design_evolution`
- `implementation_pattern`

First likely consolidation target:

- input: related investigation, discussion, and decision memories
- output: `pattern_memory`

### Evidence-backed agent memory

The value of Pallium is not just persistence. It is durable, cited, derived
knowledge that can be returned to an agent as high-signal context.

### Structured-first hybrid retrieval

Keep lexical and structured retrieval as first-class, with embeddings as an
optional layer rather than the whole retrieval model.
