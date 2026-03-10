# Hybrid Retrieval Guidance

## Executive Conclusion

Pallium should not be built around pure vector retrieval.

The target retrieval architecture should be hybrid from the start:

1. structured filters
2. lexical retrieval
3. vector retrieval
4. fusion
5. optional reranking
6. evidence-backed result packaging

The key point is not the exact benchmark numbers sometimes reported in external articles. The durable lesson is that technical team-memory corpora mix exact identifiers and fuzzy human reasoning, so lexical and semantic retrieval need to coexist.

## Why This Matters For Pallium

Pallium stores and retrieves a mix of:

- raw evidence-like `SourceItem`s
- summaries and annotations
- promoted `MemoryObject`s
- exact technical names, identifiers, acronyms, and rare terms
- paraphrased discussions, rationale, and prior conclusions

That is exactly the kind of corpus where hybrid retrieval is stronger than either pure lexical or pure vector retrieval.

For Pallium in particular:

- lexical retrieval is strong for exact technical evidence
- vector retrieval is strong for paraphrased reasoning and conceptual similarity
- structured filters reduce noise before either retrieval mode runs

## What The Current Repo Already Has

Pallium already has important pieces of the hybrid story:

- structured query filters
- lexical retrieval
- both `SourceItem` and `MemoryObject` as retrievable targets
- compact, evidence-backed retrieval packaging

So the retrieval research does not overturn the current direction. It sharpens the next retrieval architecture.

## Target Retrieval Pipeline

Recommended target query flow:

1. structured narrowing
2. lexical retrieval over selected text views
3. vector retrieval over selected text views
4. fusion of lexical and vector results
5. optional reranking
6. context assembly

For Pallium, structured narrowing should prefer filters such as:

- object type
- source type
- artifact kind
- role
- entity
- time range
- confidence threshold
- semantic package / use case

## Fusion Strategy

Recommended starting point: Reciprocal Rank Fusion (RRF).

Why it is the right first choice for Pallium:

- lexical and vector scores are not naturally comparable
- RRF works on ranks rather than raw score scales
- it needs far less tuning than weighted score blending
- it is a practical baseline while labeled retrieval evaluation is still small

Weighted fusion can be reconsidered later if Pallium accumulates stronger offline evaluation data.

## What Pallium Should Index

Pallium should not only index `MemoryObject`s.

Recommended retrieval targets:

- `MemoryObject`
- selected `SourceItem`
- selected high-value `Annotation` views later, if useful

Recommended indexed text views include:

- memory object title
- memory object summary
- decision text
- rationale text
- investigation outcome text
- normalized source text
- summary annotation text

This matters because sometimes the best retrieval target is a distilled memory, and sometimes it is still the compact raw evidence.

## What Lexical Retrieval Is Especially Good At

Lexical retrieval should be expected to carry a lot of value for:

- ticket IDs
- repo or service names
- component names
- rare architecture terms
- exact phrases from prior decisions
- domain-specific vocabulary

This is common in agent-mediated technical memory, not an edge case.

## What Vector Retrieval Is Especially Good At

Vector retrieval should be expected to carry a lot of value for:

- paraphrased design rationale
- vague requirement questions
- similar investigations with different wording
- conceptual similarity across conversations
- “have we discussed something like this before?” style queries

This is the part that makes Pallium behave more like memory than exact search.

## Role Of Reranking

Reranking should be treated as an optional second-stage capability.

Good target pattern:

- retrieve top lexical candidates
- retrieve top vector candidates
- fuse them
- optionally rerank only the top fused set

Pallium should keep a reranker extension point in the retrieval architecture, but should not block the first hybrid retrieval slice on adding a reranker.

## Debugging And Explainability

Hybrid retrieval needs explicit debugging support.

Pallium should eventually expose retrieval trace data that answers questions like:

- did this hit come from lexical retrieval?
- did it come from vector retrieval?
- did it survive because of fusion?
- which text view matched?
- what filters narrowed the candidate set?

This matters because memory systems are harder to trust when the retrieval path is opaque.

## What Not To Do

Pallium should not:

- treat pure vector retrieval as the default architecture
- assume semantic similarity alone is enough for technical corpora
- fuse lexical and vector by naive raw score addition
- index only promoted memory and ignore retrievable source evidence
- treat hybrid retrieval as a minor later polish step

## How This Fits The Current Product Slice

The current first package is `agent_conversation_memory`.

That means the immediate product value still comes from:

- prior answer reuse
- cross-thread continuity
- recurring-question recall
- tiered memory over prior agent-mediated conversations

So hybrid retrieval should be treated as the retrieval architecture Pallium is growing toward, but not necessarily as the very next user-value feature ahead of the first tiered-memory layer.

A reasonable product sequence is:

1. prove value with the first bounded tiered-memory layer
2. add retrieval trace and richer text-view modeling
3. add vector retrieval behind a provider abstraction
4. add RRF-based hybrid fusion
5. optionally add reranking later

## Recommended Roadmap Slices

Concrete slices that move Pallium toward the target retrieval architecture:

1. retrieval trace and text-view model
2. vector retrieval provider
3. hybrid retrieval with RRF fusion
4. optional reranker extension later

## External References From The Research Summary

The research summary that informed this design pointed to:

- Elastic hybrid search guidance
- Pinecone hybrid search guidance
- one anecdotal Medium report about hybrid search improving retrieval quality

The durable takeaway is the architecture pattern, not any single benchmark number.
