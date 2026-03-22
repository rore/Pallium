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
- allow separate model roles for query-time ambiguity resolution and write-time extraction so latency-sensitive query paths are not forced to use the same model profile as richer write-time typing work

Current focus:
- the benchmark-program lane is now shipped:
  - Pallium is benchmarked as a memory-decision system, not only as a retrieval stack
  - the benchmark layer now scores the real query contract, thin-agent boundary behavior, low-value promotion, rebuild churn, sharp-vs-generic competition, and injection decisions
- the direct exploratory harness is now shipped:
  - engineers can drive Pallium through the real HTTP contract with a thin generic agent loop
  - interactive replay and session capture now exist without needing a downstream integration
- the typed write-time envelope and direct Pallium-native replay safety rail are now shipped:
  - retrieval can narrow by generic memory kind before final selection
  - direct deterministic replay covers polluted recall, adjacent-topic isolation, constraint contradictions, and pending-to-processed convergence
- the query-policy stabilization slice is now shipped:
  - the first-class constraint/policy lane is now shipped with typed compatibility checks
  - the shipped subject/workstream anchor filter now separates adjacent topics before final ranking
  - a bounded query-policy contract now keeps the hot path deterministic and only allows selective semantic ambiguity resolution for unresolved cases
- the shared semantic prompt-role governance layer is now shipped for contract ownership and normalized provenance across semantic prompt roles
- the first live `write_enrichment` runtime is now shipped on top of that contract:
  - higher-level memory can carry bounded retrieval enrichment without changing the query hot path
  - `write_reconciliation` and `query_ambiguity_resolution` still remain contract-owned later roles
- prompt lifecycle should be treated as a governed semantic-contract problem,
  not as ad hoc prompt tweaking inside whatever feature currently happens to use
  a model call
- keep privacy, query-debug traceability, retention safety, and timestamped runtime logs as permanent regression gates while the stabilization lane advances
- treat live miss capture as valuable but later: first move routing authority from phrase-derived intent toward structural lane narrowing, then remove the remaining English-first residual router so captured misses become residual ambiguity and drift cases instead of mostly rediscovering known lexical control-plane weaknesses
- treat external benchmark packs as useful pressure on the core memory engine, but not as the next best investment for product stability
- treat vector retrieval and hybrid fusion as important follow-on retrieval work, but not as the next stabilization bottleneck:
  - vector retrieval should not be the immediate next feature now that the bounded query-policy slice is shipped; structural lane narrowing should come first, then language-agnostic query signals and typed constraint state, then live miss capture and replay promotion once the hot path is structurally calmer and less English-bound
  - once those deterministic narrowing layers land, vector retrieval becomes the expected semantic retrieval substrate for durable memory
  - it should stay bounded by scope, kind, and subject/workstream filters rather than acting as an unconstrained semantic fallback
  - it should not become the main mechanism for constraint/policy lookup or short-term local state

Plan from the current gaps:
Planned future query pipeline:
- cheap pre-guards for obvious no-value cases
- hard scope and visibility filtering
- kind filtering from the write-time envelope
- subject or workstream filtering when anchors exist
- constraint compatibility filtering when a typed constraint lane exists
- direct retrieval and ranking inside the narrowed set
- bounded semantic ambiguity resolution only if the deterministic path still leaves multiple plausible behaviors or candidate sets
- final packaging and `should_inject` decision
- full query/debug trace for the staged path
- first, build on the shipped write-time memory envelope so retrieval can filter by generic memory kind and other deterministic metadata before semantic ranking
- second and third, in parallel:
  - build on the shipped first-class constraint and policy lane so hard prohibitions and preferences stay enforced semantically across later routing and lifecycle work
  - the shipped subject/workstream anchor filter already removes adjacent-topic contamination before final selection
- the bounded query-policy contract and selective semantic ambiguity-resolution slice are now shipped; keep subsequent retrieval and feedback work bounded by that contract
- keep extending the shipped Pallium-native replay safety rail across all of the above so new structure is backed by deterministic tests, convergence checks, and replay fixtures
- keep Pallium-native scenario and replay expansion active across all of the above so new structure is backed by deterministic tests, convergence checks, and replay fixtures
- use the shipped shared semantic prompt-role contract layer as the governance owner for later extraction, reconciliation, enrichment, and selective query-ambiguity work
- write-time contextual enrichment and bounded background consolidation are now shipped so retrieval quality can improve without pushing more work into the query hot path
- query-time prompt use should remain selective and bounded even after that
  prompt-role formalization; it does not justify an always-on query-time model
  router
- the next feature should now be structural query lane narrowing before intent tie-break so the shipped query-policy contract becomes authoritative in the hot path and phrase-derived intent stops acting like the switchboard
- after that, remove the remaining English-first residual router by landing language-agnostic query signals and typed constraint state so residual routing depends on typed signals and bounded semantic help rather than English cue tables
- after that, move bounded memory lifecycle hardening up so stale, superseded, and contradictory structured memory are governed before broader reuse and sharing work expands
- after that, move the live miss-capture and replay-promotion loop back up so real traffic becomes bounded miss bundles and permanent regressions once captured misses are more likely to reflect residual ambiguity and operational drift than known structural or English-specific routing weaknesses
- after that, move vector retrieval up as the bounded semantic candidate-generation layer for durable memory, then add hybrid fusion so lexical precision and paraphrase recall operate over the same narrowed candidate space
- the targeted external memory pressure pack is now shipped as a non-gating confidence lane for stale-memory handling, update correctness, long noisy recall, and incremental drift; future retrieval-substrate work should use it as pressure, not as the product acceptance gate
- only after those layers are clearer should explicit shared-memory derivation and cross-container bounded memory move up; those later coordination features should build on stronger lifecycle trust so Pallium does not turn stale local continuity into stale shared continuity

Parallel workstreams for the next phase:
- Stream A (`stabilization-foundation`): the bounded query-policy and selective ambiguity-resolution foundation is now shipped
  - follow-on work in this stream should stay limited to hardening the landed policy contract and keeping later retrieval work bounded by it rather than reopening broad router design
- Stream B (`stabilization-safety`): extend the shipped Pallium-native scenario and replay rail
  - this is the safety rail and should keep turning real misses into generic deterministic regressions
  - it should keep protecting deterministic hot-path behavior, abstention behavior, low-confidence fallback, and selective semantic escalation boundaries as later features land
- Stream C (stabilization-semantics): shipped first-class constraints and subject/workstream anchors
  - the typed constraint lane and subject/workstream anchor filter are now shipped; this stream now continues with later semantic-policy refinement on top of the shipped compatibility model
- Stream D (`stabilization-enrichment`): write-time contextual enrichment and background consolidation are now shipped as the first bounded enrichment slice
  - future work in this stream should stay additive and background-oriented rather than pushing more semantic work into query-time routing
- Stream E (`semantic-contract-governance`): shared prompt-role governance is now available as the contract owner for later semantic features
  - future work in this stream should extend the shipped contract layer beyond `write_extraction` when reconciliation, enrichment, and selective query ambiguity land

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
- query-time semantic work should also report:
  - escalation rate
  - added latency and cost when escalation occurs
  - how often deterministic short-circuits avoided a model call
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

