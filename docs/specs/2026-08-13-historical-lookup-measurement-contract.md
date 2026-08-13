# Historical-Lookup Measurement Contract

> Status: adopted (2026-08-13). Owns the measurement contract for Pallium vNext
> Phase 0. Execution context: `docs/designs/015-vnext-historical-work-execution.md`
> (P0 contract + Measurement model). Strategy: `docs/context/strategy-vnext.md`.

## Purpose

Define — **before** the historical-lookup tools are exposed — the event schema,
denominators, and evaluation protocol that make the vNext reuse KPI defensible.
Without this, "reuse events per 100 sessions" silently re-runs the old
relevance-classification problem offline. This document is the contract every
later measurement is checked against; the deterministic event-logging it specifies
ships with the Phase 1 vertical slice.

The KPI is a **behavioral** measurement. Cheap deterministic facts are logged
online; the three ambiguous stages — historical *opportunity*, *influence*, and
*material use* — are evaluated **retrospectively by a sampled judge**, never by a
new online classifier. This is a hard boundary (see Non-goals).

## Definitions

**Session.** A bounded unit of agent-mediated work. Its **concrete identity key is
integration-dependent** and must be specified per integration before the denominator
is computed:

- *Coding-agent integrations* (the target of Experiment 1): the host mints a session
  id and sets `thread_ref = session_id`, so a session maps **1:1 to a `thread_ref`**
  within a `container_ref`. The session **start boundary** is `min(created_at)` over
  `source_items` sharing that `thread_ref`.
- *Channel-threaded capture integrations* (e.g. chat sources where each reply-thread
  gets its own `thread_ref` and the channel is a coarser "virtual thread"): a session
  does **not** correspond to a single `thread_ref` — one conversation fragments across
  many `thread_ref`s, with the `container_ref`/channel as the coarser unit. Counting
  `thread_ref`s as sessions here would over-count the denominator and mis-place the
  "prior turns" boundary.

**The P0 denominator is scoped to integrations where `thread_ref` maps 1:1 to a
session.** Channel-threaded / virtual-thread capture requires its own session-identity
mapping (a channel- or window-based session key) before its sessions enter the KPI —
**out of scope here, recorded so it is not silently mis-modeled.** Experiment 1 runs
on the 1:1 integrations, so this does not block P0.

**Substantive session.** A session (per the applicable mapping above) in the
measurement window with ≥1 user-authored turn *and* ≥1 assistant work turn (real work
occurred). This is a deterministic proxy computed from `source_items` (`role`,
`created_at`, and the integration's session key); the judge may drop trivially
non-substantive sessions on the sampled subset. It is the base population for
eligibility.

**Eligible session.** A substantive session where historical lookup *could
plausibly have helped*: its `container_ref` held **≥ N prior indexed source turns**
at the time the session ran — i.e. `source_items` in the same `container_ref` with
`created_at` < the session start boundary. Default **N = 50** (tunable; record the
value used with every reported number). Computed at eval time via a
`(container_ref, created_at)` join — the same reconstruction pattern the
`subtask_selector_shadow` table already relies on (`storage/sqlite_schema.py`), not
a stored flag. Eligibility is the **denominator** for the reuse KPI.

> Eligibility is a *plausibility* filter, not a claim that history was actually
> relevant to the specific task. Whether a given eligible session had a real
> historical opportunity is a sampled retrospective judgment (below), reported with
> its own uncertainty and **not** gating the thesis unless judge reliability is
> demonstrated.

**Tool-exposure population.** The set of historical lookups actually issued
(events carrying a `lookup_event_id` and an `agent_pull`/`mcp_pull` origin) together
with the source ids + raw ranks each exposed. This is a *recorded* population, never
inferred. (P0 defines the schema and the `lookup_event_id`; P1 records the
exposures.)

## Event chain (deterministic, logged online)

| Element | P0 (this slice) | P1 (with the lookup tool) |
|---|---|---|
| `lookup_event_id` returned to the caller | **Shipped** — on the query response, `str \| null` (equals the persisted `query_audit_log` id when audit logging is on) | Guaranteed non-null on the dedicated lookup path (see below) |
| `agent_pull` / `mcp_pull` origin | **Shipped** — reserved in the trigger-origin allowlist, distinct from `user_explicit`; kept out of the abstention-bypass set | Emitted by the lookup tool |
| Exposed source ids + raw ranks | Schema specified here | Recorded per lookup |
| `parent_lookup_id` on source-context expansion | Schema specified here | Recorded on expansion |
| Client session + agent identity on the event | `thread_ref` present; `agent_ref` exists on `source_items` only | Carried onto the lookup event |
| Subsequent-turn links | **Eval-time join** on `(thread_ref, container_ref, created_at)` — no stored FK | same |

**Unconditional logging requirement (P1).** The generic `/query` audit is gated by
`audit_log_enabled` (default off), so P0's `lookup_event_id` is nullable on that
path. The Phase 1 **dedicated historical-lookup path must persist its lookup event
unconditionally** — it is the path whose events feed the funnel and must not depend
on the legacy flag.

**Citation handle (optional, evaluated separately).** A per-result handle an agent
*may* cite is a high-confidence **attribution** signal, not verified incorporation
and **not** required in the baseline Experiment 1 condition (requiring a citation
adds a behavioral instruction that contaminates natural-pull observation). The
existing `id_quote` mechanism (`usage_audit_matcher.py`) is memory-object-keyed; a
raw-source analogue is deferred and optional.

## Reuse ladder — three distinct rungs

Report as three separate numbers, never one blurred metric. Per
`docs/context/lessons.md`, each number states what it measures.

1. **Verified incorporation** (observational). Retrieved history appears in the
   agent's reasoning, an action, or the answer. Explicit citation of a handle is a
   *separate, optional* attribution signal, not a substitute and not a materiality
   claim.
2. **Judged influence / necessity** (observational, stronger). A retrospective judge
   assesses whether the retrieved history *shaped* the work.
3. **Downstream benefit** (task-effect). Requires controlled exposure, user
   confirmation, or outcome comparison — **not** claimable from passive logs.

Per the `docs/context/lessons.md` invariant, all three rungs are in the
**downstream-task-effect** family (they measure whether retrieved history was *used*
downstream — not retrieval recall / candidate-recovery, and not proactive
injection-precision). They are distinguished by *claim strength*: rungs 1–2 are
observational proxies; rung 3 is the controlled/confirmed form. The rollup tags each
rung `measures = downstream-task-effect` with `claim ∈ {observational, controlled}`.

## Retrospective judge protocol

- **Sampling.** Draw a random sample of lookups (and of eligible sessions for the
  opportunity/missed-opportunity diagnostics) from the window; record sample size
  and window bounds with every number.
- **Rubric.** Per sampled lookup the judge labels: (a) was there a genuine
  historical opportunity; (b) rung-1 incorporation (yes/no + evidence span);
  (c) rung-2 influence (yes/no + rationale); (d) **user-directed vs agent-decided**,
  read from the preceding conversation turns (via the subsequent-turn join) — this
  is a judgment, never a tool field. Rung-3 is only labeled where controlled
  exposure/confirmation exists.
- **Blinding + calibration.** Use blinded A/B framing where applicable (the
  `evals/anchor_probe/subagent_audit.py` protocol is the template). Double-rate a
  subsample and report inter-rater agreement (Cohen's κ). On small samples use ≥3
  seeds with a consensus rule (per `docs/context/validation.md`, ~20pp variance is
  real).
- **Uncertainty.** Report Wilson score intervals on every proportion; never report a
  point estimate alone.
- **Empty / abandoned lookups.** A lookup returning 0 results, or followed by no turn
  that uses it, is recorded and classified empty/abandoned: kept in the lookup-count
  denominator, excluded from the useful-result and reuse numerators.

## Rollup formula

Extends the `phase6_measurement.py` rollup template.

For each rung *r*:

```
reuse_per_100_eligible[r] = 100 * (# eligible sessions with ≥1 rung-r reuse event)
                                 / (# eligible sessions)
```

Reported with: N (eligibility threshold), window bounds, sample size, Wilson
interval, and the rung label. **Empty-data-safe:** when `# eligible sessions == 0`,
emit `null` / "n/a (0 eligible)" — never divide.

Supporting rates (each with its own interval): historical-opportunity → lookup
rate; lookup → useful-result rate; lookup → each reuse rung; missed-lookup
opportunities (sampled diagnostic; non-thesis-gating unless judge reliability is
shown); user-directed vs agent-decided split (Experiment 1 cares about the
agent-decided population).

## Visibility-violation reporting

A **violation** = a returned raw source item that fails `is_visible` for the query's
scope. The invariant is **0 violations**. Report the violation count **with** the
count and types of **attempted disallowed accesses** (adversarial cases that *should*
be denied): zero violations observed with zero adversarial opportunity is **not**
evidence of enforcement. Adversarial coverage lives in the search/expansion items;
this document fixes the reporting format.

## What P0 delivers vs defers

- **P0 (now):** this contract; `lookup_event_id` on the query response; the
  `agent_pull`/`mcp_pull` origin; the rollup skeleton (empty-data-safe).
- **P1 (with the lookup tool):** the populated linked chain — recorded exposures
  (source ids + raw ranks), `parent_lookup_id` on expansion, event session/agent
  identity, and unconditional lookup-event logging.

## Non-goals

- No online "historical opportunity detector" and no online material-use matcher —
  opportunity, influence, and material use are retrospective sampled evaluations.
- No RAW/DERIVED/HYBRID shadow comparison (continuous eval track).
- No continuation/handoff (Phase 2) or cross-user (Phase 3) metrics here.
- No requirement that agents cite a handle in the baseline experiment condition.
