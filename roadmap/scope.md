Pallium now has its first realistic runtime shape for agent_conversation_memory: async ingest and background processors are shipped, thread rebuild work is serialized safely, queue and debug observability exists, the item-level semantic path extracts richer internal signals in the same LLM call, the cleaner-driven retention and runtime logging slice is shipped, and the live thread memory-quality plus thin-agent contract correction is shipped.

The north star for the next phase is not to add broad new memory product surface. It is to make Pallium reliably solve a bounded set of agent-memory jobs without repeated heuristic chasing:

- answer requirement and architecture questions from prior decisions and evidence
- resume long investigations with findings, blockers, and prior reasoning intact
- resume interrupted work from explicit checkpoints instead of transcript replay
- reuse prior answers safely across later conversations when the same conclusion should help again
- preserve findings discovered while exploring external systems without turning Pallium into the system of record
- keep long-lived conversation continuity compact and selective rather than defaulting to transcript growth
- let downstream agents stay thin by relying on Pallium's memory decisions instead of local heuristics

Current gap assessment against that north star:
- strongest today:
  - thread continuity
  - resumed-work checkpoints
  - bounded investigation carry-forward
  - package-owned injection decisions and compact carry-forward output
- partial today:
  - requirement and architecture recall when the decision or conclusion already exists in the current scope
  - repeated-question reuse within bounded local scope
  - evidence-backed reuse of findings that were surfaced clearly enough during the original interaction
- still weak or unstable:
  - routing that stays robust across paraphrase rather than phrase-specific cueing
  - hard constraints that are remembered and enforced semantically, not only textually
  - adjacent-topic separation before ranking rather than after contamination already entered the candidate set
  - stable abstention on low-value or greeting-like queries
  - systematic handling of stale, superseded, or contradictory structured memory
  - confidence that Pallium stays quiet when it should and does not force downstream semantic compensation

The main architectural lesson from the recent failures and research pass is that Pallium's remaining instability is no longer mostly a missing-test problem. It is a structure problem:
- query routing still depends too much on lexical heuristics
- important memory distinctions are still inferred too late from free text
- hard constraints are not yet first-class enough
- topic separation still happens too late in the selection path

The main modeling lesson is that moving away from phrase chasing does not mean replacing it with an opaque free-form router. The next phase should use LLMs cautiously:
- use models for bounded semantic classification and extraction only
- require structured schema outputs, versioned prompt contracts, and explicit abstain or unknown behavior
- keep later routing, filtering, compatibility, and packaging policy deterministic once typed outputs exist
- review prompt changes like code changes, backed by replay and deterministic regressions rather than anecdotal improvement claims

Current focus:
- the benchmark-program lane is now shipped:
  - Pallium is benchmarked as a memory-decision system, not only as a retrieval stack
  - the benchmark layer now scores the real query contract, thin-agent boundary behavior, low-value promotion, rebuild churn, sharp-vs-generic competition, and injection decisions
- the direct exploratory harness is now shipped:
  - engineers can drive Pallium through the real HTTP contract with a thin generic agent loop
  - interactive replay and session capture now exist without needing a downstream integration
- the next phase is architecture stabilization plus test-surface reinforcement:
  - add bounded query intent resolution before retrieval routing
  - add a typed write-time memory envelope and kind-aware prefiltering
  - add a first-class constraint/policy lane with typed compatibility checks
  - add subject and workstream anchors so adjacent-topic separation happens before final ranking
  - expand Pallium-native scenario and replay coverage in parallel so each stabilization change lands with deterministic regression protection
- keep privacy, query-debug traceability, retention safety, and timestamped runtime logs as permanent regression gates while the stabilization lane advances
- treat live miss capture as valuable but later: once the architecture is more stable, captured misses can become durable replay assets instead of mostly rediscovering known heuristic weaknesses
- treat external benchmark packs as useful pressure on the core memory engine, but not as the next best investment for product stability
- treat vector retrieval and hybrid fusion as lower-priority retrieval enhancements, not as the current product driver; only move them forward if the evidence shows recall rather than memory decision quality is the real bottleneck

Plan from the current gaps:
- first, land bounded query intent resolution so greeting/noise, recall, latest-status, resumed-work, and constraint-check queries stop competing mainly through phrase lists
- second, add a write-time memory envelope so retrieval can filter by generic memory kind and other deterministic metadata before semantic ranking
- third and fourth, in parallel once the envelope contract exists:
  - add a first-class constraint and policy lane so hard prohibitions and preferences are enforced semantically
  - add subject and workstream anchors so adjacent-topic contamination is filtered before final selection
- keep Pallium-native scenario and replay expansion active across all of the above so new structure is backed by deterministic tests, convergence checks, and replay fixtures
- after the stabilization architecture is in place, add the live miss-capture and replay-promotion loop so real traffic becomes bounded miss bundles and permanent regressions quickly
- after that, use the targeted external memory pressure pack to pressure stale-memory handling, update correctness, long noisy recall, and incremental memory drift without confusing those checks with the product acceptance gate
- only after those layers are clearer should explicit shared-memory derivation, cross-container bounded memory, vector retrieval, and hybrid fusion move up, and only if the evidence shows they are the bottleneck

Parallel workstreams for the next phase:
- Stream A (`stabilization-foundation`): bounded intent resolution plus the write-time envelope
  - this is the architecture foundation and should own the new query and memory contracts
  - it should also own the bounded classifier prompts, extraction schemas, and versioning rules
- Stream B (`stabilization-safety`): Pallium-native scenario and replay expansion
  - this is the safety rail and should keep turning real misses into generic deterministic regressions
  - it should add replay assets that specifically protect prompt contracts, abstention behavior, and low-confidence fallback
- Stream C (`stabilization-semantics`): first-class constraints plus subject/workstream anchors
  - this should start once the envelope fields exist and can then split into two parallel semantic-policy workers with a shared metadata contract

Test posture for the stabilization phase:
- every architecture feature must land with focused deterministic tests that exercise generic failure classes rather than downstream-specific wording or nouns
- replay and scenario assets should assert payload semantics, not only top-level booleans:
  - selected kinds
  - selected layers
  - required text
  - forbidden text
  - suppression and exclusion reasons
  - convergence behavior before and after async processing
- model-backed classification features should also have contract tests for:
  - valid schema output
  - abstain or unknown behavior
  - low-confidence fallback
  - prompt-versioned replay stability on representative paraphrase sets
- benchmark and readiness slices should continue to run unchanged unless the architecture change intentionally changes semantic expectations
- live misses should be generalized into reusable routing, compatibility, freshness, or contamination failure classes before they become repo fixtures

Still out of scope for this phase:
- cold archive storage for expired raw evidence
- a general graph platform
- global contradiction resolution across all memory
- broad ontology management
- public API expansion for explicit retention administration
- replacing lower-level evidence-backed memory with only higher-level summaries
- turning Pallium into a workflow engine, transcript archive, or raw tool-log store

