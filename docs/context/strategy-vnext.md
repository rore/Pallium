# Pallium vNext: Historical Agent Work as a First-Class Context Layer

> Status: adopted direction (2026-08-12), refined 2026-09-05. Refines and partially supersedes the
> derived-knowledge-first framing in [vision.md](vision.md): derived memory is
> reframed from *the* differentiator to *one continuously-evaluated representation*
> of the underlying asset — the accumulated history of agent-mediated work.
>
> Evidence below comes from read-only empirical studies over the real local
> corpus (opportunity, debiased retrieval, and representation/handoff studies).

## Goal

Evolve Pallium away from broad proactive memory injection toward a system that makes prior
agent work reliably usable across sessions, agents, and users.

The next phase should validate whether this creates real value before adding more memory
mechanisms.

## Product thesis

> Pallium makes prior agent work usable across agent contexts, sessions, agents, and users.

The core asset is the accumulated history of agent-mediated work, with retrieval, scope,
provenance, and continuity.

Derived memory is one possible representation of that history, not the product itself.

The product now has two complementary capabilities:

- **Session History** records and retrieves governed raw agent work, including exact
  work references, without requiring generated-memory packages.
- **Agent Relay** explicitly transfers context between supported agent runtimes.

Derived packages may consume Session History, but they are not required for it.

## Why change direction

Current evidence:

- Useful cross-session history exists frequently: ~38% of real prompts had clearly useful prior
  history, and most useful history was experiential rather than reconstructable from code.
- Raw hybrid history search is already strong: ~83% top-5 and ~97% top-10 on clear historical
  opportunities.
- Current derived memory did not improve retrieval recall.
- As a consumption representation, current derivation gives ~2.8× compression but only 29% fully
  complete and ~29% misleading.
- Cross-session work transfer is common in the local corpus, usually orchestrated manually by the
  user through summaries, pointers, or reading another session.
- Broad proactive injection has repeatedly struggled with current-subtask relevance.

This argues for changing the primary interaction model, not abandoning historical memory.

---

## Product bets

### 1. Historical lookup

Agents should be able to deliberately search prior agent work when they believe history may
matter. Raw history becomes a first-class retrieval substrate.

Expected flow:

`current work → historical lookup → relevant prior work → optional source expansion → continue`

Primary unknown:

> Does retrieved history improve the work enough to justify its token, latency, and
> contamination cost?

### 2. Work continuity across contexts

Make it easy to continue work from another agent context:

- same agent, new session
- parallel sessions
- Claude ↔ Codex or other agents
- different containers/projects where appropriate

Do not assume cross-agent frequency from the local corpus. The corpus strongly validates
cross-session continuity; cross-agent frequency is workflow-dependent and needs broader/live
validation.

The product should reduce the current need for:

> "summarize this so I can give it to the other session"

or

> "go read this other transcript/file."

### 3. Shared agent knowledge

Allow historical knowledge produced through one user/agent/context to become available to another
where visibility permits.

Pallium already has actor/container/visibility/provenance foundations.

The product-value hypothesis remains unvalidated and should eventually be tested in a genuinely
multi-user environment.

---

## Derived memory strategy

Keep the derived-memory implementations and stored outputs, but disable their
packages by default. There is no migration constraint for changing the default in
the current single-operator deployment.

> **Raw history is the package-independent baseline. Derived memory is an optional,
> continuously evaluated optimization layer.**

With every derived package disabled, Pallium must still start, ingest and redact
raw turns, attach structural work references, index raw history, search and expand
it, and enforce governance. It must make no derived-memory model calls.

The current derivation implementation has not demonstrated an advantage. That may mean:

- derivation is inherently unnecessary, or
- the current extraction/derivation process is not good enough.

We should distinguish those experimentally.

For historical lookups, maintain parallel paths where practical:

- RAW
- DERIVED
- HYBRID

Run DERIVED/HYBRID in shadow initially.

Continuously record:

- relevant information recovered
- RAW-only vs DERIVED-only wins
- completeness
- misleading/unsupported information
- context size
- derivation failure vs retrieval failure
- downstream material use

Periodically run controlled RAW / DERIVED / HYBRID A/B tests.

Derived memory earns more responsibility only if it repeatedly demonstrates an advantage such as:

- better precision
- lower misleading rate
- materially smaller context for equivalent quality
- normalization that recovers information raw search misses
- improved downstream agent performance

This makes derivation an empirical optimization problem instead of a product assumption.

---

## Proactive behavior

Broad proactive injection is no longer the primary product model.

Keep proactive delivery only where intent can be established with high confidence, particularly
clear continuation/resumption cases.

Any proactive behavior must justify itself separately through live precision/usefulness data.

---

## Success measurement

Primary KPI:

> **Fraction of eligible sessions with ≥1 confirmed historical reuse × 100** (session incidence, capped at 100)

A reuse event means historical agent work was retrieved and materially used in subsequent work.

Supporting metrics:

- historical opportunity → lookup rate
- lookup → useful result rate
- lookup → material-use rate
- missed lookup opportunities
- continuation/handoff success
- RAW vs DERIVED vs HYBRID performance
- cross-agent reuse
- cross-user reuse
- proactive-resume precision
- visibility violations: **0**

Retrieval Recall@K remains an offline capability metric, not the product success metric.

---

## Live experiments

### Experiment 1: Agent pull behavior

Give agents Pallium historical lookup and test whether they invoke it at appropriate moments
without explicit user prompting.

Measure the full funnel:

`historical opportunity → agent queries → useful result → material use`

This is the most important near-term validation.

### Experiment 2: Context continuity

Compare Pallium-supported continuation against the existing baseline:

- manual summary
- session/file pointer
- raw transcript inspection

Test whether Pallium reduces user orchestration while preserving correct understanding of prior
work.

### Experiment 3: Derived-memory continuous evaluation

Shadow RAW vs DERIVED vs HYBRID on real lookups and periodically A/B the representations.

Use the resulting failures to determine whether improving derivation is worthwhile.

### Experiment 4: Shared knowledge

Once deployed in a real multi-user environment, measure whether work produced through one user
materially benefits another.

---

## Near-term roadmap

1. Attach structural branch, exact Work Record, and explicit issue/PR/ticket
   references to raw turns without semantic inference.
2. Expose separate exact work-scoped and broad Session History search tools, backed
   by the same raw retrieval and expansion paths.
3. Decouple raw Session History from derived packages and disable those packages by
   default.
4. Run a time-boxed comparison of flat, grouped, and index-first navigation and of
   raw, on-demand-compressed, and persistent-derived representations.
5. Accumulate diverse post-change activity, then run the real-corpus value gate.
6. Support explicit work/session continuation only after that evidence warrants it.
7. Improve derivation only in response to measured failure modes.
8. Validate shared knowledge in an actual multi-user deployment.

---

## Non-goals for this phase

Do not invest significantly in:

- new broad proactive-injection mechanisms
- retrieval/ranking mechanism proliferation
- workflow mining
- automatic skill generation
- agent analytics/coaching
- proving derived memory superior by constructing another synthetic benchmark

---

## Decision point

After enough live usage, Pallium should be able to answer three questions:

1. **Do agents actually reuse historical work often enough for Pallium to matter?**
2. **Does Pallium make continuity across agent contexts materially easier?**
3. **Does derived memory provide enough incremental value over raw history to justify its
   complexity?**

If the answer to the first is no despite good retrieval, the core product thesis is weak.

If the first is yes but derived memory does not beat RAW/HYBRID on any meaningful dimension,
simplify the architecture around raw history.

If derived memory starts winning after improvements, promote it based on those measured advantages
rather than making it foundational by assumption.
